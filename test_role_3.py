import sys
import os

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta, timezone
from src.db.session import sync_engine, Base, SessionLocal
from src.db.models.patient import Patient
from src.db.models.encounters import Encounter
from src.db.models.queue import DoctorQueue, EscalationTimer

def setup_test():
    print("1. Connecting to Neon DB and creating tables...")
    # This creates all tables defined in your SQLAlchemy models
    Base.metadata.create_all(bind=sync_engine)
    
    db = SessionLocal()
    
    try:
        print("2. Seeding Active Escalations...")
        active_cases = [
            ("Maria G.", "+15551234567", "hand_up", "headache, edema", "Mild BP with symptoms. Escalate?"),
            ("Denise H.", "+15551234568", "hand_off", "severe RUQ pain, vision blur", "CRITICAL: Urgent hand-off to L&D requested."),
            ("Keisha T.", "+15551234569", "hand_up", "persistent nausea", "Review requested for hyperemesis.")
        ]
        
        for name, phone, tier, symptoms, question in active_cases:
            p = Patient(first_name=name, phone_number=phone, is_postpartum=False)
            db.add(p)
            db.commit()
            db.refresh(p)
            
            enc = Encounter(patient_id=p.id, tier_reached=tier)
            db.add(enc)
            db.commit()
            db.refresh(enc)
            
            q_item = DoctorQueue(
                patient_id=p.id,
                encounter_id=enc.id,
                symptoms=symptoms,
                question=question,
                status="pending"
            )
            db.add(q_item)
            db.commit()
            db.refresh(q_item)
            
            if tier == "hand_up":
                # Only hand-up gets a 20-min SLA timer in this demo
                future_time = datetime.now(timezone.utc) + timedelta(minutes=15)
                timer = EscalationTimer(
                    doctor_queue_id=q_item.id,
                    expires_at=future_time,
                    status="pending"
                )
                db.add(timer)
                db.commit()
        
        print("6. Seeding historical cases for Analytics...")
        past_data = [
            ("Denise H.", "+15550000001", "resolved", "headache", "Patient feeling better after rest."),
            ("Keisha T.", "+15550000002", "resolved", "nausea", "Followed up, no red flags."),
            ("Sarah L.", "+15550000003", "escalated_by_doctor", "BP 170/110", "ACOG Emergency threshold met."),
            ("Elena R.", "+15550000004", "resolved", "mild edema", "Advised elevation and monitoring."),
            ("Aisha B.", "+15550000005", "auto_escalated", "Severe pain", "SLA expired, auto-escalated to L&D.")
        ]
        
        for name, phone, status, symptoms, question in past_data:
            p = Patient(first_name=name, phone_number=phone, is_postpartum=False)
            db.add(p)
            db.commit()
            db.refresh(p)
            
            enc = Encounter(patient_id=p.id, tier_reached="hand_up")
            db.add(enc)
            db.commit()
            db.refresh(enc)
            
            q = DoctorQueue(
                patient_id=p.id,
                encounter_id=enc.id,
                symptoms=symptoms,
                question=question,
                status=status
            )
            db.add(q)
            db.commit()

        print("\n✅ Database Seeded Successfully with Historical Data!")

    except Exception as e:
        print(f"Error during setup: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    setup_test()
