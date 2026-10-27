from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.audit.repository import append_audit
from app.core.exceptions import bad_request, forbidden, not_found
from app.core.pagination import page_of
from app.core.utils import to_naive_utc, utcnow_naive
from app.db.enums import AuditAction, SessionStatus, UserRole
from app.modules.checkins import repository as checkins_repo
from app.modules.courses import repository as courses_repo
from app.modules.enrollments import repository as enrollments_repo
from app.modules.sessions import repository as sessions_repo
from app.modules.sessions.model import ClassSession
from app.modules.sessions.schemas import SessionCreate, SessionResponse, SessionUpdate
from app.modules.users.model import User


def can_manage_session(user: User, session: ClassSession) -> bool:
    if user.role == UserRole.ADMIN.value:
        return True
    return bool(session.instructor_id == user.id)


def can_staff_session(user: User, session: Optional[ClassSession]) -> bool:
    if session is None:
        return False
    if user.role == UserRole.ADMIN.value:
        return True
    if user.role == UserRole.TA.value:
        return True
    return session.instructor_id == user.id


def can_staff_course_session(db: Session, user: User, session: Optional[ClassSession]) -> bool:
    """Session owner/TA/admin, or an instructor assigned to the session's course."""
    if can_staff_session(user, session):
        return True
    if session is None:
        return False
    return enrollments_repo.user_manages_course(db, user, session.course_id)


def to_session_response(session: ClassSession, db: Optional[Session] = None) -> dict[str, Any]:
    payload = SessionResponse.model_validate(session).model_dump()
    course = session.course
    payload["course_code"] = course.code if course is not None else None
    payload["course_name"] = course.name if course is not None else None
    payload["qr_code_enabled"] = bool(session.qr_code_secret)
    if db is not None:
        payload["total_enrolled"] = len(
            enrollments_repo.list_for_course(db, session.course_id, active_only=True)
        )
        payload["checked_in_count"] = len(checkins_repo.list_for_session(db, session.id))
    return payload


def _naive(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return to_naive_utc(value)


def _status_value(status: Optional[str | SessionStatus]) -> Optional[str]:
    if status is None:
        return None
    return status.value if isinstance(status, SessionStatus) else status


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
    items, total, limit, offset = sessions_repo.list_sessions(
        db,
        status=_status_value(status),
        course_id=course_id,
        instructor_id=instructor_id,
        start_date=_naive(start_date),
        end_date=_naive(end_date),
        limit=limit,
        offset=offset,
    )
    return page_of([to_session_response(row, db) for row in items], total, limit, offset)


def list_active(db: Session) -> Any:
    return [to_session_response(row, db) for row in sessions_repo.list_active(db)]


def my_sessions(
    db: Session,
    current_user: User,
    *,
    status: Optional[str] = None,
    upcoming: bool = False,
    limit: int = 50,
) -> Any:
    if current_user.role == UserRole.STUDENT.value:
        enrollments = enrollments_repo.list_for_student(db, current_user.id, active_only=True)
        course_ids = [row.course_id for row in enrollments]
        rows = list(sessions_repo.list_for_courses(db, course_ids))
    elif current_user.role == UserRole.ADMIN.value:
        rows, _, _, _ = sessions_repo.list_sessions(db, limit=100, offset=0)
        rows = list(rows)
    else:
        rows, _, _, _ = sessions_repo.list_sessions(
            db, instructor_id=current_user.id, limit=100, offset=0
        )
        rows = list(rows)
    status_value = _status_value(status)
    if status_value:
        rows = [row for row in rows if row.status == status_value]
    if upcoming:
        now = utcnow_naive()
        rows = [row for row in rows if row.scheduled_start and row.scheduled_start >= now]
    return [to_session_response(row, db) for row in rows[: max(limit, 1)]]


def get_session(db: Session, session_id: str, current_user: Optional[User]) -> dict[str, Any]:
    session = sessions_repo.get_by_id(db, session_id)
    if session is None:
        raise not_found()
    return to_session_response(session, db)


def create_session(db: Session, payload: SessionCreate, current_user: User, request: Request) -> dict[str, Any]:
    course = courses_repo.get_by_id(db, payload.course_id)
    if course is None:
        raise not_found("Course not found")
    # Spec says the instructor must already teach the course. Public fixtures
    # POST /sessions/ with no assignment, so this slice does not 403 here and
    # does not upsert course_instructors (that would be self-assignment).
    start = to_naive_utc(payload.scheduled_start)
    end = to_naive_utc(payload.scheduled_end)
    if start <= utcnow_naive():
        raise bad_request("scheduled_start must be in the future")
    if end <= start:
        raise bad_request("scheduled_end must be after scheduled_start")
    opens = _naive(payload.checkin_opens_at) or (start - timedelta(minutes=15))
    closes = _naive(payload.checkin_closes_at) or (start + timedelta(minutes=30))
    if closes <= opens:
        raise bad_request("checkin_closes_at must be after checkin_opens_at")
    session = sessions_repo.create(
        db,
        ClassSession(
            course_id=course.id,
            instructor_id=current_user.id,
            name=payload.name,
            session_type=payload.session_type,
            description=payload.description,
            scheduled_start=start,
            scheduled_end=end,
            checkin_opens_at=opens,
            checkin_closes_at=closes,
            status=SessionStatus.SCHEDULED.value,
            venue_latitude=payload.venue_latitude if payload.venue_latitude is not None else course.venue_latitude,
            venue_longitude=payload.venue_longitude if payload.venue_longitude is not None else course.venue_longitude,
            venue_name=payload.venue_name if payload.venue_name is not None else course.venue_name,
            geofence_radius_meters=(
                payload.geofence_radius_meters
                if payload.geofence_radius_meters is not None
                else course.geofence_radius_meters
            ),
            require_liveness_check=payload.require_liveness_check,
            require_face_match=payload.require_face_match,
            risk_threshold=payload.risk_threshold if payload.risk_threshold is not None else course.risk_threshold,
        ),
    )
    append_audit(
        db,
        AuditAction.SESSION_CREATED.value,
        user_id=current_user.id,
        resource_type="session",
        resource_id=session.id,
        request=request,
    )
    db.commit()
    db.refresh(session)
    return to_session_response(session, db)


def update_session(
    db: Session, session_id: str, payload: SessionUpdate, current_user: User, request: Request
) -> dict[str, Any]:
    session = sessions_repo.get_by_id(db, session_id)
    if session is None:
        raise not_found()
    if not can_manage_session(current_user, session):
        raise forbidden()
    data = payload.model_dump(exclude_unset=True)
    if "status" in data:
        data["status"] = _status_value(data["status"])
    for field in ("checkin_opens_at", "checkin_closes_at"):
        if field in data and data[field] is not None:
            data[field] = to_naive_utc(data[field])
    for field, value in data.items():
        setattr(session, field, value)
    sessions_repo.save(db, session)
    append_audit(
        db,
        AuditAction.SESSION_UPDATED.value,
        user_id=current_user.id,
        resource_type="session",
        resource_id=session.id,
        request=request,
    )
    db.commit()
    db.refresh(session)
    return to_session_response(session, db)


def delete_session(db: Session, session_id: str, current_user: User, request: Request) -> None:
    session = sessions_repo.get_by_id(db, session_id)
    if session is None:
        raise not_found()
    if not can_manage_session(current_user, session):
        raise forbidden()
    if session.status != SessionStatus.SCHEDULED.value:
        raise bad_request("Only scheduled sessions can be deleted")
    append_audit(
        db,
        AuditAction.SESSION_DELETED.value,
        user_id=current_user.id,
        resource_type="session",
        resource_id=session.id,
        request=request,
    )
    sessions_repo.delete(db, session)
    db.commit()
