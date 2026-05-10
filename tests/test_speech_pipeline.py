"""
Quick smoke tests for ElevenLabs STT and TTS services.
Run with: python -m pytest tests/test_speech_pipeline.py -v -s

Requires ELEVENLABS_API_KEY in .env — no Twilio account needed.
"""
import asyncio

import pytest
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# ElevenLabs TTS: synthesize a short phrase and check we get audio bytes back.
# ---------------------------------------------------------------------------

def _elevenlabs_key_present() -> bool:
    k = __import__("os").getenv("ELEVENLABS_API_KEY", "")
    return bool(k) and not k.startswith("your_")


@pytest.mark.asyncio
@pytest.mark.skipif(not _elevenlabs_key_present(), reason="ELEVENLABS_API_KEY not set — skipping live TTS test")
async def test_elevenlabs_tts():
    from src.services.tts_elevenlabs import ElevenLabsTTS

    tts = ElevenLabsTTS()
    queue = asyncio.Queue()

    await tts.synthesize("Hello, I am Lily.", queue)

    chunks = []
    while not queue.empty():
        chunk = await queue.get()
        if chunk is not None:
            chunks.append(chunk)

    assert chunks, "ElevenLabs TTS returned no audio chunks"
    total_bytes = sum(len(c) for c in chunks)
    print(f"\n  ElevenLabs TTS OK — {len(chunks)} chunks, {total_bytes} bytes")


# ---------------------------------------------------------------------------
# ElevenLabs STT: open a connection, send silence, verify it accepts the
# connection and config without erroring.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.skipif(not _elevenlabs_key_present(), reason="ELEVENLABS_API_KEY not set — skipping live STT test")
async def test_elevenlabs_stt_connects():
    from src.services.stt_elevenlabs import ElevenLabsSTT

    queue = asyncio.Queue()
    stt = ElevenLabsSTT(queue)
    await stt.connect()

    # Send 0.5s of silence (mulaw 8kHz = 8000 bytes/s)
    silence = bytes(4000)
    await stt.send_audio(silence)
    await asyncio.sleep(0.5)
    await stt.close()

    print("\n  ElevenLabs STT OK — connection accepted, audio sent, closed cleanly")


# ---------------------------------------------------------------------------
# Full pipeline: mic → STT → LLM → TTS  (manual, skipped by default)
# Remove the skip mark to run interactively.
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="manual E2E test — needs mic access and ANTHROPIC_API_KEY")
@pytest.mark.asyncio
async def test_full_pipeline_manual():
    import sounddevice as sd
    from functools import partial
    from src.services.stt_elevenlabs import ElevenLabsSTT
    from src.services.tts_elevenlabs import ElevenLabsTTS
    from src.core.agent.llm_client import BrainManager
    from src.core.agent.prompts import LILY_SYSTEM_PROMPT, EXTRACT_SYMPTOMS_TOOL

    transcript_q = asyncio.Queue()
    audio_q = asyncio.Queue()
    stt = ElevenLabsSTT(transcript_q)
    tts = ElevenLabsTTS()
    brain = BrainManager()
    loop = asyncio.get_event_loop()

    await stt.connect()
    print("\nSpeak now (5 seconds)...")

    def record():
        audio = sd.rec(int(5 * 8000), samplerate=8000, channels=1, dtype="int16")
        sd.wait()
        return audio.tobytes()

    raw = await loop.run_in_executor(None, record)

    chunk_size = 160  # 20ms at 8kHz
    for i in range(0, len(raw), chunk_size):
        await stt.send_audio(raw[i:i + chunk_size])
        await asyncio.sleep(0.02)

    await asyncio.sleep(1.0)
    await stt.close()

    transcript = await asyncio.wait_for(transcript_q.get(), timeout=5)
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
