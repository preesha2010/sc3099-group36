"""Instructor GET /checkins/flagged is scoped to course_instructors in SQL."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

_BACKEND = Path(__file__).resolve().parents[2] / "module2-backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.db.enums import UserRole  # noqa: E402
from app.modules.checkins.service import flagged_checkins  # noqa: E402


def _page(items, total=None, limit=50, offset=0):
    return items, total if total is not None else len(items), limit, offset


def _row(**overrides):
    student = Mock(full_name="Ann", email="ann@saiv.edu.sg")
    row = Mock(
        id="chk-a",
        session_id="sess-a",
        session=Mock(name="Lecture"),
        student_id="stu-a",
        student=student,
        status="flagged",
        checked_in_at=datetime(2026, 1, 1, 12, 0, 0),
        risk_score=0.72,
        risk_factors='[{"type": "face_match_failed", "severity": "high", "weight": 0.25}]',
        appeal_reason=None,
        appealed_at=None,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _call(user, **kwargs):
    defaults = dict(course_id=None, session_id=None, limit=50)
    defaults.update(kwargs)
    return flagged_checkins(Mock(), user, **defaults)


def test_unassigned_instructor_returns_empty_without_querying_flagged():
    user = Mock(id="instr-none", role=UserRole.INSTRUCTOR.value)
    with (
        patch("app.modules.checkins.service.enrollments_repo") as enrollments_repo,
        patch("app.modules.checkins.service.checkins_repo") as checkins_repo,
    ):
        enrollments_repo.list_assigned_course_ids.return_value = []
        result = _call(user, limit=10)
    checkins_repo.list_flagged.assert_not_called()
    assert result["items"] == []
    assert result["total"] == 0
    assert result["limit"] == 10
    assert result["offset"] == 0


def test_instructor_flagged_passes_assigned_course_ids_to_repository():
    user = Mock(id="instr-a", role=UserRole.INSTRUCTOR.value)
    with (
        patch("app.modules.checkins.service.enrollments_repo") as enrollments_repo,
        patch("app.modules.checkins.service.checkins_repo") as checkins_repo,
    ):
        enrollments_repo.list_assigned_course_ids.return_value = ["course-a", "course-b"]
        checkins_repo.list_flagged.return_value = _page([_row()], 1, 10, 0)
        result = _call(user, limit=10)
        kwargs = checkins_repo.list_flagged.call_args.kwargs
    assert kwargs["course_ids"] == ["course-a", "course-b"]
    assert kwargs["course_id"] is None
    assert [item["id"] for item in result["items"]] == ["chk-a"]
    assert "student_email" not in result["items"][0]
    assert result["items"][0]["student_name"] == "Ann"


def test_instructor_flagged_filter_on_unassigned_course_is_empty():
    user = Mock(id="instr-a", role=UserRole.INSTRUCTOR.value)
    with (
        patch("app.modules.checkins.service.enrollments_repo") as enrollments_repo,
        patch("app.modules.checkins.service.checkins_repo") as checkins_repo,
    ):
        enrollments_repo.list_assigned_course_ids.return_value = ["course-a"]
        result = _call(user, course_id="course-other")
    checkins_repo.list_flagged.assert_not_called()
    assert result["items"] == []
    assert result["total"] == 0


def test_instructor_flagged_session_outside_assignment_is_empty():
    user = Mock(id="instr-a", role=UserRole.INSTRUCTOR.value)
    with (
        patch("app.modules.checkins.service.enrollments_repo") as enrollments_repo,
        patch("app.modules.checkins.service.checkins_repo") as checkins_repo,
        patch("app.modules.checkins.service.sessions_repo") as sessions_repo,
    ):
        enrollments_repo.list_assigned_course_ids.return_value = ["course-a"]
        sessions_repo.get_by_id.return_value = Mock(id="sess-x", course_id="course-x")
        result = _call(user, session_id="sess-x")
    checkins_repo.list_flagged.assert_not_called()
    assert result["items"] == []


def test_admin_flagged_does_not_pass_course_ids_scope():
    user = Mock(id="admin-1", role=UserRole.ADMIN.value)
    with (
        patch("app.modules.checkins.service.enrollments_repo") as enrollments_repo,
        patch("app.modules.checkins.service.checkins_repo") as checkins_repo,
    ):
        checkins_repo.list_flagged.return_value = _page([], 0, 5, 0)
        _call(user, limit=5)
        kwargs = checkins_repo.list_flagged.call_args.kwargs
    enrollments_repo.list_assigned_course_ids.assert_not_called()
    assert kwargs["course_ids"] is None
    assert kwargs["limit"] == 5


def test_ta_flagged_scope_is_unchanged():
    user = Mock(id="ta-1", role=UserRole.TA.value)
    with (
        patch("app.modules.checkins.service.enrollments_repo") as enrollments_repo,
        patch("app.modules.checkins.service.checkins_repo") as checkins_repo,
    ):
        enrollments_repo.list_assigned_course_ids.return_value = ["course-a"]
        checkins_repo.list_flagged.return_value = _page([], 0, 50, 0)
        _call(user)
        kwargs = checkins_repo.list_flagged.call_args.kwargs
    assert kwargs["course_ids"] == ["course-a"]
