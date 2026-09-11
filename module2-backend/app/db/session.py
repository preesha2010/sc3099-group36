from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base

settings = get_settings()

engine = create_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

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


def init_db() -> None:
    from app.db import models as _models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        dialect = connection.dialect.name
        if dialect == "postgresql":
            _install_audit_immutability(connection)
