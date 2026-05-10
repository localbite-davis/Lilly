import asyncio
import json
import os

import websockets

# ElevenLabs STT streaming WebSocket — Scribe model.
# Docs: https://elevenlabs.io/docs/api-reference/speech-to-text/stream
_WS_URL = (
    "wss://api.elevenlabs.io/v1/speech-to-text/stream"
    "?model_id=scribe_v1"
    "&language=en"
)

# How long to wait after the last is_final transcript before flushing the
# buffer to the LLM. Acts as endpointing since ElevenLabs STT doesn't have
# a built-in silence/endpointing signal like Deepgram.
_SILENCE_TIMEOUT = 0.5  # seconds


class ElevenLabsSTT:
    """
    Streams inbound mulaw audio from Twilio to ElevenLabs Scribe STT via
    WebSocket and puts finalized utterances onto `transcript_queue` as strings.

    Silence detection: after receiving an is_final transcript, a 500 ms timer
    starts. If no new is_final arrives before the timer expires, the buffer is
    flushed to the queue — mimicking Deepgram-style endpointing.
    """

    def __init__(self, transcript_queue: asyncio.Queue):
        self._queue = transcript_queue
        self._api_key = os.getenv("ELEVENLABS_API_KEY")
        self._ws = None
        self._buffer = ""
        self._flush_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self):
        headers = {"xi-api-key": self._api_key}
        self._ws = await websockets.connect(_WS_URL, additional_headers=headers)

        # Send initial audio config so ElevenLabs knows the format.
        await self._ws.send(json.dumps({
            "type": "config",
            "audio_config": {
                "encoding": "mulaw",
                "sample_rate": 8000,
                "channels": 1,
            },
        }))

        # Start listener in background.
        asyncio.ensure_future(self._listen())

    async def send_audio(self, audio: bytes):
        if self._ws:
            await self._ws.send(audio)  # binary frame

    async def close(self):
        if self._flush_task:
            self._flush_task.cancel()
        if self._ws:
            await self._ws.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _listen(self):
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                if msg.get("type") != "transcript":
                    continue

                transcript = msg.get("transcript", {})
                text = transcript.get("text", "").strip()
                is_final = transcript.get("is_final", False)

                if not text:
                    continue

                if is_final:
                    self._buffer += (" " if self._buffer else "") + text
                    self._reset_flush_timer()

        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass
        finally:
            await self._flush()

    def _reset_flush_timer(self):
        """Cancel any pending flush and start a fresh silence timer."""
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
        self._flush_task = asyncio.ensure_future(self._delayed_flush())

    async def _delayed_flush(self):
        await asyncio.sleep(_SILENCE_TIMEOUT)
        await self._flush()

    async def _flush(self):
        text = self._buffer.strip()
        if text:
            await self._queue.put(text)
            self._buffer = ""
