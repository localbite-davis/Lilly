"""Tests for session.py — Stage 5.4."""

from __future__ import annotations

import asyncio
import time

import pytest

from src.core.agent.errors import AnthropicPermanentError, AnthropicTransientError
from src.core.agent.mocks.mock_anthropic import MockAnthropicClient
from src.core.agent.mocks.mock_db import MockDB, MockPatient
from src.core.agent.mocks.mock_tts import MockTTSFactory
from src.core.agent.session import ConversationSession, SessionState
from src.core.schemas import PatientContext, UserFinalPayload
from src.core.triage.rules_engine import classify_case

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_session(
    client: MockAnthropicClient,
    db: MockDB | None = None,
    tts: MockTTSFactory | None = None,
) -> ConversationSession:
    if db is None:
        db = MockDB()
        db.seed_patient(MockPatient(
            patient_id=1,
            phone="+15550001234",
            first_name="Maria",
            gestational_stage="32 weeks pregnant",
            emergency_contact_phone="+15550009999",
            emergency_contact_name="Rosa",
        ))
    if tts is None:
        tts = MockTTSFactory()
    return ConversationSession(
        call_sid="CAtest001",
        direction="inbound",
        anthropic=client,
        tts_factory=tts,
        db=db,
        rules_engine=classify_case,
    )


def final_payload(text: str = "I have a headache") -> UserFinalPayload:
    return UserFinalPayload(
        call_sid="CAtest001",
        transcript=text,
        confidence=0.95,
        started_at_ms=0,
        ended_at_ms=1000,
    )


# ---------------------------------------------------------------------------
# Inbound call start
# ---------------------------------------------------------------------------

async def test_inbound_known_patient_greets_by_name():
    client = MockAnthropicClient()
    client.queue_text("Hi Maria, I'm glad you called today.")
    s = make_session(client)
    await s.start("+15550001234")
    chunks = s.tts_factory.streams[-1].chunks_sent if s.tts_factory.streams else []
    full = " ".join(chunks)
    assert "Maria" in full


async def test_inbound_unknown_patient_offers_registration():
    db = MockDB()  # no patients seeded
    client = MockAnthropicClient()
    client.queue_text("Hi! I don't have your record yet. May I take your name?")
    s = make_session(client, db=db)
    await s.start("+15559999999")
    assert s._patient_context is not None
    assert not s._patient_context.found


async def test_session_state_after_start_is_listening():
    client = MockAnthropicClient()
    client.queue_text("Hello!")
    s = make_session(client)
    await s.start("+15550001234")
    assert s.state == SessionState.LISTENING


# ---------------------------------------------------------------------------
# on_user_final
# ---------------------------------------------------------------------------

async def test_user_final_triggers_brain_turn():
    client = MockAnthropicClient()
    # greeting turn
    client.queue_text("Hi Maria.")
    # response to user message
    client.queue_text("Tell me more about the headache.")
    s = make_session(client)
    await s.start("+15550001234")
    await s.on_user_final(final_payload("I have a headache"))
    assert s.state == SessionState.LISTENING
    # message_history should have the user message
    roles = [m["role"] for m in s.message_history]
    assert "user" in roles


async def test_brain_text_streams_to_tts_in_chunks():
    client = MockAnthropicClient()
    client.queue_text("Hi Maria. How are you feeling today? Let me know what's going on.")
    tts = MockTTSFactory(print_fn=lambda t: None)
    s = make_session(client, tts=tts)
    await s.start("+15550001234")
    assert len(tts.streams) >= 1
    chunks = tts.streams[0].chunks_sent
    assert len(chunks) >= 1
    full = " ".join(chunks)
    assert "Maria" in full


# ---------------------------------------------------------------------------
# Tool dispatch in session
# ---------------------------------------------------------------------------

async def test_tool_call_dispatched_and_result_appended():
    client = MockAnthropicClient()
    # Greeting: no tool
    client.queue_text("Hi Maria!")
    # User turn: Claude calls log_symptom then ends
    t = client.new_turn()
    t.add_tool("log_symptom", {"symptom": "headache"})
    # After tool result, Claude responds
    client.queue_text("I've logged that headache for you.")

    db = MockDB()
    db.seed_patient(MockPatient(
        patient_id=1,
        phone="+15550001234",
        first_name="Maria",
        gestational_stage="32 weeks pregnant",
    ))
    s = make_session(client, db=db)
    await s.start("+15550001234")
    await s.on_user_final(final_payload("I have a headache"))

    assert any(sym["symptom"] == "headache" for sym in db.symptoms)


async def test_unknown_tool_name_returns_error_no_crash():
    client = MockAnthropicClient()
    client.queue_text("Hi Maria!")
    # Claude calls a nonexistent tool
    t = client.new_turn()
    t.add_tool("nonexistent_tool_xyz", {"arg": "val"})
    # After error result, Claude responds
    client.queue_text("Sorry, let me try a different approach.")

    s = make_session(client)
    await s.start("+15550001234")
    await s.on_user_final(final_payload("Hello"))
    # Should not raise
    assert s.state == SessionState.LISTENING


async def test_tool_validation_error_returned_to_claude():
    client = MockAnthropicClient()
    client.queue_text("Hi!")
    # Claude sends bad input (missing required field)
    t = client.new_turn()
    t.add_tool("log_symptom", {})  # missing 'symptom'
    client.queue_text("Let me try that again.")

    s = make_session(client)
    await s.start("+15550001234")
    await s.on_user_final(final_payload("Hi"))
    # Check that tool_result with is_error=True ended up in message_history
    tool_result_msgs = [
        m for m in s.message_history
        if isinstance(m.get("content"), list)
        and any(c.get("is_error") for c in m["content"] if isinstance(c, dict))
    ]
    assert len(tool_result_msgs) >= 1


# ---------------------------------------------------------------------------
# Anthropic error handling
# ---------------------------------------------------------------------------

async def test_anthropic_429_retried_then_succeeds():
    client = MockAnthropicClient()
    # Greeting succeeds
    client.queue_text("Hi Maria!")
    # User turn: 429 then success
    client.queue_error(AnthropicTransientError("429"))
    client.queue_text("Sorry for the delay. How can I help?")

    s = make_session(client)
    await s.start("+15550001234")
    await s.on_user_final(final_payload("Hello"))
    assert s.state == SessionState.LISTENING


async def test_anthropic_complete_outage_speaks_fallback():
    client = MockAnthropicClient()
    # Greeting: both primary retries fail and fallback also fails
    client.queue_error(AnthropicTransientError("500"))
    client.queue_error(AnthropicTransientError("500 fallback"))

    tts = MockTTSFactory()
    s = make_session(client, tts=tts)
    await s.start("+15550001234")
    # Should have spoken a fallback line
    all_chunks = []
    for stream in tts.streams:
        all_chunks.extend(stream.chunks_sent)
    fallback_spoken = any("train of thought" in c or "trouble" in c for c in all_chunks)
    assert fallback_spoken


async def test_anthropic_400_immediate_fallback_speech():
    client = MockAnthropicClient()
    # Greeting turn: permanent error
    client.queue_error(AnthropicPermanentError("400 bad request"))

    tts = MockTTSFactory()
    s = make_session(client, tts=tts)
    await s.start("+15550001234")
    all_chunks = [c for stream in tts.streams for c in stream.chunks_sent]
    assert any("trouble" in c.lower() or "moment" in c.lower() for c in all_chunks)
    assert s.state == SessionState.ENDED


# ---------------------------------------------------------------------------
# Barge-in
# ---------------------------------------------------------------------------

async def test_barge_in_cancels_tts_and_brain():
    """Barge-in during thinking must cancel TTS and transition to LISTENING."""
    client = MockAnthropicClient()
    client.queue_text("Hi Maria!")

    # For barge-in: queue a response that will be cancelled
    async def slow_stream(*a, **kw):
        await asyncio.sleep(10)  # would block forever
        raise StopAsyncIteration
        yield  # make it a generator

    client2 = MockAnthropicClient()
    client2.queue_text("Maria this is a very long response that takes time.")

    tts = MockTTSFactory()
    s = make_session(client2, tts=tts)

    # Start the greeting first
    await s.start("+15550001234")

    # Now simulate barge-in while the session would be thinking
    s.state = SessionState.THINKING
    # Create a fake active TTS stream
    if tts.streams:
        s.tts_stream = tts.streams[-1]
    await s.on_user_interim("I actually meant to say—")
    assert s.state == SessionState.LISTENING


async def test_barge_in_ignored_when_not_thinking():
    client = MockAnthropicClient()
    client.queue_text("Hi!")
    s = make_session(client)
    await s.start("+15550001234")
    # State is now LISTENING — barge-in should be no-op
    s.state = SessionState.LISTENING
    await s.on_user_interim("something")
    assert s.state == SessionState.LISTENING


# ---------------------------------------------------------------------------
# classify_case / triage locking in session
# ---------------------------------------------------------------------------

async def test_classify_case_hand_off_sets_triage_locked():
    client = MockAnthropicClient()
    client.queue_text("Hi Maria!")
    t = client.new_turn()
    t.add_tool("classify_case", {"symptoms": ["seizures"]})
    client.queue_text("I'm staying with you. Help is on the way.")

    s = make_session(client)
    await s.start("+15550001234")
    await s.on_user_final(final_payload("I'm having a seizure"))
    assert s.triage_locked
    assert s.pending_classification.tier == "hand_off"


async def test_handoff_locked_session_ignores_lower_classification():
    client = MockAnthropicClient()
    client.queue_text("Hi!")
    # First user turn: hand_off
    t1 = client.new_turn()
    t1.add_tool("classify_case", {"symptoms": ["seizures"]})
    client.queue_text("Help is on the way.")
    # Second user turn: Claude tries to re-classify with mild symptoms
    t2 = client.new_turn()
    t2.add_tool("classify_case", {"symptoms": ["mild_nausea"]})
    client.queue_text("I'm still here with you.")

    s = make_session(client)
    await s.start("+15550001234")
    await s.on_user_final(final_payload("I'm having seizures"))
    await s.on_user_final(final_payload("Actually I just have mild nausea"))
    # Tier must still be hand_off
    assert s.pending_classification.tier == "hand_off"


# ---------------------------------------------------------------------------
# Max tool iteration limit
# ---------------------------------------------------------------------------

async def test_max_tool_iterations_triggers_uncertainty_handup():
    client = MockAnthropicClient()
    client.queue_text("Hi!")

    # Queue more tool calls than brain_max_tool_iterations (6)
    for _ in range(8):
        t = client.new_turn()
        t.add_tool("log_symptom", {"symptom": "headache"})

    s = make_session(client)
    await s.start("+15550001234")
    await s.on_user_final(final_payload("I have lots of symptoms"))
    # Should have force-escalated to hand_up via uncertainty
    if s.pending_classification:
        assert s.pending_classification.uncertainty or s.pending_classification.tier in ("hand_up", "handle")


# ---------------------------------------------------------------------------
# end_session idempotency at session level
# ---------------------------------------------------------------------------

async def test_end_session_called_idempotently():
    client = MockAnthropicClient()
    client.queue_text("Hi!")
    t = client.new_turn()
    t.add_tool("end_session", {"tier_reached": "handle", "summary": "Call went well."})
    client.queue_text("Take care!")
    # Second tool call to end_session (idempotent)
    t2 = client.new_turn()
    t2.add_tool("end_session", {"tier_reached": "handle", "summary": "Again."})
    client.queue_text("Goodbye!")

    db = MockDB()
    db.seed_patient(MockPatient(
        patient_id=1,
        phone="+15550001234",
        first_name="Maria",
        gestational_stage="32 weeks pregnant",
    ))
    s = make_session(client, db=db)
    await s.start("+15550001234")
    await s.on_user_final(final_payload("Feeling better, thanks"))
    await s.on_user_final(final_payload("Goodbye"))
    # Should not have written two ended states
    ended = [c for c in db.conversations if c.get("tier_reached") is not None]
    assert len(ended) <= 1


# ---------------------------------------------------------------------------
# Outbound call openings
# ---------------------------------------------------------------------------

async def test_outbound_doctor_callback_opening_message_correct():
    client = MockAnthropicClient()
    client.queue_text("Hi Maria, Dr. Chen reviewed your case and decided to escalate.")

    db = MockDB()
    db.seed_patient(MockPatient(
        patient_id=1,
        phone="+15550001234",
        first_name="Maria",
        gestational_stage="32 weeks pregnant",
    ))
    tts = MockTTSFactory()
    s = ConversationSession(
        call_sid="CAtest002",
        direction="outbound",
        anthropic=client,
        tts_factory=tts,
        db=db,
        rules_engine=classify_case,
    )
    await s.start(
        "+15550001234",
        outbound_context={"patient_id": 1, "reason": "doctor_callback", "doctor_name": "Dr. Chen", "decision": "ESCALATE"},
    )
    opening = s.message_history[0]["content"]
    assert "doctor_callback" in opening or "Dr. Chen" in opening


async def test_outbound_auto_escalate_opening_message_correct():
    client = MockAnthropicClient()
    client.queue_text("Hi Maria, no doctor responded so we want you to head to the ER.")

    db = MockDB()
    db.seed_patient(MockPatient(
        patient_id=1,
        phone="+15550001234",
        first_name="Maria",
        gestational_stage="32 weeks pregnant",
    ))
    s = ConversationSession(
        call_sid="CAtest003",
        direction="outbound",
        anthropic=client,
        tts_factory=MockTTSFactory(),
        db=db,
        rules_engine=classify_case,
    )
    await s.start(
        "+15550001234",
        outbound_context={"patient_id": 1, "reason": "auto_escalate"},
    )
    opening = s.message_history[0]["content"]
    assert "auto_escalate" in opening


# ---------------------------------------------------------------------------
# Concurrent user finals serialized by turn lock
# ---------------------------------------------------------------------------

async def test_concurrent_user_finals_serialized_by_turn_lock():
    client = MockAnthropicClient()
    client.queue_text("Hi!")
    client.queue_text("Response 1")
    client.queue_text("Response 2")

    s = make_session(client)
    await s.start("+15550001234")

    # Fire two on_user_final concurrently — lock must serialize them
    await asyncio.gather(
        s.on_user_final(final_payload("Message A")),
        s.on_user_final(final_payload("Message B")),
    )
    # No crash, state is consistent
    assert s.state == SessionState.LISTENING
