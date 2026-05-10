"""
E2E: Hand-off path — vision changes + headache → immediate emergency.
Verifies triage lock, text suppression, and emergency contact SMS.
"""

from __future__ import annotations

import asyncio

import pytest

from src.core.agent.mocks.mock_anthropic import MockAnthropicClient
from src.core.agent.mocks.mock_db import MockDB, MockPatient
from src.core.agent.mocks.mock_tts import MockTTSFactory
from src.core.agent.session import ConversationSession, SessionState
from src.core.schemas import UserFinalPayload
from src.core.triage.rules_engine import classify_case


def _payload(text: str) -> UserFinalPayload:
    return UserFinalPayload(
        call_sid="CAe2e_handoff",
        transcript=text,
        confidence=0.96,
        started_at_ms=0,
        ended_at_ms=2500,
    )


def _make_db() -> MockDB:
    db = MockDB()
    db.seed_patient(MockPatient(
        patient_id=1,
        phone="+15550001234",
        first_name="Maria",
        gestational_stage="32 weeks pregnant",
        emergency_contact_phone="+15550009999",
        emergency_contact_name="Rosa",
    ))
    return db


async def test_e2e_handoff_path():
    db = _make_db()
    client = MockAnthropicClient()

    # Greeting
    client.queue_text("Hi Maria, I'm here. What's happening?")

    # Iteration 1: log symptoms + vitals + classify (batched)
    t1 = client.new_turn()
    t1.add_tool("log_symptom", {"symptom": "changes_in_vision"})
    t1.add_tool("log_symptom", {"symptom": "severe_headache_not_going_away"})
    t1.add_tool("log_vitals", {"bp_systolic": 165, "bp_diastolic": 115, "source": "self_report"})
    t1.add_tool("classify_case", {
        "symptoms": ["changes_in_vision", "severe_headache_not_going_away"],
        "vitals": {"bp_systolic": 165, "bp_diastolic": 115},
    })

    # Iteration 2: send emergency contact SMS + patient SMS
    t2 = client.new_turn()
    t2.add_tool("send_emergency_contact_sms", {
        "body": "Maria is on the phone with Lily. Emergency services have been contacted. Please call her.",
    })
    t2.add_tool("send_patient_sms", {
        "body": "Help is on the way. Stay on the line and stay calm. Rosa has been notified.",
    })

    # Iteration 3: end session
    t3 = client.new_turn()
    t3.add_tool("end_session", {
        "tier_reached": "hand_off",
        "summary": "Maria 32wk with vision changes, severe headache, BP 165/115. Emergency contacted.",
    })

    # Final text
    client.queue_text("I'm staying with you, Maria. Help is on the way.")

    tts = MockTTSFactory()
    session = ConversationSession(
        call_sid="CAe2e_handoff",
        direction="inbound",
        anthropic=client,
        tts_factory=tts,
        db=db,
        rules_engine=classify_case,
    )

    await session.start("+15550001234")
    await session.on_user_final(_payload(
        "I'm seeing spots in my vision and I have a terrible headache. My blood pressure is 165 over 115."
    ))

    # ── Assertions ───────────────────────────────────────────────────────────

    assert session.triage_locked, "Session must be locked at hand_off"
    assert session.pending_classification is not None
    assert session.pending_classification.tier == "hand_off"

    ec_sms = [s for s in db.sms_sent if s["to"] == "+15550009999"]
    assert len(ec_sms) >= 1, "Emergency contact must receive an SMS"

    patient_sms = [s for s in db.sms_sent if s["to"] == "+15550001234"]
    assert len(patient_sms) >= 1, "Patient must receive an SMS"

    assert session._session_ended
    ended = [c for c in db.conversations if c.get("tier_reached") == "hand_off"]
    assert len(ended) == 1


async def test_e2e_handoff_triage_locked_ignores_lower_reclassify():
    """After lock, Claude attempting to re-classify with mild symptoms is ignored."""
    db = _make_db()
    client = MockAnthropicClient()
    client.queue_text("Hi Maria!")

    # First user turn: classify → hand_off
    t1 = client.new_turn()
    t1.add_tool("classify_case", {"symptoms": ["seizures"]})
    client.queue_text("I'm staying with you. Help is on the way.")

    session = ConversationSession(
        call_sid="CAe2e_lock",
        direction="inbound",
        anthropic=client,
        tts_factory=MockTTSFactory(),
        db=db,
        rules_engine=classify_case,
    )

    await session.start("+15550001234")
    # The classify_case call happens during on_user_final, not start
    await session.on_user_final(UserFinalPayload(
        call_sid="CAe2e_lock",
        transcript="I'm having a seizure",
        confidence=0.95,
        started_at_ms=0,
        ended_at_ms=1000,
    ))
    assert session.triage_locked, "Session should be locked after hand_off classification"
    assert session.pending_classification.tier == "hand_off"

    # Now Claude tries to re-classify with mild nausea — must be ignored
    t2 = client.new_turn()
    t2.add_tool("classify_case", {"symptoms": ["mild_nausea"]})
    client.queue_text("I'm staying with you.")

    await session.on_user_final(UserFinalPayload(
        call_sid="CAe2e_lock",
        transcript="Actually I feel fine now",
        confidence=0.95,
        started_at_ms=0,
        ended_at_ms=1000,
    ))
    assert session.pending_classification.tier == "hand_off"
    assert session.triage_locked


async def test_e2e_handoff_deviating_text_suppressed():
    """Text that minimizes urgency after hand_off must be suppressed."""
    db = _make_db()
    client = MockAnthropicClient()
    client.queue_text("Hi Maria!")

    # Lock session via classify in user turn 1
    t1 = client.new_turn()
    t1.add_tool("classify_case", {"symptoms": ["seizures"]})
    # After classify result, Claude deviates
    client.queue_text("You'll be fine, this is probably nothing to worry about.")

    tts = MockTTSFactory()
    session = ConversationSession(
        call_sid="CAe2e_suppress",
        direction="inbound",
        anthropic=client,
        tts_factory=tts,
        db=db,
        rules_engine=classify_case,
    )

    await session.start("+15550001234")
    await session.on_user_final(UserFinalPayload(
        call_sid="CAe2e_suppress",
        transcript="I'm having a seizure",
        confidence=0.95,
        started_at_ms=0,
        ended_at_ms=1000,
    ))

    all_chunks = [c for stream in tts.streams for c in stream.chunks_sent]
    full_text = " ".join(all_chunks)

    assert "you'll be fine" not in full_text.lower()
    assert "nothing to worry" not in full_text.lower()
