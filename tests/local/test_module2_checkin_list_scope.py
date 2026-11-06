"""Instructor GET /checkins/ is scoped to course_instructors in SQL."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

_BACKEND = Path(__file__).resolve().parents[2] / "module2-backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.db.enums import UserRole  # noqa: E402
from app.modules.checkins.service import list_checkins  # noqa: E402


def _page(items, total=None, limit=50, offset=0):
    return items, total if total is not None else len(items), limit, offset


def _call(user, **kwargs):
    defaults = dict(
        session_id=None,
        course_id=None,
        student_id=None,
        status=None,
        min_risk_score=None,
        max_risk_score=None,
        start_date=None,
        end_date=None,
        limit=50,
        offset=0,
    )
    defaults.update(kwargs)
    db = Mock()
    return list_checkins(db, user, **defaults), db


def test_unassigned_instructor_returns_empty_without_querying_checkins():
    user = Mock(id="instr-none", role=UserRole.INSTRUCTOR.value)
    with (
        patch("app.modules.checkins.service.enrollments_repo") as enrollments_repo,
        patch("app.modules.checkins.service.checkins_repo") as checkins_repo,
    ):
        enrollments_repo.list_assigned_course_ids.return_value = []
        result, _db = _call(user, limit=10, offset=0)
    checkins_repo.list_checkins.assert_not_called()
    assert result["items"] == []
    assert result["total"] == 0
    assert result["limit"] == 10
    assert result["offset"] == 0


def test_instructor_list_passes_assigned_course_ids_to_repository():
    user = Mock(id="instr-a", role=UserRole.INSTRUCTOR.value)
    row = Mock(
        id="chk-a",
        session_id="sess-a",
        session=Mock(name="Lecture"),
        student_id="stu-a",
        student=Mock(full_name="Ann", email="ann@saiv.edu.sg"),
        status="approved",
        checked_in_at=datetime(2026, 1, 1),
        distance_from_venue_meters=1.0,
        risk_score=0.1,
        liveness_passed=True,
    )
    with (
        patch("app.modules.checkins.service.enrollments_repo") as enrollments_repo,
        patch("app.modules.checkins.service.checkins_repo") as checkins_repo,
    ):
        enrollments_repo.list_assigned_course_ids.return_value = ["course-a", "course-b"]
        checkins_repo.list_checkins.return_value = _page([row], 1, 10, 0)
        result, _db = _call(user, limit=10, offset=0)
        kwargs = checkins_repo.list_checkins.call_args.kwargs
    assert kwargs["course_ids"] == ["course-a", "course-b"]
    assert kwargs["course_id"] is None
    assert [item["id"] for item in result["items"]] == ["chk-a"]
    assert result["items"][0]["student_email"] == "ann@saiv.edu.sg"


def test_instructor_filter_on_unassigned_course_is_empty_without_query():
    user = Mock(id="instr-a", role=UserRole.INSTRUCTOR.value)
    with (
        patch("app.modules.checkins.service.enrollments_repo") as enrollments_repo,
        patch("app.modules.checkins.service.checkins_repo") as checkins_repo,
    ):
        enrollments_repo.list_assigned_course_ids.return_value = ["course-a"]
        result, _db = _call(user, course_id="course-other")
    checkins_repo.list_checkins.assert_not_called()
    assert result["items"] == []
    assert result["total"] == 0


def test_instructor_session_filter_outside_assignment_is_empty():
    user = Mock(id="instr-a", role=UserRole.INSTRUCTOR.value)
    foreign_session = Mock(id="sess-x", course_id="course-x")
    with (
        patch("app.modules.checkins.service.enrollments_repo") as enrollments_repo,
        patch("app.modules.checkins.service.checkins_repo") as checkins_repo,
        patch("app.modules.checkins.service.sessions_repo") as sessions_repo,
    ):
        enrollments_repo.list_assigned_course_ids.return_value = ["course-a"]
        sessions_repo.get_by_id.return_value = foreign_session
        result, _db = _call(user, session_id="sess-x")
    checkins_repo.list_checkins.assert_not_called()
    assert result["items"] == []


def test_admin_list_does_not_pass_course_ids_scope():
    user = Mock(id="admin-1", role=UserRole.ADMIN.value)
    with (
        patch("app.modules.checkins.service.enrollments_repo") as enrollments_repo,
        patch("app.modules.checkins.service.checkins_repo") as checkins_repo,
    ):
        checkins_repo.list_checkins.return_value = _page([], 0, 5, 0)
        _call(user, status="approved", limit=5)
        kwargs = checkins_repo.list_checkins.call_args.kwargs
    enrollments_repo.list_assigned_course_ids.assert_not_called()
    assert kwargs["course_ids"] is None
    assert kwargs["status"] == "approved"
    assert kwargs["limit"] == 5
