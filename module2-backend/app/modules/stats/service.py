from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import not_implemented
from app.modules.users.model import User


def overview(db: Session, current_user: User, *, course_id: Optional[str], days: int) -> dict[str, Any]:
    # TODO: Dashboard overview (API spec + test_stats_overview field names, e.g. today_checkins).
    not_implemented("GET /stats/overview")


def session_stats(db: Session, session_id: str, current_user: User) -> dict[str, Any]:
    # TODO: Session stats (API spec + test_stats_session: checked_in_count, approved_count, ...).
    not_implemented("GET /stats/sessions/{session_id}")


def course_stats(
    db: Session,
    course_id: str,
    current_user: User,
    *,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
) -> dict[str, Any]:
    # TODO: Course stats (API spec + test_stats_course field names).
    not_implemented("GET /stats/courses/{course_id}")


def student_stats(db: Session, student_id: str, current_user: User) -> dict[str, Any]:
    # TODO: Student stats (API spec + test_stats_student field names).
    not_implemented("GET /stats/students/{student_id}")
