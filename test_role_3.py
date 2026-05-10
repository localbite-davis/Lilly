import sys
import os

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta, timezone
from src.db.session import engine, Base, SessionLocal
from src.db.models.patient import Patient
from src.db.models.encounters import Encounter
from src.db.models.queue import DoctorQueue, EscalationTimer

def setup_test():
    print("1. Connecting to Neon DB and creating tables...")
    # This creates all tables defined in your SQLAlchemy models
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    try:
        print("2. Seeding a fake Patient (Maria)...")
        # Check if patient exists first
        patient = db.query(Patient).filter(Patient.phone_number == "+15551234567").first()
        if not patient:
            patient = Patient(first_name="Maria", phone_number="+15551234567", is_postpartum=False)
            db.add(patient)
            db.commit()
            db.refresh(patient)
            
        print("3. Seeding a fake Encounter...")
        encounter = Encounter(patient_id=patient.id, triage_tier="HAND_UP")
        db.add(encounter)
        db.commit()
        db.refresh(encounter)

        print("4. Seeding a HAND-UP case in the Doctor Queue...")
        queue_item = DoctorQueue(
            patient_id=patient.id,
            encounter_id=encounter.id,
            symptoms="headache, edema",
            question="Mild BP with symptoms. Escalate?",
            status="pending"
        )
        db.add(queue_item)
        db.commit()
        db.refresh(queue_item)

        print("5. Creating an EXPIRED 20-minute SLA Timer...")
        # We simulate that the 20 minutes actually passed 5 minutes ago
        expired_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        timer = EscalationTimer(
            doctor_queue_id=queue_item.id,
            expires_at=expired_time,
            status="pending"
        )
        db.add(timer)
        db.commit()
        
        print("\n✅ Database Seeded Successfully!")
        print("You can now test your auto-escalation by running:")
        print("python src/workers/ticker.py")

    except Exception as e:
        print(f"Error during setup: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    setup_test()
