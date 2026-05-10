"""Tests for PHI redaction in logging_setup.py — Stage 5.1."""

from __future__ import annotations

import pytest


def test_redaction_removes_phi_fields(monkeypatch):
    monkeypatch.setenv("PHI_REDACTION", "true")
    # Re-import settings with env override
    import importlib
    import src.config as cfg_mod
    importlib.reload(cfg_mod)

    from src.logging_setup import _redact_phi
    event = {"phone": "+15550001234", "call_sid": "CA123", "event": "call_started"}
    result = _redact_phi(None, None, dict(event))
    assert result["phone"] == "<redacted>"
    assert result["call_sid"] == "CA123"
    assert result["event"] == "call_started"


def test_redaction_transcript_field(monkeypatch):
    monkeypatch.setenv("PHI_REDACTION", "true")
    from src.logging_setup import _redact_phi
    event = {"transcript": "I have a headache", "event": "user_final"}
    result = _redact_phi(None, None, dict(event))
    assert result["transcript"] == "<redacted>"
    assert result["event"] == "user_final"


def test_no_redaction_when_disabled(monkeypatch):
    monkeypatch.setenv("PHI_REDACTION", "false")
    import importlib
    import src.config as cfg_mod
    importlib.reload(cfg_mod)

    # Manually test with phi_redaction=False
    import src.logging_setup as ls
    # Temporarily patch settings
    original = cfg_mod.settings.phi_redaction
    cfg_mod.settings.phi_redaction = False
    event = {"phone": "+15550001234", "event": "test"}
    result = ls._redact_phi(None, None, dict(event))
    cfg_mod.settings.phi_redaction = True
    assert result["phone"] == "+15550001234"
