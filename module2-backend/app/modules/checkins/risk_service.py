"""GPS / device / liveness risk scoring. Called only from checkins.service."""

from typing import Any, Optional


def assess(
    *,
    distance_m: Optional[float],
    geofence_m: float,
    liveness_passed: Optional[bool],
    face_match_passed: Optional[bool],
    unknown_device: bool,
    threshold: float,
) -> dict[str, Any]:
    """Return {risk_score, status, factors, signals} using SECURITY-REQUIREMENTS.md."""
    # TODO: Weighted risk + status (API spec / SECURITY-REQUIREMENTS: threshold, liveness,
    # face match, 2x geofence). Used by submit_checkin; keep public NTU check-in non-rejected.
    from app.core.exceptions import not_implemented

    not_implemented("checkins.risk_service.assess")
