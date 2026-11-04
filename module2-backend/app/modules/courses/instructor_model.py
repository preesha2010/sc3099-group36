import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.utils import utcnow_naive
from app.db.base import Base


class CourseInstructor(Base):
    """Admin-managed teaching assignment. Separate from sessions.instructor_id."""

    __tablename__ = "course_instructors"
    __table_args__ = (
        UniqueConstraint("course_id", "instructor_id", name="uq_course_instructor"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    course_id = Column(String(36), ForeignKey("courses.id"), nullable=False, index=True)
    instructor_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    assigned_at = Column(DateTime, nullable=False, default=utcnow_naive)
    assigned_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    course = relationship("Course", back_populates="instructor_links")
    instructor = relationship("User", foreign_keys=[instructor_id])
