"""
Local call simulator — no Twilio account needed.

Mimics what Twilio does over WebSocket:
  1. Sends a fake "start" event to the /stream endpoint.
  2. Records your mic in real time, encodes to mulaw 8kHz, sends as Twilio
     "media" frames.
  3. Receives mulaw audio back from Lily and plays it through your speakers.

Usage:
    python tests/simulate_call.py              # record until Ctrl+C
    python tests/simulate_call.py --seconds 8  # record for 8 seconds then stop

Requirements (in addition to requirements.txt):
    pip install sounddevice numpy
"""

import argparse
import asyncio
import audioop
import base64
import json
import sys
import time
import uuid

import numpy as np
import sounddevice as sd
import websockets

SERVER_WS = "ws://localhost:8000/api/twilio/voice/stream"
SAMPLE_RATE = 8000
CHUNK_MS = 20                          # send 20 ms chunks — matches Twilio's cadence
CHUNK_FRAMES = SAMPLE_RATE * CHUNK_MS // 1000   # 160 samples per chunk


def pcm16_to_mulaw(pcm_bytes: bytes) -> bytes:
    return audioop.lin2ulaw(pcm_bytes, 2)   # 2 bytes per sample (int16)


def mulaw_to_pcm16(mulaw_bytes: bytes) -> bytes:
    return audioop.ulaw2lin(mulaw_bytes, 2)


async def simulate(record_seconds: float | None):
    print("\n🌸  Lily call simulator")
    print("   Connecting to", SERVER_WS)

    try:
        ws = await websockets.connect(SERVER_WS)
    except OSError:
        print("\n✗  Could not connect. Is the server running?")
        print("   Run:  bash start.sh --no-docker\n")
        sys.exit(1)

    stream_sid = f"MZ{uuid.uuid4().hex[:32]}"

    # ── Send Twilio "start" event ──────────────────────────────────────────────
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
    print("   ✓ Connected. Lily should greet you in a moment...\n")

    # ── Shared state ───────────────────────────────────────────────────────────
    stop_event = asyncio.Event()
    seq = [2]

    # ── Task: record mic → send to server ─────────────────────────────────────
    async def send_mic():
        loop = asyncio.get_event_loop()
        deadline = time.time() + record_seconds if record_seconds else None

        print("   🎙  Speak now", f"(recording for {record_seconds}s)" if record_seconds else "(Ctrl+C to stop)")
        print()

        def callback(indata, frames, _time, status):
            if stop_event.is_set():
                raise sd.CallbackStop()
            if deadline and time.time() > deadline:
                stop_event.set()
                raise sd.CallbackStop()

            pcm = (indata[:, 0] * 32767).astype(np.int16).tobytes()
            mulaw = pcm16_to_mulaw(pcm)
            payload = base64.b64encode(mulaw).decode()

            msg = json.dumps({
                "event": "media",
                "sequenceNumber": str(seq[0]),
                "media": {
                    "track": "inbound",
                    "chunk": str(seq[0]),
                    "timestamp": str(int(time.time() * 1000)),
                    "payload": payload,
                },
                "streamSid": stream_sid,
            })
            seq[0] += 1
            asyncio.run_coroutine_threadsafe(ws.send(msg), loop)

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=CHUNK_FRAMES,
            callback=callback,
        ):
            await stop_event.wait()

        # Send Twilio "stop" event
        await ws.send(json.dumps({"event": "stop", "streamSid": stream_sid}))
        print("\n   🎙  Recording stopped.")

    # ── Task: receive audio from server → play through speakers ───────────────
    async def receive_and_play():
        audio_buffer = bytearray()

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
                pcm = mulaw_to_pcm16(mulaw)
                audio_buffer.extend(pcm)

                # Play in 200 ms chunks to keep latency low
                chunk_bytes = SAMPLE_RATE * 2 * 200 // 1000  # 200 ms of int16
                while len(audio_buffer) >= chunk_bytes:
                    chunk = bytes(audio_buffer[:chunk_bytes])
                    del audio_buffer[:chunk_bytes]

                    samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32767
                    sd.play(samples, samplerate=SAMPLE_RATE, blocking=False)

    # ── Run both tasks concurrently ────────────────────────────────────────────
    try:
        await asyncio.gather(send_mic(), receive_and_play())
    except (KeyboardInterrupt, websockets.ConnectionClosed):
        pass
    finally:
        await ws.close()
        print("\n   Call ended.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate a Twilio call to Lily locally.")
    parser.add_argument("--seconds", type=float, default=None, help="Stop recording after N seconds.")
    args = parser.parse_args()

    try:
        asyncio.run(simulate(args.seconds))
    except KeyboardInterrupt:
        print("\n   Interrupted.\n")
