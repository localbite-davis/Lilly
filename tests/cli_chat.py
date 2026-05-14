#!/usr/bin/env python
"""
CLI test harness for Layer 2.
Uses real Anthropic API + mock TTS (prints to stdout) + mock DB.

Usage:
    conda run -n lily python scripts/cli_chat.py --phone +15550001234
    conda run -n lily python scripts/cli_chat.py --phone +15559999999  # unknown, triggers registration

Ctrl+C to end the call.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Make sure project root is on path when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

log = structlog.get_logger("cli_chat")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_block(block) -> dict:
    t = getattr(block, "type", None)
    if t == "text":
        return {"type": "text", "text": block.text}
    if t == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if t == "tool_result":
        return {"type": "tool_result", "tool_use_id": block.tool_use_id, "content": block.content}
    return {"type": "text", "text": str(block)}


# ---------------------------------------------------------------------------
# Real Anthropic client wrapper (implementing AnthropicLike)
# ---------------------------------------------------------------------------

class RealAnthropicClient:
    def __init__(self, api_key: str) -> None:
        import anthropic
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def stream_messages(
        self,
        model: str,
        system: list[dict],
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
        temperature: float,
    ):
        from src.core.agent.interfaces import (
            MessageStop,
            TextDelta,
            ToolUseStart,
            ToolUseStop,
        )
        import json

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
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "text_delta":
                        yield TextDelta(delta.text)
                    elif delta_type == "input_json_delta":
                        if current_tool_id:
                            tool_inputs[current_tool_id] = tool_inputs.get(current_tool_id, "") + delta.partial_json

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


# ---------------------------------------------------------------------------
# CLI TTS — prints to stdout
# ---------------------------------------------------------------------------

class CliTTSStream:
    def __init__(self, prefix: str = "Lily") -> None:
        self._active = True
        self._prefix = prefix
        self._buffer = ""

    @property
    def is_active(self) -> bool:
        return self._active

    async def feed(self, text: str) -> None:
        if self._active:
            print(f"\033[36m{self._prefix}:\033[0m {text}", flush=True)

    async def flush(self) -> None:
        pass

    async def cancel(self) -> None:
        self._active = False

    async def close(self) -> None:
        self._active = False


class CliTTSFactory:
    async def open_stream(self, call_sid: str, voice_id: str) -> CliTTSStream:
        return CliTTSStream()


# ---------------------------------------------------------------------------
# Seeded mock DB for CLI
# ---------------------------------------------------------------------------

def build_demo_db(phone: str) -> "MockDB":
    from src.core.agent.mocks.mock_db import MockDB, MockPatient

    db = MockDB()
    if phone == "+15550001234":
        db.seed_patient(MockPatient(
            patient_id=1,
            phone=phone,
            first_name="Maria",
            gestational_stage="32 weeks pregnant",
            language="en",
            has_bp_cuff=True,
            has_wearable=False,
            emergency_contact_name="Rosa",
            emergency_contact_phone="+15550009999",
            recent_summaries=["Mild nausea last week, now resolved."],
            standing_orders=[],
            follow_up_flags=["recheck_bp_tomorrow"],
        ))
    # Spanish demo patient
    if phone == "+15550005678":
        db.seed_patient(MockPatient(
            patient_id=2,
            phone=phone,
            first_name="Sofia",
            gestational_stage="28 semanas de embarazo",
            language="es",
            has_bp_cuff=True,
            has_wearable=False,
            emergency_contact_name="Carmen",
            emergency_contact_phone="+15550008888",
            recent_summaries=["Náuseas leves la semana pasada, ahora resueltas."],
            standing_orders=[],
            follow_up_flags=[],
        ))
    return db


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------

async def main(phone: str, api_key: str) -> None:
    from src.core.agent.session import ConversationSession
    from src.core.schemas import UserFinalPayload
    from src.core.triage.rules_engine import classify_case

    db = build_demo_db(phone)
    client = RealAnthropicClient(api_key)
    tts = CliTTSFactory()

    patient = await db.get_patient_by_phone(phone)
    patient_label = f"found patient: {patient.first_name}, {patient.gestational_stage}" if patient else "unknown caller"
    print(f"\n\033[33m[Lily, calling {phone}, {patient_label}]\033[0m")
    print("\033[90mType your messages. Press Ctrl+C or type 'quit' to end.\033[0m\n")

    session = ConversationSession(
        call_sid="CLIchat001",
        direction="inbound",
        anthropic=client,
        tts_factory=tts,
        db=db,
        rules_engine=classify_case,
    )

    await session.start(phone)

    while True:
        try:
            user_input = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("\033[32mYou> \033[0m")
            )
        except (EOFError, KeyboardInterrupt):
            break

        if user_input.strip().lower() in ("quit", "exit", "bye"):
            break

        if not user_input.strip():
            continue

        payload = UserFinalPayload(
            call_sid="CLIchat001",
            transcript=user_input,
            confidence=1.0,
            started_at_ms=0,
            ended_at_ms=0,
        )
        await session.on_user_final(payload)

    await session.on_call_stop("user_quit")
    print("\n\033[33m[Call ended]\033[0m")
    print(f"  Symptoms logged: {list(session._symptoms_logged)}")
    print(f"  Vitals logged:   {session._vitals_logged}")
    if session.pending_classification:
        print(f"  Final tier:      {session.pending_classification.tier}")
    print(f"  SMS sent:        {len(db.sms_sent)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lily Layer 2 CLI harness")
    parser.add_argument("--phone", default="+15550001234", help="Caller phone number")
    parser.add_argument(
        "--api-key",
        default=os.getenv("ANTHROPIC_API_KEY", ""),
        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)",
    )
    args = parser.parse_args()

    if not args.api_key:
        print("Error: set ANTHROPIC_API_KEY or pass --api-key", file=sys.stderr)
        sys.exit(1)

    asyncio.run(main(args.phone, args.api_key))
