from __future__ import annotations

import asyncio
import base64
import json
import time
import os

import websockets

# optimize_streaming_latency=4 → maximum latency optimization
# ulaw_8000 → Twilio-ready format, no conversion needed
_WS_URL = (
    "wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
    "?model_id=eleven_turbo_v2_5"
    "&output_format=ulaw_8000"
    "&optimize_streaming_latency=4"
)

_GENERATION_CONFIG = {"chunk_length_schedule": [50, 100, 150]}
_VOICE_SETTINGS = {"stability": 0.45, "similarity_boost": 0.75, "speed": 1.0}


class ElevenLabsTTS:
    """
    One-shot synthesizer. Opens a fresh WebSocket per call.
    Used when you have the full text upfront.
    """

    def __init__(self):
        self._api_key = os.getenv("ELEVENLABS_API_KEY")
        self._voice_id = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

    async def synthesize(self, text: str, audio_queue: asyncio.Queue):
        """
        Convert `text` to speech and put mulaw audio chunks onto `audio_queue`.
        Puts `None` as a sentinel when synthesis is complete.
        """
        url = _WS_URL.format(voice_id=self._voice_id)
        headers = {"xi-api-key": self._api_key}

        async with websockets.connect(url, additional_headers=headers) as ws:
            await ws.send(json.dumps({
                "text": " ",
                "voice_settings": _VOICE_SETTINGS,
                "generation_config": _GENERATION_CONFIG,
            }))
            await ws.send(json.dumps({"text": text, "flush": True}))
            await ws.send(json.dumps({"text": ""}))

            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("audio"):
                    await audio_queue.put(base64.b64decode(msg["audio"]))

        await audio_queue.put(None)


class ElevenLabsTTSStream:
    """
    Implements TTSStreamLike. Keeps a single ElevenLabs WebSocket open for a
    full conversational turn, feeding text chunks incrementally as Claude
    streams them. Mutes the STT after playback to prevent echo loops.
    """

    def __init__(
        self,
        voice_id: str,
        api_key: str,
        audio_out_queue: asyncio.Queue,
        stt=None,  # ElevenLabsSTT — optional, used for echo mute
    ):
        self._voice_id = voice_id
        self._api_key = api_key
        self._audio_out_queue = audio_out_queue
        self._stt = stt
        self._ws = None
        self._receiver_task: asyncio.Task | None = None
        self._total_bytes = 0
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    async def feed(self, text: str) -> None:
        """Feed a text chunk. Opens the WebSocket on first call."""
        if self._ws is None:
            await self._open()
        await self._ws.send(json.dumps({"text": text}))

    async def flush(self) -> None:
        """Signal end-of-turn, drain remaining audio, then close."""
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"text": ""}))  # EOS
            if self._receiver_task:
                await self._receiver_task
        except Exception:
            pass
        finally:
            await self._cleanup()

    async def cancel(self) -> None:
        """Immediately abort — called on barge-in."""
        if self._receiver_task:
            self._receiver_task.cancel()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None
        self._active = False

    async def close(self) -> None:
        await self.flush()

    async def _open(self) -> None:
        url = _WS_URL.format(voice_id=self._voice_id)
        self._ws = await websockets.connect(
            url, additional_headers={"xi-api-key": self._api_key}
        )
        # BOS frame — must come first
        await self._ws.send(json.dumps({
            "text": " ",
            "voice_settings": _VOICE_SETTINGS,
            "generation_config": _GENERATION_CONFIG,
        }))
        self._total_bytes = 0
        self._active = True
        self._receiver_task = asyncio.create_task(self._receive_audio())

    async def _receive_audio(self) -> None:
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if msg.get("audio"):
                    chunk = base64.b64decode(msg["audio"])
                    await self._audio_out_queue.put(chunk)
                    self._total_bytes += len(chunk)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _cleanup(self) -> None:
        if self._stt and self._total_bytes > 0:
            duration = self._total_bytes / 8000.0
            self._stt.mute_until(time.monotonic() + duration + 0.5)
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None
        self._active = False


class ElevenLabsTTSFactory:
    """
    Implements TTSFactoryLike. Creates one ElevenLabsTTSStream per turn.
    The same audio_out_queue and stt reference are shared across all turns
    within a call.
    """

    def __init__(self, audio_out_queue: asyncio.Queue, stt=None):
        self._audio_out_queue = audio_out_queue
        self._stt = stt

    async def open_stream(self, call_sid: str, voice_id: str) -> ElevenLabsTTSStream:
        from src.config import settings
        api_key = settings.elevenlabs_api_key
        return ElevenLabsTTSStream(
            voice_id=voice_id,
            api_key=api_key,
            audio_out_queue=self._audio_out_queue,
            stt=self._stt,
        )
