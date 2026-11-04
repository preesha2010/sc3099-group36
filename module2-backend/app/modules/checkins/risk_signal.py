import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from app.core.utils import utcnow_naive
from app.db.base import Base


class RiskSignal(Base):
    __tablename__ = "risk_signals"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    checkin_id = Column(String(36), ForeignKey("checkins.id"), nullable=False, index=True)
    signal_type = Column(String(50), nullable=False, index=True)
    severity = Column(String(20), nullable=False, index=True)
    confidence = Column(Float, nullable=False, default=1.0)
    details = Column(Text, nullable=True)
    weight = Column(Float, nullable=False, default=0.1)
    detected_at = Column(DateTime, nullable=False, default=utcnow_naive, index=True)

    checkin = relationship("CheckIn", back_populates="risk_signals")
