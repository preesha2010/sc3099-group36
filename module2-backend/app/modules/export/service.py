import csv
import io
from datetime import datetime
from typing import Any, Optional

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.exceptions import bad_request, forbidden, not_found
from app.core.utils import to_naive_utc
from app.modules.checkins import repository as checkins_repo
from app.modules.courses import repository as courses_repo
from app.modules.enrollments import repository as enrollments_repo
from app.modules.sessions import repository as sessions_repo
from app.modules.sessions.service import can_manage_session
from app.modules.users.model import User


def _rate(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return float(numerator) / float(denominator)


def _session_record(checkin) -> dict[str, Any]:
    student = checkin.student
    return {
        "student_id": checkin.student_id,
        "student_name": student.full_name if student is not None else None,
        "student_email": student.email if student is not None else None,
        "status": checkin.status,
        "checked_in_at": checkin.checked_in_at,
        "risk_score": checkin.risk_score,
        "distance_from_venue_meters": checkin.distance_from_venue_meters,
        "liveness_passed": checkin.liveness_passed,
    }


def _attendance_rows(db, course, start_date: Optional[datetime], end_date: Optional[datetime]) -> list[dict[str, Any]]:
    start = to_naive_utc(start_date) if start_date else None
    end = to_naive_utc(end_date) if end_date else None
    all_items: list = []
    offset = 0
    while True:
        chunk, total, limit, _ = checkins_repo.list_checkins(
            db,
            course_id=course.id,
            start_date=start,
            end_date=end,
            limit=100,
            offset=offset,
        )
        all_items.extend(chunk)
        offset += limit
        if offset >= total or not chunk:
            break
    payload = []
    for checkin in all_items:
        student = checkin.student
        session = checkin.session
        payload.append(
            {
                "student_id": checkin.student_id,
                "student_name": student.full_name if student is not None else None,
                "student_email": student.email if student is not None else None,
                "session_date": session.scheduled_start.date().isoformat() if session and session.scheduled_start else None,
                "session_name": session.name if session is not None else None,
                "status": checkin.status,
                "checked_in_at": checkin.checked_in_at,
                "risk_score": checkin.risk_score,
            }
        )
    return payload


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
    course = courses_repo.get_by_id(db, course_id)
    if course is None:
        raise not_found("Course not found")
    if not enrollments_repo.user_manages_course(db, current_user, course_id):
        raise forbidden()
    records = _attendance_rows(db, course, start_date, end_date)
    kind = (fmt or "csv").lower()
    if kind == "json":
        return records
    if kind == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "student_id",
                "student_name",
                "student_email",
                "session_date",
                "session_name",
                "status",
                "checked_in_at",
                "risk_score",
            ]
        )
        for row in records:
            checked = row["checked_in_at"]
            writer.writerow(
                [
                    row["student_id"] or "",
                    row["student_name"] or "",
                    row["student_email"] or "",
                    row["session_date"] or "",
                    row["session_name"] or "",
                    row["status"] or "",
                    checked.isoformat() if checked is not None else "",
                    row["risk_score"] if row["risk_score"] is not None else "",
                ]
            )
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="attendance-{course.id}.csv"'},
        )
    raise bad_request("Invalid export format")


def session_export(db: Session, session_id: str, current_user: User, request: Request, *, fmt: str):
    session = sessions_repo.get_by_id(db, session_id)
    if session is None:
        raise not_found("Session not found")
    if not (
        can_manage_session(current_user, session)
        or enrollments_repo.user_manages_course(db, current_user, session.course_id)
    ):
        raise forbidden()
    enrolled = enrollments_repo.list_for_course(db, session.course_id, active_only=True)
    checkins = checkins_repo.list_for_session(db, session.id)
    total_enrolled = len(enrolled)
    records = [_session_record(row) for row in checkins]
    payload = {
        "session_id": session.id,
        "session_name": session.name,
        "summary": {
            "total_enrolled": total_enrolled,
            "checked_in": len(records),
            "attendance_rate": _rate(len(records), total_enrolled),
        },
        "records": records,
    }
    kind = (fmt or "csv").lower()
    if kind == "json":
        return payload
    if kind == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "student_id",
                "student_name",
                "student_email",
                "session_date",
                "session_name",
                "status",
                "checked_in_at",
                "risk_score",
            ]
        )
        session_date = session.scheduled_start.date().isoformat() if session.scheduled_start else ""
        for row in records:
            checked = row["checked_in_at"]
            writer.writerow(
                [
                    row["student_id"] or "",
                    row["student_name"] or "",
                    row["student_email"] or "",
                    session_date,
                    session.name,
                    row["status"] or "",
                    checked.isoformat() if checked is not None else "",
                    row["risk_score"] if row["risk_score"] is not None else "",
                ]
            )
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="session-{session.id}.csv"'},
        )
    raise bad_request("Invalid export format")
