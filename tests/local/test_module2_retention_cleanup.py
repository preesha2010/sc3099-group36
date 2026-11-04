"""Isolated sqlite tests for expired check-in retention cleanup."""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

_BACKEND = Path(__file__).resolve().parents[2] / "module2-backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.audit.model import AuditLog  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db import models as _models  # noqa: E402, F401
from app.modules.checkins.model import CheckIn  # noqa: E402
from app.modules.checkins.risk_signal import RiskSignal  # noqa: E402
from app.modules.courses.model import Course  # noqa: E402
from app.modules.sessions.model import ClassSession  # noqa: E402
from app.modules.users.model import User  # noqa: E402
from app.retention.cleanup import purge_expired_checkins  # noqa: E402
from app.retention.safety import is_shared_saiv_database  # noqa: E402
from app.retention.__main__ import main as retention_cli_main  # noqa: E402

NOW = datetime(2024, 6, 15, 12, 0, 0)


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'retention.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(db, *, email=None, deletion=None) -> User:
    user = User(
        id=str(uuid.uuid4()),
        email=email or f"{uuid.uuid4().hex[:8]}@test.com",
        full_name="Retention User",
        hashed_password="x",
        role="student",
        scheduled_deletion_at=deletion,
    )
    db.add(user)
    db.flush()
    return user


def _session(db, user: User) -> ClassSession:
    course = Course(
        id=str(uuid.uuid4()),
        code=f"R{uuid.uuid4().hex[:6].upper()}",
        name="Retention Course",
        semester="AY2024-25 Sem 1",
    )
    db.add(course)
    db.flush()
    session = ClassSession(
        id=str(uuid.uuid4()),
        course_id=course.id,
        instructor_id=user.id,
        name="Lecture",
        scheduled_start=NOW,
        scheduled_end=NOW + timedelta(hours=2),
        checkin_opens_at=NOW - timedelta(minutes=10),
        checkin_closes_at=NOW + timedelta(hours=1),
        status="closed",
    )
    db.add(session)
    db.flush()
    return session


def _checkin(db, session, user, *, deletion, status="approved") -> CheckIn:
    row = CheckIn(
        id=str(uuid.uuid4()),
        session_id=session.id,
        student_id=user.id,
        status=status,
        checked_in_at=NOW - timedelta(days=40),
        risk_score=0.1,
        scheduled_deletion_at=deletion,
    )
    db.add(row)
    db.flush()
    return row


def _signal(db, checkin: CheckIn) -> RiskSignal:
    row = RiskSignal(
        id=str(uuid.uuid4()),
        checkin_id=checkin.id,
        signal_type="device_unknown",
        severity="low",
        weight=0.1,
    )
    db.add(row)
    db.flush()
    return row


def _audit(db, user, checkin: CheckIn) -> AuditLog:
    row = AuditLog(
        id=str(uuid.uuid4()),
        user_id=user.id,
        action="checkin_approved",
        resource_type="checkin",
        resource_id=checkin.id,
        success=True,
        timestamp=NOW,
    )
    db.add(row)
    db.flush()
    return row


def test_expired_checkins_are_removed_with_risk_signals(db):
    user = _user(db)
    other = _user(db)
    session = _session(db, user)
    expired = _checkin(db, session, user, deletion=NOW - timedelta(seconds=1))
    keep = _checkin(db, session, other, deletion=NOW + timedelta(days=1))
    expired_signal = _signal(db, expired)
    keep_signal = _signal(db, keep)
    audit = _audit(db, user, expired)
    db.commit()
    expired_id, keep_id = expired.id, keep.id
    expired_signal_id, keep_signal_id = expired_signal.id, keep_signal.id
    audit_id = audit.id

    result = purge_expired_checkins(db, now=NOW)
    assert result["checkins_deleted"] == 1
    assert result["risk_signals_deleted"] == 1

    assert db.get(CheckIn, expired_id) is None
    assert db.get(RiskSignal, expired_signal_id) is None
    assert db.get(CheckIn, keep_id) is not None
    assert db.get(RiskSignal, keep_signal_id) is not None
    remaining_audit = db.get(AuditLog, audit_id)
    assert remaining_audit is not None
    assert remaining_audit.resource_id == expired_id
    assert remaining_audit.action == "checkin_approved"


def test_unexpired_and_unscheduled_checkins_remain(db):
    user = _user(db)
    other = _user(db)
    session = _session(db, user)
    future = _checkin(db, session, user, deletion=NOW + timedelta(days=30), status="flagged")
    unscheduled = _checkin(db, session, other, deletion=None, status="rejected")
    db.commit()
    original_status = future.status

    result = purge_expired_checkins(db, now=NOW)
    assert result == {"checkins_deleted": 0, "risk_signals_deleted": 0}
    assert db.get(CheckIn, future.id).status == original_status
    assert db.get(CheckIn, unscheduled.id) is not None


def test_cleanup_twice_is_idempotent(db):
    user = _user(db)
    session = _session(db, user)
    expired = _checkin(db, session, user, deletion=NOW - timedelta(days=1))
    _signal(db, expired)
    db.commit()

    first = purge_expired_checkins(db, now=NOW)
    second = purge_expired_checkins(db, now=NOW)
    assert first["checkins_deleted"] == 1
    assert second == {"checkins_deleted": 0, "risk_signals_deleted": 0}
    assert db.query(CheckIn).count() == 0
    assert db.query(RiskSignal).count() == 0


def test_commit_failure_leaves_checkins_and_signals(db):
    user = _user(db)
    session = _session(db, user)
    expired = _checkin(db, session, user, deletion=NOW - timedelta(days=1))
    signal = _signal(db, expired)
    db.commit()

    with patch.object(db, "commit", side_effect=RuntimeError("commit failed")):
        with pytest.raises(RuntimeError, match="commit failed"):
            purge_expired_checkins(db, now=NOW)

    assert db.get(CheckIn, expired.id) is not None
    assert db.get(RiskSignal, signal.id) is not None


def test_does_not_delete_users_or_audit_even_if_user_timestamp_expired(db):
    user = _user(db, deletion=NOW - timedelta(days=1))
    session = _session(db, user)
    keep = _checkin(db, session, user, deletion=NOW + timedelta(days=5))
    audit = _audit(db, user, keep)
    db.commit()

    purge_expired_checkins(db, now=NOW)
    assert db.get(User, user.id) is not None
    assert db.get(CheckIn, keep.id) is not None
    assert db.get(AuditLog, audit.id) is not None
    assert db.query(AuditLog).count() == 1


def test_fresh_checkin_default_retention_is_not_expired(db):
    user = _user(db)
    session = _session(db, user)
    row = CheckIn(
        id=str(uuid.uuid4()),
        session_id=session.id,
        student_id=user.id,
        status="approved",
        checked_in_at=NOW,
        risk_score=0.0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    assert row.scheduled_deletion_at is not None
    assert row.scheduled_deletion_at > NOW

    result = purge_expired_checkins(db, now=NOW)
    assert result["checkins_deleted"] == 0
    assert db.get(CheckIn, row.id) is not None


def test_shared_saiv_database_guard():
    assert is_shared_saiv_database("postgresql://saiv:saiv_password@localhost:5434/saiv") is True
    assert is_shared_saiv_database("postgresql://saiv:pw@localhost:5434/saiv_prod") is False
    assert is_shared_saiv_database("sqlite:///C:/tmp/retention.db") is False


def test_cli_refuses_shared_saiv_database():
    settings = type("S", (), {"DATABASE_URL": "postgresql://saiv:saiv_password@localhost:5434/saiv"})()
    with patch("app.retention.__main__.get_settings", return_value=settings):
        with patch("app.retention.__main__.SessionLocal") as session_local:
            assert retention_cli_main() == 2
            session_local.assert_not_called()


def test_fastapi_startup_does_not_create_retention_thread():
    import threading

    from fastapi.testclient import TestClient

    from app.main import app

    with patch("app.main.init_db"):
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            names = {thread.name for thread in threading.enumerate()}
    assert "saiv-retention-cleanup" not in names
    with pytest.raises(ModuleNotFoundError):
        __import__("app.retention.scheduler")
