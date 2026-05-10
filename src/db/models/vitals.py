from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.sql import func

from src.db.session import Base


class Vitals(Base):
    __tablename__ = "vitals"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True, index=True)

    # Vital signs
    systolic_bp = Column(Integer, nullable=True)
    diastolic_bp = Column(Integer, nullable=True)
    heart_rate = Column(Integer, nullable=True)
    spo2 = Column(Integer, nullable=True)
    temperature = Column(Float, nullable=True)
    weight_lbs = Column(Float, nullable=True)

    source = Column(String, nullable=False)     # self_report | sms_vitals | wearable
    recorded_at = Column(DateTime(timezone=True), server_default=func.now())


class SymptomLog(Base):
    __tablename__ = "symptom_log"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    symptom = Column(String, nullable=False)
    logged_at = Column(DateTime(timezone=True), server_default=func.now())


class SMSVitals(Base):
    """Latest vitals received via SMS from a wearable device. One row per patient (upserted)."""
    __tablename__ = "sms_vitals"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, unique=True, index=True)
    heart_rate = Column(Integer, nullable=True)
    spo2 = Column(Integer, nullable=True)
    systolic_bp = Column(Integer, nullable=True)
    diastolic_bp = Column(Integer, nullable=True)
    received_at = Column(DateTime(timezone=True), server_default=func.now())
