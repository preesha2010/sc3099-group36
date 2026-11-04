import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from app.core.utils import utcnow_naive
from app.db.base import Base


class ClassSession(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    course_id = Column(String(36), ForeignKey("courses.id"), nullable=False, index=True)
    instructor_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    session_type = Column(String(50), default="lecture")
    description = Column(Text, nullable=True)
    scheduled_start = Column(DateTime, nullable=False, index=True)
    scheduled_end = Column(DateTime, nullable=False)
    checkin_opens_at = Column(DateTime, nullable=False)
    checkin_closes_at = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False, default="scheduled", index=True)
    actual_start = Column(DateTime, nullable=True)
    actual_end = Column(DateTime, nullable=True)
    venue_latitude = Column(Float, nullable=True)
    venue_longitude = Column(Float, nullable=True)
    venue_name = Column(String(255), nullable=True)
    geofence_radius_meters = Column(Float, nullable=True)
    require_liveness_check = Column(Boolean, default=True)
    require_face_match = Column(Boolean, default=False)
    risk_threshold = Column(Float, nullable=True)
    qr_code_secret = Column(String(64), nullable=True)
    qr_code_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)

    course = relationship("Course", back_populates="sessions")
    instructor = relationship("User", foreign_keys=[instructor_id])
    checkins = relationship("CheckIn", back_populates="session")
