"""
RealAnthropicClient — production implementation of AnthropicLike.

Wraps the Anthropic async SDK and yields normalized StreamEvent objects.
Shared by twilio_voice.py (prod) and scripts/test_call.py (CLI harness).
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import anthropic

from src.config import settings
from src.core.agent.interfaces import (
    MessageStop,
    StreamEvent,
    TextDelta,
    ToolUseStart,
    ToolUseStop,
)


class RealAnthropicClient:
    """Implements AnthropicLike against the real Anthropic streaming API."""

    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def stream_messages(
        self,
        model: str,
        system: list[dict],
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[StreamEvent]:
        tool_inputs: dict[str, str] = {}
        tool_names: dict[str, str] = {}
        current_tool_id: str | None = None

        async with self._client.messages.stream(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        ) as stream:
            async for raw in stream:
                event_type = getattr(raw, "type", None)

                if event_type == "content_block_start":
                    block = raw.content_block
                    if getattr(block, "type", None) == "tool_use":
                        current_tool_id = block.id
                        tool_names[block.id] = block.name
                        tool_inputs[block.id] = ""
                        yield ToolUseStart(block.id, block.name)

                elif event_type == "content_block_delta":
                    delta = raw.delta
                    if getattr(delta, "type", None) == "text_delta":
                        yield TextDelta(delta.text)
                    elif getattr(delta, "type", None) == "input_json_delta":
                        if current_tool_id:
                            tool_inputs[current_tool_id] = (
                                tool_inputs.get(current_tool_id, "") + delta.partial_json
                            )

                elif event_type == "content_block_stop":
                    if current_tool_id and current_tool_id in tool_names:
                        raw_json = tool_inputs.get(current_tool_id, "{}")
                        try:
                            parsed = json.loads(raw_json) if raw_json else {}
                        except json.JSONDecodeError:
                            parsed = {}
                        yield ToolUseStop(current_tool_id, tool_names[current_tool_id], parsed)
                        current_tool_id = None

                elif event_type == "message_stop":
                    msg = await stream.get_final_message()
                    assistant_msg = {
                        "role": "assistant",
                        "content": [_serialize_block(b) for b in msg.content],
                    }
                    yield MessageStop(
                        stop_reason=msg.stop_reason or "end_turn",
                        full_assistant_message=assistant_msg,
                    )


def _serialize_block(block) -> dict:
    """Strip SDK-internal fields — only send API-accepted keys back as history."""
    t = getattr(block, "type", None)
    if t == "text":
        return {"type": "text", "text": block.text}
    if t == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if t == "tool_result":
        return {"type": "tool_result", "tool_use_id": block.tool_use_id, "content": block.content}
    return {"type": "text", "text": str(block)}
