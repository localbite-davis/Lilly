"""
Cross-layer Pydantic schemas for Lily Layer 2.
All other layers import from here — no business logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class WordConf(BaseModel):
    word: str
    confidence: float
    start_ms: int
    end_ms: int


class UserFinalPayload(BaseModel):
    call_sid: str
    transcript: str
    confidence: float = Field(ge=0.0, le=1.0)
    word_confidences: list[WordConf] = []
    started_at_ms: int
    ended_at_ms: int
    detected_language: str = "en" 


class StandingOrderView(BaseModel):
    condition: str
    intervention: str
    doctor_name: str


class PatientContext(BaseModel):
    found: bool
    patient_id: int | None = None
    first_name: str | None = None
    gestational_stage: str | None = None
    language: Literal["en", "es"] = "en"
    has_bp_cuff: bool = False
    has_wearable: bool = False
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    recent_summaries: list[str] = []
    standing_orders: list[StandingOrderView] = []
    follow_up_flags: list[str] = []


class VitalsPayload(BaseModel):
    bp_systolic: int | None = None
    bp_diastolic: int | None = None
    hr: int | None = None
    spo2: int | None = None
    source: Literal["self_report", "sms_vitals", "wearable"]
    received_at: datetime


class TriageInput(BaseModel):
    symptoms: list[str]
    vitals: dict[str, int | None] = {}
    gestational_weeks: int | None = None
    postpartum_days: int | None = None
    flags: list[str] = []


class TriageOutput(BaseModel):
    tier: Literal["handle", "hand_up", "hand_off"]
    reason: str
    triggered_rules: list[str]
    uncertainty: bool
    next_action: str


class CasePacket(BaseModel):
    patient_first_name: str
    gestational_stage: str
    vitals_snapshot: VitalsPayload | None
    acog_signs: list[str]
    lily_recommendation: str
    specific_question: str
    conversation_id: int


class ToolResult(BaseModel):
    """All tool handlers return one of these. Never raise out of a handler."""
    ok: bool
    data: dict | None = None
    error: str | None = None
    error_code: str | None = None
