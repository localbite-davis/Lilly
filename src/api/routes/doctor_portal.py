from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.db.models.queue import DoctorQueue, EscalationTimer
from src.db.models.patient import Patient
from src.services.telephony import trigger_emergency_callback

router = APIRouter()

@router.get("/queue")
def get_doctor_queue(db: Session = Depends(get_db)):
    """Returns all pending HAND-UP cases for the doctor dashboard."""
    pending_items = db.query(DoctorQueue, Patient).join(Patient).filter(
        DoctorQueue.status == "pending"
    ).all()

    results = []
    for queue_item, patient in pending_items:
        timer = db.query(EscalationTimer).filter(
            EscalationTimer.doctor_queue_id == queue_item.id,
            EscalationTimer.status == "pending"
        ).first()

        results.append({
            "id": queue_item.id,
            "patient_name": patient.first_name,
            "patient_phone": patient.phone_number,
            "symptoms": queue_item.symptoms,
            "question": queue_item.question,
            "created_at": queue_item.created_at,
            "expires_at": timer.expires_at if timer else None,
        })

    return {"queue": results}

@router.post("/queue/{item_id}/approve")
def approve_case(item_id: int, db: Session = Depends(get_db)):
    """Doctor approves the case."""
    queue_item = db.query(DoctorQueue).filter(DoctorQueue.id == item_id).first()
    if not queue_item:
        raise HTTPException(status_code=404, detail="Queue item not found")

    queue_item.status = "resolved"
    timer = db.query(EscalationTimer).filter(EscalationTimer.doctor_queue_id == item_id).first()
    if timer:
        timer.status = "cancelled"
    db.commit()
    return {"status": "success"}

@router.post("/queue/{item_id}/escalate")
def escalate_case(item_id: int, db: Session = Depends(get_db)):
    """Doctor manually escalates to 911."""
    queue_item = db.query(DoctorQueue).filter(DoctorQueue.id == item_id).first()
    if not queue_item:
        raise HTTPException(status_code=404, detail="Queue item not found")

    queue_item.status = "escalated_by_doctor"
    timer = db.query(EscalationTimer).filter(EscalationTimer.doctor_queue_id == item_id).first()
    if timer:
        timer.status = "cancelled"
    patient = db.query(Patient).filter(Patient.id == queue_item.patient_id).first()
    db.commit()

    if patient:
        trigger_emergency_callback(patient.phone_number)

    return {"status": "success"}
