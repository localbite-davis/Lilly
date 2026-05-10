"""
End-to-end test for the doctor queue pipeline.

Usage:
    python scripts/test_doctor_queue.py [--base-url http://localhost:8000]

What it does:
1. Inserts a synthetic doctor_queue row directly into NeonDB
2. Calls GET /api/portal/queue and verifies the row appears
3. Calls POST /api/portal/cases/{id}/approve and checks the status updates
4. Cleans up the synthetic row

Pass --keep to skip cleanup (useful for manual dashboard inspection).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from dotenv import load_dotenv

load_dotenv()


def _get_db():
    from src.db.session import SessionLocal
    return SessionLocal()


def _ensure_test_patient(db) -> int:
    from src.db.models.patient import Patient
    patient = db.query(Patient).filter(Patient.phone_number == "+10000000000").first()
    if not patient:
        patient = Patient(
            phone_number="+10000000000",
            first_name="TestPatient",
            gestational_stage="28 weeks",
            verbal_consent_given=True,
        )
        db.add(patient)
        db.flush()
    return patient.id


def _ensure_test_conversation(db, patient_id: int) -> int:
    from src.db.models.encounters import Conversation
    conv = Conversation(
        patient_id=patient_id,
        call_sid="test-call-sid-000",
        direction="inbound",
        tier_reached="hand_up",
    )
    db.add(conv)
    db.flush()
    return conv.id


def run(base_url: str, keep: bool):
    db = _get_db()
    queue_id = None
    conv_id = None

    try:
        from src.db.models.queue import DoctorQueue, EscalationTimer

        # ── 1. Insert synthetic queue entry ──────────────────────────────────
        patient_id = _ensure_test_patient(db)
        conv_id = _ensure_test_conversation(db, patient_id)

        entry = DoctorQueue(
            patient_id=patient_id,
            encounter_id=conv_id,
            symptoms="severe_headache, blurred_vision",
            vitals=json.dumps({"bp_systolic": 148, "bp_diastolic": 94, "hr": 88}),
            question="Patient 28 wks, BP 148/94, severe headache x2h — escalate to L&D?",
            status="pending",
        )
        db.add(entry)
        db.flush()
        queue_id = entry.id

        timer = EscalationTimer(
            doctor_queue_id=queue_id,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=20),
            status="pending",
        )
        db.add(timer)
        db.commit()
        print(f"[✓] Inserted doctor_queue row id={queue_id} (patient_id={patient_id})")

        # ── 2. Verify portal can see it ───────────────────────────────────────
        resp = httpx.get(f"{base_url}/api/portal/queue", timeout=10)
        if resp.status_code != 200:
            print(f"[✗] GET /api/portal/queue → HTTP {resp.status_code}")
            print(resp.text[:400])
            sys.exit(1)

        rows = resp.json()
        match = next((r for r in rows if r["id"] == queue_id), None)
        if not match:
            print(f"[✗] Queue entry id={queue_id} not found in portal response.")
            print(f"    Response contained {len(rows)} row(s).")
            sys.exit(1)

        print(f"[✓] Portal sees the ticket:")
        print(f"    patient={match['patient_name']}  tier={match['tier']}  timer={match['timer']}s")
        print(f"    symptoms={match['symptoms']}")
        print(f"    sbar={match['sbar']}")

        # ── 3. Simulate doctor approve ────────────────────────────────────────
        resp2 = httpx.post(
            f"{base_url}/api/portal/cases/{queue_id}/approve",
            json={"note": "Looks stable — monitor BP every 2h"},
            timeout=10,
        )
        if resp2.status_code != 200:
            print(f"[✗] POST /cases/{queue_id}/approve → HTTP {resp2.status_code}")
            print(resp2.text[:400])
            sys.exit(1)

        db.expire(entry)
        db.refresh(entry)
        if entry.status != "resolved":
            print(f"[✗] Expected status='resolved', got '{entry.status}'")
            sys.exit(1)

        print(f"[✓] Doctor approve action processed — status={entry.status}")

        # ── 4. Verify ticket no longer appears in pending queue ───────────────
        resp3 = httpx.get(f"{base_url}/api/portal/queue", timeout=10)
        still_pending = next((r for r in resp3.json() if r["id"] == queue_id), None)
        if still_pending:
            print(f"[✗] Ticket still appears as pending after approve.")
            sys.exit(1)

        print(f"[✓] Ticket removed from pending queue after approve.")
        print()
        print("All checks passed — doctor queue pipeline is working end-to-end.")

    finally:
        if not keep and queue_id:
            from src.db.models.queue import EscalationTimer
            db.query(EscalationTimer).filter(EscalationTimer.doctor_queue_id == queue_id).delete()
            db.query(type(entry)).filter_by(id=queue_id).delete()
            if conv_id:
                from src.db.models.encounters import Conversation
                db.query(Conversation).filter(Conversation.id == conv_id).delete()
            db.commit()
            print(f"[cleanup] Removed test row id={queue_id}")
        elif keep:
            print(f"[keep] Left test row id={queue_id} in DB for manual inspection.")
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--keep", action="store_true", help="Skip cleanup")
    args = parser.parse_args()
    run(args.base_url, args.keep)
