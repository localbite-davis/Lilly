from sqlalchemy import Column, String, Integer, DateTime, Boolean
from sqlalchemy.sql import func
from src.db.session import Base

class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True, nullable=False)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    
    # Clinical Context
    estimated_due_date = Column(DateTime, nullable=True)
    is_postpartum = Column(Boolean, default=False)
    delivery_date = Column(DateTime, nullable=True)
    
    # Emergency Information
    emergency_contact_name = Column(String, nullable=True)
    emergency_contact_phone = Column(String, nullable=True)
    preferred_language = Column(String, default="en")

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
