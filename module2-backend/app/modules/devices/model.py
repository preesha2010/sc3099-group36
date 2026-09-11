import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.utils import utcnow_naive
from app.db.base import Base


class Device(Base):
    __tablename__ = "devices"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    device_fingerprint = Column(String(64), unique=True, nullable=False, index=True)
    device_name = Column(String(255), nullable=True)
    platform = Column(String(50), nullable=True)
    browser = Column(String(100), nullable=True)
    os_version = Column(String(50), nullable=True)
    app_version = Column(String(50), nullable=True)
    public_key = Column(Text, nullable=False, default="unspecified")
    public_key_created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    public_key_expires_at = Column(DateTime, nullable=True)
    attestation_passed = Column(Boolean, default=False)
    last_attestation_at = Column(DateTime, nullable=True)
    attestation_token = Column(Text, nullable=True)
    is_trusted = Column(Boolean, default=False, index=True)
    trust_score = Column(String(20), default="low")
    is_emulator = Column(Boolean, default=False)
    is_rooted_jailbroken = Column(Boolean, default=False)
    first_seen_at = Column(DateTime, nullable=False, default=utcnow_naive)
    last_seen_at = Column(DateTime, nullable=False, default=utcnow_naive)
    total_checkins = Column(Integer, default=0)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    revoked_at = Column(DateTime, nullable=True)
    revocation_reason = Column(Text, nullable=True)

    user = relationship("User", back_populates="devices")
