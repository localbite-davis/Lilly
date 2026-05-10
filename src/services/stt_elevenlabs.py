import asyncio
import audioop
import io
import os
import sys
import time
import wave

import httpx


def _log(msg: str):
    print(f"[stt] {msg}", flush=True)
    sys.stdout.flush()

_API_URL = "https://api.elevenlabs.io/v1/speech-to-text"

# RMS amplitude threshold to distinguish speech from background silence.
_SPEECH_THRESHOLD = 1500

# Number of CONSECUTIVE below-threshold frames before we flush. At 20ms
# per frame, 35 frames = 700ms of continuous silence. Single loud blips
# (crackle, breath) don't reset the silence run, so this is robust against
# noisy environments.
_SILENCE_FRAMES = 35

# Don't bother transcribing clips shorter than this (just noise).
_MIN_AUDIO_BYTES = 3200  # ~0.4s of mulaw 8kHz

# Force-flush if the buffer ever gets this large.
_MAX_BUFFER_BYTES = 96000  # ~12s of mulaw 8kHz


class ElevenLabsSTT:
    """
    Buffers inbound mulaw audio from Twilio. Uses energy-based VAD to
    distinguish speech from silence — the silence timer only counts down
    after real speech, so continuous background audio never blocks it.
    """

    def __init__(self, transcript_queue: asyncio.Queue):
        self._queue = transcript_queue
        self._api_key = os.getenv("ELEVENLABS_API_KEY")
        self._buffer = bytearray()
        self._had_speech = False
        self._silence_run = 0
        self._chunks_seen = 0
        self._max_rms = 0
        # Echo-cancellation guard: ignore inbound audio while Lily is speaking.
        # start_mute() is called when TTS opens (mutes immediately).
        # end_mute(duration) is called when TTS closes with the actual playback
        # duration + buffer so echo tail is also suppressed.
        self._muted_until: float = 0.0
        # When set, Scribe is told to use this language instead of auto-detecting.
        # Eliminates wrong-script transcriptions once the caller's language is known.
        self._pinned_language: str | None = None

    def start_mute(self) -> None:
        """Mute indefinitely — call when TTS stream opens."""
        self._muted_until = float("inf")
        self._buffer.clear()
        self._had_speech = False
        self._silence_run = 0

    def end_mute(self, tail_s: float) -> None:
        """Lift mute after tail_s seconds — call when TTS stream closes."""
        self._muted_until = time.monotonic() + tail_s

    def pin_language(self, lang_code: str) -> None:
        """Lock Scribe to a specific language — stops wrong-script transcriptions."""
        if self._pinned_language != lang_code:
            self._pinned_language = lang_code
            _log(f"language pinned to '{lang_code}' — disabling auto-detection")

    async def connect(self):
        pass  # REST — no persistent connection needed

    async def send_audio(self, audio: bytes):
        # Drop everything while Lily is speaking — prevents the simulator
        # from transcribing her own voice through the local speakers.
        import time as _time
        if _time.monotonic() < self._muted_until:
            self._buffer.clear()
            self._had_speech = False
            self._silence_run = 0
            return

        pcm = audioop.ulaw2lin(audio, 2)
        rms = audioop.rms(pcm, 2)
        is_speech = rms > _SPEECH_THRESHOLD

        # Diagnostic — every ~2s
        self._chunks_seen += 1
        self._max_rms = max(self._max_rms, rms)
        if self._chunks_seen % 100 == 0:
            _log(f"stats — max RMS={self._max_rms} (threshold={_SPEECH_THRESHOLD}), buffered={len(self._buffer)}, silence_run={self._silence_run}")
            self._max_rms = 0

        if is_speech:
            self._buffer.extend(audio)
            self._had_speech = True
            self._silence_run = 0
        elif self._had_speech:
            # Keep buffering silence frames too — preserves natural pauses
            # in the WAV we send to Scribe.
            self._buffer.extend(audio)
            self._silence_run += 1
            if self._silence_run >= _SILENCE_FRAMES:
                await self._flush()
                return

        # Failsafe — buffer too big
        if len(self._buffer) > _MAX_BUFFER_BYTES:
            _log(f"buffer hit {_MAX_BUFFER_BYTES} bytes — force flushing")
            await self._flush()

    async def close(self):
        await self._flush()

    async def _flush(self):
        if not self._had_speech or len(self._buffer) < _MIN_AUDIO_BYTES:
            self._buffer.clear()
            self._had_speech = False
            self._silence_run = 0
            return

        audio_bytes = bytes(self._buffer)
        self._buffer.clear()
        self._had_speech = False
        self._silence_run = 0

        _log(f"flushing {len(audio_bytes)} bytes → ElevenLabs Scribe")
        text, detected_language = await self._transcribe(audio_bytes)
        if not text:
            _log("empty transcript — skipping")
            return
        # Scribe wraps non-speech sounds in parentheses: (Upbeat music plays),
        # (laughter), etc. Drop these — they are never patient speech.
        stripped = text.strip()
        if stripped.startswith("(") and stripped.endswith(")"):
            _log(f"discarding non-speech annotation: '{text}'")
            return
        # Discard noise: single words / very short strings are almost always
        # echo bleed, background noise, or a mulaw artefact — not real speech.
        if len(stripped) < 8 or len(stripped.split()) < 2:
            _log(f"discarding noise ({len(stripped.split())} word(s)): '{text}'")
            return
        _log(f"transcript: '{text}' (language: {detected_language})")
        await self._queue.put((text, detected_language))

    async def _transcribe(self, mulaw_bytes: bytes) -> tuple[str, str]:
        wav_bytes = _mulaw_to_wav(mulaw_bytes)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                if self._pinned_language:
                    scribe_data = {"model_id": "scribe_v1", "language_code": self._pinned_language}
                else:
                    scribe_data = {"model_id": "scribe_v1", "detect_language": True}
                response = await client.post(
                    _API_URL,
                    headers={"xi-api-key": self._api_key},
                    files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                    data=scribe_data,
                )
                if response.status_code != 200:
                    _log(f"Scribe HTTP {response.status_code}: {response.text[:200]}")
                    return "", "en"
                data = response.json()
                text = data.get("text", "").strip()
                language = data.get("language_code", "en")[:2]
                return text, language
        except Exception as e:
            _log(f"transcription error: {e!r}")
            return "", "en"


def _mulaw_to_wav(mulaw_bytes: bytes) -> bytes:
    pcm = audioop.ulaw2lin(mulaw_bytes, 2)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(pcm)
    return buf.getvalue()
