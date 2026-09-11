"""Import every ORM model so Base.metadata is complete for create_all / Alembic."""

from app.audit.model import AuditLog
from app.modules.checkins.model import CheckIn
from app.modules.checkins.risk_signal import RiskSignal
from app.modules.courses.model import Course
from app.modules.devices.model import Device
from app.modules.enrollments.model import Enrollment
from app.modules.sessions.model import ClassSession
from app.modules.users.model import User

__all__ = [
    "AuditLog",
    "CheckIn",
    "ClassSession",
    "Course",
    "Device",
    "Enrollment",
    "RiskSignal",
    "User",
]
