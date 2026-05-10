"""
Seed the database with realistic demo data for the doctor dashboard.

Usage:
    python scripts/seed_demo_data.py           # insert fresh demo data
    python scripts/seed_demo_data.py --wipe    # wipe ALL demo rows first, then re-seed

Idempotent: skips patients whose phone numbers already exist.
"""

from __future__ import annotations

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

from src.db.session import SessionLocal
from src.db.models.patient import Patient
from src.db.models.encounters import Conversation, StandingOrder, FollowUpFlag
from src.db.models.queue import DoctorQueue, EscalationTimer

# ---------------------------------------------------------------------------
# Demo patients
# ---------------------------------------------------------------------------

PATIENTS = [
    {
        "phone_number": "+15550000001",
        "first_name": "Maria",
        "last_name": "Santos",
        "gestational_stage": "34 weeks pregnant",
        "is_postpartum": False,
        "has_bp_cuff": True,
        "has_wearable": False,
        "emergency_contact_name": "Carlos Santos",
        "emergency_contact_phone": "+15550000010",
        "preferred_language": "es",
        "verbal_consent_given": True,
    },
    {
        "phone_number": "+15550000002",
        "first_name": "Aisha",
        "last_name": "Okafor",
        "gestational_stage": "28 weeks pregnant",
        "is_postpartum": False,
        "has_bp_cuff": True,
        "has_wearable": True,
        "emergency_contact_name": "Emeka Okafor",
        "emergency_contact_phone": "+15550000011",
        "preferred_language": "en",
        "verbal_consent_given": True,
    },
    {
        "phone_number": "+15550000003",
        "first_name": "Priya",
        "last_name": "Nair",
        "gestational_stage": "6 weeks postpartum",
        "is_postpartum": True,
        "has_bp_cuff": False,
        "has_wearable": False,
        "emergency_contact_name": "Ravi Nair",
        "emergency_contact_phone": "+15550000012",
        "preferred_language": "en",
        "verbal_consent_given": True,
    },
    {
        "phone_number": "+15550000004",
        "first_name": "Destiny",
        "last_name": "Williams",
        "gestational_stage": "22 weeks pregnant",
        "is_postpartum": False,
        "has_bp_cuff": False,
        "has_wearable": False,
        "emergency_contact_name": "Tamara Williams",
        "emergency_contact_phone": "+15550000013",
        "preferred_language": "en",
        "verbal_consent_given": True,
    },
    {
        "phone_number": "+15550000005",
        "first_name": "Fatima",
        "last_name": "Al-Rashid",
        "gestational_stage": "38 weeks pregnant",
        "is_postpartum": False,
        "has_bp_cuff": True,
        "has_wearable": True,
        "emergency_contact_name": "Omar Al-Rashid",
        "emergency_contact_phone": "+15550000014",
        "preferred_language": "en",
        "verbal_consent_given": True,
    },
]

# ---------------------------------------------------------------------------
# Standing orders (per patient, by index into PATIENTS)
# ---------------------------------------------------------------------------

STANDING_ORDERS = [
    # Maria — preeclampsia watch
    (0, "BP ≥ 140/90 on two readings 4h apart", "Take labetalol 200mg, go to L&D", "Dr. Rivera"),
    # Aisha — gestational diabetes
    (1, "Fasting blood glucose > 95 mg/dL", "Adjust evening snack, call clinic next morning", "Dr. Patel"),
    # Fatima — GBS positive
    (4, "Active labor onset", "Proceed immediately to hospital for IV penicillin", "Dr. Chen"),
]

# ---------------------------------------------------------------------------
# Queue cases (pending — doctors need to act)
# ---------------------------------------------------------------------------

NOW = datetime.now(timezone.utc)

PENDING_CASES = [
    # Maria — severe headache + high BP (hand_up)
    {
        "patient_idx": 0,
        "tier": "hand_up",
        "summary": "Patient called reporting severe headache unresponsive to Tylenol, visual disturbances, and BP reading of 152/96 at home.",
        "symptoms": "severe_headache_not_going_away, changes_in_vision, edema_hands",
        "vitals": {"bp_systolic": 152, "bp_diastolic": 96, "hr": 94},
        "question": "Maria 34 wks, BP 152/96, severe headache x3h unresponsive to Tylenol, bilateral hand edema, visual blurring — preeclampsia? Admit or monitor at home?",
        "minutes_ago": 8,
        "timer_minutes": 12,
    },
    # Aisha — heavy vaginal bleeding (hand_off → still needs doctor note)
    {
        "patient_idx": 1,
        "tier": "hand_off",
        "summary": "Patient reported heavy vaginal bleeding, blood-red, soaking a pad every 30 minutes. Unable to self-transport. Emergency services notified.",
        "symptoms": "heavy_vaginal_bleeding, unable_to_self_transport_emergency",
        "vitals": {"bp_systolic": 108, "bp_diastolic": 68, "hr": 112},
        "question": "Aisha 28 wks, heavy vaginal bleeding (pad/30min), HR 112, BP 108/68, cannot self-transport — placenta previa vs abruption? EMS en route.",
        "minutes_ago": 3,
        "timer_minutes": 17,
    },
    # Destiny — decreased fetal movement (hand_up)
    {
        "patient_idx": 3,
        "tier": "hand_up",
        "summary": "Patient reports baby has not moved in over 8 hours. Last movement felt early this morning. No pain, no bleeding. Anxious.",
        "symptoms": "decreased_fetal_movement",
        "vitals": {},
        "question": "Destiny 22 wks, no fetal movement x8h, no vitals available, no other symptoms — kick count protocol or NST today?",
        "minutes_ago": 15,
        "timer_minutes": 5,
    },
]

# ---------------------------------------------------------------------------
# Past / resolved cases
# ---------------------------------------------------------------------------

PAST_CASES = [
    # Priya — postpartum heavy bleeding (resolved)
    {
        "patient_idx": 2,
        "tier": "hand_up",
        "status": "resolved",
        "summary": "Postpartum patient reported heavy bleeding 6 weeks post C-section. Doctor reviewed and authorized uterine massage protocol. Bleeding resolved within 2 hours.",
        "symptoms": "heavy_vaginal_bleeding, postpartum_bleeding_heavy",
        "vitals": {"bp_systolic": 118, "bp_diastolic": 74, "hr": 98},
        "question": "Priya 6wk postpartum, heavy bleeding since morning, BP 118/74, HR 98 — secondary PPH vs retained products?",
        "hours_ago": 5,
    },
    # Fatima — preterm contractions (resolved, escalated)
    {
        "patient_idx": 4,
        "tier": "hand_up",
        "status": "escalated_by_doctor",
        "summary": "Patient reported regular contractions every 7 minutes at 38 weeks. Doctor escalated to L&D admission. Baby delivered safely.",
        "symptoms": "preterm_labor_signs",
        "vitals": {"bp_systolic": 128, "bp_diastolic": 82, "hr": 88},
        "question": "Fatima 38 wks GBS+, regular contractions q7min x90min — active labor? Proceed to L&D for IV penicillin.",
        "hours_ago": 18,
    },
    # Maria earlier call (resolved)
    {
        "patient_idx": 0,
        "tier": "hand_up",
        "status": "resolved",
        "summary": "Maria reported mild BP elevation and headache two days ago. Doctor advised home monitoring every 4 hours and follow-up call next day.",
        "symptoms": "severe_headache_not_going_away, systolic_bp_over_140",
        "vitals": {"bp_systolic": 142, "bp_diastolic": 88, "hr": 82},
        "question": "Maria 33 wks, BP 142/88, headache, no visual changes — home monitoring protocol or admit?",
        "hours_ago": 52,
    },
]


def _get_or_create_patient(db, data: dict) -> Patient:
    existing = db.query(Patient).filter(Patient.phone_number == data["phone_number"]).first()
    if existing:
        return existing
    p = Patient(**data)
    db.add(p)
    db.flush()
    return p


def seed(db, wipe: bool):
    if wipe:
        print("Wiping existing demo data...")
        demo_phones = [p["phone_number"] for p in PATIENTS]
        demo_patients = db.query(Patient).filter(Patient.phone_number.in_(demo_phones)).all()
        demo_ids = [p.id for p in demo_patients]
        if demo_ids:
            convs = db.query(Conversation).filter(Conversation.patient_id.in_(demo_ids)).all()
            conv_ids = [c.id for c in convs]
            if conv_ids:
                queue_items = db.query(DoctorQueue).filter(DoctorQueue.encounter_id.in_(conv_ids)).all()
                queue_ids = [q.id for q in queue_items]
                if queue_ids:
                    db.query(EscalationTimer).filter(EscalationTimer.doctor_queue_id.in_(queue_ids)).delete(synchronize_session=False)
                db.query(DoctorQueue).filter(DoctorQueue.encounter_id.in_(conv_ids)).delete(synchronize_session=False)
                db.query(FollowUpFlag).filter(FollowUpFlag.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
            db.query(StandingOrder).filter(StandingOrder.patient_id.in_(demo_ids)).delete(synchronize_session=False)
            db.query(Conversation).filter(Conversation.patient_id.in_(demo_ids)).delete(synchronize_session=False)
            db.query(Patient).filter(Patient.id.in_(demo_ids)).delete(synchronize_session=False)
        db.commit()
        print("Wipe complete.\n")

    # ── Patients ──────────────────────────────────────────────────────────────
    print("Creating patients...")
    patient_rows = []
    for data in PATIENTS:
        p = _get_or_create_patient(db, data)
        patient_rows.append(p)
        print(f"  {p.first_name} {p.last_name} ({p.gestational_stage}) — id={p.id}")
    db.flush()

    # ── Standing orders ───────────────────────────────────────────────────────
    print("\nCreating standing orders...")
    for patient_idx, condition, intervention, doctor in STANDING_ORDERS:
        p = patient_rows[patient_idx]
        so = StandingOrder(
            patient_id=p.id,
            condition=condition,
            intervention=intervention,
            doctor_name=doctor,
            active=True,
        )
        db.add(so)
        print(f"  [{doctor}] {p.first_name}: if {condition[:50]}...")
    db.flush()

    # ── Pending queue cases ───────────────────────────────────────────────────
    print("\nCreating pending doctor queue cases...")
    for case in PENDING_CASES:
        p = patient_rows[case["patient_idx"]]
        started = NOW - timedelta(minutes=case["minutes_ago"])
        conv = Conversation(
            patient_id=p.id,
            call_sid=f"demo-{p.phone_number}-{case['tier']}",
            direction="inbound",
            tier_reached=case["tier"],
            summary=case["summary"],
            ended_at=started + timedelta(minutes=8),
        )
        db.add(conv)
        db.flush()

        vitals_json = json.dumps(case["vitals"]) if case["vitals"] else None
        queue_item = DoctorQueue(
            patient_id=p.id,
            encounter_id=conv.id,
            symptoms=case["symptoms"],
            vitals=vitals_json,
            question=case["question"],
            status="pending",
            created_at=started,
        )
        db.add(queue_item)
        db.flush()

        timer = EscalationTimer(
            doctor_queue_id=queue_item.id,
            expires_at=NOW + timedelta(minutes=case["timer_minutes"]),
            status="pending",
        )
        db.add(timer)
        print(f"  [{case['tier'].upper()}] {p.first_name} — {case['minutes_ago']}min ago, {case['timer_minutes']}min left on timer")

    db.flush()

    # ── Past / resolved cases ─────────────────────────────────────────────────
    print("\nCreating past resolved cases...")
    for case in PAST_CASES:
        p = patient_rows[case["patient_idx"]]
        started = NOW - timedelta(hours=case["hours_ago"])
        conv = Conversation(
            patient_id=p.id,
            call_sid=f"demo-past-{p.phone_number}-{case['hours_ago']}h",
            direction="inbound",
            tier_reached=case["tier"],
            summary=case["summary"],
            ended_at=started + timedelta(minutes=12),
        )
        db.add(conv)
        db.flush()

        vitals_json = json.dumps(case["vitals"]) if case["vitals"] else None
        queue_item = DoctorQueue(
            patient_id=p.id,
            encounter_id=conv.id,
            symptoms=case["symptoms"],
            vitals=vitals_json,
            question=case["question"],
            status=case["status"],
            created_at=started,
        )
        db.add(queue_item)
        print(f"  [{case['status'].upper()}] {p.first_name} — {case['hours_ago']}h ago")

    db.commit()
    print("\n✓ Demo data seeded successfully.")
    print(f"  {len(PENDING_CASES)} pending cases in doctor queue")
    print(f"  {len(PAST_CASES)} resolved/escalated cases in history")
    print(f"  {len(PATIENTS)} demo patients")
    print(f"  {len(STANDING_ORDERS)} standing orders")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--wipe", action="store_true", help="Remove existing demo rows before seeding")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        seed(db, wipe=args.wipe)
    finally:
        db.close()
