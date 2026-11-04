"""Upsert isolated E2E fixtures. Refuses the shared saiv database. Does not DROP tables."""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

_DIR = Path(__file__).resolve().parent
_REPO = _DIR.parents[2]
_BACKEND = _REPO / "module2-backend"
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from isolation import IsolationError, assert_isolated_database_name  # noqa: E402
from settings import load_settings  # noqa: E402

REQUIRED_TABLES = (
    "users",
    "courses",
    "sessions",
    "enrollments",
    "course_instructors",
    "checkins",
    "risk_signals",
)

USERS = (
    ("admin", "e2e.admin@saiv.edu.sg", "E2E Admin", "admin"),
    ("instructor", "e2e.instructor@saiv.edu.sg", "E2E Instructor", "instructor"),
    ("outsider", "e2e.outsider@saiv.edu.sg", "E2E Unassigned Instructor", "instructor"),
    ("success", "e2e.success@saiv.edu.sg", "E2E Success Student", "student"),
    ("mismatch", "e2e.mismatch@saiv.edu.sg", "E2E Mismatch Student", "student"),
    ("liveness", "e2e.liveness@saiv.edu.sg", "E2E Liveness Student", "student"),
    ("outage", "e2e.outage@saiv.edu.sg", "E2E Outage Student", "student"),
)

COURSE_CODE = "E2E101"
SESSION_NAME = "E2E Active Session"
NTU_LAT, NTU_LNG = 1.3483, 103.6831


def seed() -> dict[str, str]:
    settings = load_settings()
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        current = connection.execute(text("SELECT current_database()")).scalar()
        assert_isolated_database_name(str(current))
        if str(current) != settings.database.database:
            raise IsolationError(
                f"Connected to {current!r} but E2E_DATABASE_URL names "
                f"{settings.database.database!r}"
            )
        inspector = inspect(engine)
        missing = [name for name in REQUIRED_TABLES if not inspector.has_table(name)]
        if missing:
            raise IsolationError(
                "Isolated database is missing tables: "
                + ", ".join(missing)
                + ". Start isolated Module 2 once so its own init_db can create "
                "schema, then re-run seed. This script will not create, drop, "
                "or migrate tables."
            )

    from app.core.security import hash_password
    from app.core.utils import utcnow_naive
    from app.modules.checkins.model import CheckIn
    from app.modules.checkins.risk_signal import RiskSignal
    from app.modules.courses.instructor_model import CourseInstructor
    from app.modules.courses.model import Course
    from app.modules.enrollments.model import Enrollment
    from app.modules.sessions.model import ClassSession
    from app.modules.users.model import User

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    nonce = f"isolated-e2e {uuid4()}"
    try:
        hashed = hash_password(settings.password)
        users: dict = {}
        for key, email, name, role in USERS:
            user = db.query(User).filter(User.email == email).one_or_none()
            if user is None:
                user = User(
                    email=email,
                    full_name=name,
                    hashed_password=hashed,
                    role=role,
                    is_active=True,
                    camera_consent=False,
                    geolocation_consent=True,
                )
                db.add(user)
                db.flush()
            else:
                user.hashed_password = hashed
                user.role = role
                user.is_active = True
                user.camera_consent = False
                user.is_locked = False
                user.failed_login_count = 0
                keep_outage_template = key == "outage" and (
                    settings.run_outage or settings.run_retry
                )
                if not keep_outage_template:
                    user.face_enrolled = False
                    user.face_embedding_hash = None
            users[key] = user

        student_ids = [users[key].id for key in ("success", "mismatch", "liveness", "outage")]
        checkin_ids = [
            row.id
            for row in db.query(CheckIn.id).filter(CheckIn.student_id.in_(student_ids)).all()
        ]
        if checkin_ids:
            db.query(RiskSignal).filter(RiskSignal.checkin_id.in_(checkin_ids)).delete(
                synchronize_session=False
            )
            db.query(CheckIn).filter(CheckIn.id.in_(checkin_ids)).delete(synchronize_session=False)

        course = db.query(Course).filter(Course.code == COURSE_CODE).one_or_none()
        if course is None:
            course = Course(
                code=COURSE_CODE,
                name="Isolated M2/M3 E2E Course",
                description=nonce,
                semester="2026S1",
                is_active=True,
                venue_latitude=NTU_LAT,
                venue_longitude=NTU_LNG,
                venue_name="NTU E2E Lab",
                geofence_radius_meters=150.0,
                require_face_recognition=True,
                require_device_binding=False,
                risk_threshold=0.5,
            )
            db.add(course)
            db.flush()
        else:
            course.description = nonce
            course.require_face_recognition = True
            course.venue_latitude = NTU_LAT
            course.venue_longitude = NTU_LNG
            course.geofence_radius_meters = 150.0
            course.require_device_binding = False

        link = (
            db.query(CourseInstructor)
            .filter(
                CourseInstructor.course_id == course.id,
                CourseInstructor.instructor_id == users["instructor"].id,
            )
            .one_or_none()
        )
        if link is None:
            db.add(
                CourseInstructor(
                    course_id=course.id,
                    instructor_id=users["instructor"].id,
                    is_active=True,
                    assigned_by_id=users["admin"].id,
                )
            )
        else:
            link.is_active = True

        now = utcnow_naive()
        session = db.query(ClassSession).filter(ClassSession.name == SESSION_NAME).one_or_none()
        if session is None:
            session = ClassSession(
                course_id=course.id,
                instructor_id=users["instructor"].id,
                name=SESSION_NAME,
                session_type="lecture",
                scheduled_start=now - timedelta(minutes=10),
                scheduled_end=now + timedelta(hours=2),
                checkin_opens_at=now - timedelta(minutes=10),
                checkin_closes_at=now + timedelta(hours=2),
                status="active",
                venue_latitude=NTU_LAT,
                venue_longitude=NTU_LNG,
                venue_name="NTU E2E Lab",
                geofence_radius_meters=150.0,
                require_liveness_check=True,
                require_face_match=True,
                risk_threshold=0.5,
                qr_code_secret=None,
            )
            db.add(session)
            db.flush()
        else:
            session.status = "active"
            session.course_id = course.id
            session.instructor_id = users["instructor"].id
            session.checkin_opens_at = now - timedelta(minutes=10)
            session.checkin_closes_at = now + timedelta(hours=2)
            session.require_liveness_check = True
            session.require_face_match = True
            session.venue_latitude = NTU_LAT
            session.venue_longitude = NTU_LNG

        for key in ("success", "mismatch", "liveness", "outage"):
            enrollment = (
                db.query(Enrollment)
                .filter(
                    Enrollment.student_id == users[key].id,
                    Enrollment.course_id == course.id,
                )
                .one_or_none()
            )
            if enrollment is None:
                db.add(
                    Enrollment(
                        student_id=users[key].id,
                        course_id=course.id,
                        is_active=True,
                    )
                )
            else:
                enrollment.is_active = True
                enrollment.dropped_at = None

        db.commit()
        return {
            "database": str(current),
            "nonce": nonce,
            "admin_id": users["admin"].id,
            "instructor_id": users["instructor"].id,
            "outsider_id": users["outsider"].id,
            "success_id": users["success"].id,
            "mismatch_id": users["mismatch"].id,
            "liveness_id": users["liveness"].id,
            "outage_id": users["outage"].id,
            "course_id": course.id,
            "session_id": session.id,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        engine.dispose()


def main() -> int:
    try:
        ids = seed()
    except IsolationError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    for key, value in ids.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
