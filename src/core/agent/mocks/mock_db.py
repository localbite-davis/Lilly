"""In-memory mock database for Layer 2 tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class MockPatient:
    patient_id: int
    phone: str
    first_name: str
    gestational_stage: str
    language: str = "en"
    has_bp_cuff: bool = False
    has_wearable: bool = False
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    recent_summaries: list[str] = field(default_factory=list)
    standing_orders: list[dict] = field(default_factory=list)
    follow_up_flags: list[str] = field(default_factory=list)


class MockDB:
    def __init__(self) -> None:
        self._patients: dict[str, MockPatient] = {}
        self._patients_by_id: dict[int, MockPatient] = {}
        self._next_patient_id = 1
        self._next_conv_id = 1
        self._next_review_id = 1
        self.conversations: list[dict] = []
        self.symptoms: list[dict] = []
        self.vitals: list[dict] = []
        self.reviews: list[dict] = []
        self.sms_sent: list[dict] = []
        self.audit_log: list[dict] = []
        self._sms_vitals: dict[int, dict] = {}

    def seed_patient(self, patient: MockPatient) -> None:
        self._patients[patient.phone] = patient
        self._patients_by_id[patient.patient_id] = patient
        if patient.patient_id >= self._next_patient_id:
            self._next_patient_id = patient.patient_id + 1

    async def get_patient_by_phone(self, phone: str) -> MockPatient | None:
        return self._patients.get(phone)

    async def get_patient_by_id(self, patient_id: int) -> MockPatient | None:
        return self._patients_by_id.get(patient_id)

    async def create_patient(self, **fields: Any) -> MockPatient:
        p = MockPatient(patient_id=self._next_patient_id, **fields)
        self._next_patient_id += 1
        self._patients[p.phone] = p
        self._patients_by_id[p.patient_id] = p
        return p

    async def register_patient(
        self, phone: str, first_name: str, gestational_stage: str, verbal_consent_given: bool
    ) -> MockPatient:
        if not verbal_consent_given:
            raise ValueError("Verbal consent required for registration")
        return await self.create_patient(
            phone=phone,
            first_name=first_name,
            gestational_stage=gestational_stage,
        )

    async def create_conversation(
        self, patient_id: int | None, call_sid: str, direction: str
    ) -> int:
        conv_id = self._next_conv_id
        self._next_conv_id += 1
        self.conversations.append({
            "conversation_id": conv_id,
            "patient_id": patient_id,
            "call_sid": call_sid,
            "direction": direction,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        return conv_id

    async def link_conversation_to_patient(
        self, conversation_id: int, patient_id: int
    ) -> None:
        for c in self.conversations:
            if c["conversation_id"] == conversation_id:
                c["patient_id"] = patient_id
                break

    async def end_conversation(
        self, conversation_id: int, tier_reached: str, summary: str
    ) -> None:
        for c in self.conversations:
            if c["conversation_id"] == conversation_id:
                c["ended_at"] = datetime.now(timezone.utc).isoformat()
                c["tier_reached"] = tier_reached
                c["summary"] = summary
                break

    async def log_symptom(
        self, conversation_id: int, patient_id: int | None, symptom: str
    ) -> None:
        self.symptoms.append({
            "conversation_id": conversation_id,
            "patient_id": patient_id,
            "symptom": symptom,
            "logged_at": datetime.now(timezone.utc).isoformat(),
        })

    async def log_vitals(
        self, conversation_id: int, patient_id: int | None, vitals: dict
    ) -> None:
        self.vitals.append({
            "conversation_id": conversation_id,
            "patient_id": patient_id,
            **vitals,
            "logged_at": datetime.now(timezone.utc).isoformat(),
        })

    async def get_latest_sms_vitals(self, patient_id: int) -> dict | None:
        return self._sms_vitals.get(patient_id)

    def inject_sms_vitals(self, patient_id: int, vitals: dict) -> None:
        self._sms_vitals[patient_id] = vitals

    async def request_doctor_review(
        self, conversation_id: int, case_packet: dict
    ) -> int:
        review_id = self._next_review_id
        self._next_review_id += 1
        self.reviews.append({
            "review_id": review_id,
            "conversation_id": conversation_id,
            "case_packet": case_packet,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        })
        return review_id

    async def send_sms(self, to_phone: str, body: str) -> None:
        self.sms_sent.append({"to": to_phone, "body": body})

    async def audit(
        self,
        actor: str,
        action: str,
        patient_id: int | None,
        conversation_id: int | None,
    ) -> None:
        self.audit_log.append({
            "actor": actor,
            "action": action,
            "patient_id": patient_id,
            "conversation_id": conversation_id,
        })
