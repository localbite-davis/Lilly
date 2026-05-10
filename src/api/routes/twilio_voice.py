"""
Twilio Media Streams WebSocket handler.

Round trip:
    Twilio WS → ElevenLabs STT → ConversationSession (Layer 2) → ElevenLabs TTS → Twilio WS

Layer 2 (ConversationSession) owns:
  - Patient lookup + context from NeonDB
  - Pinecone memory retrieval
  - Claude streaming with tool dispatch
  - Triage logic
  - Post-call summarization
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from twilio.twiml.voice_response import VoiceResponse, Connect

from src.core.agent.real_client import RealAnthropicClient
from src.core.agent.session import ConversationSession
from src.core.schemas import UserFinalPayload
from src.core.triage.rules_engine import classify_case
from src.db.real_db import RealDB
from src.services.stt_elevenlabs import ElevenLabsSTT
from src.services.tts_elevenlabs import ElevenLabsTTSFactory

router = APIRouter()

# callSid → caller phone number — populated on /incoming, consumed on /stream
_pending_calls: dict[str, str] = {}


def _log(msg: str):
    print(f"[lily] {msg}", flush=True)
    sys.stdout.flush()


@router.post("/incoming")
async def handle_incoming_call(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "")
    from_number = form.get("From", "unknown")
    _pending_calls[call_sid] = from_number
    _log(f"incoming call_sid={call_sid} from={from_number}")

    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{request.headers.get('host')}/api/twilio/voice/stream")
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")


@router.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _log("WebSocket connected")

    transcript_queue: asyncio.Queue[str | None] = asyncio.Queue()
    audio_out_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    stream_sid: str | None = None
    session: ConversationSession | None = None
    stt: ElevenLabsSTT | None = None

    # ── Task 1: receive Twilio events ────────────────────────────────────────
    async def twilio_receiver():
        nonlocal stream_sid, session, stt
        try:
            async for raw in websocket.iter_text():
                msg = json.loads(raw)
                event = msg.get("event")

                if event == "start":
                    start_data = msg["start"]
                    stream_sid = start_data["streamSid"]
                    call_sid = start_data.get("callSid", "")
                    from_number = _pending_calls.pop(call_sid, "unknown")
                    _log(f"start stream_sid={stream_sid} from={from_number}")

                    stt = ElevenLabsSTT(transcript_queue)
                    await stt.connect()

                    tts_factory = ElevenLabsTTSFactory(audio_out_queue, stt)
                    session = ConversationSession(
                        call_sid=call_sid,
                        direction="inbound",
                        anthropic=RealAnthropicClient(),
                        tts_factory=tts_factory,
                        db=RealDB(),
                        rules_engine=classify_case,
                    )

                    # start() fetches patient context from NeonDB + Pinecone,
                    # then streams the greeting through Claude → TTS.
                    asyncio.ensure_future(session.start(from_number=from_number))

                elif event == "media":
                    if stt:
                        audio = base64.b64decode(msg["media"]["payload"])
                        await stt.send_audio(audio)

                elif event == "stop":
                    _log("stop event received")
                    break

        except WebSocketDisconnect:
            _log("client disconnected")
        except Exception as exc:
            _log(f"receiver error: {exc!r}")
        finally:
            if stt:
                await stt.close()
            await transcript_queue.put(None)

    # ── Task 2: transcript → ConversationSession ─────────────────────────────
    async def llm_loop():
        try:
            while True:
                item = await transcript_queue.get()
                if item is None:
                    break
                if session is None:
                    continue

                transcript, detected_language = item

                # Drop echo that slipped through mute: after language lock,
                # short transcripts in a different language are almost always
                # Lily's own TTS voice being picked up through the phone.
                if (
                    session
                    and session._language_locked
                    and detected_language != session._language
                    and len(transcript.split()) < 5
                ):
                    _log(f"dropping echo [{detected_language}]: '{transcript[:60]}'")
                    continue

                _log(f"user [{detected_language}] → '{transcript}'")
                await session.on_user_final(UserFinalPayload(
                    call_sid=stream_sid or "",
                    transcript=transcript,
                    confidence=1.0,
                    detected_language=detected_language,
                ))
        except Exception as exc:
            _log(f"llm_loop error: {exc!r}")
        finally:
            if session:
                await session.on_call_stop("hangup")
            await audio_out_queue.put(None)

    # ── Task 3: audio out → Twilio ───────────────────────────────────────────
    async def twilio_sender():
        sent = 0
        try:
            while True:
                chunk = await audio_out_queue.get()
                if chunk is None:
                    break
                if not stream_sid:
                    continue
                try:
                    await websocket.send_text(json.dumps({
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": base64.b64encode(chunk).decode()},
                    }))
                    sent += 1
                except (RuntimeError, WebSocketDisconnect):
                    break
        finally:
            _log(f"sender done — {sent} chunks sent")

    await asyncio.gather(twilio_receiver(), llm_loop(), twilio_sender())
    _log("session ended")
