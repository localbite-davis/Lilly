import asyncio
import base64
import json
import os

import websockets

# optimize_streaming_latency=4 → maximum latency optimization (may slightly
# reduce quality); ulaw_8000 → Twilio-ready format, no conversion needed.
_WS_URL = (
    "wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
    "?model_id=eleven_turbo_v2_5"
    "&output_format=ulaw_8000"
    "&optimize_streaming_latency=4"
)

# chunk_length_schedule: ElevenLabs starts generating audio after accumulating
# this many characters. Lower first value = faster first audio chunk.
_GENERATION_CONFIG = {"chunk_length_schedule": [50, 100, 150]}

_VOICE_SETTINGS = {"stability": 0.45, "similarity_boost": 0.75, "speed": 1.0}


class ElevenLabsTTS:
    """
    Streams text to ElevenLabs via their WebSocket streaming-input API and puts
    raw mulaw audio bytes onto `audio_queue` as they arrive.

    Each call to `synthesize()` opens a fresh WebSocket connection so that
    concurrent synthesis calls are independent. The caller is responsible for
    draining `audio_queue` and forwarding audio to Twilio.
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
            # BOS frame — must be first, carries config.
            await ws.send(json.dumps({
                "text": " ",
                "voice_settings": _VOICE_SETTINGS,
                "generation_config": _GENERATION_CONFIG,
            }))

            # Send the full text and flush immediately.
            await ws.send(json.dumps({"text": text, "flush": True}))

            # EOS — tells ElevenLabs no more text is coming.
            await ws.send(json.dumps({"text": ""}))

            # Drain audio responses until the server closes the connection.
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("audio"):
                    await audio_queue.put(base64.b64decode(msg["audio"]))

        # Sentinel so the sender knows this utterance is done.
        await audio_queue.put(None)
