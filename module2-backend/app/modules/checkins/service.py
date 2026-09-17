import json
from datetime import datetime
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import bad_request, not_found, not_implemented
from app.core.utils import haversine_meters, to_naive_utc, utcnow_naive
from app.db.enums import CheckinStatus, SessionStatus
from app.modules.checkins import repository as checkins_repo
from app.modules.checkins.model import CheckIn
from app.modules.checkins.schemas import AppealRequest, CheckinCreate, ReviewRequest
from app.modules.enrollments import repository as enrollments_repo
from app.modules.sessions import repository as sessions_repo
from app.modules.users.model import User


def _checkin_create_payload(checkin: CheckIn) -> dict[str, Any]:
    return {
        "id": checkin.id,
        "session_id": checkin.session_id,
        "student_id": checkin.student_id,
        "status": checkin.status,
        "checked_in_at": checkin.checked_in_at,
        "risk_score": checkin.risk_score,
        "latitude": checkin.latitude,
        "longitude": checkin.longitude,
        "location_accuracy_meters": checkin.location_accuracy_meters,
        "distance_from_venue_meters": checkin.distance_from_venue_meters,
    }


def submit_checkin(db: Session, payload: CheckinCreate, current_user: User, request: Request) -> dict[str, Any]:
    # TODO: Singapore-only check-ins (course clarification, graded): reject 403 or
    # status=rejected for public IP outside SG (X-Forwarded-For first hop) or GPS outside SG.
    # TODO: Spec check-in status table — flag if risk >= threshold; reject if liveness
    # failed or GPS > 2x geofence (via risk_service.assess). Public happy-path tests omit
    # liveness and require status pending|approved|flagged, not rejected.
    # TODO: Bind device_fingerprint (API spec / devices tests); do not store raw face images.
    session = sessions_repo.get_by_id(db, payload.session_id)
    if session is None:
        raise not_found("Session not found")

    if session.status != SessionStatus.ACTIVE.value:
        raise bad_request("Session not active")

    now = utcnow_naive()
    opens = to_naive_utc(session.checkin_opens_at)
    closes = to_naive_utc(session.checkin_closes_at)
    if now < opens or now > closes:
        raise bad_request("Check-in window closed")

    if not enrollments_repo.is_enrolled(db, current_user.id, session.course_id):
        raise bad_request("Student is not enrolled in this course")

    if checkins_repo.get_by_session_student(db, session.id, current_user.id) is not None:
        raise bad_request("Already checked in")

    distance = None
    if (
        payload.latitude is not None
        and payload.longitude is not None
        and session.venue_latitude is not None
        and session.venue_longitude is not None
    ):
        distance = haversine_meters(
            payload.latitude,
            payload.longitude,
            session.venue_latitude,
            session.venue_longitude,
        )

    checkin = CheckIn(
        session_id=session.id,
        student_id=current_user.id,
        status=CheckinStatus.APPROVED.value,
        checked_in_at=now,
        latitude=payload.latitude,
        longitude=payload.longitude,
        location_accuracy_meters=payload.location_accuracy_meters,
        distance_from_venue_meters=distance,
        risk_score=0.0,
    )
    try:
        checkins_repo.create(db, checkin)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise bad_request("Already checked in")
    db.refresh(checkin)
    return _checkin_create_payload(checkin)


def list_checkins(
    db: Session,
    current_user: User,
    *,
    session_id: Optional[str],
    course_id: Optional[str],
    student_id: Optional[str],
    status: Optional[str],
    min_risk_score: Optional[float],
    max_risk_score: Optional[float],
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    limit: int,
    offset: int,
) -> dict[str, Any]:
    # TODO: Instructor/admin paginated list (API spec + test_list_all_checkins: {items, total}).
    not_implemented("GET /checkins/")


def my_checkins(db: Session, current_user: User) -> Any:
    rows = checkins_repo.list_for_student(db, current_user.id)
    items = []
    for row in rows:
        session = row.session
        course = session.course if session is not None else None
        items.append(
            {
                "id": row.id,
                "session_id": row.session_id,
                "session_name": session.name if session is not None else None,
                "course_code": course.code if course is not None else None,
                "status": row.status,
                "checked_in_at": row.checked_in_at,
                "risk_score": row.risk_score,
            }
        )
    return items


def session_checkins(db: Session, session_id: str, current_user: User) -> Any:
    rows = checkins_repo.list_for_session(db, session_id)
    items = []
    for row in rows:
        student = row.student
        device = row.device
        factors: list[Any] = []
        if row.risk_factors:
            try:
                parsed = json.loads(row.risk_factors)
                if isinstance(parsed, list):
                    factors = parsed
            except json.JSONDecodeError:
                factors = []
        items.append(
            {
                "id": row.id,
                "student_id": row.student_id,
                "student_name": student.full_name if student is not None else None,
                "student_email": student.email if student is not None else None,
                "status": row.status,
                "checked_in_at": row.checked_in_at,
                "distance_from_venue_meters": row.distance_from_venue_meters,
                "risk_score": row.risk_score,
                "risk_factors": factors,
                "liveness_passed": row.liveness_passed,
                "device_trusted": bool(device.is_trusted) if device is not None else False,
            }
        )
    return items


def flagged_checkins(db: Session, current_user: User) -> Any:
    # TODO: Flagged/appealed review queue (API spec; test_flagged_checkins_queue wants
    # {items, total} and status flagged|appealed). list_flagged currently omits appealed.
    not_implemented("GET /checkins/flagged")


def get_checkin(db: Session, checkin_id: str, current_user: User) -> dict[str, Any]:
    # TODO: GET one check-in (API spec: owner student, or instructor/TA for the session).
    not_implemented("GET /checkins/{checkin_id}")


def appeal(db: Session, checkin_id: str, payload: AppealRequest, current_user: User, request: Request) -> dict[str, Any]:
    # TODO: Student appeal of rejected/flagged check-in (API spec: 7-day window, once).
    not_implemented("POST /checkins/{checkin_id}/appeal")


def review(db: Session, checkin_id: str, payload: ReviewRequest, current_user: User, request: Request) -> dict[str, Any]:
    # TODO: Instructor/TA review of flagged/appealed check-in (API spec).
    not_implemented("POST /checkins/{checkin_id}/review")
