"""Isolated M2/M3 E2E fixtures. Skips unless SAIV_E2E_ISOLATED=1 is set."""
from __future__ import annotations

import base64
import os
import sys
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

_DIR = Path(__file__).resolve().parent
_PACKAGE_DIR = _DIR.resolve()
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

from isolation import IsolationError  # noqa: E402
from seed import COURSE_CODE, seed  # noqa: E402
from settings import load_settings  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: isolated M2/M3 backend E2E")


def _is_m2_m3_item(item) -> bool:
    path = getattr(item, "path", None) or Path(str(item.fspath))
    try:
        Path(path).resolve().relative_to(_PACKAGE_DIR)
    except ValueError:
        return False
    return True


def pytest_collection_modifyitems(config, items):
    if os.environ.get("SAIV_E2E_ISOLATED", "").strip() == "1":
        return
    skip = pytest.mark.skip(
        reason=(
            "M2/M3 integration E2E is opt-in. Set SAIV_E2E_ISOLATED=1 and the "
            "E2E_* URLs documented in tests/integration/m2_m3/README.md."
        )
    )
    for item in items:
        if _is_m2_m3_item(item):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def e2e_settings():
    try:
        return load_settings()
    except IsolationError as exc:
        pytest.fail(str(exc))


@pytest.fixture(scope="session")
def e2e_ids(e2e_settings):
    try:
        ids = seed()
    except IsolationError as exc:
        pytest.fail(str(exc))
    _assert_m2_uses_isolated_db(e2e_settings, ids)
    return ids


@pytest.fixture(scope="session")
def m2(e2e_settings, e2e_ids):
    with httpx.Client(base_url=e2e_settings.m2_url, timeout=30.0) as client:
        health = client.get("/health")
        assert health.status_code == 200, health.text
        yield client


@pytest.fixture(scope="session")
def m3(e2e_settings):
    with httpx.Client(base_url=e2e_settings.face_url, timeout=30.0) as client:
        yield client


@pytest.fixture(scope="session")
def images(e2e_settings):
    sample_dir = e2e_settings.sample_dir
    obama = sample_dir / "obama.jpg"
    biden = sample_dir / "biden.jpg"
    if not obama.is_file() or not biden.is_file():
        pytest.fail(
            f"Need {obama} and {biden}. Set E2E_SAMPLE_DIR if samples live elsewhere."
        )
    gray_buf = BytesIO()
    Image.new("RGB", (256, 256), "gray").save(gray_buf, format="PNG")
    return {
        "obama": base64.b64encode(obama.read_bytes()).decode("ascii"),
        "biden": base64.b64encode(biden.read_bytes()).decode("ascii"),
        "gray": base64.b64encode(gray_buf.getvalue()).decode("ascii"),
    }


def _assert_m2_uses_isolated_db(settings, ids: dict[str, str]) -> None:
    """Abort if Module 2 is attached to a different database than E2E_DATABASE_URL."""
    try:
        response = httpx.post(
            f"{settings.m2_url}/api/v1/auth/login",
            json={"email": "e2e.admin@saiv.edu.sg", "password": settings.password},
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise IsolationError(
            f"Cannot reach isolated Module 2 at {settings.m2_url}: {exc}"
        ) from exc
    if response.status_code != 200:
        raise IsolationError(
            f"Isolated Module 2 login failed ({response.status_code}). "
            "Start M2 against E2E_DATABASE_URL, not the shared saiv database."
        )
    token = response.json()["access_token"]
    course = httpx.get(
        f"{settings.m2_url}/api/v1/courses/{ids['course_id']}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15.0,
    )
    if course.status_code != 200:
        raise IsolationError(
            f"GET /courses/{ids['course_id']} returned {course.status_code}. "
            "Module 2 is not using E2E_DATABASE_URL; refusing to create HTTP data."
        )
    body = course.json()
    if body.get("code") != COURSE_CODE or ids["nonce"] not in str(body.get("description", "")):
        raise IsolationError(
            "Module 2 returned a course that does not match the isolated seed nonce. "
            "Refusing to continue so the shared saiv database cannot be modified."
        )
