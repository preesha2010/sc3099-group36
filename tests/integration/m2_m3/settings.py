"""Load teammate-configured isolated E2E settings. No defaults to shared SAIV."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

from isolation import (
    DatabaseTarget,
    IsolationError,
    assert_isolated_database_name,
    assert_isolated_http_url,
    parse_database_url,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE_DIR = REPO_ROOT / "sample_images"


@dataclass(frozen=True)
class E2ESettings:
    database_url: str
    database: DatabaseTarget
    m2_url: str
    face_url: str
    password: str
    sample_dir: Path
    run_outage: bool
    run_retry: bool


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise IsolationError(
            f"{name} is required. This suite has no default that points at shared SAIV."
        )
    return value


def load_settings() -> E2ESettings:
    if os.environ.get("SAIV_E2E_ISOLATED", "").strip() != "1":
        raise IsolationError(
            "Set SAIV_E2E_ISOLATED=1 to confirm you are targeting an isolated "
            "Module 2 / Module 3 environment, not the shared saiv database."
        )

    database_url = _require_env("E2E_DATABASE_URL")
    target = parse_database_url(database_url)
    assert_isolated_database_name(target.database)

    m2_url = _require_env("E2E_M2_URL").rstrip("/")
    face_url = _require_env("E2E_FACE_URL").rstrip("/")
    assert_isolated_http_url("E2E_M2_URL", m2_url)
    assert_isolated_http_url("E2E_FACE_URL", face_url)

    sample_dir = Path(os.environ.get("E2E_SAMPLE_DIR", str(DEFAULT_SAMPLE_DIR))).resolve()
    password = os.environ.get("E2E_PASSWORD", "E2ePass123!").strip() or "E2ePass123!"
    return E2ESettings(
        database_url=database_url,
        database=target,
        m2_url=m2_url,
        face_url=face_url,
        password=password,
        sample_dir=sample_dir,
        run_outage=os.environ.get("E2E_RUN_OUTAGE", "").strip() == "1",
        run_retry=os.environ.get("E2E_RUN_RETRY", "").strip() == "1",
    )
