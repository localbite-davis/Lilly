import os
import sys
import time
from datetime import datetime, timezone

# Add the project root to the Python path so 'src' can be found
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy.orm import Session
from src.db.session import SessionLocal
from src.db.models.queue import EscalationTimer, DoctorQueue
from src.db.models.patient import Patient
from src.db.models.encounters import Encounter
from src.services.telephony import trigger_emergency_callback

def poll_for_expired_timers():
    """
    Infinite loop that wakes up every 30 seconds to check for expired HAND-UP timers.
    If a timer is expired and pending, it auto-escalates to HAND-OFF.
    """
    print("Ticker started: Polling for expired SLA timers every 30s...")
    
    # In demo mode, timers expire much faster
    is_demo = os.getenv("DEMO_MODE", "True") == "True"
    poll_interval = 5 if is_demo else 30
    
    while True:
        try:
            db: Session = SessionLocal()
            now = datetime.now(timezone.utc)
            
            # Find all pending timers that have expired
            expired_timers = db.query(EscalationTimer).filter(
                EscalationTimer.status == "pending",
                EscalationTimer.expires_at <= now
            ).all()
            
            for timer in expired_timers:
                print(f"⚠️ Timer {timer.id} EXPIRED! Auto-escalating...")
                
                # 1. Update Timer Status
                timer.status = "fired"
                
                # 2. Update Doctor Queue Status
                queue_item = db.query(DoctorQueue).filter(DoctorQueue.id == timer.doctor_queue_id).first()
                if queue_item:
                    queue_item.status = "auto_escalated"
                    
                    # 3. Trigger Outbound Call (Hour 18 Milestone)
                    patient = db.query(Patient).filter(Patient.id == queue_item.patient_id).first()
                    if patient:
                        trigger_emergency_callback(patient.phone_number)
                
                db.commit()
                
        except Exception as e:
            print(f"Ticker Error: {e}")
        finally:
            db.close()
            
        time.sleep(poll_interval)

if __name__ == "__main__":
    poll_for_expired_timers()
