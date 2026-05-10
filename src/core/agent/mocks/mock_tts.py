"""Mock TTS stream and factory for tests and CLI harness."""

from __future__ import annotations

import asyncio
from typing import Callable


class MockTTSStream:
    def __init__(self, print_fn: Callable[[str], None] | None = None) -> None:
        self._active = True
        self._chunks: list[str] = []
        self._print = print_fn or (lambda t: None)

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def chunks_sent(self) -> list[str]:
        return list(self._chunks)

    async def feed(self, text: str) -> None:
        if self._active:
            self._chunks.append(text)
            self._print(f"[TTS chunk] {text}")

    async def flush(self) -> None:
        pass

    async def cancel(self) -> None:
        self._active = False

    async def close(self) -> None:
        self._active = False


class MockTTSFactory:
    def __init__(self, print_fn: Callable[[str], None] | None = None) -> None:
        self._print = print_fn
        self.streams: list[MockTTSStream] = []

    async def open_stream(self, call_sid: str, voice_id: str) -> MockTTSStream:
        stream = MockTTSStream(print_fn=self._print)
        self.streams.append(stream)
        return stream
