"""
Scriptable mock Anthropic client for Layer 2 tests.

Usage:
    client = MockAnthropicClient()
    client.queue_text("Hi Maria, how can I help?")
    client.queue_tool_call("log_symptom", {"symptom": "headache"})
    client.queue_text("I've logged that for you.")
    session = ConversationSession(..., anthropic=client, ...)
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from src.core.agent.interfaces import (
    MessageStop,
    TextDelta,
    ToolUseStart,
    ToolUseStop,
)


class _Turn:
    """One scripted assistant response."""

    def __init__(self) -> None:
        self.events: list = []
        self._tool_counter = 0

    def add_text(self, text: str) -> "_Turn":
        self.events.append(("text", text))
        return self

    def add_tool(self, name: str, input_dict: dict) -> "_Turn":
        tid = f"toolu_mock_{self._tool_counter:03d}"
        self._tool_counter += 1
        self.events.append(("tool", tid, name, input_dict))
        return self

    def _build_assistant_message(self) -> dict:
        content = []
        for ev in self.events:
            if ev[0] == "text":
                content.append({"type": "text", "text": ev[1]})
            else:
                _, tid, name, inp = ev
                content.append({
                    "type": "tool_use",
                    "id": tid,
                    "name": name,
                    "input": inp,
                })
        stop = "end_turn" if not any(e[0] == "tool" for e in self.events) else "tool_use"
        return {"role": "assistant", "content": content, "stop_reason": stop}

    async def stream(self) -> AsyncIterator:
        has_tools = any(e[0] == "tool" for e in self.events)
        text_parts = []
        for ev in self.events:
            if ev[0] == "text":
                yield TextDelta(ev[1])
                text_parts.append(ev[1])
            else:
                _, tid, name, inp = ev
                yield ToolUseStart(tid, name)
                yield ToolUseStop(tid, name, inp)
        yield MessageStop(
            stop_reason="tool_use" if has_tools else "end_turn",
            full_assistant_message=self._build_assistant_message(),
        )


class MockAnthropicClient:
    """
    Queue up scripted turns. Each call to stream_messages pops the next one.
    Raises RuntimeError if the queue is exhausted.
    """

    def __init__(self) -> None:
        self._queue: list[_Turn | Exception] = []

    def queue_turn(self, *events: tuple) -> "_Turn":
        t = _Turn()
        self._queue.append(t)
        return t

    def queue_text(self, text: str) -> None:
        t = _Turn()
        t.add_text(text)
        self._queue.append(t)

    def queue_tool_then_text(self, tool_name: str, tool_input: dict, text: str) -> None:
        t = _Turn()
        t.add_text("")
        self._queue.append(t)
        t2 = _Turn()
        t2.add_tool(tool_name, tool_input)
        t2.add_text("")
        self._queue.append(t2)
        t3 = _Turn()
        t3.add_text(text)
        self._queue.append(t3)

    def queue_error(self, exc: Exception) -> None:
        self._queue.append(exc)

    def new_turn(self) -> _Turn:
        t = _Turn()
        self._queue.append(t)
        return t

    async def stream_messages(
        self,
        model: str,
        system: list[dict],
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator:
        if not self._queue:
            raise RuntimeError("MockAnthropicClient: no more scripted turns")
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        async for event in item.stream():
            yield event
