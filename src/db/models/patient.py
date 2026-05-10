from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from src.db.session import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True, nullable=False)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)

    # Clinical context
    gestational_stage = Column(String, nullable=True)   # "32 weeks pregnant" | "8 weeks postpartum"
    estimated_due_date = Column(DateTime, nullable=True)
    is_postpartum = Column(Boolean, default=False)
    delivery_date = Column(DateTime, nullable=True)

    # Equipment
    has_bp_cuff = Column(Boolean, default=False)
    has_wearable = Column(Boolean, default=False)

    # Emergency contact
    emergency_contact_name = Column(String, nullable=True)
    emergency_contact_phone = Column(String, nullable=True)

    # Preferences
    preferred_language = Column(String, default="en")

    # Consent
    verbal_consent_given = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
