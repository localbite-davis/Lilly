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

# RAG is best-effort — if the knowledge_base module or its deps are missing,
# the call should still work, just without retrieved context.
try:
    from knowledge_base.retrieve import rag_for_turn  # type: ignore
    _RAG_AVAILABLE = True
except Exception:  # pragma: no cover — module isn't on the import path or chroma not built
    rag_for_turn = None  # type: ignore
    _RAG_AVAILABLE = False
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


class AsyncWriteQueue:
    """
    Runs DB writes in a background asyncio task so tool handlers can return
    immediately to Claude without blocking on network round-trips.

    Usage:
        queue.enqueue(db.log_symptom(...))   # fire-and-forget
        await queue.drain()                  # call before closing the session
    """

    def __init__(self) -> None:
        self._q: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._worker())

    def enqueue(self, coro) -> None:
        self._q.put_nowait(coro)

    async def drain(self) -> None:
        """Block until all queued writes complete."""
        await self._q.join()
        if self._task:
            self._task.cancel()
            self._task = None

    async def _worker(self) -> None:
        while True:
            coro = await self._q.get()
            try:
                await coro
            except Exception as exc:
                log.error("write_queue_failed", exc_info=exc)
            finally:
                self._q.task_done()


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
        self._language: str = settings.default_language
        # Buffer for user messages that arrive while a brain turn holds the lock.
        # Drained inside the lock so history never ends with an assistant message.
        self._pending_user_messages: list[dict] = []
        self._language_locked: bool = False

        # RAG addendum for the current user turn — set in on_user_final, read
        # in _stream_one_response, persists through tool-resolution loops so
        # follow-up Claude calls in the same turn keep the same context.
        self._rag_addendum: str = ""

        self.tts_stream: TTSStreamLike | None = None
        self._brain_task: asyncio.Task | None = None
        self._turn_lock = asyncio.Lock()

        self._anthropic = anthropic
        self._tts_factory = tts_factory
        self.tts_factory = tts_factory   # public alias for tests
        self._db = db
        self._rules_engine = rules_engine
        self._write_queue = AsyncWriteQueue()
        self._chunker = TextChunker(
            max_chars=settings.tts_chunk_max_chars,
            min_chars=settings.tts_chunk_min_chars,
        )

    # -----------------------------------------------------------------------
    # Public Layer-1-facing API
    # -----------------------------------------------------------------------

    def enqueue(self, coro) -> None:
        """Fire-and-forget a DB write coroutine. Runs in the background worker."""
        self._write_queue.enqueue(coro)

    async def start(self, from_number: str, outbound_context: dict | None = None) -> None:
        self._write_queue.start()
        self._from_number = from_number

        # Load patient BEFORE creating the conversation so the FK is set correctly.
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

        self.conversation_id = await self._db.create_conversation(
            patient_id=self.patient_id,  # correctly None for new callers, set for known patients
            call_sid=self.call_sid,
            direction=self.direction,
        )

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
        # Lock language on first detected turn
        if not self._language_locked and payload.detected_language:
            self._language = payload.detected_language
            self._language_locked = True
            log.info(
                "language_detected",
                call_sid=self.call_sid,
                language=self._language,
            )
        self._pending_user_messages.append({"role": "user", "content": payload.transcript})

        # Run RAG retrieval BEFORE the brain turn. Best-effort — if classify
        # or retrieve fails, we proceed without retrieved context rather than
        # break the call. Smalltalk turns return has_context=False and we
        # skip injection (saves ~150ms per turn).
        self._rag_addendum = await self._compute_rag_addendum(payload.transcript)

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
        await self._write_queue.drain()

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

        # Generate summary and persist to Pinecone in the background.
        # Only worth summarizing if there was actual conversation content.
        if self.patient_id is not None and len(self.message_history) > 2:
            asyncio.ensure_future(self._summarize_and_store())

        self.state = SessionState.ENDED

    async def _summarize_and_store(self) -> None:
        """Build transcript, summarize via Claude Haiku, save to Pinecone."""
        from src.core.memory.summarizer import summarize_call, save_call_summary
        try:
            transcript = self._build_transcript()
            tier = self.pending_classification.tier if self.pending_classification else "handle"
            summary = await summarize_call(
                transcript=transcript,
                symptoms=list(self._symptoms_logged),
                vitals=dict(self._vitals_logged),
                tier=tier,
            )
            await save_call_summary(
                patient_id=self.patient_id,
                conversation_id=self.conversation_id,
                summary=summary,
            )
            log.info("pinecone_summary_saved", patient_id=self.patient_id)
        except Exception as exc:
            log.warning("summarize_and_store_failed", exc_info=exc)

    def _build_transcript(self) -> str:
        """Flatten message_history into a readable transcript string."""
        lines = []
        for msg in self.message_history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, str):
                if content == "<call_started>":
                    continue
                speaker = "Patient" if role == "user" else "Lily"
                lines.append(f"{speaker}: {content}")
            elif isinstance(content, list):
                # Tool result blocks — skip for transcript
                pass
        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Internal: RAG retrieval for the current user turn
    # -----------------------------------------------------------------------

    async def _compute_rag_addendum(self, user_text: str) -> str:
        """
        Best-effort RAG retrieval. Returns an addendum string to append to
        the system prompt, or "" on smalltalk turns / errors.

        Smalltalk turns ("hey lily", "thanks", "okay") classify as
        non-clinical / non-navigational / non-emotional and skip retrieval
        entirely — saves ~150ms per turn and avoids polluting the prompt.
        """
        if not _RAG_AVAILABLE or rag_for_turn is None:
            return ""
        try:
            rag = await rag_for_turn(user_text, base_system_prompt="")
        except Exception as exc:
            log.warning("rag_failed", call_sid=self.call_sid, error=repr(exc))
            return ""

        if not rag.has_context or not rag.addendum:
            log.info("rag_skipped", call_sid=self.call_sid, reason="smalltalk")
            return ""

        log.info(
            "rag_injected",
            call_sid=self.call_sid,
            chunks=len(rag.chunks),
            classification=(
                f"clinical={rag.classification.is_clinical}"
                f" nav={rag.classification.is_navigational}"
                f" emotional={rag.classification.is_emotional}"
            ),
            actions=rag.action_types_retrieved,
        )
        return rag.addendum

    # -----------------------------------------------------------------------
    # Internal: the turn loop
    # -----------------------------------------------------------------------

    async def _run_brain_turn(self) -> None:
        async with self._turn_lock:
            # Drain buffered user messages into history atomically under the lock.
            # This prevents the history from ending with an assistant message when
            # two transcripts arrive during a single brain turn (400 prefill error).
            while self._pending_user_messages:
                self.message_history.append(self._pending_user_messages.pop(0))
            self.state = SessionState.THINKING
            loop_start = time.monotonic()
            try:
                voice_id = (
                    settings.lily_voice_id_es or settings.lily_voice_id
                    if self._language == "es"
                    else settings.lily_voice_id
                )
                self.tts_stream = await self._tts_factory.open_stream(
                    call_sid=self.call_sid,
                    voice_id=voice_id,
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

        # Build the system prompt and append the RAG addendum if we
        # retrieved any (only set on clinical/navigational/emotional turns).
        base_system = build_system_prompt(
            self._patient_context or PatientContext(found=False),
            language=self._language,
        )
        system_prompt = base_system
        if self._rag_addendum:
            system_prompt = base_system + [{"type": "text", "text": self._rag_addendum}]

        try:
            async for event in stream_turn(
                client=self._anthropic,
                model=settings.lily_model,
                system=system_prompt,
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
                        handler(self, tu.input), timeout=settings.brain_tool_timeout_s
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
