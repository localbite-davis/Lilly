import asyncio
import os

from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveTranscriptionEvents,
    LiveOptions,
)


class DeepgramSTT:
    """
    Streams inbound mulaw audio from Twilio to Deepgram and puts finalized
    utterances onto `transcript_queue` as plain strings.

    Latency levers used:
    - nova-2 model (fastest accurate model)
    - endpointing=300ms  → Deepgram commits a segment after 300 ms of silence
    - utterance_end_ms=1000 → backup flush after 1 s of silence (catches edge cases
      where speech_final never fires, e.g. very short utterances)
    - interim_results=True  → we don't act on interims but Deepgram needs them
      enabled to emit speech_final correctly
    """

    def __init__(self, transcript_queue: asyncio.Queue):
        self._queue = transcript_queue
        self._connection = None
        self._buffer = ""

        self._client = DeepgramClient(
            api_key=os.getenv("DEEPGRAM_API_KEY"),
            config=DeepgramClientOptions(options={"keepalive": "true"}),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self):
        self._connection = self._client.listen.asyncwebsocket.v("1")
        self._connection.on(LiveTranscriptionEvents.Transcript, self._on_transcript)
        self._connection.on(LiveTranscriptionEvents.UtteranceEnd, self._on_utterance_end)

        options = LiveOptions(
            model="nova-2",
            encoding="mulaw",
            sample_rate=8000,
            channels=1,
            interim_results=True,
            utterance_end_ms=1000,
            endpointing=300,
            smart_format=True,
            language="en-US",
        )
        await self._connection.start(options)

    async def send_audio(self, audio: bytes):
        if self._connection:
            await self._connection.send(audio)

    async def close(self):
        if self._connection:
            await self._connection.finish()

    # ------------------------------------------------------------------
    # Deepgram event handlers
    # ------------------------------------------------------------------

    async def _on_transcript(self, result, **kwargs):
        alt = result.channel.alternatives[0]
        text = alt.transcript
        if not text or not result.is_final:
            return

        self._buffer += (" " if self._buffer else "") + text

        # speech_final=True means Deepgram's endpointing detected silence —
        # flush immediately for minimum LLM latency.
        if result.speech_final:
            await self._flush()

    async def _on_utterance_end(self, result, **kwargs):
        # Backup flush: fires after utterance_end_ms of silence even if
        # speech_final never came (e.g. very short single-word utterances).
        await self._flush()

    async def _flush(self):
        text = self._buffer.strip()
        if text:
            await self._queue.put(text)
            self._buffer = ""
