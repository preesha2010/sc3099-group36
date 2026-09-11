from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.core.pagination import clamp_page
from app.modules.checkins.model import CheckIn
from app.modules.checkins.risk_signal import RiskSignal
from app.modules.sessions.model import ClassSession


def get_by_id(db: Session, checkin_id: str) -> Optional[CheckIn]:
    return db.query(CheckIn).filter(CheckIn.id == checkin_id).first()


def get_by_session_student(db: Session, session_id: str, student_id: str) -> Optional[CheckIn]:
    return (
        db.query(CheckIn)
        .filter(CheckIn.session_id == session_id, CheckIn.student_id == student_id)
        .first()
    )


def create(db: Session, checkin: CheckIn) -> CheckIn:
    db.add(checkin)
    db.flush()
    return checkin


def save(db: Session, checkin: CheckIn) -> CheckIn:
    db.add(checkin)
    db.flush()
    return checkin


def add_risk_signal(db: Session, signal: RiskSignal) -> RiskSignal:
    db.add(signal)
    db.flush()
    return signal


def list_for_student(db: Session, student_id: str) -> Sequence[CheckIn]:
    return (
        db.query(CheckIn)
        .filter(CheckIn.student_id == student_id)
        .order_by(CheckIn.checked_in_at.desc())
        .all()
    )


def list_for_session(db: Session, session_id: str) -> Sequence[CheckIn]:
    return db.query(CheckIn).filter(CheckIn.session_id == session_id).all()


def list_flagged(db: Session) -> Sequence[CheckIn]:
    return db.query(CheckIn).filter(CheckIn.status == "flagged").all()


def list_checkins(
    db: Session,
    *,
    session_id: Optional[str] = None,
    course_id: Optional[str] = None,
    student_id: Optional[str] = None,
    status: Optional[str] = None,
    min_risk_score: Optional[float] = None,
    max_risk_score: Optional[float] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[CheckIn], int, int, int]:
    limit, offset = clamp_page(limit, offset)
    query = db.query(CheckIn)
    if course_id:
        query = query.join(ClassSession, CheckIn.session_id == ClassSession.id).filter(
            ClassSession.course_id == course_id
        )
    if session_id:
        query = query.filter(CheckIn.session_id == session_id)
    if student_id:
        query = query.filter(CheckIn.student_id == student_id)
    if status:
        query = query.filter(CheckIn.status == status)
    if min_risk_score is not None:
        query = query.filter(CheckIn.risk_score >= min_risk_score)
    if max_risk_score is not None:
        query = query.filter(CheckIn.risk_score <= max_risk_score)
    if start_date:
        query = query.filter(CheckIn.checked_in_at >= start_date)
    if end_date:
        query = query.filter(CheckIn.checked_in_at <= end_date)
    total = query.count()
    items = query.order_by(CheckIn.checked_in_at.desc()).offset(offset).limit(limit).all()
    return items, total, limit, offset
