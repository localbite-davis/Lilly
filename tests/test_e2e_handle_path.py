"""
E2E: Handle path — Maria calls with mild nausea, Lily coaches her, call ends normally.
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

pytestmark = pytest.mark.asyncio


def _payload(text: str) -> UserFinalPayload:
    return UserFinalPayload(
        call_sid="CAe2e_handle",
        transcript=text,
        confidence=0.95,
        started_at_ms=0,
        ended_at_ms=1500,
    )


async def test_e2e_handle_path():
    db = MockDB()
    db.seed_patient(MockPatient(
        patient_id=1,
        phone="+15550001234",
        first_name="Maria",
        gestational_stage="32 weeks pregnant",
        has_bp_cuff=False,
        has_wearable=False,
    ))

    client = MockAnthropicClient()

    # Turn 0: greeting
    client.queue_text("Hi Maria! I'm glad you called. What's going on today?")

    # Turn 1: Maria mentions nausea — Lily logs symptom, classifies, coaches
    t1 = client.new_turn()
    t1.add_tool("log_symptom", {"symptom": "mild_nausea"})
    # After log_symptom result
    t2 = client.new_turn()
    t2.add_tool("classify_case", {"symptoms": ["mild_nausea"]})
    # After classify_case result (tier=handle)
    client.queue_text(
        "Mild nausea at 32 weeks is really common. "
        "Try eating small, frequent meals and ginger tea. "
        "How long has this been going on?"
    )

    # Turn 2: Maria says she's feeling better, Lily ends call
    t3 = client.new_turn()
    t3.add_tool("send_patient_sms", {"body": "Hope you feel better soon! Drink lots of water."})
    t4 = client.new_turn()
    t4.add_tool("end_session", {
        "tier_reached": "handle",
        "summary": "Maria had mild nausea at 32 weeks. Advised small meals and ginger tea.",
        "follow_up_flags": ["recheck_nausea_next_call"],
    })
    client.queue_text("Take care Maria! Call me any time.")

    tts = MockTTSFactory()
    session = ConversationSession(
        call_sid="CAe2e_handle",
        direction="inbound",
        anthropic=client,
        tts_factory=tts,
        db=db,
        rules_engine=classify_case,
    )

    await session.start("+15550001234")
    await session.on_user_final(_payload("I've been feeling a little nauseous today."))
    await session.on_user_final(_payload("Actually I'm feeling better now, thank you!"))

    # Assertions
    symptom_names = [s["symptom"] for s in db.symptoms]
    assert "mild_nausea" in symptom_names, "classify_case must receive the logged symptom"

    assert session.pending_classification is not None
    assert session.pending_classification.tier == "handle"
    assert not session.triage_locked

    assert session._session_ended, "end_session must be called"

    assert any("Hope you feel better" in s["body"] for s in db.sms_sent)

    # request_doctor_review must NOT have been called
    assert len(db.reviews) == 0

    ended = [c for c in db.conversations if c.get("tier_reached") == "handle"]
    assert len(ended) == 1


async def test_e2e_handle_path_tts_produces_output():
    """Verify TTS receives non-empty chunks on a handle call."""
    db = MockDB()
    db.seed_patient(MockPatient(
        patient_id=1,
        phone="+15550001234",
        first_name="Maria",
        gestational_stage="32 weeks pregnant",
    ))

    client = MockAnthropicClient()
    client.queue_text("Hi Maria, how are you today?")
    client.queue_text("Glad to hear you're okay. Take care!")
    t = client.new_turn()
    t.add_tool("end_session", {"tier_reached": "handle", "summary": "All fine."})
    client.queue_text("Goodbye!")

    tts = MockTTSFactory()
    session = ConversationSession(
        call_sid="CAe2e_handle_tts",
        direction="inbound",
        anthropic=client,
        tts_factory=tts,
        db=db,
        rules_engine=classify_case,
    )

    await session.start("+15550001234")
    await session.on_user_final(_payload("I'm fine, just checking in."))

    all_chunks = [c for stream in tts.streams for c in stream.chunks_sent]
    assert len(all_chunks) > 0
    full_text = " ".join(all_chunks)
    assert "Maria" in full_text or "how" in full_text.lower()
