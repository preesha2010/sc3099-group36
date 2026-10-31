import math
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.exceptions import forbidden, not_found
from app.core.utils import to_naive_utc, utcnow_naive
from app.db.enums import CheckinStatus, SessionStatus, UserRole
from app.modules.checkins.model import CheckIn
from app.modules.courses.model import Course
from app.modules.enrollments import repository as enrollments_repo
from app.modules.enrollments.model import Enrollment
from app.modules.sessions import repository as sessions_repo
from app.modules.sessions.model import ClassSession
from app.modules.sessions.service import can_staff_course_session
from app.modules.users import repository as users_repo
from app.modules.users.model import User


def _rate(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return float(numerator) / float(denominator)


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _avg_risk(query) -> float:
    value = query.with_entities(func.avg(CheckIn.risk_score)).scalar()
    return float(value) if value is not None else 0.0


# API-SPECIFICATION.md GET /stats/sessions/{session_id}:
# low < 0.3, medium 0.3 <= risk < 0.5, high >= 0.5. Timeline buckets are 5 minutes.
_RISK_LOW_MAX = 0.3
_RISK_MEDIUM_MAX = 0.5
_TIMELINE_BUCKET_MINUTES = 5


def risk_band(score: Optional[float]) -> str:
    value = float(score or 0.0)
    if value < _RISK_LOW_MAX:
        return "low"
    if value < _RISK_MEDIUM_MAX:
        return "medium"
    return "high"


def arrival_offset_minutes(checked_in_at: Optional[datetime], scheduled_start: Optional[datetime]) -> Optional[float]:
    if checked_in_at is None or scheduled_start is None:
        return None
    arrival = to_naive_utc(checked_in_at)
    start = to_naive_utc(scheduled_start)
    return (arrival - start).total_seconds() / 60.0


def timeline_bucket_minute(offset_minutes: float) -> int:
    """Floor into a 5-minute bucket relative to scheduled_start (early arrivals are negative)."""
    width = float(_TIMELINE_BUCKET_MINUTES)
    return int(math.floor(offset_minutes / width) * width)


def overview(db: Session, current_user: User, *, course_id: Optional[str], days: int) -> dict[str, Any]:
    now = utcnow_naive()
    today = _day_start(now)
    week_start = now - timedelta(days=7)

    if course_id:
        course = db.query(Course).filter(Course.id == course_id).first()
        if course is None:
            raise not_found("Course not found")
        if not enrollments_repo.user_manages_course(db, current_user, course_id):
            raise forbidden()

    session_q = db.query(ClassSession)
    checkin_q = db.query(CheckIn)
    if course_id:
        session_q = session_q.filter(ClassSession.course_id == course_id)
        checkin_q = checkin_q.join(ClassSession, CheckIn.session_id == ClassSession.id).filter(
            ClassSession.course_id == course_id
        )
        course_q = db.query(Course).filter(Course.id == course_id)
        enrolled_q = db.query(Enrollment).filter(
            Enrollment.course_id == course_id, Enrollment.is_active.is_(True)
        )
    else:
        course_q = db.query(Course)
        enrolled_q = db.query(Enrollment).filter(Enrollment.is_active.is_(True))

    total_sessions = session_q.count()
    active_sessions = session_q.filter(ClassSession.status == SessionStatus.ACTIVE.value).count()
    total_courses = course_q.count()
    if course_id:
        total_students = enrolled_q.count()
    else:
        total_students = db.query(User).filter(User.role == UserRole.STUDENT.value).count()

    today_checkins = checkin_q.filter(CheckIn.checked_in_at >= today).count()
    week_checkins = checkin_q.filter(CheckIn.checked_in_at >= week_start).count()
    flagged_pending = checkin_q.filter(
        CheckIn.status.in_([CheckinStatus.FLAGGED.value, CheckinStatus.APPEALED.value])
    ).count()
    total_checkins = checkin_q.count()
    approved = checkin_q.filter(CheckIn.status == CheckinStatus.APPROVED.value).count()
    approval_rate = _rate(approved, total_checkins)
    avg_risk = _avg_risk(checkin_q)
    high_risk_today = checkin_q.filter(CheckIn.checked_in_at >= today, CheckIn.risk_score >= 0.5).count()

    sessions = session_q.all()
    enrollment_by_course: dict[str, int] = {}
    attendance_rates = []
    for session in sessions:
        if session.course_id not in enrollment_by_course:
            enrollment_by_course[session.course_id] = len(
                enrollments_repo.list_for_course(db, session.course_id, active_only=True)
            )
        checked = db.query(CheckIn).filter(CheckIn.session_id == session.id).count()
        attendance_rates.append(_rate(checked, enrollment_by_course[session.course_id]))
    average_attendance_rate = _rate(sum(attendance_rates), len(attendance_rates))

    checkins_by_day = []
    attendance_rate_by_day = []
    for offset in range(days):
        day = _day_start(now - timedelta(days=offset))
        next_day = day + timedelta(days=1)
        count = checkin_q.filter(CheckIn.checked_in_at >= day, CheckIn.checked_in_at < next_day).count()
        day_sessions = [
            session
            for session in sessions
            if session.scheduled_start is not None and day <= session.scheduled_start < next_day
        ]
        expected = sum(enrollment_by_course.get(session.course_id, 0) for session in day_sessions)
        checkins_by_day.append({"date": day.date().isoformat(), "count": count})
        attendance_rate_by_day.append({"date": day.date().isoformat(), "rate": _rate(count, expected)})

    return {
        "total_sessions": total_sessions,
        "active_sessions": active_sessions,
        "total_courses": total_courses,
        "total_students": total_students,
        "today_checkins": today_checkins,
        "total_checkins_today": today_checkins,
        "total_checkins_week": week_checkins,
        "flagged_pending": flagged_pending,
        "flagged_pending_review": flagged_pending,
        "approval_rate": approval_rate,
        "average_attendance_rate": average_attendance_rate,
        "average_risk_score": avg_risk,
        "high_risk_checkins_today": high_risk_today,
        "trends": {
            "checkins_by_day": checkins_by_day,
            "attendance_rate_by_day": attendance_rate_by_day,
        },
    }


def session_stats(db: Session, session_id: str, current_user: User) -> dict[str, Any]:
    session = sessions_repo.get_by_id(db, session_id)
    if session is None:
        raise not_found("Session not found")
    if not can_staff_course_session(db, current_user, session):
        raise forbidden()
    course = session.course
    enrolled = enrollments_repo.list_for_course(db, session.course_id, active_only=True)
    checkins = db.query(CheckIn).filter(CheckIn.session_id == session.id).all()
    by_status = {
        "approved": 0,
        "flagged": 0,
        "rejected": 0,
        "pending": 0,
        "appealed": 0,
    }
    risk_sum = 0.0
    dist_sum = 0.0
    dist_n = 0
    risk_distribution = {"low": 0, "medium": 0, "high": 0}
    timeline_counts: Counter[int] = Counter()
    arrival_sum = 0.0
    arrival_n = 0
    scheduled_start = session.scheduled_start
    for row in checkins:
        if row.status in by_status:
            by_status[row.status] += 1
        risk_sum += float(row.risk_score or 0.0)
        risk_distribution[risk_band(row.risk_score)] += 1
        if row.distance_from_venue_meters is not None:
            dist_sum += row.distance_from_venue_meters
            dist_n += 1
        offset = arrival_offset_minutes(row.checked_in_at, scheduled_start)
        if offset is not None:
            arrival_sum += offset
            arrival_n += 1
            timeline_counts[timeline_bucket_minute(offset)] += 1
    checked_in_count = len(checkins)
    total_enrolled = len(enrolled)
    return {
        "session_id": session.id,
        "session_name": session.name,
        "course_code": course.code if course is not None else None,
        "scheduled_start": session.scheduled_start,
        "status": session.status,
        "total_enrolled": total_enrolled,
        "checked_in_count": checked_in_count,
        "checked_in": checked_in_count,
        "approved_count": by_status["approved"],
        "flagged_count": by_status["flagged"],
        "attendance_rate": _rate(checked_in_count, total_enrolled),
        "average_risk_score": _rate(risk_sum, checked_in_count),
        "average_distance_meters": _rate(dist_sum, dist_n),
        "average_checkin_time_minutes": _rate(arrival_sum, arrival_n),
        "risk_distribution": risk_distribution,
        "checkin_timeline": [
            {"minute": minute, "count": timeline_counts[minute]}
            for minute in sorted(timeline_counts)
        ],
        "by_status": {k: v for k, v in by_status.items() if k != "appealed"},
    }


def course_stats(
    db: Session,
    course_id: str,
    current_user: User,
    *,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
) -> dict[str, Any]:
    course = db.query(Course).filter(Course.id == course_id).first()
    if course is None:
        raise not_found("Course not found")
    if not enrollments_repo.user_manages_course(db, current_user, course_id):
        raise forbidden()
    start = to_naive_utc(start_date) if start_date else None
    end = to_naive_utc(end_date) if end_date else None
    session_q = db.query(ClassSession).filter(ClassSession.course_id == course_id)
    if start:
        session_q = session_q.filter(ClassSession.scheduled_start >= start)
    if end:
        session_q = session_q.filter(ClassSession.scheduled_start <= end)
    sessions = session_q.all()
    enrolled = enrollments_repo.list_for_course(db, course_id, active_only=True)
    total_enrolled = len(enrolled)
    session_rows = []
    rates = []
    flagged_checkins = 0
    for session in sessions:
        checkins = db.query(CheckIn).filter(CheckIn.session_id == session.id).all()
        checked_in = len(checkins)
        flagged_checkins += sum(1 for row in checkins if row.status in (CheckinStatus.FLAGGED.value, CheckinStatus.APPEALED.value))
        rate = _rate(checked_in, total_enrolled)
        rates.append(rate)
        session_rows.append(
            {
                "session_id": session.id,
                "name": session.name,
                "date": session.scheduled_start.date().isoformat() if session.scheduled_start else None,
                "attendance_rate": rate,
                "checked_in": checked_in,
            }
        )
    student_attendance = []
    low_attendance_alerts = []
    session_ids = [s.id for s in sessions]
    for enrollment in enrolled:
        student = enrollment.student
        attended = 0
        risk_sum = 0.0
        if session_ids:
            rows = db.query(CheckIn).filter(
                CheckIn.student_id == enrollment.student_id,
                CheckIn.session_id.in_(session_ids),
            ).all()
            attended = len(rows)
            risk_sum = sum(float(r.risk_score or 0.0) for r in rows)
        att_rate = _rate(attended, len(sessions))
        item = {
            "student_id": enrollment.student_id,
            "student_name": student.full_name if student is not None else None,
            "sessions_attended": attended,
            "attendance_rate": att_rate,
            "average_risk_score": _rate(risk_sum, attended),
        }
        student_attendance.append(item)
        if att_rate < 0.6 and sessions:
            low_attendance_alerts.append(
                {
                    "student_id": enrollment.student_id,
                    "student_name": student.full_name if student is not None else None,
                    "attendance_rate": att_rate,
                    "sessions_missed": len(sessions) - attended,
                }
            )
    average_attendance_rate = _rate(sum(rates), len(rates))
    return {
        "course_id": course.id,
        "course_code": course.code,
        "course_name": course.name,
        "total_sessions": len(sessions),
        "total_enrolled": total_enrolled,
        "average_attendance_rate": average_attendance_rate,
        "overall_attendance_rate": average_attendance_rate,
        "flagged_checkins": flagged_checkins,
        "sessions": session_rows,
        "student_attendance": student_attendance,
        "low_attendance_alerts": low_attendance_alerts,
    }


def student_stats(db: Session, student_id: str, current_user: User) -> dict[str, Any]:
    student = users_repo.get_by_id(db, student_id)
    if student is None:
        raise not_found("Student not found")
    is_admin = current_user.role == UserRole.ADMIN.value
    if not is_admin and not (
        current_user.role == UserRole.INSTRUCTOR.value
        and enrollments_repo.instructor_teaches_enrolled_student(db, current_user.id, student_id)
    ):
        raise forbidden()
    enrollments = list(enrollments_repo.list_for_student(db, student_id, active_only=True))
    if not is_admin:
        enrollments = [
            row
            for row in enrollments
            if enrollments_repo.instructor_teaches_course(db, current_user.id, row.course_id)
        ]
        if not enrollments:
            raise forbidden()
    course_ids = [row.course_id for row in enrollments]
    sessions = sessions_repo.list_for_courses(db, course_ids)
    authorized_session_ids = {session.id for session in sessions}
    checkins = [
        row
        for row in db.query(CheckIn)
        .filter(CheckIn.student_id == student_id)
        .order_by(CheckIn.checked_in_at.desc())
        .all()
        if row.session_id in authorized_session_ids
    ]
    attended_ids = {row.session_id for row in checkins}
    total_sessions = len(sessions)
    attended_sessions = len(attended_ids)
    courses_payload = []
    for enrollment in enrollments:
        course = enrollment.course
        course_sessions = [s for s in sessions if s.course_id == enrollment.course_id]
        course_checkins = [c for c in checkins if c.session_id in {s.id for s in course_sessions}]
        courses_payload.append(
            {
                "course_id": enrollment.course_id,
                "course_code": course.code if course is not None else None,
                "attendance_rate": _rate(len(course_checkins), len(course_sessions)),
                "sessions_attended": len(course_checkins),
                "total_sessions": len(course_sessions),
                "average_risk_score": _rate(sum(float(c.risk_score or 0.0) for c in course_checkins), len(course_checkins)),
            }
        )
    recent = []
    for row in checkins[:10]:
        session = row.session
        course = session.course if session is not None else None
        item = {
            "session_name": session.name if session is not None else None,
            "course_code": course.code if course is not None else None,
            "checked_in_at": row.checked_in_at,
            "status": row.status,
            "session_id": row.session_id,
        }
        recent.append(item)
    return {
        "student_id": student.id,
        "student_name": student.full_name,
        "student_email": student.email,
        "total_enrolled_courses": len(enrollments),
        "total_sessions": total_sessions,
        "attended_sessions": attended_sessions,
        "attendance_rate": _rate(attended_sessions, total_sessions),
        "recent_sessions": recent,
        "recent_checkins": recent,
        "courses": courses_payload,
    }
