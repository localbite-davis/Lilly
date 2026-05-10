"""Shared fixtures for Layer 2 test suite."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from src.core.agent.mocks.mock_anthropic import MockAnthropicClient
from src.core.agent.mocks.mock_db import MockDB, MockPatient
from src.core.agent.mocks.mock_tts import MockTTSFactory
from src.core.schemas import PatientContext, StandingOrderView


@pytest.fixture
def mock_db() -> MockDB:
    db = MockDB()
    db.seed_patient(MockPatient(
        patient_id=1,
        phone="+15550001234",
        first_name="Maria",
        gestational_stage="32 weeks pregnant",
        has_bp_cuff=True,
        has_wearable=False,
        emergency_contact_name="Rosa",
        emergency_contact_phone="+15550009999",
        recent_summaries=["Mild nausea last week, now resolved."],
        standing_orders=[],
        follow_up_flags=[],
    ))
    return db


@pytest.fixture
def mock_tts_factory() -> MockTTSFactory:
    return MockTTSFactory()


@pytest.fixture
def mock_anthropic() -> MockAnthropicClient:
    return MockAnthropicClient()


@pytest.fixture
def known_patient_context() -> PatientContext:
    return PatientContext(
        found=True,
        patient_id=1,
        first_name="Maria",
        gestational_stage="32 weeks pregnant",
        language="en",
        has_bp_cuff=True,
        has_wearable=False,
        emergency_contact_name="Rosa",
        emergency_contact_phone="+15550009999",
        recent_summaries=["Mild nausea last week, now resolved."],
        standing_orders=[
            StandingOrderView(
                condition="nausea persists >3 days",
                intervention="Unisom 25mg at bedtime",
                doctor_name="Dr. Chen",
            )
        ],
        follow_up_flags=["recheck_bp_tomorrow"],
    )


@pytest.fixture
def unknown_patient_context() -> PatientContext:
    return PatientContext(found=False)


@pytest.fixture
def rules_engine_fn():
    from src.core.triage.rules_engine import classify_case
    return classify_case
