"""
ConversationSession — the Layer 2 state machine and orchestrator.

Public API (called by Layer 1):
  start(from_number, outbound_context)  — on call start
  on_user_final(payload)               — on Deepgram final transcript
  on_user_interim(partial_text)        — on Deepgram interim (barge-in trigger)
  on_call_stop(reason)                 — on Twilio call end

Internal flow:
  start → _run_brain_turn (greeting)
  on_user_final → _run_brain_turn (each user turn)
  on_user_interim → barge-in cancel if TTS active
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from enum import Enum
from typing import Callable, Literal

import structlog

from src.config import settings
from src.core.agent.brain import stream_turn
from src.core.agent.errors import (
    AnthropicPermanentError,
    AnthropicTransientError,
    SessionStateError,
    StreamCancelledError,
)
from src.core.agent.interfaces import (
    DBLike,
    MessageStop,
    TextDelta,
    ToolUseStop,
    TTSFactoryLike,
    TTSStreamLike,
    AnthropicLike,
)
from src.core.agent.prompts import build_system_prompt
from src.core.agent.tools import TOOL_DEFINITIONS, TOOL_HANDLERS
from src.core.agent.tts_bridge import TextChunker
from src.core.schemas import (
    PatientContext,
    ToolResult,
    TriageOutput,
    UserFinalPayload,
    VitalsPayload,
)

log = structlog.get_logger(__name__)

# Phrases that signal deviation from hand-off mode — suppress these
_HANDOFF_DEVIATION_PATTERNS = re.compile(
    r"\b(you(?:'ll| will) be fine|this isn'?t urgent|not urgent|let'?s wait|"
    r"nothing to worry|i'?m sure it'?s|probably nothing|don'?t worry|"
    r"seems? fine|looks? fine|should be okay|wait and see)\b",
    re.IGNORECASE,
)

_HANDOFF_SAFE_LINE = "I'm staying with you. Help is on the way."


class SessionState(str, Enum):
    INIT = "init"
    GREETING = "greeting"
    LISTENING = "listening"
    THINKING = "thinking"
    TOOL_DISPATCH = "tool_dispatch"
    HAND_OFF_MODE = "hand_off_mode"
    ENDING = "ending"
    ENDED = "ended"


class ConversationSession:
    def __init__(
        self,
        call_sid: str,
        direction: Literal["inbound", "outbound"],
        anthropic: AnthropicLike,
        tts_factory: TTSFactoryLike,
        db: DBLike,
        rules_engine: Callable,
    ) -> None:
        self.call_sid = call_sid
        self.direction = direction
        self.state = SessionState.INIT

        self.patient_id: int | None = None
        self.conversation_id: int | None = None
        self.message_history: list[dict] = []
        self.pending_classification: TriageOutput | None = None
        self.triage_locked: bool = False
        self.sms_vitals_buffer: dict | None = None

        self._from_number: str = ""
        self._patient_context: PatientContext | None = None
        self._symptoms_logged: set[str] = set()
        self._vitals_logged: dict = {}
        self._follow_up_flags: list[str] = []
        self._session_ended: bool = False
        self._consecutive_validation_failures: dict[str, int] = {}

        self.tts_stream: TTSStreamLike | None = None
        self._brain_task: asyncio.Task | None = None
        self._turn_lock = asyncio.Lock()

        self._anthropic = anthropic
        self._tts_factory = tts_factory
        self.tts_factory = tts_factory   # public alias for tests
        self._db = db
        self._rules_engine = rules_engine
        self._chunker = TextChunker(
            max_chars=settings.tts_chunk_max_chars,
            min_chars=settings.tts_chunk_min_chars,
        )

    # -----------------------------------------------------------------------
    # Public Layer-1-facing API
    # -----------------------------------------------------------------------

    async def start(self, from_number: str, outbound_context: dict | None = None) -> None:
        self._from_number = from_number
        self.conversation_id = await self._db.create_conversation(
            patient_id=None,
            call_sid=self.call_sid,
            direction=self.direction,
        )

        if self.direction == "inbound":
            self._patient_context = await self._load_patient_context(from_number)
            if self._patient_context.found:
                self.patient_id = self._patient_context.patient_id
            self.message_history = [{"role": "user", "content": "<call_started>"}]
        else:
            pid = (outbound_context or {}).get("patient_id")
            self._patient_context = await self._load_patient_context_by_id(pid)
            if self._patient_context.found:
                self.patient_id = self._patient_context.patient_id
            opening = self._build_outbound_opening(outbound_context or {})
            self.message_history = [{"role": "user", "content": opening}]

        self.state = SessionState.GREETING
        await self._run_brain_turn()
        if self.state != SessionState.ENDED:
            self.state = SessionState.LISTENING

    async def on_user_final(self, payload: UserFinalPayload) -> None:
        if self.state == SessionState.ENDED:
            return
        log.info(
            "user_final",
            call_sid=self.call_sid,
            confidence=payload.confidence,
        )
        self.message_history.append({"role": "user", "content": payload.transcript})
        await self._run_brain_turn()

    async def on_user_interim(self, partial_text: str) -> None:
        if not partial_text.strip():
            return
        if self.state not in (SessionState.THINKING, SessionState.TOOL_DISPATCH):
            return
        if self.tts_stream is None or not self.tts_stream.is_active:
            return

        log.info("barge_in_detected", call_sid=self.call_sid)

        await asyncio.gather(
            self._cancel_tts_safely(),
            self._cancel_brain_task_safely(),
            return_exceptions=True,
        )
        self._chunker = TextChunker(
            max_chars=settings.tts_chunk_max_chars,
            min_chars=settings.tts_chunk_min_chars,
        )
        self.state = SessionState.LISTENING

    async def on_call_stop(self, reason: str) -> None:
        log.info("call_stopped", call_sid=self.call_sid, reason=reason)
        await asyncio.gather(
            self._cancel_tts_safely(),
            self._cancel_brain_task_safely(),
            return_exceptions=True,
        )
        if not self._session_ended and self.conversation_id is not None:
            tier = "handle"
            if self.pending_classification:
                tier = self.pending_classification.tier
            try:
                await self._db.end_conversation(
                    conversation_id=self.conversation_id,
                    tier_reached=tier,
                    summary="Call ended by network.",
                )
            except Exception:
                pass
        self.state = SessionState.ENDED

    # -----------------------------------------------------------------------
    # Internal: the turn loop
    # -----------------------------------------------------------------------

    async def _run_brain_turn(self) -> None:
        async with self._turn_lock:
            self.state = SessionState.THINKING
            loop_start = time.monotonic()
            try:
                self.tts_stream = await self._tts_factory.open_stream(
                    call_sid=self.call_sid,
                    voice_id=settings.lily_voice_id,
                )
            except Exception as exc:
                log.error("tts_open_failed", call_sid=self.call_sid, exc_info=exc)
                await self._speak_fallback("I'm having a little trouble. Bear with me.")
                return

            self._chunker = TextChunker(
                max_chars=settings.tts_chunk_max_chars,
                min_chars=settings.tts_chunk_min_chars,
            )

            for iteration in range(settings.brain_max_tool_iterations):
                try:
                    tool_uses = await self._stream_one_response()
                except AnthropicPermanentError as exc:
                    log.error("anthropic_permanent", call_sid=self.call_sid, exc_info=exc)
                    await self._speak_fallback(
                        "I'm having trouble connecting. Please try calling again in a moment."
                    )
                    await self._terminate_call()
                    return
                except AnthropicTransientError as exc:
                    log.warning("anthropic_failed_after_retries", call_sid=self.call_sid, exc_info=exc)
                    await self._speak_fallback(
                        "I'm sorry, I lost my train of thought. Could you say that again?"
                    )
                    self.state = SessionState.LISTENING
                    return
                except StreamCancelledError:
                    return

                if not tool_uses:
                    break

                await self._dispatch_tools(tool_uses)

            else:
                log.error("brain_tool_iteration_limit", call_sid=self.call_sid)
                await self._speak_fallback(
                    "I'm getting tangled up. Let me hand you to a doctor to be safe."
                )
                await self._force_handup_via_uncertainty()
                return

            total_ms = (time.monotonic() - loop_start) * 1000
            log.info("turn_complete", call_sid=self.call_sid, total_ms=round(total_ms))

            if total_ms > settings.total_loop_budget_ms:
                log.warning(
                    "turn_over_budget",
                    call_sid=self.call_sid,
                    total_ms=round(total_ms),
                    budget_ms=settings.total_loop_budget_ms,
                )

            if self.state != SessionState.ENDED:
                self.state = SessionState.LISTENING

    # -----------------------------------------------------------------------
    # Internal: one Anthropic streaming call
    # -----------------------------------------------------------------------

    async def _stream_one_response(self) -> list[ToolUseStop]:
        tool_uses: list[ToolUseStop] = []
        self._brain_task = asyncio.current_task()
        suppressed_in_handoff = False

        try:
            async for event in stream_turn(
                client=self._anthropic,
                model=settings.lily_model,
                system=build_system_prompt(self._patient_context or PatientContext(found=False)),
                messages=self.message_history,
                tools=TOOL_DEFINITIONS,
                max_tokens=settings.brain_max_tokens,
                temperature=settings.brain_temperature,
                timeout_s=settings.brain_request_timeout_s,
                max_retries=settings.brain_max_retries,
                fallback_model=settings.lily_model_fallback,
            ):
                if isinstance(event, TextDelta):
                    text = event.text
                    if self.triage_locked and _HANDOFF_DEVIATION_PATTERNS.search(text):
                        suppressed_in_handoff = True
                        log.warning(
                            "handoff_text_suppressed",
                            call_sid=self.call_sid,
                            text_snippet=text[:60],
                        )
                        continue
                    chunks = self._chunker.feed(text)
                    for chunk in chunks:
                        if self.tts_stream:
                            await self.tts_stream.feed(chunk)

                elif isinstance(event, ToolUseStop):
                    tool_uses.append(event)

                elif isinstance(event, MessageStop):
                    tail = self._chunker.flush()
                    if tail and self.tts_stream:
                        if not (self.triage_locked and _HANDOFF_DEVIATION_PATTERNS.search(tail)):
                            await self.tts_stream.feed(tail)
                        else:
                            suppressed_in_handoff = True

                    if self.tts_stream:
                        await self.tts_stream.flush()

                    self.message_history.append(event.full_assistant_message)

                    if suppressed_in_handoff and not tool_uses:
                        # Everything was suppressed — speak the safe fallback
                        if self.tts_stream:
                            await self.tts_stream.feed(_HANDOFF_SAFE_LINE)

                    return tool_uses

        except asyncio.CancelledError:
            await self._cancel_tts_safely()
            raise StreamCancelledError()
        finally:
            self._brain_task = None

        return tool_uses

    # -----------------------------------------------------------------------
    # Internal: tool dispatch
    # -----------------------------------------------------------------------

    async def _dispatch_tools(self, tool_uses: list[ToolUseStop]) -> None:
        self.state = SessionState.TOOL_DISPATCH
        tool_results: list[dict] = []

        for tu in tool_uses:
            try:
                handler = TOOL_HANDLERS[tu.name]
            except KeyError:
                result = ToolResult(
                    ok=False,
                    error=f"Unknown tool: {tu.name}",
                    error_code="UNKNOWN_TOOL",
                )
            else:
                # Track consecutive validation failures per tool
                try:
                    raw_result = await asyncio.wait_for(
                        handler(self, tu.input), timeout=0.5
                    )
                    result = raw_result
                    if result.error_code == "TOOL_VALIDATION_ERROR":
                        self._consecutive_validation_failures[tu.name] = (
                            self._consecutive_validation_failures.get(tu.name, 0) + 1
                        )
                        if self._consecutive_validation_failures[tu.name] >= 2:
                            log.error(
                                "consecutive_validation_failures",
                                tool=tu.name,
                                call_sid=self.call_sid,
                            )
                            await self._force_handup_via_uncertainty()
                    else:
                        self._consecutive_validation_failures[tu.name] = 0
                except asyncio.TimeoutError:
                    result = ToolResult(ok=False, error="Tool timed out.", error_code="TOOL_TIMEOUT")
                except Exception as exc:
                    log.error("tool_unexpected_exception", tool=tu.name, call_sid=self.call_sid, exc_info=exc)
                    result = ToolResult(ok=False, error="Internal error.", error_code="TOOL_HANDLER_ERROR")

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.tool_use_id,
                "content": json.dumps(result.model_dump()),
                "is_error": not result.ok,
            })

        self.message_history.append({"role": "user", "content": tool_results})

    # -----------------------------------------------------------------------
    # Internal: patient context loading
    # -----------------------------------------------------------------------

    async def _load_patient_context(self, phone: str) -> PatientContext:
        try:
            patient = await self._db.get_patient_by_phone(phone)
            if patient is None:
                return PatientContext(found=False)
            return PatientContext(
                found=True,
                patient_id=patient.patient_id,
                first_name=patient.first_name,
                gestational_stage=patient.gestational_stage,
                language=getattr(patient, "language", "en"),
                has_bp_cuff=getattr(patient, "has_bp_cuff", False),
                has_wearable=getattr(patient, "has_wearable", False),
                emergency_contact_name=getattr(patient, "emergency_contact_name", None),
                emergency_contact_phone=getattr(patient, "emergency_contact_phone", None),
                recent_summaries=getattr(patient, "recent_summaries", []),
                standing_orders=[],
                follow_up_flags=getattr(patient, "follow_up_flags", []),
            )
        except Exception as exc:
            log.error("load_patient_context_failed", phone="<redacted>", exc_info=exc)
            return PatientContext(found=False)

    async def _load_patient_context_by_id(self, patient_id: int | None) -> PatientContext:
        if patient_id is None:
            return PatientContext(found=False)
        try:
            patient = await self._db.get_patient_by_id(patient_id)
            if patient is None:
                return PatientContext(found=False)
            return PatientContext(
                found=True,
                patient_id=patient.patient_id,
                first_name=patient.first_name,
                gestational_stage=patient.gestational_stage,
            )
        except Exception as exc:
            log.error("load_patient_context_by_id_failed", patient_id=patient_id, exc_info=exc)
            return PatientContext(found=False)

    # -----------------------------------------------------------------------
    # Internal: outbound opening
    # -----------------------------------------------------------------------

    def _build_outbound_opening(self, ctx: dict) -> str:
        reason = ctx.get("reason", "doctor_callback")
        if reason == "doctor_callback":
            doctor = ctx.get("doctor_name", "your doctor")
            decision = ctx.get("decision", "ESCALATE")
            return (
                f"<system_callback> {doctor} reviewed the case and decided: {decision}. "
                "Greet her warmly, name the doctor, deliver the decision, "
                "send the SMS with the hospital address, and end the call after she confirms understanding."
            )
        if reason == "auto_escalate":
            return (
                "<system_auto_escalate> No doctor responded within 20 minutes. "
                "Greet her warmly, explain calmly that to be safe she should head "
                "to the nearest ER now, send the SMS with the address, ask if she has someone to drive."
            )
        return f"<system_outbound> {ctx}"

    # -----------------------------------------------------------------------
    # Internal: TTS and brain task cancellation
    # -----------------------------------------------------------------------

    async def _cancel_tts_safely(self) -> None:
        if self.tts_stream is not None:
            try:
                await asyncio.wait_for(self.tts_stream.cancel(), timeout=0.2)
            except Exception:
                pass

    async def _cancel_brain_task_safely(self) -> None:
        if self._brain_task is not None and not self._brain_task.done():
            self._brain_task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._brain_task), timeout=0.2
                )
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

    # -----------------------------------------------------------------------
    # Internal: fallback speech
    # -----------------------------------------------------------------------

    async def _speak_fallback(self, text: str) -> None:
        try:
            if self.tts_stream is None or not self.tts_stream.is_active:
                self.tts_stream = await self._tts_factory.open_stream(
                    call_sid=self.call_sid,
                    voice_id=settings.lily_voice_id,
                )
            await self.tts_stream.feed(text)
            await self.tts_stream.flush()
        except Exception as exc:
            log.error("speak_fallback_failed", call_sid=self.call_sid, exc_info=exc)

    # -----------------------------------------------------------------------
    # Internal: force hand-up due to uncertainty
    # -----------------------------------------------------------------------

    async def _force_handup_via_uncertainty(self) -> None:
        from src.core.schemas import TriageOutput
        self.pending_classification = TriageOutput(
            tier="hand_up",
            reason="Uncertainty escalation — tool loop or validation failure.",
            triggered_rules=[],
            uncertainty=True,
            next_action="request_doctor_review",
        )
        log.warning("force_handup_uncertainty", call_sid=self.call_sid)

    async def _terminate_call(self) -> None:
        self.state = SessionState.ENDED
