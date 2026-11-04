"""GET /stats/sessions/{id} risk_distribution, checkin_timeline, average_checkin_time_minutes."""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

_BACKEND = Path(__file__).resolve().parents[2] / "module2-backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.modules.stats.service import (  # noqa: E402
    arrival_offset_minutes,
    risk_band,
    session_stats,
    timeline_bucket_minute,
)

NTU_LAT, NTU_LNG = 1.3483, 103.6831
START = datetime(2024, 1, 15, 14, 0, 0)


def _checkin(
    *,
    risk_score=0.1,
    checked_in_at=None,
    status="approved",
    distance=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        risk_score=risk_score,
        distance_from_venue_meters=distance,
        checked_in_at=checked_in_at,
    )


def _call_session_stats(rows, *, scheduled_start=START, enrolled=0):
    session = SimpleNamespace(
        id="session-1",
        name="Lecture 5",
        course_id="course-1",
        course=SimpleNamespace(code="CS6101"),
        scheduled_start=scheduled_start,
        status="active",
    )
    db = Mock()
    db.query.return_value.filter.return_value.all.return_value = list(rows)
    user = SimpleNamespace(id="instructor-1", role="instructor")
    with (
        patch("app.modules.stats.service.sessions_repo.get_by_id", return_value=session),
        patch("app.modules.stats.service.can_staff_course_session", return_value=True),
        patch(
            "app.modules.stats.service.enrollments_repo.list_for_course",
            return_value=[object()] * enrolled,
        ),
    ):
        return session_stats(db, session.id, user)


def test_risk_band_matches_session_stats_spec():
    assert risk_band(None) == "low"
    assert risk_band(0.0) == "low"
    assert risk_band(0.2999) == "low"
    assert risk_band(0.3) == "medium"
    assert risk_band(0.4999) == "medium"
    assert risk_band(0.5) == "high"
    assert risk_band(0.7) == "high"
    assert risk_band(1.0) == "high"


def test_timeline_buckets_early_on_time_and_late():
    assert timeline_bucket_minute(-12.0) == -15
    assert timeline_bucket_minute(-0.1) == -5
    assert timeline_bucket_minute(0.0) == 0
    assert timeline_bucket_minute(4.9) == 0
    assert timeline_bucket_minute(5.0) == 5
    assert timeline_bucket_minute(14.9) == 10
    assert timeline_bucket_minute(15.0) == 15


def test_arrival_offset_skips_missing_timestamps():
    assert arrival_offset_minutes(None, START) is None
    assert arrival_offset_minutes(START, None) is None
    assert arrival_offset_minutes(None, None) is None
    later = START + timedelta(minutes=3, seconds=12)
    assert arrival_offset_minutes(later, START) == pytest.approx(3.2)
    early = START - timedelta(minutes=8)
    assert arrival_offset_minutes(early, START) == pytest.approx(-8.0)


def test_aware_timestamps_convert_before_offset():
    start = datetime(2024, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
    arrival = datetime(2024, 1, 15, 14, 10, 0, tzinfo=timezone.utc)
    assert arrival_offset_minutes(arrival, start) == pytest.approx(10.0)


def test_session_stats_empty_session_zeros_new_fields():
    data = _call_session_stats([])
    assert data["checked_in"] == 0
    assert data["checked_in_count"] == 0
    assert data["risk_distribution"] == {"low": 0, "medium": 0, "high": 0}
    assert data["checkin_timeline"] == []
    assert data["average_checkin_time_minutes"] == 0.0
    assert data["average_risk_score"] == 0.0
    assert data["average_distance_meters"] == 0.0
    assert data["by_status"] == {
        "approved": 0,
        "flagged": 0,
        "rejected": 0,
        "pending": 0,
    }


def test_session_stats_mixed_scores_missing_arrival_and_early_offset():
    data = _call_session_stats(
        [
            _checkin(risk_score=0.1, checked_in_at=START + timedelta(minutes=1)),
            _checkin(risk_score=0.4, checked_in_at=START + timedelta(minutes=6)),
            _checkin(risk_score=0.8, checked_in_at=START - timedelta(minutes=4)),
            _checkin(risk_score=None, checked_in_at=None),
        ]
    )
    assert data["checked_in"] == 4
    assert data["risk_distribution"] == {"low": 2, "medium": 1, "high": 1}
    assert data["checkin_timeline"] == [
        {"minute": -5, "count": 1},
        {"minute": 0, "count": 1},
        {"minute": 5, "count": 1},
    ]
    assert data["average_checkin_time_minutes"] == pytest.approx((1 + 6 + -4) / 3)


def test_session_stats_groups_same_five_minute_bucket():
    data = _call_session_stats(
        [
            _checkin(checked_in_at=START + timedelta(minutes=1)),
            _checkin(checked_in_at=START + timedelta(minutes=4)),
            _checkin(checked_in_at=START + timedelta(minutes=5)),
        ]
    )
    assert data["checkin_timeline"] == [
        {"minute": 0, "count": 2},
        {"minute": 5, "count": 1},
    ]
    assert data["average_checkin_time_minutes"] == pytest.approx((1 + 4 + 5) / 3)


def test_session_stats_negative_timeline_for_early_arrivals():
    data = _call_session_stats(
        [
            _checkin(checked_in_at=START - timedelta(minutes=12)),
            _checkin(checked_in_at=START - timedelta(seconds=6)),
        ]
    )
    assert data["checkin_timeline"] == [
        {"minute": -15, "count": 1},
        {"minute": -5, "count": 1},
    ]
    assert data["average_checkin_time_minutes"] < 0
    assert all(item["minute"] < 0 for item in data["checkin_timeline"])


def test_session_stats_missing_scheduled_start_omits_timeline_and_average():
    """sessions.scheduled_start is NOT NULL; this covers the defensive None branch."""
    data = _call_session_stats(
        [
            _checkin(risk_score=0.4, checked_in_at=START + timedelta(minutes=3)),
            _checkin(risk_score=0.1, checked_in_at=START + timedelta(minutes=8)),
        ],
        scheduled_start=None,
    )
    assert data["scheduled_start"] is None
    assert data["checkin_timeline"] == []
    assert data["average_checkin_time_minutes"] == 0.0
    assert data["risk_distribution"] == {"low": 1, "medium": 1, "high": 0}
    assert data["checked_in"] == 2


@pytest.mark.points(0, category="session_stats_fields")
def test_empty_session_stats_include_spec_fields(
    client, test_session, auth_headers_instructor
):
    response = client.get(
        f"/api/v1/stats/sessions/{test_session['id']}",
        headers=auth_headers_instructor,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["session_id"] == test_session["id"]
    assert data["checked_in"] == 0
    assert data["checked_in_count"] == 0
    assert data["approved_count"] == 0
    assert data["flagged_count"] == 0
    assert data["attendance_rate"] == 0.0
    assert data["average_risk_score"] == 0.0
    assert data["average_distance_meters"] == 0.0
    assert data["average_checkin_time_minutes"] == 0.0
    assert data["risk_distribution"] == {"low": 0, "medium": 0, "high": 0}
    assert data["checkin_timeline"] == []
    assert data["by_status"] == {
        "approved": 0,
        "flagged": 0,
        "rejected": 0,
        "pending": 0,
    }


@pytest.mark.points(0, category="session_stats_fields")
def test_session_stats_fields_after_checkin(
    client,
    test_course,
    test_enrollment,
    test_session,
    auth_headers_instructor,
    auth_headers_student,
    auth_headers_admin,
):
    now = datetime.now(timezone.utc)
    created = client.post(
        "/api/v1/sessions/",
        headers=auth_headers_instructor,
        json={
            "course_id": test_course["id"],
            "name": f"Stats fields {uuid.uuid4().hex[:6]}",
            "session_type": "lecture",
            "scheduled_start": (now + timedelta(minutes=5)).isoformat(),
            "scheduled_end": (now + timedelta(hours=2)).isoformat(),
            "checkin_opens_at": (now - timedelta(minutes=10)).isoformat(),
            "checkin_closes_at": (now + timedelta(minutes=30)).isoformat(),
            "venue_latitude": NTU_LAT,
            "venue_longitude": NTU_LNG,
            "geofence_radius_meters": 100.0,
        },
    )
    assert created.status_code in (200, 201), created.text
    session = created.json()
    activate = client.patch(
        f"/api/v1/admin/sessions/{session['id']}/status",
        headers=auth_headers_admin,
        json={"status": "active"},
    )
    assert activate.status_code == 200, activate.text

    checkin = client.post(
        "/api/v1/checkins/",
        headers=auth_headers_student,
        json={
            "session_id": session["id"],
            "latitude": NTU_LAT,
            "longitude": NTU_LNG,
            "device_fingerprint": f"fp_{uuid.uuid4().hex[:10]}",
        },
    )
    assert checkin.status_code == 201, checkin.text

    stats = client.get(
        f"/api/v1/stats/sessions/{session['id']}",
        headers=auth_headers_instructor,
    )
    assert stats.status_code == 200, stats.text
    data = stats.json()
    dist = data["risk_distribution"]
    assert set(dist) == {"low", "medium", "high"}
    assert dist["low"] + dist["medium"] + dist["high"] == 1
    assert data["checked_in"] == 1
    assert data["checked_in_count"] == 1
    assert isinstance(data["checkin_timeline"], list)
    assert len(data["checkin_timeline"]) == 1
    bucket = data["checkin_timeline"][0]
    assert bucket["count"] == 1
    assert isinstance(bucket["minute"], int)
    assert bucket["minute"] % 5 == 0
    scheduled = datetime.fromisoformat(session["scheduled_start"].replace("Z", "+00:00"))
    checked = datetime.fromisoformat(checkin.json()["checked_in_at"].replace("Z", "+00:00"))
    expected = (checked - scheduled).total_seconds() / 60.0
    assert data["average_checkin_time_minutes"] == pytest.approx(expected, abs=0.05)
    if expected < 0:
        assert bucket["minute"] < 0
    assert data["session_id"] == session["id"]
    assert "approved_count" in data
    assert "attendance_rate" in data
