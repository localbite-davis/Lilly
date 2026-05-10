"""Tests for brain.py — Stage 5.4."""

from __future__ import annotations

import asyncio

import pytest

from src.core.agent.brain import stream_turn
from src.core.agent.errors import AnthropicPermanentError, AnthropicTransientError
from src.core.agent.interfaces import MessageStop, TextDelta, ToolUseStop
from src.core.agent.mocks.mock_anthropic import MockAnthropicClient

pytestmark = pytest.mark.asyncio


async def collect_events(client, model="claude-sonnet-4-6", max_retries=0, fallback_model=None):
    events = []
    async for ev in stream_turn(
        client=client,
        model=model,
        system=[{"type": "text", "text": "You are Lily."}],
        messages=[{"role": "user", "content": "Hello"}],
        tools=[],
        max_tokens=128,
        temperature=0.4,
        timeout_s=5.0,
        max_retries=max_retries,
        fallback_model=fallback_model,
    ):
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

async def test_text_response_yields_text_delta_and_stop():
    client = MockAnthropicClient()
    client.queue_text("Hi Maria, how are you?")
    events = await collect_events(client)
    text_events = [e for e in events if isinstance(e, TextDelta)]
    stop_events = [e for e in events if isinstance(e, MessageStop)]
    assert len(text_events) >= 1
    assert len(stop_events) == 1
    assert any("Maria" in e.text for e in text_events)


async def test_tool_call_yields_tool_use_stop():
    client = MockAnthropicClient()
    t = client.new_turn()
    t.add_tool("log_symptom", {"symptom": "headache"})
    events = await collect_events(client)
    tool_events = [e for e in events if isinstance(e, ToolUseStop)]
    assert len(tool_events) == 1
    assert tool_events[0].name == "log_symptom"
    assert tool_events[0].input == {"symptom": "headache"}


async def test_full_assistant_message_in_stop():
    client = MockAnthropicClient()
    client.queue_text("Hello world")
    events = await collect_events(client)
    stop = next(e for e in events if isinstance(e, MessageStop))
    assert stop.full_assistant_message["role"] == "assistant"


# ---------------------------------------------------------------------------
# Retry on transient error
# ---------------------------------------------------------------------------

async def test_transient_error_retried_on_second_attempt():
    client = MockAnthropicClient()
    # First attempt raises, second succeeds
    client.queue_error(AnthropicTransientError("429 rate limit"))
    client.queue_text("Sorry about that, here I am.")
    events = await collect_events(client, max_retries=1)
    text_events = [e for e in events if isinstance(e, TextDelta)]
    assert any("here I am" in e.text for e in text_events)


async def test_transient_error_exhausts_retries_raises():
    client = MockAnthropicClient()
    client.queue_error(AnthropicTransientError("500 server error"))
    client.queue_error(AnthropicTransientError("500 server error again"))
    with pytest.raises(AnthropicTransientError):
        await collect_events(client, max_retries=0)


async def test_fallback_model_used_after_primary_exhausted():
    """After primary exhausts retries, fallback model is tried."""
    primary_client = MockAnthropicClient()
    primary_client.queue_error(AnthropicTransientError("Primary model down"))
    primary_client.queue_text("Fallback response here.")

    events = await collect_events(
        primary_client,
        max_retries=0,
        fallback_model="claude-haiku-4-5-20251001",
    )
    # The second turn (on fallback model) should produce text
    text_events = [e for e in events if isinstance(e, TextDelta)]
    assert any("Fallback" in e.text for e in text_events)


# ---------------------------------------------------------------------------
# Permanent error — no retry
# ---------------------------------------------------------------------------

async def test_permanent_error_raises_immediately():
    client = MockAnthropicClient()
    client.queue_error(AnthropicPermanentError("401 unauthorized"))
    with pytest.raises(AnthropicPermanentError):
        await collect_events(client, max_retries=3)
    # No further attempts should have been made
    assert len(client._queue) == 0  # nothing consumed after the raise


# ---------------------------------------------------------------------------
# CancelledError propagates (barge-in simulation)
# ---------------------------------------------------------------------------

async def test_cancelled_error_propagates():
    """CancelledError must propagate out of stream_turn when task is cancelled."""

    class SlowClient:
        async def stream_messages(self, **kwargs):
            await asyncio.sleep(10)
            if False:
                yield  # make it an async generator

    client = SlowClient()

    async def run():
        task = asyncio.create_task(collect_events(client))
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            return await task
        except asyncio.CancelledError:
            raise

    with pytest.raises(asyncio.CancelledError):
        await run()
