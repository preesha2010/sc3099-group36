"""Refuse the shared SAIV database and other unsafe targets."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote, urlparse

FORBIDDEN_DATABASES = frozenset({"saiv", "postgres", "template0", "template1"})
FORBIDDEN_COMPOSE_PROJECTS = frozenset({"sc3099-group36", "student-starter-0908"})
SHARED_CONTAINER_HINTS = frozenset(
    {"saiv-backend", "saiv-postgres", "saiv-face-recognition", "saiv-redis"}
)


class IsolationError(RuntimeError):
    """The configured target is the shared SAIV stack or is incomplete."""


@dataclass(frozen=True)
class DatabaseTarget:
    url: str
    host: str | None
    port: int | None
    database: str


def parse_database_url(url: str) -> DatabaseTarget:
    parsed = urlparse(url)
    if parsed.scheme not in {"postgresql", "postgres", "postgresql+psycopg2"}:
        raise IsolationError(f"E2E_DATABASE_URL must be PostgreSQL, not {parsed.scheme!r}")
    database = unquote(parsed.path.lstrip("/").split("/")[0]).strip()
    if not database:
        raise IsolationError("E2E_DATABASE_URL is missing a database name")
    return DatabaseTarget(
        url=url,
        host=parsed.hostname,
        port=parsed.port,
        database=database,
    )


def assert_isolated_database_name(database: str) -> None:
    if database.lower() in FORBIDDEN_DATABASES:
        raise IsolationError(
            f"Refusing database {database!r}. This suite must not use the shared "
            "'saiv' database or Postgres maintenance databases. Create a dedicated "
            "isolated database (for example saiv_m2_m3_e2e) and set E2E_DATABASE_URL."
        )


def assert_isolated_http_url(name: str, url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise IsolationError(f"{name} must be an absolute http(s) URL")
