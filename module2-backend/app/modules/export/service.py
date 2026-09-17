from datetime import datetime
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.exceptions import not_implemented
from app.modules.users.model import User


def attendance_export(
    db: Session,
    course_id: str,
    current_user: User,
    request: Request,
    *,
    fmt: str,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
):
    # TODO: Course attendance export csv|json (API spec GET /export/attendance/{course_id}).
    not_implemented("GET /export/attendance/{course_id}")


def session_export(db: Session, session_id: str, current_user: User, request: Request, *, fmt: str):
    # TODO: Session export (API spec; test_export_session_attendance_json wants
    # {session_id, summary, records} with total_enrolled and attendance_rate).
    not_implemented("GET /export/session/{session_id}")
