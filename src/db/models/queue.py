from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from src.db.session import Base

class DoctorQueue(Base):
    __tablename__ = "doctor_queue"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    encounter_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    
    # Case details
    symptoms = Column(Text, nullable=False)
    vitals = Column(Text, nullable=True)
    question = Column(Text, nullable=False) # e.g. "BP 148/94, headache... send to L&D?"
    
    status = Column(String, default="pending") # pending, resolved, auto_escalated
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class EscalationTimer(Base):
    __tablename__ = "escalation_timers"

    id = Column(Integer, primary_key=True, index=True)
    doctor_queue_id = Column(Integer, ForeignKey("doctor_queue.id"), nullable=False)
    
    expires_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String, default="pending") # pending, fired, cancelled
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
