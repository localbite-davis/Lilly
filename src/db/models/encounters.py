from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from src.db.session import Base


class Conversation(Base):
    """One phone call. Previously called Encounter; kept compatible by aliasing."""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True, index=True)
    call_sid = Column(String, nullable=True, index=True)
    direction = Column(String, default="inbound")           # inbound | outbound
    tier_reached = Column(String, nullable=True)            # handle | hand_up | hand_off
    summary = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)


# Backward-compat alias — existing code importing Encounter still works
Encounter = Conversation


class StandingOrder(Base):
    __tablename__ = "standing_orders"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    condition = Column(String, nullable=False)
    intervention = Column(Text, nullable=False)
    doctor_name = Column(String, nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FollowUpFlag(Base):
    __tablename__ = "follow_up_flags"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    flag = Column(String, nullable=False)
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DoctorReview(Base):
    __tablename__ = "doctor_reviews"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    case_packet_json = Column(Text, nullable=False)         # JSON blob of CasePacket
    status = Column(String, default="pending")              # pending | reviewed | escalated
    doctor_decision = Column(String, nullable=True)
    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    actor = Column(String, nullable=False)                  # "lily" | "doctor" | "system"
    action = Column(String, nullable=False)
    patient_id = Column(Integer, nullable=True)
    conversation_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SMSLog(Base):
    __tablename__ = "sms_log"

    id = Column(Integer, primary_key=True, index=True)
    to_phone = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    sent_at = Column(DateTime(timezone=True), server_default=func.now())
