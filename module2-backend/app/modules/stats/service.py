from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import not_implemented
from app.modules.users.model import User


def overview(db: Session, current_user: User, *, course_id: Optional[str], days: int) -> dict[str, Any]:
    not_implemented("GET /stats/overview")


def session_stats(db: Session, session_id: str, current_user: User) -> dict[str, Any]:
    not_implemented("GET /stats/sessions/{session_id}")


def course_stats(
    db: Session,
    course_id: str,
    current_user: User,
    *,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
) -> dict[str, Any]:
    not_implemented("GET /stats/courses/{course_id}")


def student_stats(db: Session, student_id: str, current_user: User) -> dict[str, Any]:
    not_implemented("GET /stats/students/{student_id}")
