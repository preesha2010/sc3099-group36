"""HTTP E2E for isolated Module 2 talking to a real Module 3.

These tests create data only after isolation guards pass. They never start,
stop, or delete Docker services or volumes.
"""
from __future__ import annotations

import math

import httpx
import pytest

from http_api import auth_headers, checkin, checkins_for, enroll, user_row

SUCCESS_EMAIL = "e2e.success@saiv.edu.sg"
MISMATCH_EMAIL = "e2e.mismatch@saiv.edu.sg"
LIVENESS_EMAIL = "e2e.liveness@saiv.edu.sg"
OUTAGE_EMAIL = "e2e.outage@saiv.edu.sg"
INSTRUCTOR_EMAIL = "e2e.instructor@saiv.edu.sg"
OUTSIDER_EMAIL = "e2e.outsider@saiv.edu.sg"
ADMIN_EMAIL = "e2e.admin@saiv.edu.sg"


@pytest.mark.integration
def test_face_enrollment_through_m2(m2, m3, e2e_settings, e2e_ids, images):
    ready = m3.get("/ready")
    if ready.status_code != 200:
        pytest.fail(
            f"Isolated Module 3 /ready returned {ready.status_code}. "
            "Workspace module3-face-recognition is a stub; use a working M3 "
            "with FACE_TEMPLATE_MODE=sha256 (or equivalent) and /ready."
        )
    response = enroll(m2, e2e_settings, SUCCESS_EMAIL, images["obama"])
    row = user_row(e2e_settings, SUCCESS_EMAIL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("face_enrolled") is True
    assert row["face_enrolled"] is True
    assert row["face_embedding_hash"]


@pytest.mark.integration
def test_successful_verify_liveness_risk_and_persistence(
    m2, e2e_settings, e2e_ids, images
):
    before = checkins_for(e2e_settings, e2e_ids["success_id"])
    response = checkin(
        m2, e2e_settings, SUCCESS_EMAIL, e2e_ids["session_id"], images["obama"]
    )
    after = checkins_for(e2e_settings, e2e_ids["success_id"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["liveness_passed"] is True
    assert body["face_match_passed"] is True
    assert len(after) == len(before) + 1
    stored = after[-1]
    assert stored["status"] == "approved"
    assert stored["liveness_passed"] is True
    assert stored["face_match_passed"] is True
    assert stored["risk_score"] is not None


@pytest.mark.integration
def test_failed_face_match_is_flagged(m2, e2e_settings, e2e_ids, images):
    enrolled = enroll(m2, e2e_settings, MISMATCH_EMAIL, images["obama"])
    assert enrolled.status_code == 200, enrolled.text
    response = checkin(
        m2, e2e_settings, MISMATCH_EMAIL, e2e_ids["session_id"], images["biden"]
    )
    after = checkins_for(e2e_settings, e2e_ids["mismatch_id"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "flagged"
    assert body["face_match_passed"] is False
    assert after
    assert after[-1]["status"] == "flagged"
    assert after[-1]["face_match_passed"] is False


@pytest.mark.integration
def test_failed_liveness_is_rejected(m2, e2e_settings, e2e_ids, images):
    enrolled = enroll(m2, e2e_settings, LIVENESS_EMAIL, images["obama"])
    assert enrolled.status_code == 200, enrolled.text
    response = checkin(
        m2, e2e_settings, LIVENESS_EMAIL, e2e_ids["session_id"], images["gray"]
    )
    after = checkins_for(e2e_settings, e2e_ids["liveness_id"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "rejected"
    assert body["liveness_passed"] is False
    assert after
    assert after[-1]["status"] == "rejected"
    assert after[-1]["liveness_passed"] is False


@pytest.mark.integration
def test_direct_m3_risk_assess(m3):
    response = m3.post(
        "/risk/assess",
        json={"liveness_score": 0.91, "face_match_score": 0.88},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    score = body.get("risk_score")
    assert isinstance(score, (int, float)) and not isinstance(score, bool)
    assert math.isfinite(float(score))
    assert 0.0 <= float(score) <= 1.0


@pytest.mark.integration
def test_prepare_outage_student_enrollment(m2, e2e_settings, images):
    """Enroll the outage user while Module 3 is up so a later 503 run can skip enroll."""
    response = enroll(m2, e2e_settings, OUTAGE_EMAIL, images["obama"])
    row = user_row(e2e_settings, OUTAGE_EMAIL)
    assert response.status_code == 200, response.text
    assert row["face_enrolled"] is True


@pytest.mark.integration
def test_duplicate_checkin_rejected(m2, e2e_settings, e2e_ids, images):
    before = checkins_for(e2e_settings, e2e_ids["success_id"])
    if not before:
        first = checkin(
            m2, e2e_settings, SUCCESS_EMAIL, e2e_ids["session_id"], images["obama"]
        )
        assert first.status_code == 201, first.text
        before = checkins_for(e2e_settings, e2e_ids["success_id"])
    response = checkin(
        m2, e2e_settings, SUCCESS_EMAIL, e2e_ids["session_id"], images["obama"]
    )
    after = checkins_for(e2e_settings, e2e_ids["success_id"])
    assert response.status_code == 400, response.text
    assert len(after) == len(before)


@pytest.mark.integration
def test_instructor_course_assignment_and_roster(m2, e2e_settings, e2e_ids):
    course_id = e2e_ids["course_id"]
    assigned = m2.get(
        f"/api/v1/enrollments/course/{course_id}",
        headers=auth_headers(m2, e2e_settings, INSTRUCTOR_EMAIL),
    )
    unassigned = m2.get(
        f"/api/v1/enrollments/course/{course_id}",
        headers=auth_headers(m2, e2e_settings, OUTSIDER_EMAIL),
    )
    admin_links = m2.get(
        f"/api/v1/admin/courses/{course_id}/instructors",
        headers=auth_headers(m2, e2e_settings, ADMIN_EMAIL),
    )
    assert assigned.status_code == 200, assigned.text
    body = assigned.json()
    assert body["course_id"] == course_id
    assert body.get("total_enrolled", 0) >= 4
    assert unassigned.status_code == 403, unassigned.text
    assert admin_links.status_code == 200, admin_links.text
    instructors = admin_links.json().get("instructors", admin_links.json())
    if isinstance(instructors, dict):
        instructors = instructors.get("items", [instructors])
    assert any(
        row.get("instructor_id") == e2e_ids["instructor_id"]
        and row.get("is_active") is True
        for row in instructors
    )


@pytest.mark.integration
def test_required_m3_outage_returns_503_without_row(
    m2, m3, e2e_settings, e2e_ids, images
):
    if not e2e_settings.run_outage:
        pytest.skip(
            "Optional. Stop only your isolated Module 3, then rerun with E2E_RUN_OUTAGE=1. "
            "Do not stop saiv-face-recognition."
        )
    try:
        m3.get("/health")
        pytest.skip("Isolated Module 3 is still reachable; outage test did not stop it.")
    except httpx.HTTPError:
        pass
    if not user_row(e2e_settings, OUTAGE_EMAIL)["face_enrolled"]:
        pytest.fail(
            "Outage student is not enrolled. Enroll e2e.outage@saiv.edu.sg while "
            "isolated Module 3 is up, then stop only that M3 process and rerun."
        )
    before = checkins_for(e2e_settings, e2e_ids["outage_id"])
    response = checkin(
        m2, e2e_settings, OUTAGE_EMAIL, e2e_ids["session_id"], images["obama"]
    )
    after = checkins_for(e2e_settings, e2e_ids["outage_id"])
    assert response.status_code == 503, response.text
    assert len(after) == len(before)


@pytest.mark.integration
def test_m3_recovery_retry_creates_checkin(m2, m3, e2e_settings, e2e_ids, images):
    if not e2e_settings.run_retry:
        pytest.skip(
            "Optional. After isolated Module 3 is healthy again, rerun with E2E_RUN_RETRY=1."
        )
    ready = m3.get("/ready")
    if ready.status_code != 200:
        pytest.fail(f"Isolated Module 3 /ready returned {ready.status_code}")
    before = checkins_for(e2e_settings, e2e_ids["outage_id"])
    response = checkin(
        m2, e2e_settings, OUTAGE_EMAIL, e2e_ids["session_id"], images["obama"]
    )
    after = checkins_for(e2e_settings, e2e_ids["outage_id"])
    assert response.status_code == 201, response.text
    assert response.json()["status"] in {"approved", "flagged", "rejected"}
    assert len(after) == len(before) + 1
