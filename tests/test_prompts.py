"""Tests for prompts.py — Stage 5.2."""

from __future__ import annotations

import pytest

from src.core.schemas import PatientContext, StandingOrderView
from src.core.agent.prompts import (
    LILY_STATIC_SYSTEM_PROMPT,
    build_system_prompt,
    render_context_block,
)


def test_imports():
    """Smoke: all schema and prompt symbols importable."""
    from src.core.schemas import (
        UserFinalPayload, PatientContext, TriageOutput,
        VitalsPayload, ToolResult, CasePacket, TriageInput,
    )
    from src.core.agent.errors import (
        Layer2Error, AnthropicTransientError, AnthropicPermanentError,
        ToolValidationError, StreamCancelledError, TriageLockViolation,
    )
    from src.core.agent.interfaces import TextDelta, ToolUseStop, MessageStop
    from src.config import settings
    assert settings.lily_model == "claude-sonnet-4-6"


def test_static_prompt_is_stable():
    first = LILY_STATIC_SYSTEM_PROMPT
    second = LILY_STATIC_SYSTEM_PROMPT
    assert first is second, "Static prompt should be a module-level constant"
    word_count = len(first.split())
    # Proxy for token count: 1500–2500 tokens ≈ 1125–1875 words
    assert 500 < word_count < 3000, f"Static prompt word count unexpected: {word_count}"


def test_static_prompt_has_required_sections():
    p = LILY_STATIC_SYSTEM_PROMPT.upper()
    assert "HARD LIMITS" in p
    assert "TOOL-USE RULES" in p
    assert "TONE CALIBRATION" in p
    assert "END CONDITIONS" in p


def test_no_phi_in_static_prompt():
    """Static prompt must not contain real names, phones, or dates."""
    p = LILY_STATIC_SYSTEM_PROMPT
    suspicious = ["+1", "555", "2024-", "2025-", "DOB:", "Patient ID:"]
    for term in suspicious:
        assert term not in p, f"Possible PHI in static prompt: {term!r}"


def test_context_rendering_found(known_patient_context):
    block = render_context_block(known_patient_context)
    assert "Maria" in block
    assert "32 weeks pregnant" in block
    assert "Dr. Chen" in block
    assert "recheck_bp_tomorrow" in block
    assert "Unisom" in block


def test_context_rendering_not_found(unknown_patient_context):
    block = render_context_block(unknown_patient_context)
    assert "not in our system" in block
    assert "registration" in block


def test_build_system_prompt_returns_two_blocks(known_patient_context):
    system = build_system_prompt(known_patient_context)
    assert len(system) == 2
    assert system[0]["type"] == "text"
    assert "cache_control" in system[0]
    assert system[1]["type"] == "text"
    assert "cache_control" not in system[1]


def test_build_system_prompt_static_block_cached(known_patient_context):
    system = build_system_prompt(known_patient_context)
    assert system[0]["cache_control"]["type"] == "ephemeral"


def test_standing_orders_formatted(known_patient_context):
    block = render_context_block(known_patient_context)
    assert "nausea persists" in block
    assert "Unisom 25mg" in block


def test_context_rendering_no_standing_orders():
    ctx = PatientContext(
        found=True,
        patient_id=2,
        first_name="Ana",
        gestational_stage="8 weeks postpartum",
    )
    block = render_context_block(ctx)
    assert "none on file" in block


def test_context_rendering_no_summaries():
    ctx = PatientContext(
        found=True,
        patient_id=3,
        first_name="Luz",
        gestational_stage="20 weeks pregnant",
    )
    block = render_context_block(ctx)
    assert "no prior calls" in block
