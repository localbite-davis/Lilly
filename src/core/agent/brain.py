"""
Brain — wraps Anthropic streaming API with retry logic and normalized events.

stream_turn() yields StreamEvent objects. Handles:
  - Retry on transient errors (429, 5xx, network) with exponential backoff.
  - Fallback to secondary model after primary exhausts retries.
  - Permanent errors (400, 401, 403) — no retry.
  - Mid-stream interruption — yield MessageStop with error, raise transient.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator

import structlog
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from src.core.agent.errors import AnthropicPermanentError, AnthropicTransientError
from src.core.agent.interfaces import (
    AnthropicLike,
    MessageStop,
    StreamEvent,
    TextDelta,
    ToolUseInputDelta,
    ToolUseStart,
    ToolUseStop,
)

log = structlog.get_logger(__name__)


def _is_permanent(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(code in msg for code in ["400", "401", "403", "invalid_api_key", "permission"])


def _wrap_client_stream(
    client: AnthropicLike,
    model: str,
    system: list[dict],
    messages: list[dict],
    tools: list[dict],
    max_tokens: int,
    temperature: float,
    timeout_s: float,
) -> AsyncIterator[StreamEvent]:
    """Thin async generator around client.stream_messages with timeout."""

    async def _inner():
        try:
            async with asyncio.timeout(timeout_s):
                async for event in client.stream_messages(
                    model=model,
                    system=system,
                    messages=messages,
                    tools=tools,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ):
                    yield event
        except asyncio.TimeoutError as exc:
            raise AnthropicTransientError(f"Anthropic request timed out after {timeout_s}s") from exc
        except Exception as exc:
            if _is_permanent(exc):
                raise AnthropicPermanentError(str(exc)) from exc
            raise AnthropicTransientError(str(exc)) from exc

    return _inner()


async def stream_turn(
    client: AnthropicLike,
    model: str,
    system: list[dict],
    messages: list[dict],
    tools: list[dict],
    max_tokens: int,
    temperature: float,
    timeout_s: float,
    max_retries: int = 2,
    fallback_model: str | None = None,
) -> AsyncIterator[StreamEvent]:
    """
    Streams one assistant turn. Yields normalized StreamEvent objects.

    Retry policy:
      - AnthropicTransientError: exponential backoff, up to max_retries+1 total attempts.
      - After exhaustion on primary model: one attempt on fallback_model.
      - AnthropicPermanentError: propagate immediately, no retry.

    Caller is responsible for catching asyncio.CancelledError (barge-in).
    """
    ttft_start = time.monotonic()
    first_token_logged = False

    async def _attempt(model_name: str) -> AsyncIterator[StreamEvent]:
        nonlocal first_token_logged
        try:
            async for event in _wrap_client_stream(
                client, model_name, system, messages, tools, max_tokens, temperature, timeout_s
            ):
                if not first_token_logged and isinstance(event, TextDelta):
                    ttft_ms = (time.monotonic() - ttft_start) * 1000
                    log.info("brain_ttft", model=model_name, ttft_ms=round(ttft_ms))
                    first_token_logged = True
                yield event
        except AnthropicPermanentError:
            raise
        except AnthropicTransientError:
            raise

    models_to_try = [(model, max_retries + 1)]
    if fallback_model:
        models_to_try.append((fallback_model, 1))

    last_exc: Exception | None = None
    for model_name, attempts in models_to_try:
        for attempt_num in range(1, attempts + 1):
            try:
                async for event in _attempt(model_name):
                    yield event
                return
            except AnthropicPermanentError:
                raise
            except AnthropicTransientError as exc:
                last_exc = exc
                if attempt_num < attempts:
                    delay = min(0.5 * (2 ** (attempt_num - 1)), 4.0)
                    log.warning(
                        "brain_retry",
                        model=model_name,
                        attempt=attempt_num,
                        delay_s=delay,
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)

    raise AnthropicTransientError(
        f"All retries exhausted. Last error: {last_exc}"
    ) from last_exc
