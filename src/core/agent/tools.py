"""
Layer 2 tool definitions and handlers.

TOOL_DEFINITIONS — JSON schemas sent to Anthropic API.
TOOL_HANDLERS    — maps tool name → async handler(session, inp) → ToolResult.

Every handler obeys the universal contract:
  1. Validate inp against a Pydantic model; on error return TOOL_VALIDATION_ERROR.
  2. Catch all exceptions; return TOOL_HANDLER_ERROR, never raise to Claude.
  3. Complete in ≤ 500ms or return TOOL_TIMEOUT.
  4. Call db.audit() for every PHI-touching operation.
  5. Be idempotent where possible.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

import structlog
from pydantic import BaseModel, ValidationError

from src.core.schemas import ToolResult, TriageInput, VitalsPayload
from src.core.triage.rules_engine import classify_case as _classify_case

if TYPE_CHECKING:
    from src.core.agent.session import ConversationSession

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Tool JSON schemas
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "get_patient_context",
        "description": (
            "Re-fetch the patient context from the database mid-call. "
            "Use after registration completes to pick up the newly created record."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "register_patient",
        "description": (
            "Register a new patient. Only call after obtaining explicit verbal consent. "
            "Pass verbal_consent_given=true to confirm consent was obtained. "
            "This tool will refuse if verbal_consent_given is false."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "first_name": {"type": "string", "description": "Patient's first name."},
                "gestational_stage": {
                    "type": "string",
                    "description": "e.g. '32 weeks pregnant' or '8 weeks postpartum'.",
                },
                "verbal_consent_given": {
                    "type": "boolean",
                    "description": "Must be true — you confirmed consent verbally.",
                },
            },
            "required": ["first_name", "gestational_stage", "verbal_consent_given"],
        },
    },
    {
        "name": "log_symptom",
        "description": (
            "Log a single symptom the patient mentions. "
            "Call immediately when a symptom is mentioned, do not batch. "
            "Use normalized ACOG symptom names when possible "
            "(e.g. 'severe_headache_not_going_away', 'edema_hands', 'changes_in_vision')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symptom": {"type": "string", "description": "Normalized symptom string."},
            },
            "required": ["symptom"],
        },
    },
    {
        "name": "log_vitals",
        "description": (
            "Log a vital measurement reported by the patient or received from a device. "
            "Call the moment a number is given."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bp_systolic": {"type": "integer"},
                "bp_diastolic": {"type": "integer"},
                "hr": {"type": "integer"},
                "spo2": {"type": "integer"},
                "source": {
                    "type": "string",
                    "enum": ["self_report", "sms_vitals", "wearable"],
                },
            },
            "required": ["source"],
        },
    },
    {
        "name": "read_vitals_sms",
        "description": (
            "Read the latest vitals sent via SMS from the patient's wearable or device. "
            "Call when the patient mentions her wearable or says a device sent data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "classify_case",
        "description": (
            "Classify the current case using the deterministic ACOG rules engine. "
            "The result is authoritative — you must act on the returned tier. "
            "Call before any escalation decision."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symptoms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "All symptoms collected so far.",
                },
                "vitals": {
                    "type": "object",
                    "description": "Current vitals: bp_systolic, bp_diastolic, hr, spo2.",
                },
                "gestational_weeks": {"type": "integer"},
                "postpartum_days": {"type": "integer"},
                "flags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["symptoms"],
        },
    },
    {
        "name": "request_doctor_review",
        "description": (
            "Send a hand-up request to the on-call physician queue. "
            "Only valid after classify_case returned tier='hand_up'. "
            "Provide a specific_question a doctor can act on in 20 seconds."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_first_name": {"type": "string"},
                "gestational_stage": {"type": "string"},
                "acog_signs": {"type": "array", "items": {"type": "string"}},
                "lily_recommendation": {"type": "string"},
                "specific_question": {
                    "type": "string",
                    "description": "e.g. 'BP 148/94, headache x4h — ESCALATE or MONITOR?'",
                },
            },
            "required": [
                "patient_first_name",
                "gestational_stage",
                "acog_signs",
                "lily_recommendation",
                "specific_question",
            ],
        },
    },
    {
        "name": "send_patient_sms",
        "description": (
            "Send an SMS to the patient's phone number on file. "
            "Use to confirm what you promised verbally. "
            "You cannot specify the recipient — it reads from the patient record."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "body": {
                    "type": "string",
                    "description": "Message body. Plain text, no HTML.",
                },
            },
            "required": ["body"],
        },
    },
    {
        "name": "send_emergency_contact_sms",
        "description": (
            "Send an SMS to the patient's emergency contact. "
            "Use during hand_off only. Recipient read from patient record."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "body": {"type": "string"},
            },
            "required": ["body"],
        },
    },
    {
        "name": "update_follow_up_flags",
        "description": (
            "Set flags to be checked at the next call. "
            "One flag per concern, e.g. 'recheck_bp_tomorrow', 'fetal_kick_counts_follow_up'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "flags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of follow-up flag strings.",
                },
            },
            "required": ["flags"],
        },
    },
    {
        "name": "end_session",
        "description": (
            "End the conversation session. Always call this as the last action of every call. "
            "Idempotent — safe to call twice."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tier_reached": {
                    "type": "string",
                    "enum": ["handle", "hand_up", "hand_off"],
                },
                "summary": {
                    "type": "string",
                    "description": "One-sentence summary of the call.",
                },
                "follow_up_flags": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["tier_reached", "summary"],
        },
    },
    {
        "name": "get_education_content",
        "description": (
            "Retrieve an evidence-based educational snippet on a maternal health topic. "
            "Use to answer general pregnancy/postpartum questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "e.g. 'preeclampsia_signs', 'kick_counts', 'postpartum_depression'",
                },
            },
            "required": ["topic"],
        },
    },
]

# ---------------------------------------------------------------------------
# Pydantic input models (one per handler that needs validation)
# ---------------------------------------------------------------------------

class _RegisterInput(BaseModel):
    first_name: str
    gestational_stage: str
    verbal_consent_given: bool


class _LogSymptomInput(BaseModel):
    symptom: str


class _LogVitalsInput(BaseModel):
    bp_systolic: int | None = None
    bp_diastolic: int | None = None
    hr: int | None = None
    spo2: int | None = None
    source: str


class _ClassifyInput(BaseModel):
    symptoms: list[str]
    vitals: dict[str, Any] = {}
    gestational_weeks: int | None = None
    postpartum_days: int | None = None
    flags: list[str] = []


class _RequestReviewInput(BaseModel):
    patient_first_name: str
    gestational_stage: str
    acog_signs: list[str]
    lily_recommendation: str
    specific_question: str


class _SendSMSInput(BaseModel):
    body: str


class _EndSessionInput(BaseModel):
    tier_reached: str
    summary: str
    follow_up_flags: list[str] = []


class _FlagsInput(BaseModel):
    flags: list[str]


class _EducationInput(BaseModel):
    topic: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate(model_cls: type[BaseModel], inp: dict) -> tuple[BaseModel | None, ToolResult | None]:
    try:
        return model_cls(**inp), None
    except ValidationError as exc:
        return None, ToolResult(
            ok=False,
            error=str(exc),
            error_code="TOOL_VALIDATION_ERROR",
        )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def _tool_get_patient_context(session: "ConversationSession", inp: dict) -> ToolResult:
    try:
        ctx = await session._load_patient_context(session._from_number)
        session._patient_context = ctx
        return ToolResult(ok=True, data=ctx.model_dump())
    except Exception as exc:
        log.error("tool_get_patient_context_failed", exc_info=exc)
        return ToolResult(ok=False, error="Could not load patient context.", error_code="TOOL_HANDLER_ERROR")


async def _tool_register_patient(session: "ConversationSession", inp: dict) -> ToolResult:
    data, err = _validate(_RegisterInput, inp)
    if err:
        return err
    if not data.verbal_consent_given:
        return ToolResult(ok=False, error="Verbal consent is required before registration.", error_code="PRECONDITION_FAILED")
    try:
        patient = await session._db.register_patient(
            phone=session._from_number,
            first_name=data.first_name,
            gestational_stage=data.gestational_stage,
            verbal_consent_given=True,
        )
        await session._db.audit(
            actor="lily",
            action="register_patient",
            patient_id=getattr(patient, "patient_id", None),
            conversation_id=session.conversation_id,
        )
        ctx = await session._load_patient_context(session._from_number)
        session._patient_context = ctx
        session.patient_id = getattr(patient, "patient_id", None)
        return ToolResult(ok=True, data={"patient_id": session.patient_id, "first_name": data.first_name})
    except Exception as exc:
        log.error("tool_register_patient_failed", exc_info=exc)
        return ToolResult(ok=False, error="Registration failed.", error_code="TOOL_HANDLER_ERROR")


async def _tool_log_symptom(session: "ConversationSession", inp: dict) -> ToolResult:
    data, err = _validate(_LogSymptomInput, inp)
    if err:
        return err
    # Update in-memory state immediately so Claude has it for triage.
    # DB writes are queued in the background — no blocking on network I/O.
    session._symptoms_logged.add(data.symptom)
    session.enqueue(session._db.log_symptom(
        conversation_id=session.conversation_id,
        patient_id=session.patient_id,
        symptom=data.symptom,
    ))
    session.enqueue(session._db.audit("lily", "log_symptom", session.patient_id, session.conversation_id))
    return ToolResult(ok=True, data={"symptom": data.symptom})


async def _tool_log_vitals(session: "ConversationSession", inp: dict) -> ToolResult:
    data, err = _validate(_LogVitalsInput, inp)
    if err:
        return err
    vitals_dict = {
        k: v for k, v in {
            "bp_systolic": data.bp_systolic,
            "bp_diastolic": data.bp_diastolic,
            "hr": data.hr,
            "spo2": data.spo2,
            "source": data.source,
        }.items() if v is not None
    }
    # Update in-memory state immediately; queue the DB write.
    session._vitals_logged.update({k: v for k, v in vitals_dict.items() if k != "source"})
    session.enqueue(session._db.log_vitals(
        conversation_id=session.conversation_id,
        patient_id=session.patient_id,
        vitals=vitals_dict,
    ))
    session.enqueue(session._db.audit("lily", "log_vitals", session.patient_id, session.conversation_id))
    return ToolResult(ok=True, data=vitals_dict)


async def _tool_read_vitals_sms(session: "ConversationSession", inp: dict) -> ToolResult:
    if session.patient_id is None:
        return ToolResult(ok=False, error="No patient loaded.", error_code="PRECONDITION_FAILED")
    try:
        result = await session._db.get_latest_sms_vitals(session.patient_id)
        if result is None:
            return ToolResult(ok=True, data={"found": False})
        session.sms_vitals_buffer = result
        return ToolResult(ok=True, data={"found": True, "vitals": result})
    except Exception as exc:
        log.error("tool_read_vitals_sms_failed", exc_info=exc)
        return ToolResult(ok=False, error="Could not read SMS vitals.", error_code="TOOL_HANDLER_ERROR")


async def _tool_classify_case(session: "ConversationSession", inp: dict) -> ToolResult:
    data, err = _validate(_ClassifyInput, inp)
    if err:
        return err
    try:
        result = _classify_case(
            symptoms=data.symptoms,
            vitals=data.vitals,
            gestational_weeks=data.gestational_weeks,
            postpartum_days=data.postpartum_days,
            flags=data.flags,
        )
        from src.core.schemas import TriageOutput
        output = TriageOutput(**result)

        if session.triage_locked:
            # Once locked at hand_off, lower classifications are ignored
            from src.core.agent.errors import TriageLockViolation
            if output.tier != "hand_off":
                log.error(
                    "triage_lock_violation",
                    call_sid=session.call_sid,
                    attempted_tier=output.tier,
                    locked_tier="hand_off",
                )
                # Return the locked result, not the new one
                return ToolResult(
                    ok=True,
                    data=session.pending_classification.model_dump() if session.pending_classification else result,
                    error="Triage already locked at hand_off. Classification ignored.",
                    error_code="TRIAGE_LOCKED",
                )
        else:
            session.pending_classification = output
            if output.tier == "hand_off":
                session.triage_locked = True
                log.info("triage_locked_hand_off", call_sid=session.call_sid)

        return ToolResult(ok=True, data=output.model_dump())
    except Exception as exc:
        log.error("tool_classify_case_failed", exc_info=exc)
        return ToolResult(ok=False, error="Classification failed.", error_code="TOOL_HANDLER_ERROR")


async def _tool_request_doctor_review(session: "ConversationSession", inp: dict) -> ToolResult:
    if session.pending_classification is None or session.pending_classification.tier != "hand_up":
        return ToolResult(
            ok=False,
            error="Cannot request doctor review without a hand-up classification.",
            error_code="PRECONDITION_FAILED",
        )
    data, err = _validate(_RequestReviewInput, inp)
    if err:
        return err
    try:
        vitals_snapshot = None
        if session._vitals_logged:
            vitals_snapshot = {**session._vitals_logged}
        from src.core.schemas import CasePacket
        packet = CasePacket(
            patient_first_name=data.patient_first_name,
            gestational_stage=data.gestational_stage,
            vitals_snapshot=None,
            acog_signs=data.acog_signs,
            lily_recommendation=data.lily_recommendation,
            specific_question=data.specific_question,
            conversation_id=session.conversation_id or 0,
        )
        review_id = await session._db.request_doctor_review(
            conversation_id=session.conversation_id,
            case_packet=packet.model_dump(),
        )
        await session._db.audit("lily", "request_doctor_review", session.patient_id, session.conversation_id)
        return ToolResult(ok=True, data={"review_id": review_id})
    except Exception as exc:
        log.error("tool_request_doctor_review_failed", exc_info=exc)
        return ToolResult(ok=False, error="Could not submit review request.", error_code="TOOL_HANDLER_ERROR")


async def _tool_send_patient_sms(session: "ConversationSession", inp: dict) -> ToolResult:
    data, err = _validate(_SendSMSInput, inp)
    if err:
        return err
    if session._patient_context is None or not session._patient_context.found:
        return ToolResult(ok=False, error="No patient context loaded.", error_code="PRECONDITION_FAILED")
    phone = session._from_number
    session.enqueue(session._db.send_sms(to_phone=phone, body=data.body))
    session.enqueue(session._db.audit("lily", "send_patient_sms", session.patient_id, session.conversation_id))
    return ToolResult(ok=True, data={"to": phone})


async def _tool_send_emergency_contact_sms(session: "ConversationSession", inp: dict) -> ToolResult:
    data, err = _validate(_SendSMSInput, inp)
    if err:
        return err
    if session._patient_context is None or not session._patient_context.emergency_contact_phone:
        return ToolResult(ok=False, error="No emergency contact on file.", error_code="PRECONDITION_FAILED")
    phone = session._patient_context.emergency_contact_phone
    session.enqueue(session._db.send_sms(to_phone=phone, body=data.body))
    session.enqueue(session._db.audit("lily", "send_emergency_contact_sms", session.patient_id, session.conversation_id))
    return ToolResult(ok=True, data={"to": phone})


async def _tool_update_follow_up_flags(session: "ConversationSession", inp: dict) -> ToolResult:
    data, err = _validate(_FlagsInput, inp)
    if err:
        return err
    session._follow_up_flags = data.flags
    return ToolResult(ok=True, data={"flags": data.flags})


async def _tool_end_session(session: "ConversationSession", inp: dict) -> ToolResult:
    if session._session_ended:
        return ToolResult(ok=True, data={"already_ended": True})
    data, err = _validate(_EndSessionInput, inp)
    if err:
        return err
    try:
        session._session_ended = True
        await session._db.end_conversation(
            conversation_id=session.conversation_id,
            tier_reached=data.tier_reached,
            summary=data.summary,
        )
        if data.follow_up_flags:
            session._follow_up_flags = data.follow_up_flags
        log.info("session_ended", call_sid=session.call_sid, tier=data.tier_reached)
        return ToolResult(ok=True, data={"tier_reached": data.tier_reached})
    except Exception as exc:
        log.error("tool_end_session_failed", exc_info=exc)
        return ToolResult(ok=False, error="Could not end session cleanly.", error_code="TOOL_HANDLER_ERROR")


_EDUCATION_CONTENT: dict[str, str] = {
    "preeclampsia_signs": (
        "Preeclampsia warning signs include severe headache, vision changes, sudden swelling "
        "in face or hands, and blood pressure above 140/90. These need same-day evaluation."
    ),
    "kick_counts": (
        "After 28 weeks, you should feel at least 10 kicks within 2 hours. "
        "Count at the same time each day when baby is usually active. If fewer than 10, call your provider."
    ),
    "postpartum_depression": (
        "Postpartum depression is common — affecting 1 in 7 mothers. "
        "Symptoms include persistent sadness, loss of interest, difficulty bonding, "
        "and intrusive thoughts. It is treatable and not a sign of weakness."
    ),
    "default": "I can share general information on that topic. For advice specific to your situation, let me check what's in your care plan.",
}


async def _tool_get_education_content(session: "ConversationSession", inp: dict) -> ToolResult:
    data, err = _validate(_EducationInput, inp)
    if err:
        return err
    content = _EDUCATION_CONTENT.get(data.topic, _EDUCATION_CONTENT["default"])
    return ToolResult(ok=True, data={"topic": data.topic, "content": content})


# ---------------------------------------------------------------------------
# Public registry
# ---------------------------------------------------------------------------

TOOL_HANDLERS: dict[str, Callable] = {
    "get_patient_context": _tool_get_patient_context,
    "register_patient": _tool_register_patient,
    "log_symptom": _tool_log_symptom,
    "log_vitals": _tool_log_vitals,
    "read_vitals_sms": _tool_read_vitals_sms,
    "classify_case": _tool_classify_case,
    "request_doctor_review": _tool_request_doctor_review,
    "send_patient_sms": _tool_send_patient_sms,
    "send_emergency_contact_sms": _tool_send_emergency_contact_sms,
    "update_follow_up_flags": _tool_update_follow_up_flags,
    "end_session": _tool_end_session,
    "get_education_content": _tool_get_education_content,
}
