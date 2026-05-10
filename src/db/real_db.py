"""
RealDB — async DBLike adapter that implements the Layer 2 DBLike protocol
against NeonDB via SQLAlchemy async + asyncpg.

Layer 2 instantiates one RealDB per process (not per call). Each method
opens a fresh session, executes, commits, and closes. Thread-safe.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.db.models.encounters import (
    AuditLog,
    Conversation,
    DoctorReview,
    FollowUpFlag,
    SMSLog,
    StandingOrder,
)
from src.db.models.patient import Patient
from src.db.models.vitals import SMSVitals, SymptomLog, Vitals
from src.db.session import get_async_session

log = structlog.get_logger(__name__)


class _PatientRow:
    """Thin wrapper over ORM row so Layer 2 sees the expected attribute names."""

    def __init__(self, row: Patient, summaries: list[str], standing_orders: list[dict], follow_up_flags: list[str]) -> None:
        self.patient_id = row.id
        self.phone = row.phone_number
        self.first_name = row.first_name or ""
        self.gestational_stage = row.gestational_stage or ""
        self.language = row.preferred_language or "en"
        self.has_bp_cuff = row.has_bp_cuff or False
        self.has_wearable = row.has_wearable or False
        self.emergency_contact_name = row.emergency_contact_name
        self.emergency_contact_phone = row.emergency_contact_phone
        self.recent_summaries = summaries
        self.standing_orders = standing_orders
        self.follow_up_flags = follow_up_flags


class RealDB:
    """Implements DBLike protocol against real NeonDB."""

    # ── Patient ───────────────────────────────────────────────────────────────

    async def get_patient_by_phone(self, phone: str) -> _PatientRow | None:
        async with get_async_session() as session:
            row = await session.scalar(
                select(Patient).where(Patient.phone_number == phone)
            )
            if row is None:
                return None
            return await self._build_patient_row(session, row)

    async def get_patient_by_id(self, patient_id: int) -> _PatientRow | None:
        async with get_async_session() as session:
            row = await session.get(Patient, patient_id)
            if row is None:
                return None
            return await self._build_patient_row(session, row)

    async def create_patient(self, **fields: Any) -> _PatientRow:
        async with get_async_session() as session:
            row = Patient(
                phone_number=fields.get("phone", ""),
                first_name=fields.get("first_name"),
                gestational_stage=fields.get("gestational_stage"),
                preferred_language=fields.get("language", "en"),
                has_bp_cuff=fields.get("has_bp_cuff", False),
                has_wearable=fields.get("has_wearable", False),
                emergency_contact_name=fields.get("emergency_contact_name"),
                emergency_contact_phone=fields.get("emergency_contact_phone"),
                verbal_consent_given=True,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _PatientRow(row, [], [], [])

    async def register_patient(
        self, phone: str, first_name: str, gestational_stage: str, verbal_consent_given: bool
    ) -> _PatientRow:
        if not verbal_consent_given:
            raise ValueError("Verbal consent required")
        async with get_async_session() as session:
            existing = await session.scalar(
                select(Patient).where(Patient.phone_number == phone)
            )
            if existing:
                existing.first_name = first_name
                existing.gestational_stage = gestational_stage
                existing.verbal_consent_given = True
                await session.flush()
                await session.refresh(existing)
                return _PatientRow(existing, [], [], [])
            row = Patient(
                phone_number=phone,
                first_name=first_name,
                gestational_stage=gestational_stage,
                verbal_consent_given=True,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _PatientRow(row, [], [], [])

    async def link_conversation_to_patient(
        self, conversation_id: int, patient_id: int
    ) -> None:
        async with get_async_session() as session:
            conv = await session.get(Conversation, conversation_id)
            if conv:
                conv.patient_id = patient_id

    # ── Conversations ────────────────────────────────────────────────────────

    async def create_conversation(
        self, patient_id: int | None, call_sid: str, direction: str
    ) -> int:
        async with get_async_session() as session:
            conv = Conversation(
                patient_id=patient_id,
                call_sid=call_sid,
                direction=direction,
            )
            session.add(conv)
            await session.flush()
            await session.refresh(conv)
            return conv.id

    async def end_conversation(
        self, conversation_id: int, tier_reached: str, summary: str
    ) -> None:
        async with get_async_session() as session:
            conv = await session.get(Conversation, conversation_id)
            if conv:
                conv.tier_reached = tier_reached
                conv.summary = summary
                conv.ended_at = datetime.now(timezone.utc)

    # ── Clinical data ────────────────────────────────────────────────────────

    async def log_symptom(
        self, conversation_id: int, patient_id: int | None, symptom: str
    ) -> None:
        async with get_async_session() as session:
            session.add(SymptomLog(
                patient_id=patient_id,
                conversation_id=conversation_id,
                symptom=symptom,
            ))

    async def log_vitals(
        self, conversation_id: int, patient_id: int | None, vitals: dict
    ) -> None:
        async with get_async_session() as session:
            session.add(Vitals(
                patient_id=patient_id,
                conversation_id=conversation_id,
                systolic_bp=vitals.get("bp_systolic"),
                diastolic_bp=vitals.get("bp_diastolic"),
                heart_rate=vitals.get("hr"),
                spo2=vitals.get("spo2"),
                source=vitals.get("source", "self_report"),
            ))

    async def get_latest_sms_vitals(self, patient_id: int) -> dict | None:
        async with get_async_session() as session:
            row = await session.scalar(
                select(SMSVitals).where(SMSVitals.patient_id == patient_id)
            )
            if row is None:
                return None
            return {
                k: v for k, v in {
                    "hr": row.heart_rate,
                    "spo2": row.spo2,
                    "bp_systolic": row.systolic_bp,
                    "bp_diastolic": row.diastolic_bp,
                }.items() if v is not None
            }

    # ── Doctor workflow ───────────────────────────────────────────────────────

    async def request_doctor_review(
        self, conversation_id: int, case_packet: dict
    ) -> int:
        async with get_async_session() as session:
            review = DoctorReview(
                conversation_id=conversation_id,
                patient_id=case_packet.get("conversation_id"),  # reuse field for patient tracing
                case_packet_json=json.dumps(case_packet),
            )
            session.add(review)
            await session.flush()
            await session.refresh(review)
            return review.id

    # ── SMS ───────────────────────────────────────────────────────────────────

    async def send_sms(self, to_phone: str, body: str) -> None:
        """
        Log SMS to DB. Wire to Twilio in Layer 1 (Voice Pipeline Lead).
        # TODO(human): call Twilio client here for real SMS delivery.
        """
        async with get_async_session() as session:
            session.add(SMSLog(to_phone=to_phone, body=body))
        log.info("sms_queued", to="<redacted>", body_len=len(body))

    # ── Audit ────────────────────────────────────────────────────────────────

    async def audit(
        self,
        actor: str,
        action: str,
        patient_id: int | None,
        conversation_id: int | None,
    ) -> None:
        async with get_async_session() as session:
            session.add(AuditLog(
                actor=actor,
                action=action,
                patient_id=patient_id,
                conversation_id=conversation_id,
            ))

    # ── Internal helpers ─────────────────────────────────────────────────────

    async def _build_patient_row(self, session: Any, row: Patient) -> _PatientRow:
        # Fetch 3 most recent conversation summaries
        result = await session.execute(
            select(Conversation.summary)
            .where(
                Conversation.patient_id == row.id,
                Conversation.summary.isnot(None),
            )
            .order_by(Conversation.started_at.desc())
            .limit(5)
        )
        summaries = [r[0] for r in result.all() if r[0]][::-1]  # oldest first

        # Fetch active standing orders
        so_result = await session.execute(
            select(StandingOrder)
            .where(StandingOrder.patient_id == row.id, StandingOrder.active.is_(True))
        )
        standing_orders = [
            {
                "condition": so.condition,
                "intervention": so.intervention,
                "doctor_name": so.doctor_name,
            }
            for so in so_result.scalars().all()
        ]

        # Fetch unresolved follow-up flags
        flag_result = await session.execute(
            select(FollowUpFlag.flag)
            .where(
                FollowUpFlag.patient_id == row.id,
                FollowUpFlag.resolved.is_(False),
            )
            .order_by(FollowUpFlag.created_at.desc())
            .limit(10)
        )
        flags = [r[0] for r in flag_result.all()]

        return _PatientRow(row, summaries, standing_orders, flags)
