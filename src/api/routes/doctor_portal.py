from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.db.models.queue import DoctorQueue, EscalationTimer
from src.db.models.patient import Patient
from src.db.models.encounters import StandingOrder, Encounter
from src.services.telephony import trigger_emergency_callback

router = APIRouter()

@router.get("/queue")
def get_doctor_queue(db: Session = Depends(get_db)):
    """Returns all pending HAND-UP cases for the doctor dashboard."""
    pending_items = db.query(DoctorQueue, Patient, Encounter).join(Patient).join(Encounter, DoctorQueue.encounter_id == Encounter.id).filter(
        DoctorQueue.status == "pending"
    ).all()

    results = []
    for queue_item, patient, encounter in pending_items:
        timer = db.query(EscalationTimer).filter(
            EscalationTimer.doctor_queue_id == queue_item.id,
            EscalationTimer.status == "pending"
        ).first()

        # Calculate timer seconds for the frontend
        timer_seconds = None
        if timer:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            delta = timer.expires_at - now
            timer_seconds = int(delta.total_seconds())

        results.append({
            "id": queue_item.id,
            "patient_name": patient.first_name,
            "initials": patient.first_name[:2].upper() if patient.first_name else "P",
            "stage": patient.gestational_stage or ("Postpartum" if patient.is_postpartum else "Pregnant"),
            "tier": encounter.tier_reached,
            "bp": "148/94", # Mock vitals for now or extract from queue_item.vitals if JSON
            "hr": "88",
            "spo2": "98%",
            "bp_alert": False,
            "symptoms": (queue_item.symptoms or "").split(", "),
            "sbar": queue_item.question,
            "timer": timer_seconds
        })

    return results

@router.post("/cases/{item_id}/{action}")
def handle_case_action(item_id: int, action: str, db: Session = Depends(get_db)):
    """Doctor performs an action on a case (approve, escalate, or note)."""
    queue_item = db.query(DoctorQueue).filter(DoctorQueue.id == item_id).first()
    if not queue_item:
        raise HTTPException(status_code=404, detail="Queue item not found")

    if action == "approve":
        queue_item.status = "resolved"
        timer = db.query(EscalationTimer).filter(EscalationTimer.doctor_queue_id == item_id).first()
        if timer:
            timer.status = "cancelled"
    elif action == "escalate":
        queue_item.status = "escalated_by_doctor"
        timer = db.query(EscalationTimer).filter(EscalationTimer.doctor_queue_id == item_id).first()
        if timer:
            timer.status = "cancelled"
        patient = db.query(Patient).filter(Patient.id == queue_item.patient_id).first()
        if patient:
            trigger_emergency_callback(patient.phone_number)
    elif action == "note":
        # Just logging for now
        print(f"Note added to case {item_id}")
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    db.commit()
    return {"status": "success"}

@router.get("/past")
def get_past_cases(db: Session = Depends(get_db)):
    """Returns resolved/escalated cases for history."""
    past_items = db.query(DoctorQueue, Patient).join(Patient).filter(
        DoctorQueue.status.in_(["resolved", "escalated_by_doctor", "auto_escalated"])
    ).order_by(DoctorQueue.created_at.desc()).all()

    results = []
    for item, patient in past_items:
        results.append({
            "id": item.id,
            "patient_name": patient.first_name,
            "initials": patient.first_name[:2].upper() if patient.first_name else "P",
            "stage": patient.gestational_stage or "Patient",
            "status": item.status,
            "symptoms": (item.symptoms or "").split(", "),
            "resolved_at": item.created_at # Mocked as creation time for now
        })
    return results

@router.get("/standing-orders")
def get_standing_orders(db: Session = Depends(get_db)):
    """Returns all active standing orders."""
    orders = db.query(StandingOrder, Patient).join(Patient).all()
    return [{
        "id": o.id,
        "patient_name": p.first_name,
        "condition": o.condition,
        "intervention": o.intervention,
        "doctor_name": o.doctor_name
    } for o, p in orders]

@router.post("/standing-orders")
def create_standing_order(data: dict, db: Session = Depends(get_db)):
    """Creates a new standing order."""
    # Note: in a real app we'd map the name to a patient_id
    # For this hackathon demo, we'll assume patient 1
    new_order = StandingOrder(
        patient_id=1,
        condition=data.get("condition"),
        intervention=data.get("intervention"),
        doctor_name="Dr. Demo"
    )
    db.add(new_order)
    db.commit()
    return {"status": "success"}

@router.get("/analytics")
def get_analytics(db: Session = Depends(get_db)):
    """Returns basic metrics for the dashboard including global context."""
    total_resolved = db.query(DoctorQueue).filter(DoctorQueue.status == "resolved").count()
    total_escalated = db.query(DoctorQueue).filter(DoctorQueue.status.contains("escalated")).count()
    
    return {
        "resolved_today": total_resolved,
        "avg_response_time": "11m",
        "triage_accuracy": "98%",
        "active_monitors": 42,
        "global_crisis": {
            "daily_preventable_deaths": 800,
            "annual_maternal_mortality": 287000,
            "preeclampsia_prevalence": "5-8%",
            "preventable_percentage": "80%"
        },
        "lilly_stats": {
            "care_hubs": 12,
            "patients_monitored": 1250,
            "lives_saved_estimate": 84,
            "critical_escalations": total_escalated
        }
    }
