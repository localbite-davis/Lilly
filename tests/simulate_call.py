"""
Local call simulator — no Twilio account needed.

Records mic at the system's native rate (16kHz), downsamples to 8kHz mulaw,
sends as Twilio media frames. Plays Lily's responses through speakers.

Usage:
    python tests/simulate_call.py
"""

import asyncio
import audioop
import base64
import json
import signal
import sys
import time
import traceback
import uuid
import wave

import numpy as np
import sounddevice as sd
import websockets

SERVER_WS = "ws://localhost:8000/api/twilio/voice/stream"

# Mic native rate — most mics don't support 8kHz directly.
MIC_RATE = 16000
# Twilio's rate
TWILIO_RATE = 8000
# 20ms blocks at MIC_RATE
MIC_BLOCK = MIC_RATE * 20 // 1000

OUTPUT_WAV = "received_audio.wav"


async def main():
    print(f"\n🌸  Connecting to {SERVER_WS}\n", flush=True)

    try:
        ws = await websockets.connect(SERVER_WS)
    except OSError as e:
        print(f"✗ Could not connect: {e}")
        sys.exit(1)
    print("✓ WebSocket connected", flush=True)

    stream_sid = f"MZ{uuid.uuid4().hex[:32]}"
    loop = asyncio.get_event_loop()

    await ws.send(json.dumps({
        "event": "start",
        "sequenceNumber": "1",
        "start": {
            "streamSid": stream_sid,
            "accountSid": "AC_simulated",
            "callSid": "CA_simulated",
            "tracks": ["inbound"],
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
        },
        "streamSid": stream_sid,
    }))
    print("✓ Sent start event", flush=True)

    # ── Setup mic (input) ────────────────────────────────────────────────────
    rate_state = [None]   # ratecv state for incremental downsampling
    seq = [2]
    mic_chunks_sent = [0]
    stop_event = asyncio.Event()

    def input_cb(indata, frames, _time, status):
        if status:
            print(f"  [mic] status: {status}", flush=True)
        if stop_event.is_set():
            raise sd.CallbackStop()

        try:
            # float32 mono → int16 PCM at MIC_RATE
            pcm16 = (indata[:, 0] * 32767).astype(np.int16).tobytes()
            # Downsample MIC_RATE → 8000 Hz, keeping ratecv state across chunks
            pcm8k, rate_state[0] = audioop.ratecv(pcm16, 2, 1, MIC_RATE, TWILIO_RATE, rate_state[0])
            # PCM16 8kHz → mulaw
            mulaw = audioop.lin2ulaw(pcm8k, 2)

            msg = json.dumps({
                "event": "media",
                "sequenceNumber": str(seq[0]),
                "media": {
                    "track": "inbound",
                    "chunk": str(seq[0]),
                    "timestamp": str(int(time.time() * 1000)),
                    "payload": base64.b64encode(mulaw).decode(),
                },
                "streamSid": stream_sid,
            })
            seq[0] += 1
            asyncio.run_coroutine_threadsafe(ws.send(msg), loop)
            mic_chunks_sent[0] += 1
            if mic_chunks_sent[0] in (1, 50, 200):
                print(f"  [mic] sent {mic_chunks_sent[0]} chunks to server", flush=True)
        except Exception as e:
            print(f"  [mic] callback error: {e}", flush=True)

    try:
        input_stream = sd.InputStream(
            samplerate=MIC_RATE, channels=1, dtype="float32",
            blocksize=MIC_BLOCK, callback=input_cb,
        )
        input_stream.start()
        print(f"✓ Mic capture started ({MIC_RATE}Hz → downsample → {TWILIO_RATE}Hz mulaw)", flush=True)
    except Exception as e:
        print(f"✗ Mic failed to start: {e}\n  Check System Settings → Privacy → Microphone")
        traceback.print_exc()
        await ws.close()
        sys.exit(1)

    # ── Setup playback (output) ──────────────────────────────────────────────
    play_buffer = bytearray()
    received_pcm = bytearray()
    chunks_received = [0]

    def output_cb(outdata, frames, _time, status):
        needed = frames * 2
        if len(play_buffer) >= needed:
            chunk = bytes(play_buffer[:needed])
            del play_buffer[:needed]
        else:
            chunk = bytes(play_buffer) + b"\x00" * (needed - len(play_buffer))
            play_buffer.clear()
        outdata[:] = np.frombuffer(chunk, dtype=np.int16).reshape(-1, 1)

    try:
        output_stream = sd.OutputStream(
            samplerate=TWILIO_RATE, channels=1, dtype="int16",
            callback=output_cb, blocksize=400,
        )
        output_stream.start()
        print("✓ Speaker output started\n", flush=True)
    except Exception as e:
        print(f"✗ Output stream failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    print("🎙  Ready. Lily will greet you, then speak after the greeting.\n   Ctrl+C to end.\n", flush=True)

    # ── Signal handler — single Ctrl+C cleanly stops everything ──────────────
    shutdown_event = asyncio.Event()

    def request_shutdown():
        if not shutdown_event.is_set():
            print("\nCtrl+C — shutting down...", flush=True)
            shutdown_event.set()

    loop.add_signal_handler(signal.SIGINT, request_shutdown)
    loop.add_signal_handler(signal.SIGTERM, request_shutdown)

    # ── Receive loop ─────────────────────────────────────────────────────────
    async def receive_loop():
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("event") == "media":
                payload = msg["media"].get("payload", "")
                if not payload:
                    continue
                mulaw = base64.b64decode(payload)
                pcm = audioop.ulaw2lin(mulaw, 2)
                play_buffer.extend(pcm)
                received_pcm.extend(pcm)
                chunks_received[0] += 1
                if chunks_received[0] == 1:
                    print("🔊 Lily is speaking...", flush=True)

    try:
        # Race the receive loop against the shutdown signal.
        receive_task = asyncio.create_task(receive_loop())
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        done, pending = await asyncio.wait(
            {receive_task, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
    except websockets.ConnectionClosed as e:
        print(f"\nServer closed connection: {e}")
    except Exception as e:
        print(f"\nReceive loop error: {e}")
        traceback.print_exc()
    finally:
        stop_event.set()
        try:
            input_stream.stop(); input_stream.close()
        except Exception:
            pass
        if play_buffer:
            await asyncio.sleep(len(play_buffer) / (TWILIO_RATE * 2) + 0.5)
        try:
            output_stream.stop(); output_stream.close()
        except Exception:
            pass
        try:
            await ws.send(json.dumps({"event": "stop", "streamSid": stream_sid}))
            await ws.close()
        except Exception:
            pass

        if received_pcm:
            with wave.open(OUTPUT_WAV, "wb") as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(TWILIO_RATE)
                wf.writeframes(bytes(received_pcm))
            print(f"\n✓ Mic chunks sent: {mic_chunks_sent[0]}")
            print(f"✓ Audio chunks received: {chunks_received[0]}")
            print(f"✓ Saved to {OUTPUT_WAV} (play with: afplay {OUTPUT_WAV})\n")
        else:
            print(f"\n✗ No audio received. Mic chunks sent: {mic_chunks_sent[0]}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.\n")
