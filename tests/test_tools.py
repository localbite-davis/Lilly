"""Tests for tools.py — Stage 5.3."""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from src.core.agent.mocks.mock_anthropic import MockAnthropicClient
from src.core.agent.mocks.mock_db import MockDB, MockPatient
from src.core.agent.mocks.mock_tts import MockTTSFactory
from src.core.agent.tools import TOOL_HANDLERS
from src.core.schemas import PatientContext, TriageOutput

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers to build a minimal session without full ConversationSession machinery
# ---------------------------------------------------------------------------

def make_session(db: MockDB, patient: MockPatient | None = None):
    from src.core.agent.session import ConversationSession
    from src.core.triage.rules_engine import classify_case

    s = ConversationSession(
        call_sid="CAtest001",
        direction="inbound",
        anthropic=MockAnthropicClient(),
        tts_factory=MockTTSFactory(),
        db=db,
        rules_engine=classify_case,
    )
    s.conversation_id = 1
    s._from_number = "+15550001234"
    s._write_queue.start()  # start background worker for enqueued DB writes

    if patient:
        s.patient_id = patient.patient_id
        s._patient_context = PatientContext(
            found=True,
            patient_id=patient.patient_id,
            first_name=patient.first_name,
            gestational_stage=patient.gestational_stage,
            emergency_contact_phone=patient.emergency_contact_phone,
            emergency_contact_name=patient.emergency_contact_name,
        )
    return s


# ---------------------------------------------------------------------------
# log_symptom
# ---------------------------------------------------------------------------

async def test_log_symptom_happy(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    result = await TOOL_HANDLERS["log_symptom"](s, {"symptom": "headache"})
    assert result.ok
    # Symptom is in session memory immediately
    assert "headache" in s._symptoms_logged
    # DB write is queued — drain before checking the mock DB
    await s._write_queue.drain()
    assert mock_db.symptoms[0]["symptom"] == "headache"


async def test_log_symptom_validation_error(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    result = await TOOL_HANDLERS["log_symptom"](s, {})
    assert not result.ok
    assert result.error_code == "TOOL_VALIDATION_ERROR"


async def test_log_symptom_db_failure(mock_db, monkeypatch):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)

    async def bad(*a, **kw):
        raise RuntimeError("DB down")

    monkeypatch.setattr(mock_db, "log_symptom", bad)
    result = await TOOL_HANDLERS["log_symptom"](s, {"symptom": "headache"})
    # Tool returns ok=True immediately — DB failures are fire-and-forget,
    # logged by the queue worker but not surfaced to Claude.
    assert result.ok
    assert "headache" in s._symptoms_logged


# ---------------------------------------------------------------------------
# log_vitals
# ---------------------------------------------------------------------------

async def test_log_vitals_happy(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    result = await TOOL_HANDLERS["log_vitals"](s, {
        "bp_systolic": 148, "bp_diastolic": 94, "source": "self_report"
    })
    assert result.ok
    # Vitals in session memory immediately
    assert s._vitals_logged["bp_systolic"] == 148
    # Drain queue before checking mock DB
    await s._write_queue.drain()
    assert mock_db.vitals[0]["bp_systolic"] == 148


async def test_log_vitals_validation_error(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    result = await TOOL_HANDLERS["log_vitals"](s, {"bp_systolic": 148})  # missing source
    assert not result.ok
    assert result.error_code == "TOOL_VALIDATION_ERROR"


async def test_log_vitals_db_failure(mock_db, monkeypatch):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)

    async def bad(*a, **kw):
        raise RuntimeError("DB down")

    monkeypatch.setattr(mock_db, "log_vitals", bad)
    result = await TOOL_HANDLERS["log_vitals"](s, {"bp_systolic": 148, "source": "self_report"})
    # Tool returns ok=True immediately — DB failure is swallowed by the queue worker.
    assert result.ok
    assert s._vitals_logged["bp_systolic"] == 148


# ---------------------------------------------------------------------------
# classify_case — the safety-critical handler
# ---------------------------------------------------------------------------

async def test_classify_case_happy_handle(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    result = await TOOL_HANDLERS["classify_case"](s, {"symptoms": ["mild_nausea"]})
    assert result.ok
    assert result.data["tier"] == "handle"
    assert not s.triage_locked


async def test_classify_case_hand_up(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    result = await TOOL_HANDLERS["classify_case"](s, {"symptoms": ["severe_headache_not_going_away"]})
    assert result.ok
    assert result.data["tier"] == "hand_up"
    assert not s.triage_locked
    assert s.pending_classification.tier == "hand_up"


async def test_classify_case_hand_off_locks_session(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    result = await TOOL_HANDLERS["classify_case"](s, {"symptoms": ["seizures"]})
    assert result.ok
    assert result.data["tier"] == "hand_off"
    assert s.triage_locked
    assert s.pending_classification.tier == "hand_off"


async def test_classify_case_lock_ignores_lower_tier(mock_db):
    """Once locked at hand_off, a follow-up classify returning handle must be ignored."""
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    # First: lock to hand_off
    await TOOL_HANDLERS["classify_case"](s, {"symptoms": ["seizures"]})
    assert s.triage_locked

    # Second: attempt to classify with mild symptom — must not downgrade
    result = await TOOL_HANDLERS["classify_case"](s, {"symptoms": ["mild_nausea"]})
    assert result.ok
    assert result.error_code == "TRIAGE_LOCKED"
    assert s.pending_classification.tier == "hand_off"  # unchanged


async def test_classify_case_validation_error(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    result = await TOOL_HANDLERS["classify_case"](s, {})  # missing symptoms
    assert not result.ok
    assert result.error_code == "TOOL_VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# request_doctor_review — precondition enforcement
# ---------------------------------------------------------------------------

async def test_request_doctor_review_requires_hand_up(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    # No classification set
    result = await TOOL_HANDLERS["request_doctor_review"](s, {
        "patient_first_name": "Maria",
        "gestational_stage": "32 weeks",
        "acog_signs": ["headache"],
        "lily_recommendation": "Evaluate",
        "specific_question": "ESCALATE?",
    })
    assert not result.ok
    assert result.error_code == "PRECONDITION_FAILED"


async def test_request_doctor_review_wrong_tier(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    s.pending_classification = TriageOutput(
        tier="handle", reason="OK", triggered_rules=[], uncertainty=False, next_action="continue"
    )
    result = await TOOL_HANDLERS["request_doctor_review"](s, {
        "patient_first_name": "Maria",
        "gestational_stage": "32 weeks",
        "acog_signs": [],
        "lily_recommendation": "Monitor",
        "specific_question": "Check?",
    })
    assert not result.ok
    assert result.error_code == "PRECONDITION_FAILED"


async def test_request_doctor_review_happy(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    s.pending_classification = TriageOutput(
        tier="hand_up", reason="BP elevated", triggered_rules=["systolic_bp_over_140"],
        uncertainty=False, next_action="request review"
    )
    result = await TOOL_HANDLERS["request_doctor_review"](s, {
        "patient_first_name": "Maria",
        "gestational_stage": "32 weeks pregnant",
        "acog_signs": ["systolic_bp_over_140"],
        "lily_recommendation": "Physician evaluation needed.",
        "specific_question": "BP 148/94, headache — ESCALATE or MONITOR?",
    })
    assert result.ok
    assert len(mock_db.reviews) == 1
    assert mock_db.reviews[0]["case_packet"]["specific_question"] == "BP 148/94, headache — ESCALATE or MONITOR?"


async def test_request_doctor_review_db_failure(mock_db, monkeypatch):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    s.pending_classification = TriageOutput(
        tier="hand_up", reason="test", triggered_rules=[], uncertainty=False, next_action="review"
    )

    async def bad(*a, **kw):
        raise RuntimeError("DB down")

    monkeypatch.setattr(mock_db, "request_doctor_review", bad)
    result = await TOOL_HANDLERS["request_doctor_review"](s, {
        "patient_first_name": "Maria",
        "gestational_stage": "32 weeks",
        "acog_signs": [],
        "lily_recommendation": "x",
        "specific_question": "x?",
    })
    assert not result.ok
    assert result.error_code == "TOOL_HANDLER_ERROR"


# ---------------------------------------------------------------------------
# send_patient_sms
# ---------------------------------------------------------------------------

async def test_send_patient_sms_happy(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    result = await TOOL_HANDLERS["send_patient_sms"](s, {"body": "Doctor will call soon."})
    assert result.ok
    await s._write_queue.drain()
    assert mock_db.sms_sent[0]["body"] == "Doctor will call soon."


async def test_send_patient_sms_no_patient(mock_db):
    s = make_session(mock_db)  # no patient loaded
    result = await TOOL_HANDLERS["send_patient_sms"](s, {"body": "Hello"})
    assert not result.ok
    assert result.error_code == "PRECONDITION_FAILED"


async def test_send_patient_sms_validation_error(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    result = await TOOL_HANDLERS["send_patient_sms"](s, {})
    assert not result.ok
    assert result.error_code == "TOOL_VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# end_session — idempotency
# ---------------------------------------------------------------------------

async def test_end_session_happy(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    result = await TOOL_HANDLERS["end_session"](s, {
        "tier_reached": "handle",
        "summary": "Maria feeling better.",
    })
    assert result.ok
    assert result.data["tier_reached"] == "handle"
    assert s._session_ended


async def test_end_session_idempotent(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    await TOOL_HANDLERS["end_session"](s, {"tier_reached": "handle", "summary": "ok"})
    result2 = await TOOL_HANDLERS["end_session"](s, {"tier_reached": "hand_up", "summary": "again"})
    assert result2.ok
    assert result2.data.get("already_ended") is True
    # DB should only have one ended conversation
    ended = [c for c in mock_db.conversations if c.get("tier_reached") is not None]
    assert len(ended) <= 1


async def test_end_session_validation_error(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    result = await TOOL_HANDLERS["end_session"](s, {})
    assert not result.ok
    assert result.error_code == "TOOL_VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# read_vitals_sms
# ---------------------------------------------------------------------------

async def test_read_vitals_sms_no_data(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    result = await TOOL_HANDLERS["read_vitals_sms"](s, {})
    assert result.ok
    assert result.data["found"] is False


async def test_read_vitals_sms_with_data(mock_db):
    patient = mock_db._patients["+15550001234"]
    mock_db.inject_sms_vitals(1, {"hr": 102, "spo2": 97})
    s = make_session(mock_db, patient)
    result = await TOOL_HANDLERS["read_vitals_sms"](s, {})
    assert result.ok
    assert result.data["found"] is True
    assert result.data["vitals"]["hr"] == 102


# ---------------------------------------------------------------------------
# register_patient — consent gate
# ---------------------------------------------------------------------------

async def test_register_patient_requires_consent(mock_db):
    s = make_session(mock_db)
    s._patient_context = PatientContext(found=False)
    result = await TOOL_HANDLERS["register_patient"](s, {
        "first_name": "Ana",
        "gestational_stage": "28 weeks pregnant",
        "verbal_consent_given": False,
    })
    assert not result.ok
    assert result.error_code == "PRECONDITION_FAILED"


async def test_register_patient_happy(mock_db):
    s = make_session(mock_db)
    s._patient_context = PatientContext(found=False)
    result = await TOOL_HANDLERS["register_patient"](s, {
        "first_name": "Ana",
        "gestational_stage": "28 weeks pregnant",
        "verbal_consent_given": True,
    })
    assert result.ok
    assert result.data["first_name"] == "Ana"


# ---------------------------------------------------------------------------
# send_emergency_contact_sms
# ---------------------------------------------------------------------------

async def test_send_ec_sms_happy(mock_db):
    patient = mock_db._patients["+15550001234"]
    s = make_session(mock_db, patient)
    result = await TOOL_HANDLERS["send_emergency_contact_sms"](s, {"body": "Maria needs help."})
    assert result.ok
    await s._write_queue.drain()
    assert mock_db.sms_sent[0]["to"] == "+15550009999"


async def test_send_ec_sms_no_contact(mock_db):
    s = make_session(mock_db)
    s._patient_context = PatientContext(found=True, patient_id=99, first_name="X", gestational_stage="unknown")
    result = await TOOL_HANDLERS["send_emergency_contact_sms"](s, {"body": "Help!"})
    assert not result.ok
    assert result.error_code == "PRECONDITION_FAILED"


# ---------------------------------------------------------------------------
# Unknown tool name
# ---------------------------------------------------------------------------

async def test_unknown_tool_name_not_in_registry():
    assert "nonexistent_tool" not in TOOL_HANDLERS
