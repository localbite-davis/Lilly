#!/usr/bin/env python
"""
End-to-end CLI test harness — real NeonDB + Pinecone, console TTS.

Tests the full storage and retrieval loop without Twilio or ElevenLabs:
  - Patient lookup from NeonDB
  - Pinecone memory retrieval injected into Claude's context
  - Claude responds with full tool access
  - Symptoms / vitals / triage written back to NeonDB
  - Post-call summary saved to Pinecone

Usage (IMPORTANT: activate conda env first — conda run breaks interactive TTY):

    conda activate lily
    python scripts/test_call.py --phone +15550001234   # known patient
    python scripts/test_call.py --phone +19995550000   # unknown → registration flow

Ctrl+C or type 'quit' to end.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

# Make sure project root is on path when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

# Force DEBUG=false so SQLAlchemy engine echo is off in this script.
# Must happen before any src.* import so Settings() picks it up on init.
import os
os.environ["DEBUG"] = "false"

import logging
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)


# ── ANSI colours ─────────────────────────────────────────────────────────────
CYAN   = "\033[36m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
GREY   = "\033[90m"
RED    = "\033[31m"
BLUE   = "\033[34m"
RESET  = "\033[0m"


def _banner(label: str, colour: str = YELLOW) -> None:
    print(f"\n{colour}{'─' * 60}{RESET}")
    print(f"{colour}  {label}{RESET}")
    print(f"{colour}{'─' * 60}{RESET}")


def _log(label: str, value: str = "", colour: str = GREY) -> None:
    tag = f"{colour}[{label}]{RESET}"
    print(f"  {tag} {value}", flush=True)


# ── Logging DB wrapper ────────────────────────────────────────────────────────

class VerboseDB:
    """
    Thin wrapper around RealDB that prints every read/write to the console
    so you can see exactly what's hitting NeonDB during the call.
    """

    def __init__(self, inner):
        self._db = inner

    async def get_patient_by_phone(self, phone: str):
        result = await self._db.get_patient_by_phone(phone)
        if result:
            _log("NeonDB READ", f"patient found — id={result.patient_id} name={result.first_name} stage={result.gestational_stage}", BLUE)
        else:
            _log("NeonDB READ", f"no patient found for {phone}", GREY)
        return result

    async def get_patient_by_id(self, patient_id: int):
        return await self._db.get_patient_by_id(patient_id)

    async def create_patient(self, **fields):
        result = await self._db.create_patient(**fields)
        _log("NeonDB WRITE", f"patient created — id={result.patient_id} name={fields.get('first_name')}", GREEN)
        return result

    async def create_conversation(self, patient_id, call_sid: str, direction: str) -> int:
        conv_id = await self._db.create_conversation(patient_id, call_sid, direction)
        _log("NeonDB WRITE", f"conversation created — id={conv_id} patient_id={patient_id}", GREEN)
        return conv_id

    async def end_conversation(self, conversation_id: int, tier_reached: str, summary: str) -> None:
        await self._db.end_conversation(conversation_id, tier_reached, summary)
        _log("NeonDB WRITE", f"conversation ended — id={conversation_id} tier={tier_reached}", GREEN)
        _log("NeonDB WRITE", f"summary: {summary[:120]}{'...' if len(summary) > 120 else ''}", GREY)

    async def log_symptom(self, conversation_id: int, patient_id, symptom: str) -> None:
        await self._db.log_symptom(conversation_id, patient_id, symptom)
        _log("NeonDB WRITE", f"symptom logged — '{symptom}'", GREEN)

    async def log_vitals(self, conversation_id: int, patient_id, vitals: dict) -> None:
        await self._db.log_vitals(conversation_id, patient_id, vitals)
        _log("NeonDB WRITE", f"vitals logged — {vitals}", GREEN)

    async def get_latest_sms_vitals(self, patient_id: int):
        result = await self._db.get_latest_sms_vitals(patient_id)
        if result:
            _log("NeonDB READ", f"SMS vitals found — {result}", BLUE)
        return result

    async def request_doctor_review(self, conversation_id: int, case_packet: dict) -> int:
        review_id = await self._db.request_doctor_review(conversation_id, case_packet)
        _log("NeonDB WRITE", f"doctor review requested — review_id={review_id}", RED)
        return review_id

    async def send_sms(self, to_phone: str, body: str) -> None:
        await self._db.send_sms(to_phone, body)
        _log("NeonDB WRITE", f"SMS logged → {to_phone}: {body[:80]}", GREEN)

    async def audit(self, actor: str, action: str, patient_id, conversation_id) -> None:
        await self._db.audit(actor, action, patient_id, conversation_id)

    async def register_patient(self, phone: str, first_name: str, gestational_stage: str, verbal_consent_given: bool):
        result = await self._db.register_patient(phone, first_name, gestational_stage, verbal_consent_given)
        _log("NeonDB WRITE", f"patient registered — {first_name}, {gestational_stage}", GREEN)
        return result


# ── Real Anthropic client (implementing AnthropicLike) ───────────────────────

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
        import json
        from src.core.agent.interfaces import (
            MessageStop, TextDelta, ToolUseStart, ToolUseStop,
        )

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
                        _log("TOOL CALL", f"→ {block.name}", YELLOW)
                        yield ToolUseStart(block.id, block.name)

                elif event_type == "content_block_delta":
                    delta = raw.delta
                    if getattr(delta, "type", None) == "text_delta":
                        yield TextDelta(delta.text)
                    elif getattr(delta, "type", None) == "input_json_delta":
                        if current_tool_id:
                            tool_inputs[current_tool_id] = tool_inputs.get(current_tool_id, "") + delta.partial_json

                elif event_type == "content_block_stop":
                    if current_tool_id and current_tool_id in tool_names:
                        raw_json = tool_inputs.get(current_tool_id, "{}")
                        try:
                            parsed = json.loads(raw_json) if raw_json else {}
                        except json.JSONDecodeError:
                            parsed = {}
                        _log("TOOL INPUT", f"{parsed}", YELLOW)
                        yield ToolUseStop(current_tool_id, tool_names[current_tool_id], parsed)
                        current_tool_id = None

                elif event_type == "message_stop":
                    msg = await stream.get_final_message()
                    assistant_msg = {
                        "role": "assistant",
                        "content": [
                            block.model_dump() if hasattr(block, "model_dump") else {"type": "text", "text": str(block)}
                            for block in msg.content
                        ],
                    }
                    yield MessageStop(
                        stop_reason=msg.stop_reason or "end_turn",
                        full_assistant_message=assistant_msg,
                    )


# ── Console TTS ───────────────────────────────────────────────────────────────

class ConsoleTTSStream:
    """Prints Claude's text chunks to stdout as they arrive."""

    def __init__(self) -> None:
        self._active = True
        self._started = False

    @property
    def is_active(self) -> bool:
        return self._active

    async def feed(self, text: str) -> None:
        if not self._active:
            return
        if not self._started:
            print(f"\n{CYAN}Lily:{RESET} ", end="", flush=True)
            self._started = True
        print(text, end="", flush=True)

    async def flush(self) -> None:
        if self._started:
            print()  # newline after response
        self._started = False

    async def cancel(self) -> None:
        if self._started:
            print(f" {GREY}[barge-in]{RESET}")
        self._active = False
        self._started = False

    async def close(self) -> None:
        await self.flush()
        self._active = False


class ConsoleTTSFactory:
    async def open_stream(self, call_sid: str, voice_id: str) -> ConsoleTTSStream:
        return ConsoleTTSStream()


# ── Pinecone memory preview ───────────────────────────────────────────────────

async def _show_pinecone_context(patient_id: int) -> None:
    """Preview what Pinecone would inject into this call."""
    try:
        from src.core.memory.vector_store import memory_store
        summaries = await memory_store.retrieve_summaries(patient_id, top_k=5)
        if summaries:
            _log("Pinecone READ", f"{len(summaries)} past summaries retrieved", BLUE)
            for i, s in enumerate(summaries, 1):
                _log(f"  memory[{i}]", s[:120], GREY)
        else:
            _log("Pinecone READ", "no past summaries found (first call or empty index)", GREY)
    except Exception as exc:
        _log("Pinecone", f"unavailable — {exc}", GREY)


# ── Main REPL ─────────────────────────────────────────────────────────────────

async def main(phone: str, api_key: str) -> None:
    from src.core.agent.session import ConversationSession
    from src.core.schemas import UserFinalPayload
    from src.core.triage.rules_engine import classify_case
    from src.db.real_db import RealDB

    _banner("Lily CLI — real NeonDB + Pinecone + Claude")

    db = VerboseDB(RealDB())
    client = RealAnthropicClient(api_key)
    tts = ConsoleTTSFactory()

    # Show what's in the DB before starting
    _log("Startup", f"looking up {phone} in NeonDB ...", GREY)
    patient = await db.get_patient_by_phone(phone)

    if patient:
        _log("Startup", f"Pinecone memories for patient_id={patient.patient_id} ...", GREY)
        await _show_pinecone_context(patient.patient_id)

    _banner("Call started  —  type your message, Ctrl+C or 'quit' to end")
    print(f"{GREY}(Tool calls, NeonDB reads/writes, and Pinecone ops will be shown inline){RESET}\n")

    session = ConversationSession(
        call_sid="TEST-CLI-001",
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
                None, lambda: input(f"\n{GREEN}You>{RESET} ")
            )
        except (EOFError, KeyboardInterrupt):
            break

        if user_input.strip().lower() in ("quit", "exit", "bye"):
            break
        if not user_input.strip():
            continue

        await session.on_user_final(UserFinalPayload(
            call_sid="TEST-CLI-001",
            transcript=user_input,
            confidence=1.0,
            started_at_ms=0,
            ended_at_ms=0,
        ))

    await session.on_call_stop("user_quit")

    _banner("Call ended — summary")
    print(f"  Symptoms logged : {list(session._symptoms_logged)}")
    print(f"  Vitals logged   : {session._vitals_logged}")
    print(f"  Triage locked   : {session.triage_locked}")
    if session.pending_classification:
        print(f"  Final tier      : {session.pending_classification.tier}")
    print(f"  State           : {session.state}")
    print()


if __name__ == "__main__":
    if not sys.stdin.isatty():
        print(
            f"{RED}Error: stdin is not a TTY. "
            "conda run breaks interactive input.\n"
            f"Run instead:{RESET}\n"
            "  conda activate lily\n"
            "  python scripts/test_call.py --phone +19995550000",
            file=sys.stderr,
        )
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Lily CLI — real NeonDB + Pinecone + Claude")
    parser.add_argument("--phone", default="+15550001234", help="Caller phone number to simulate")
    parser.add_argument(
        "--api-key",
        default=os.getenv("ANTHROPIC_API_KEY", ""),
        help="Anthropic API key (defaults to ANTHROPIC_API_KEY env var)",
    )
    args = parser.parse_args()

    if not args.api_key:
        print(f"{RED}Error: set ANTHROPIC_API_KEY in .env or pass --api-key{RESET}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(main(args.phone, args.api_key))
