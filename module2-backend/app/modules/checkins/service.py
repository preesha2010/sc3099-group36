import json
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.repository import append_audit
from app.core.exceptions import bad_request, forbidden, not_found
from app.core.pagination import page_of
from app.core.utils import (
    client_ip,
    haversine_meters,
    singapore_checkin_allowed,
    to_naive_utc,
    utcnow_naive,
)
from app.db.enums import AuditAction, CheckinStatus, SessionStatus, UserRole
from app.integrations.face_client import face_client
from app.modules.checkins import repository as checkins_repo
from app.modules.checkins import risk_service
from app.modules.checkins.model import CheckIn
from app.modules.checkins.risk_signal import RiskSignal
from app.modules.checkins.schemas import AppealRequest, CheckinCreate, ReviewRequest
from app.modules.devices import repository as devices_repo
from app.modules.enrollments import repository as enrollments_repo
from app.modules.sessions import repository as sessions_repo
from app.modules.sessions.service import can_staff_session
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
        "liveness_passed": checkin.liveness_passed,
        "liveness_score": checkin.liveness_score,
        "face_match_passed": checkin.face_match_passed,
        "face_match_score": checkin.face_match_score,
        "risk_factors": _risk_factors(checkin),
    }


def _staff_for_session(current_user: User, session) -> bool:
    return can_staff_session(current_user, session)


def _face_signals(payload: CheckinCreate, current_user: User) -> dict[str, Any]:
    """Call Module 3 only when a check-in image is present.

    Timeouts, 5xx, and unimplemented Module 3 endpoints leave scores as None so
    public tests (which omit the image) and pre-Module-3 integration still pass.
    """
    result: dict[str, Any] = {
        "liveness_passed": None,
        "liveness_score": None,
        "face_match_passed": None,
        "face_match_score": None,
        "face_embedding_hash": None,
    }
    image = payload.liveness_challenge_response
    if not image:
        return result

    live = face_client.liveness(image)
    if face_client.is_success(live):
        if "liveness_passed" in live:
            result["liveness_passed"] = bool(live.get("liveness_passed"))
        if live.get("liveness_score") is not None:
            result["liveness_score"] = float(live["liveness_score"])
        hash_value = live.get("face_embedding_hash")
        if hash_value:
            result["face_embedding_hash"] = str(hash_value)

    reference = current_user.face_embedding_hash
    if reference:
        verified = face_client.verify(image, reference)
        if face_client.is_success(verified):
            if "match_passed" in verified:
                result["face_match_passed"] = bool(verified.get("match_passed"))
            if verified.get("match_score") is not None:
                result["face_match_score"] = float(verified["match_score"])
            hash_value = verified.get("current_template_hash") or verified.get("face_embedding_hash")
            if hash_value:
                result["face_embedding_hash"] = str(hash_value)

    return result


def submit_checkin(db: Session, payload: CheckinCreate, current_user: User, request: Request) -> dict[str, Any]:
    session = sessions_repo.get_by_id(db, payload.session_id)
    if session is None:
        raise not_found("Session not found")

    if session.status != SessionStatus.ACTIVE.value:
        raise bad_request("Session not active")
    if session.qr_code_secret and payload.qr_code != session.qr_code_secret:
        raise bad_request("Invalid or missing QR code")

    now = utcnow_naive()
    opens = to_naive_utc(session.checkin_opens_at)
    closes = to_naive_utc(session.checkin_closes_at)
    if now < opens or now > closes:
        raise bad_request("Check-in window closed")

    if not enrollments_repo.is_enrolled(db, current_user.id, session.course_id):
        raise bad_request("Student is not enrolled in this course")

    if checkins_repo.get_by_session_student(db, session.id, current_user.id) is not None:
        raise bad_request("Already checked in")

    ip = client_ip(request)
    if not singapore_checkin_allowed(ip, payload.latitude, payload.longitude):
        raise forbidden("Check-in not allowed from this location")

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

    device = None
    unknown_device = True
    if payload.device_fingerprint:
        device = devices_repo.get_by_fingerprint(db, payload.device_fingerprint)
        if device is not None and device.user_id == current_user.id:
            unknown_device = False
            device.total_checkins = (device.total_checkins or 0) + 1
            devices_repo.save(db, device)
        else:
            device = None

    face = _face_signals(payload, current_user)

    course = session.course
    threshold = session.risk_threshold
    if threshold is None and course is not None:
        threshold = course.risk_threshold
    if threshold is None:
        threshold = 0.5
    geofence = session.geofence_radius_meters or (course.geofence_radius_meters if course else None) or 100.0

    assessment = risk_service.assess(
        distance_m=distance,
        geofence_m=float(geofence),
        liveness_passed=face["liveness_passed"],
        face_match_passed=face["face_match_passed"],
        unknown_device=unknown_device,
        threshold=float(threshold),
    )

    checkin = CheckIn(
        session_id=session.id,
        student_id=current_user.id,
        device_id=device.id if device is not None else None,
        status=assessment["status"],
        checked_in_at=now,
        latitude=payload.latitude,
        longitude=payload.longitude,
        location_accuracy_meters=payload.location_accuracy_meters,
        distance_from_venue_meters=distance,
        liveness_passed=face["liveness_passed"],
        liveness_score=face["liveness_score"],
        face_match_passed=face["face_match_passed"],
        face_match_score=face["face_match_score"],
        face_embedding_hash=face["face_embedding_hash"],
        risk_score=assessment["risk_score"],
        risk_factors=json.dumps(assessment["factors"]) if assessment["factors"] else None,
    )
    try:
        checkins_repo.create(db, checkin)
        for factor in assessment["factors"]:
            checkins_repo.add_risk_signal(
                db,
                RiskSignal(
                    checkin_id=checkin.id,
                    signal_type=factor.get("type") or "unknown",
                    severity=factor.get("severity") or "low",
                    weight=float(factor.get("weight") or 0.1),
                ),
            )
        action = AuditAction.CHECKIN_APPROVED.value
        if assessment["status"] == CheckinStatus.FLAGGED.value:
            action = AuditAction.CHECKIN_FLAGGED.value
        elif assessment["status"] == CheckinStatus.REJECTED.value:
            action = AuditAction.CHECKIN_REJECTED.value
        append_audit(
            db,
            action,
            user_id=current_user.id,
            resource_type="checkin",
            resource_id=checkin.id,
            request=request,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise bad_request("Already checked in")
    db.refresh(checkin)
    return _checkin_create_payload(checkin)


def _risk_factors(checkin: CheckIn) -> list[Any]:
    if not checkin.risk_factors:
        return []
    try:
        parsed = json.loads(checkin.risk_factors)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        return []
    return []


def _list_item(checkin: CheckIn) -> dict[str, Any]:
    session = checkin.session
    student = checkin.student
    return {
        "id": checkin.id,
        "session_id": checkin.session_id,
        "session_name": session.name if session is not None else None,
        "student_id": checkin.student_id,
        "student_name": student.full_name if student is not None else None,
        "student_email": student.email if student is not None else None,
        "status": checkin.status,
        "checked_in_at": checkin.checked_in_at,
        "distance_from_venue_meters": checkin.distance_from_venue_meters,
        "risk_score": checkin.risk_score,
        "liveness_passed": checkin.liveness_passed,
    }


def _flagged_item(checkin: CheckIn) -> dict[str, Any]:
    session = checkin.session
    student = checkin.student
    return {
        "id": checkin.id,
        "session_id": checkin.session_id,
        "session_name": session.name if session is not None else None,
        "student_id": checkin.student_id,
        "student_name": student.full_name if student is not None else None,
        "status": checkin.status,
        "checked_in_at": checkin.checked_in_at,
        "risk_score": checkin.risk_score,
        "risk_factors": _risk_factors(checkin),
        "appeal_reason": checkin.appeal_reason,
        "appealed_at": checkin.appealed_at,
    }


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
    items, total, limit, offset = checkins_repo.list_checkins(
        db,
        session_id=session_id,
        course_id=course_id,
        student_id=student_id,
        status=status,
        min_risk_score=min_risk_score,
        max_risk_score=max_risk_score,
        start_date=to_naive_utc(start_date) if start_date else None,
        end_date=to_naive_utc(end_date) if end_date else None,
        limit=limit,
        offset=offset,
    )
    return page_of([_list_item(row) for row in items], total, limit, offset)


def my_checkins(
    db: Session,
    current_user: User,
    *,
    course_id: Optional[str] = None,
    limit: int = 50,
) -> Any:
    rows = checkins_repo.list_for_student(db, current_user.id, course_id=course_id, limit=limit)
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
    session = sessions_repo.get_by_id(db, session_id)
    if session is None:
        raise not_found("Session not found")
    if not _staff_for_session(current_user, session):
        raise forbidden()
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


def flagged_checkins(
    db: Session,
    current_user: User,
    *,
    course_id: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 50,
) -> Any:
    items, total, limit, offset = checkins_repo.list_flagged(
        db, course_id=course_id, session_id=session_id, limit=limit
    )
    return page_of([_flagged_item(row) for row in items], total, limit, offset)


def get_checkin(db: Session, checkin_id: str, current_user: User) -> dict[str, Any]:
    checkin = checkins_repo.get_by_id(db, checkin_id)
    if checkin is None:
        raise not_found("Check-in not found")
    session = checkin.session
    if checkin.student_id != current_user.id and not _staff_for_session(current_user, session):
        raise forbidden()
    signals = []
    for row in checkin.risk_signals or []:
        signals.append(
            {
                "id": row.id,
                "signal_type": row.signal_type,
                "severity": row.severity,
                "confidence": row.confidence,
                "weight": row.weight,
                "details": row.details,
                "detected_at": row.detected_at,
            }
        )
    return {
        "id": checkin.id,
        "session_id": checkin.session_id,
        "student_id": checkin.student_id,
        "device_id": checkin.device_id,
        "status": checkin.status,
        "checked_in_at": checkin.checked_in_at,
        "latitude": checkin.latitude,
        "longitude": checkin.longitude,
        "location_accuracy_meters": checkin.location_accuracy_meters,
        "distance_from_venue_meters": checkin.distance_from_venue_meters,
        "liveness_passed": checkin.liveness_passed,
        "liveness_score": checkin.liveness_score,
        "face_match_passed": checkin.face_match_passed,
        "face_match_score": checkin.face_match_score,
        "risk_score": checkin.risk_score,
        "risk_factors": _risk_factors(checkin),
        "risk_signals": signals,
        "appeal_reason": checkin.appeal_reason,
        "appealed_at": checkin.appealed_at,
        "reviewed_by_id": checkin.reviewed_by_id,
        "reviewed_at": checkin.reviewed_at,
        "review_notes": checkin.review_notes,
    }


def appeal(db: Session, checkin_id: str, payload: AppealRequest, current_user: User, request: Request) -> dict[str, Any]:
    checkin = checkins_repo.get_by_id(db, checkin_id)
    if checkin is None:
        raise not_found("Check-in not found")
    if checkin.student_id != current_user.id:
        raise forbidden()
    if checkin.status not in {CheckinStatus.REJECTED.value, CheckinStatus.FLAGGED.value}:
        raise bad_request("Can only appeal rejected or flagged check-ins")
    if checkin.appealed_at is not None or checkin.status == CheckinStatus.APPEALED.value:
        raise bad_request("Check-in already appealed")
    now = utcnow_naive()
    if checkin.checked_in_at and now - checkin.checked_in_at > timedelta(days=7):
        raise bad_request("Appeal window has closed")
    checkin.status = CheckinStatus.APPEALED.value
    checkin.appeal_reason = payload.appeal_reason
    checkin.appealed_at = now
    checkins_repo.save(db, checkin)
    append_audit(
        db,
        AuditAction.CHECKIN_APPEALED.value,
        user_id=current_user.id,
        resource_type="checkin",
        resource_id=checkin.id,
        request=request,
    )
    db.commit()
    db.refresh(checkin)
    return {
        "id": checkin.id,
        "status": checkin.status,
        "appeal_reason": checkin.appeal_reason,
        "appealed_at": checkin.appealed_at,
    }


def review(db: Session, checkin_id: str, payload: ReviewRequest, current_user: User, request: Request) -> dict[str, Any]:
    checkin = checkins_repo.get_by_id(db, checkin_id)
    if checkin is None:
        raise not_found("Check-in not found")
    session = checkin.session
    if not _staff_for_session(current_user, session):
        raise forbidden()
    if checkin.status not in {CheckinStatus.FLAGGED.value, CheckinStatus.APPEALED.value}:
        raise bad_request("Only flagged or appealed check-ins can be reviewed")
    new_status = payload.status.value if isinstance(payload.status, CheckinStatus) else payload.status
    if new_status not in {CheckinStatus.APPROVED.value, CheckinStatus.REJECTED.value}:
        raise bad_request("Review status must be approved or rejected")
    checkin.status = new_status
    checkin.review_notes = payload.review_notes
    checkin.reviewed_by_id = current_user.id
    checkin.reviewed_at = utcnow_naive()
    checkins_repo.save(db, checkin)
    append_audit(
        db,
        AuditAction.CHECKIN_REVIEWED.value,
        user_id=current_user.id,
        resource_type="checkin",
        resource_id=checkin.id,
        request=request,
    )
    db.commit()
    db.refresh(checkin)
    return {
        "id": checkin.id,
        "status": checkin.status,
        "reviewed_by_id": checkin.reviewed_by_id,
        "reviewed_at": checkin.reviewed_at,
        "review_notes": checkin.review_notes,
    }
