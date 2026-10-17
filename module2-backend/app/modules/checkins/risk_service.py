"""GPS / device / liveness risk scoring. Called only from checkins.service."""

from typing import Any, Optional

from app.db.enums import CheckinStatus, SignalSeverity, SignalType


def assess(
    *,
    distance_m: Optional[float],
    geofence_m: float,
    liveness_passed: Optional[bool],
    face_match_passed: Optional[bool],
    unknown_device: bool,
    threshold: float,
) -> dict[str, Any]:
    """Return {risk_score, status, factors} using SECURITY-REQUIREMENTS.md."""
    factors: list[dict[str, Any]] = []
    liveness_risk = 0.0
    face_risk = 0.0
    device_risk = 0.15 if unknown_device else 0.0
    network_risk = 0.0
    geo_risk = 0.0
    critical_reject = False

    radius = geofence_m if geofence_m and geofence_m > 0 else 100.0
    if distance_m is not None:
        if distance_m > 2 * radius:
            geo_risk = 1.0
            critical_reject = True
            factors.append(
                {
                    "type": SignalType.GEO_OUT_OF_BOUNDS.value,
                    "severity": SignalSeverity.CRITICAL.value,
                    "weight": 0.15,
                }
            )
        elif distance_m > radius:
            geo_risk = 0.7
            factors.append(
                {
                    "type": SignalType.GEO_OUT_OF_BOUNDS.value,
                    "severity": SignalSeverity.HIGH.value,
                    "weight": 0.15,
                }
            )
        else:
            geo_risk = min(distance_m / radius, 1.0) * 0.2

    if liveness_passed is False:
        liveness_risk = 1.0
        critical_reject = True
        factors.append(
            {
                "type": SignalType.LIVENESS_FAILED.value,
                "severity": SignalSeverity.CRITICAL.value,
                "weight": 0.25,
            }
        )
    elif liveness_passed is True:
        liveness_risk = 0.0

    if face_match_passed is False:
        face_risk = 1.0
        factors.append(
            {
                "type": SignalType.FACE_MATCH_FAILED.value,
                "severity": SignalSeverity.HIGH.value,
                "weight": 0.25,
            }
        )

    if unknown_device:
        factors.append(
            {
                "type": SignalType.DEVICE_UNKNOWN.value,
                "severity": SignalSeverity.MEDIUM.value,
                "weight": 0.15,
            }
        )

    risk_score = (
        0.25 * liveness_risk
        + 0.25 * face_risk
        + 0.20 * device_risk
        + 0.15 * network_risk
        + 0.15 * geo_risk
    )
    risk_score = round(min(max(risk_score, 0.0), 1.0), 4)

    if critical_reject:
        status = CheckinStatus.REJECTED.value
    elif risk_score >= threshold:
        status = CheckinStatus.FLAGGED.value
    else:
        status = CheckinStatus.APPROVED.value

    return {"risk_score": risk_score, "status": status, "factors": factors}
