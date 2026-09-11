from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.core.pagination import clamp_page
from app.core.utils import utcnow_naive
from app.db.enums import SessionStatus
from app.modules.sessions.model import ClassSession


def get_by_id(db: Session, session_id: str) -> Optional[ClassSession]:
    return db.query(ClassSession).filter(ClassSession.id == session_id).first()


def create(db: Session, session: ClassSession) -> ClassSession:
    db.add(session)
    db.flush()
    return session


def save(db: Session, session: ClassSession) -> ClassSession:
    session.updated_at = utcnow_naive()
    db.add(session)
    db.flush()
    return session


def delete(db: Session, session: ClassSession) -> None:
    db.delete(session)
    db.flush()


def list_sessions(
    db: Session,
    *,
    status: Optional[str] = None,
    course_id: Optional[str] = None,
    instructor_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[ClassSession], int, int, int]:
    limit, offset = clamp_page(limit, offset)
    query = db.query(ClassSession)
    if status:
        query = query.filter(ClassSession.status == status)
    if course_id:
        query = query.filter(ClassSession.course_id == course_id)
    if instructor_id:
        query = query.filter(ClassSession.instructor_id == instructor_id)
    if start_date:
        query = query.filter(ClassSession.scheduled_start >= start_date)
    if end_date:
        query = query.filter(ClassSession.scheduled_start <= end_date)
    total = query.count()
    items = query.order_by(ClassSession.scheduled_start.desc()).offset(offset).limit(limit).all()
    return items, total, limit, offset


def list_active(db: Session) -> Sequence[ClassSession]:
    now = utcnow_naive()
    return (
        db.query(ClassSession)
        .filter(ClassSession.status == SessionStatus.ACTIVE.value)
        .filter(ClassSession.checkin_opens_at <= now)
        .filter(ClassSession.checkin_closes_at >= now)
        .order_by(ClassSession.scheduled_start.asc())
        .all()
    )
