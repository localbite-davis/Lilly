import asyncio
import base64
import json
import os
from datetime import datetime
from functools import partial

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from twilio.twiml.voice_response import VoiceResponse, Connect

from src.core.agent.llm_client import BrainManager
from src.core.agent.prompts import LILY_SYSTEM_PROMPT, EXTRACT_SYMPTOMS_TOOL
from src.core.agent.state import ConversationState
from src.services.stt_elevenlabs import ElevenLabsSTT
from src.services.tts_elevenlabs import ElevenLabsTTS

router = APIRouter()

# Shared across calls — one instance is fine (stateless clients).
_brain = BrainManager()
_tts = ElevenLabsTTS()

GREETING = (
    "Hello, I'm Lily, your maternal health companion. "
    "I'm here for you anytime. How are you feeling today?"
)


# ---------------------------------------------------------------------------
# Incoming call webhook — returns TwiML that opens a Media Stream WebSocket.
# ---------------------------------------------------------------------------

@router.post("/incoming")
async def handle_incoming_call(request: Request):
    form_data = await request.form()
    caller_number = form_data.get("From", "unknown")  # noqa: used for DB lookup below
    # TODO: fetch Patient record by caller_number and pass patient_id to WS

    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{request.headers.get('host')}/api/twilio/voice/stream")
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")


# ---------------------------------------------------------------------------
# WebSocket endpoint — real-time STT → LLM → TTS pipeline.
#
# Three concurrent async tasks share two queues:
#
#   transcript_queue : ElevenLabsSTT → llm_tts_task
#   audio_out_queue  : llm_tts_task → twilio_sender_task
#
# Task 1 · twilio_receiver  — reads Twilio media frames, pipes audio to ElevenLabs STT.
# Task 2 · llm_tts          — waits for transcripts, calls LLM, streams TTS.
# Task 3 · twilio_sender    — drains audio_out_queue, sends mulaw back to Twilio.
# ---------------------------------------------------------------------------

@router.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    transcript_queue: asyncio.Queue[str | None] = asyncio.Queue()
    audio_out_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    stt = ElevenLabsSTT(transcript_queue)
    await stt.connect()

    # stream_sid is set when Twilio sends the "start" event.
    stream_sid: dict[str, str] = {}

    # Conversation state — patient_id=0 until DB lookup is wired in.
    state = ConversationState(
        call_sid="pending",
        patient_id=0,
        started_at=datetime.utcnow(),
    )

    # Send Lily's greeting immediately after the call connects.
    asyncio.ensure_future(_speak(GREETING, audio_out_queue, state))

    # ------------------------------------------------------------------
    # Task 1: receive audio from Twilio, feed to Deepgram.
    # ------------------------------------------------------------------
    async def twilio_receiver():
        try:
            async for raw in websocket.iter_text():
                msg = json.loads(raw)
                event = msg.get("event")

                if event == "start":
                    sid = msg["start"]["streamSid"]
                    state.call_sid = sid
                    stream_sid["value"] = sid

                elif event == "media":
                    audio = base64.b64decode(msg["media"]["payload"])
                    await stt.send_audio(audio)

                elif event == "stop":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            await stt.close()
            await transcript_queue.put(None)  # signal llm_tts to exit

    # ------------------------------------------------------------------
    # Task 2: transcript → LLM → ElevenLabs TTS → audio_out_queue.
    # ------------------------------------------------------------------
    async def llm_tts():
        system = LILY_SYSTEM_PROMPT.format(
            patient_name="there",       # TODO: pull from patient record
            date_context="unknown",
            memory_summary="No prior calls.",
        )
        loop = asyncio.get_event_loop()

        while True:
            transcript = await transcript_queue.get()
            if transcript is None:
                break

            state.add_message("user", transcript)

            # BrainManager.generate_response is synchronous (blocking HTTP).
            # Run it in a thread pool so the event loop stays free.
            response = await loop.run_in_executor(
                None,
                partial(
                    _brain.generate_response,
                    system,
                    state.message_history,
                    [EXTRACT_SYMPTOMS_TOOL],
                ),
            )

            # Tool calls are handled by the triage module — not our concern here.
            if response["type"] != "text":
                continue

            reply_text = response["content"]
            state.add_message("assistant", reply_text)
            await _speak(reply_text, audio_out_queue, state)

        await audio_out_queue.put(None)  # signal twilio_sender to exit

    # ------------------------------------------------------------------
    # Task 3: drain audio_out_queue and send mulaw frames back to Twilio.
    # ------------------------------------------------------------------
    async def twilio_sender():
        while True:
            chunk = await audio_out_queue.get()
            if chunk is None:
                break
            sid = stream_sid.get("value")
            if not sid:
                continue  # stream_sid not yet set; discard (shouldn't happen for greeting)
            await websocket.send_text(json.dumps({
                "event": "media",
                "streamSid": sid,
                "media": {"payload": base64.b64encode(chunk).decode()},
            }))

    await asyncio.gather(twilio_receiver(), llm_tts(), twilio_sender())


# ---------------------------------------------------------------------------
# Helper: synthesize text and drain chunks into the shared audio queue.
# ---------------------------------------------------------------------------

async def _speak(text: str, audio_out_queue: asyncio.Queue, state: ConversationState):
    """
    Runs ElevenLabs synthesis and forwards every audio chunk directly into
    audio_out_queue. The sentinel `None` from ElevenLabsTTS is consumed here
    so the sender never sees a premature termination signal.
    """
    local_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    await _tts.synthesize(text, local_queue)
    while True:
        chunk = await local_queue.get()
        if chunk is None:
            break
        await audio_out_queue.put(chunk)
