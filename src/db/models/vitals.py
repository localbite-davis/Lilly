from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from src.db.session import Base

class Vitals(Base):
    __tablename__ = "vitals"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    
    # Vital signs
    systolic_bp = Column(Integer, nullable=True)
    diastolic_bp = Column(Integer, nullable=True)
    heart_rate = Column(Integer, nullable=True)
    temperature = Column(Float, nullable=True)
    weight_lbs = Column(Float, nullable=True)

    # Context
    source = Column(String, nullable=False) # e.g., "SMS", "Voice"
    recorded_at = Column(DateTime(timezone=True), server_default=func.now())

    # Patient relationship could be added here
    # patient = relationship("Patient", back_populates="vitals")
