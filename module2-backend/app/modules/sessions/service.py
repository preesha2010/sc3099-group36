from datetime import datetime
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.exceptions import not_implemented
from app.modules.sessions.schemas import SessionCreate, SessionUpdate
from app.modules.users.model import User


def list_sessions(
    db: Session,
    current_user: User,
    *,
    status: Optional[str],
    course_id: Optional[str],
    instructor_id: Optional[str],
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    limit: int,
    offset: int,
) -> dict[str, Any]:
    not_implemented("GET /sessions/")


def list_active(db: Session) -> Any:
    not_implemented("GET /sessions/active")


def my_sessions(db: Session, current_user: User) -> Any:
    not_implemented("GET /sessions/my-sessions")


def get_session(db: Session, session_id: str, current_user: Optional[User]) -> dict[str, Any]:
    not_implemented("GET /sessions/{session_id}")


def create_session(db: Session, payload: SessionCreate, current_user: User, request: Request) -> dict[str, Any]:
    not_implemented("POST /sessions/")


def update_session(
    db: Session, session_id: str, payload: SessionUpdate, current_user: User, request: Request
) -> dict[str, Any]:
    not_implemented("PATCH /sessions/{session_id}")


def delete_session(db: Session, session_id: str, current_user: User, request: Request) -> None:
    not_implemented("DELETE /sessions/{session_id}")
