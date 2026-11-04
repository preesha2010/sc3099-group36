import uuid
from datetime import datetime, timezone
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base

settings = get_settings()

_engine_kwargs = {"pool_pre_ping": True}
if settings.DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 20

engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _install_audit_immutability(connection) -> None:
    connection.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION prevent_audit_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit_logs are immutable';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    connection.execute(text("DROP TRIGGER IF EXISTS audit_logs_no_update ON audit_logs"))
    connection.execute(text("DROP TRIGGER IF EXISTS audit_logs_no_delete ON audit_logs"))
    connection.execute(
        text(
            """
            CREATE TRIGGER audit_logs_no_update
            BEFORE UPDATE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TRIGGER audit_logs_no_delete
            BEFORE DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();
            """
        )
    )


def _backfill_course_instructors(connection) -> None:
    """Idempotent: copy distinct session owners into course_instructors."""
    rows = connection.execute(
        text(
            """
            SELECT DISTINCT s.course_id, s.instructor_id
            FROM sessions s
            WHERE s.instructor_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM course_instructors ci
                WHERE ci.course_id = s.course_id AND ci.instructor_id = s.instructor_id
              )
            """
        )
    ).fetchall()
    assigned_at = datetime.now(timezone.utc).replace(tzinfo=None)
    for course_id, instructor_id in rows:
        connection.execute(
            text(
                """
                INSERT INTO course_instructors
                    (id, course_id, instructor_id, is_active, assigned_at)
                VALUES
                    (:id, :course_id, :instructor_id, TRUE, :assigned_at)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "course_id": course_id,
                "instructor_id": instructor_id,
                "assigned_at": assigned_at,
            },
        )


def init_db() -> None:
    from app.db import models as _models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        dialect = connection.dialect.name
        if dialect == "postgresql":
            _install_audit_immutability(connection)
        _backfill_course_instructors(connection)
