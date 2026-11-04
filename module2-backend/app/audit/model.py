import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text

from app.core.utils import utcnow_naive
from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(50), nullable=False, index=True)
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(String(36), nullable=True)
    ip_address = Column(String(45), nullable=True, index=True)
    user_agent = Column(String(500), nullable=True)
    device_id = Column(String(36), nullable=True)
    details = Column(Text, nullable=True)
    success = Column(Boolean, default=True)
    timestamp = Column(DateTime, nullable=False, default=utcnow_naive, index=True)
