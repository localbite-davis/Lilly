from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from src.db.session import Base

class Encounter(Base):
    __tablename__ = "encounters"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    
    # Encounter Details
    call_sid = Column(String, nullable=True, index=True) # Twilio Call SID
    triage_tier = Column(String, nullable=False, default="HANDLE") # HANDLE, HAND-UP, HAND-OFF
    
    # Summaries
    llm_summary = Column(Text, nullable=True)
    symptoms_reported = Column(Text, nullable=True)
    
    # Timestamps
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
