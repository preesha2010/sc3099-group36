import uuid
from datetime import timedelta

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from app.core.config import get_settings
from app.core.utils import utcnow_naive
from app.db.base import Base

settings = get_settings()


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    camera_consent = Column(Boolean, default=False)
    geolocation_consent = Column(Boolean, default=False)
    face_embedding_hash = Column(String(64), nullable=True)
    face_enrolled = Column(Boolean, default=False)
    failed_login_count = Column(Integer, nullable=False, default=0)
    is_locked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)
    last_login_at = Column(DateTime, nullable=True)
    scheduled_deletion_at = Column(
        DateTime,
        nullable=True,
        default=lambda: utcnow_naive() + timedelta(days=settings.DATA_RETENTION_DAYS),
    )

    devices = relationship("Device", back_populates="user")
    enrollments = relationship("Enrollment", back_populates="student", foreign_keys="Enrollment.student_id")
    checkins = relationship("CheckIn", back_populates="student", foreign_keys="CheckIn.student_id")
