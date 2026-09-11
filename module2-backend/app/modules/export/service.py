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
    not_implemented("GET /export/attendance/{course_id}")


def session_export(db: Session, session_id: str, current_user: User, request: Request, *, fmt: str):
    not_implemented("GET /export/session/{session_id}")
