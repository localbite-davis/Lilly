"""
E2E: Hand-up path — the Section 8 demo.
Maria: headache + edema → BP 148/94 → SMS vitals HR:102 → hand_up → doctor review.
"""

from __future__ import annotations

import asyncio

import pytest

from src.core.agent.mocks.mock_anthropic import MockAnthropicClient
from src.core.agent.mocks.mock_db import MockDB, MockPatient
from src.core.agent.mocks.mock_tts import MockTTSFactory
from src.core.agent.session import ConversationSession
from src.core.schemas import UserFinalPayload
from src.core.triage.rules_engine import classify_case


def _payload(text: str) -> UserFinalPayload:
    return UserFinalPayload(
        call_sid="CAe2e_handup",
        transcript=text,
        confidence=0.95,
        started_at_ms=0,
        ended_at_ms=2000,
    )


async def test_e2e_handup_path():
    db = MockDB()
    db.seed_patient(MockPatient(
        patient_id=1,
        phone="+15550001234",
        first_name="Maria",
        gestational_stage="32 weeks pregnant",
        has_bp_cuff=True,
        has_wearable=True,
        emergency_contact_phone="+15550009999",
        emergency_contact_name="Rosa",
    ))
    db.inject_sms_vitals(1, {"hr": 102, "spo2": 97})

    client = MockAnthropicClient()

    # Greeting
    client.queue_text("Hi Maria! I'm here. What's going on today?")

    # Iteration 1 response to user message 1: log both symptoms together
    t1 = client.new_turn()
    t1.add_tool("log_symptom", {"symptom": "severe_headache_not_going_away"})
    t1.add_tool("log_symptom", {"symptom": "edema_hands"})

    # Iteration 2 (after symptom results): ask for BP, log it + read SMS vitals
    t2 = client.new_turn()
    t2.add_tool("log_vitals", {"bp_systolic": 148, "bp_diastolic": 94, "source": "self_report"})
    t2.add_tool("read_vitals_sms", {})

    # Iteration 3 (after vitals results): log HR from SMS + classify
    t3 = client.new_turn()
    t3.add_tool("log_vitals", {"hr": 102, "source": "sms_vitals"})
    t3.add_tool("classify_case", {
        "symptoms": ["severe_headache_not_going_away", "edema_hands"],
        "vitals": {"bp_systolic": 148, "bp_diastolic": 94, "hr": 102},
    })

    # Iteration 4 (after classify result hand_up): request review + send SMS
    t4 = client.new_turn()
    t4.add_tool("request_doctor_review", {
        "patient_first_name": "Maria",
        "gestational_stage": "32 weeks pregnant",
        "acog_signs": ["severe_headache_not_going_away", "edema_hands", "systolic_bp_over_140"],
        "lily_recommendation": "Physician evaluation needed today.",
        "specific_question": "Maria 32wk, BP 148/94, HR 102, headache x4h, bilateral hand edema — ESCALATE?",
    })
    t4.add_tool("send_patient_sms", {
        "body": "A doctor is reviewing your case. Please keep your phone close. We'll call back soon."
    })

    # Iteration 5: end session
    t5 = client.new_turn()
    t5.add_tool("end_session", {
        "tier_reached": "hand_up",
        "summary": "Maria 32wk with headache, edema hands, BP 148/94. Doctor review requested.",
        "follow_up_flags": ["await_doctor_decision"],
    })

    # Final text (iteration 6 — no tools, text only)
    client.queue_text(
        "Maria, a doctor is reviewing your information right now. "
        "Please keep your phone close — they'll call you back shortly."
    )

    tts = MockTTSFactory()
    session = ConversationSession(
        call_sid="CAe2e_handup",
        direction="inbound",
        anthropic=client,
        tts_factory=tts,
        db=db,
        rules_engine=classify_case,
    )

    await session.start("+15550001234")
    await session.on_user_final(_payload("I have a bad headache and my hands are really puffy."))
    await session.on_user_final(_payload("My blood pressure is 148 over 94."))

    # ── Assertions ───────────────────────────────────────────────────────────

    symptom_names = [s["symptom"] for s in db.symptoms]
    assert "severe_headache_not_going_away" in symptom_names
    assert "edema_hands" in symptom_names

    vitals_sources = [v.get("source") for v in db.vitals]
    assert "self_report" in vitals_sources
    assert "sms_vitals" in vitals_sources

    bp_vitals = [v for v in db.vitals if v.get("bp_systolic") == 148]
    assert len(bp_vitals) >= 1, "BP 148 must be logged"

    hr_vitals = [v for v in db.vitals if v.get("hr") == 102]
    assert len(hr_vitals) >= 1, "HR 102 from SMS vitals must be logged"

    assert session.pending_classification is not None
    assert session.pending_classification.tier == "hand_up"
    assert not session.triage_locked  # hand_up does NOT lock

    assert len(db.reviews) == 1
    assert db.reviews[0]["case_packet"]["specific_question"] != ""

    sms_bodies = [s["body"] for s in db.sms_sent]
    assert any("doctor" in b.lower() or "review" in b.lower() for b in sms_bodies)

    assert session._session_ended
    ended = [c for c in db.conversations if c.get("tier_reached") == "hand_up"]
    assert len(ended) == 1
