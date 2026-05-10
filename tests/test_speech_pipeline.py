"""
Quick smoke tests for Deepgram STT and ElevenLabs TTS services.
Run with: python -m pytest tests/test_speech_pipeline.py -v -s

Requires DEEPGRAM_API_KEY and ELEVENLABS_API_KEY in .env
No Twilio account needed.
"""
import asyncio
import os

import pytest
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# ElevenLabs: synthesize a short phrase and check we get audio bytes back.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_elevenlabs_synthesizes_audio():
    from src.services.tts_elevenlabs import ElevenLabsTTS

    tts = ElevenLabsTTS()
    queue = asyncio.Queue()

    await tts.synthesize("Hello, I am Lily.", queue)

    chunks = []
    while not queue.empty():
        chunk = await queue.get()
        if chunk is not None:
            chunks.append(chunk)

    assert chunks, "ElevenLabs returned no audio chunks"
    total_bytes = sum(len(c) for c in chunks)
    print(f"\n  ElevenLabs OK — received {len(chunks)} chunks, {total_bytes} bytes total")


# ---------------------------------------------------------------------------
# Deepgram: open a connection, send a short silence buffer, then close.
# Verifies the API key and connection params are accepted.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deepgram_connects():
    from src.services.stt_deepgram import DeepgramSTT

    queue = asyncio.Queue()
    stt = DeepgramSTT(queue)
    await stt.connect()

    # Send 0.5s of silence (mulaw 8kHz = 8000 bytes/s)
    silence = bytes(4000)
    await stt.send_audio(silence)
    await asyncio.sleep(0.5)
    await stt.close()

    print("\n  Deepgram OK — connection accepted, audio sent, closed cleanly")


# ---------------------------------------------------------------------------
# Full pipeline: STT mic → LLM → TTS  (manual, only run if you want E2E)
# Skipped by default; remove the skip mark to run.
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="manual E2E test — needs mic access and all 3 API keys")
@pytest.mark.asyncio
async def test_full_pipeline_manual():
    import sounddevice as sd
    from src.services.stt_deepgram import DeepgramSTT
    from src.services.tts_elevenlabs import ElevenLabsTTS
    from src.core.agent.llm_client import BrainManager
    from src.core.agent.prompts import LILY_SYSTEM_PROMPT, EXTRACT_SYMPTOMS_TOOL
    from functools import partial

    transcript_q = asyncio.Queue()
    audio_q = asyncio.Queue()
    stt = DeepgramSTT(transcript_q)
    tts = ElevenLabsTTS()
    brain = BrainManager()
    loop = asyncio.get_event_loop()

    await stt.connect()
    print("\nSpeak now (5 seconds)...")

    # Record 5 seconds of mic audio at 8kHz mulaw
    def record():
        audio = sd.rec(int(5 * 8000), samplerate=8000, channels=1, dtype="int16")
        sd.wait()
        return audio.tobytes()

    raw = await loop.run_in_executor(None, record)

    # Send in 20ms chunks (160 bytes each)
    chunk_size = 160
    for i in range(0, len(raw), chunk_size):
        await stt.send_audio(raw[i:i + chunk_size])
        await asyncio.sleep(0.02)

    await asyncio.sleep(1.5)  # let Deepgram flush
    await stt.close()

    transcript = await asyncio.wait_for(transcript_q.get(), timeout=3)
    print(f"  Transcript: {transcript!r}")

    system = LILY_SYSTEM_PROMPT.format(
        patient_name="Test User", date_context="unknown", memory_summary="none"
    )
    response = await loop.run_in_executor(
        None, partial(brain.generate_response, system, [{"role": "user", "content": transcript}], [EXTRACT_SYMPTOMS_TOOL])
    )
    reply = response.get("content", "")
    print(f"  LLM reply: {reply!r}")

    await tts.synthesize(reply, audio_q)
    chunks = []
    while True:
        c = await audio_q.get()
        if c is None:
            break
        chunks.append(c)
    print(f"  TTS audio: {sum(len(c) for c in chunks)} bytes")
