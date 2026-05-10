"""
Audio pipeline orchestrator (Aryan's territory).

Handles the round trip:
    Twilio WS → STT (ElevenLabs Scribe) → Claude → TTS (ElevenLabs) → Twilio WS

The LLM call itself is a single function: text in, text out. The teammate
working on memory / tools / triage will wrap `generate_reply()` later to
inject patient context, knowledge-graph snippets, tool definitions, etc.
This file should NOT need to change when that happens.
"""

import asyncio
import base64
import json
import sys
import time
from functools import partial

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from twilio.twiml.voice_response import VoiceResponse, Connect

from src.core.agent.llm_client import BrainManager
from src.services.stt_elevenlabs import ElevenLabsSTT
from src.services.tts_elevenlabs import ElevenLabsTTS

router = APIRouter()
_brain = BrainManager()
_tts = ElevenLabsTTS()

GREETING = "Hey, this is Lily. What's up?"

# Minimal system prompt — teammate will swap this for the full one with
# patient context + memory + tool instructions.
SYSTEM_PROMPT = (
    "You are Lily, a warm and supportive maternal health companion. "
    "Keep replies SHORT (1-2 sentences) so they're quick to speak aloud."
)


def log(msg: str):
    print(f"[lily] {msg}", flush=True)
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Single LLM hop — the only seam the memory/triage teammate needs to extend.
# ---------------------------------------------------------------------------

async def generate_reply(history: list[dict]) -> str:
    """
    Given the conversation so far ([{role, content}, ...]), return Lily's
    next spoken reply as plain text.
    """
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        partial(_brain.generate_response, SYSTEM_PROMPT, history, None),
    )
    return response.get("content", "") or "Sorry, could you say that again?"


# ---------------------------------------------------------------------------
# Twilio entry point — TwiML returns a stream URL.
# ---------------------------------------------------------------------------

@router.post("/incoming")
async def handle_incoming_call(request: Request):
    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{request.headers.get('host')}/api/twilio/voice/stream")
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")


# ---------------------------------------------------------------------------
# WebSocket: 3 concurrent tasks share two queues
#   transcript_queue : STT → llm
#   audio_out_queue  : llm → sender
# ---------------------------------------------------------------------------

@router.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    log("WebSocket connected")

    transcript_queue: asyncio.Queue[str | None] = asyncio.Queue()
    audio_out_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    stt = ElevenLabsSTT(transcript_queue)
    await stt.connect()

    stream_sid: dict[str, str] = {}
    history: list[dict] = []

    # ── Task 1: receive Twilio events ────────────────────────────────────────
    async def twilio_receiver():
        greeted = False
        try:
            async for raw in websocket.iter_text():
                msg = json.loads(raw)
                event = msg.get("event")

                if event == "start":
                    stream_sid["value"] = msg["start"]["streamSid"]
                    log(f"start  stream_sid={stream_sid['value']}")
                    if not greeted:
                        greeted = True
                        asyncio.ensure_future(_speak(GREETING, audio_out_queue, stt))

                elif event == "media":
                    audio = base64.b64decode(msg["media"]["payload"])
                    await stt.send_audio(audio)

                elif event == "stop":
                    log("stop event")
                    break

        except WebSocketDisconnect:
            log("client disconnected")
        except Exception as e:
            log(f"receiver error: {e!r}")
        finally:
            await stt.close()
            await transcript_queue.put(None)

    # ── Task 2: transcript → LLM → TTS ───────────────────────────────────────
    async def llm_loop():
        try:
            while True:
                transcript = await transcript_queue.get()
                if transcript is None:
                    break

                log(f"user → '{transcript}'")
                history.append({"role": "user", "content": transcript})

                reply = await generate_reply(history)
                history.append({"role": "assistant", "content": reply})
                log(f"lily → '{reply[:80]}{'...' if len(reply) > 80 else ''}'")

                await _speak(reply, audio_out_queue, stt)
        except Exception as e:
            log(f"llm error: {e!r}")
        finally:
            await audio_out_queue.put(None)

    # ── Task 3: audio out → Twilio ───────────────────────────────────────────
    async def twilio_sender():
        sent = 0
        try:
            while True:
                chunk = await audio_out_queue.get()
                if chunk is None:
                    break
                sid = stream_sid.get("value")
                if not sid:
                    continue
                try:
                    await websocket.send_text(json.dumps({
                        "event": "media",
                        "streamSid": sid,
                        "media": {"payload": base64.b64encode(chunk).decode()},
                    }))
                    sent += 1
                except (RuntimeError, WebSocketDisconnect):
                    break
        finally:
            log(f"sender done — {sent} chunks sent")

    await asyncio.gather(twilio_receiver(), llm_loop(), twilio_sender())
    log("session ended")


# ---------------------------------------------------------------------------
# Helper: synthesize text → audio chunks, mute STT during playback to
# prevent the local-mic echo loop.
# ---------------------------------------------------------------------------

async def _speak(text: str, audio_out_queue: asyncio.Queue, stt):
    log(f"TTS  → '{text[:60]}{'...' if len(text) > 60 else ''}'")
    local_q: asyncio.Queue[bytes | None] = asyncio.Queue()
    try:
        await _tts.synthesize(text, local_q)
    except Exception as e:
        log(f"TTS error: {e!r}")
        return

    total_bytes = 0
    while True:
        chunk = await local_q.get()
        if chunk is None:
            break
        await audio_out_queue.put(chunk)
        total_bytes += len(chunk)

    duration = total_bytes / 8000.0
    stt.mute_until(time.monotonic() + duration + 0.5)
