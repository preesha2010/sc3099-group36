"""Documented multi-signal attendance-risk calculation."""

import ipaddress
from typing import Dict, List, Tuple

from fastapi import HTTPException

from app.schemas import RiskAssessRequest


WEIGHTS = {"liveness": 0.25, "face_match": 0.25, "device": 0.20, "network": 0.15, "geolocation": 0.15}


def detect_vpn_proxy(ip_address: str, user_agent: str) -> Tuple[bool, float]:
    """Flag documented private/loopback IPs and common VPN/proxy client labels."""
    reasons = []
    try:
        if ip_address and (ipaddress.ip_address(ip_address).is_private or ipaddress.ip_address(ip_address).is_loopback):
            reasons.append("private_or_loopback_ip")
    except ValueError:
        reasons.append("invalid_ip")
    if user_agent and any(keyword in user_agent.lower() for keyword in ("vpn", "proxy", "tor")):
        reasons.append("vpn_or_proxy_user_agent")
    return bool(reasons), min(1.0, 0.5 * len(reasons))


def assess_risk(request: RiskAssessRequest) -> Tuple[float, str, Dict[str, float], List[str]]:
    """Return a bounded score, documented risk level, signal breakdown, and advice."""
    recommendations: List[str] = []

    def inverted_score(score: float | None, name: str, recommendation: str) -> float:
        if score is None:
            return 0.5
        if not 0.0 <= score <= 1.0:
            raise HTTPException(status_code=400, detail=f"{name} must be between 0 and 1")
        risk = round(1.0 - score, 3)
        if risk >= 0.5:
            recommendations.append(recommendation)
        return risk

    liveness_risk = inverted_score(request.liveness_score, "liveness_score", "Improve lighting and face visibility")
    face_risk = inverted_score(request.face_match_score, "face_match_score", "Re-enroll face or improve image quality")
    device_risk = 0.0 if request.device_signature and request.device_public_key else 0.5
    if device_risk:
        recommendations.append("Use a registered and trusted device")
    is_vpn, network_risk = detect_vpn_proxy(request.ip_address or "", request.user_agent or "")
    if is_vpn:
        recommendations.append("Disable VPN or proxy for check-in")

    geolocation_risk = 0.5
    if request.geolocation is not None:
        geo = request.geolocation
        if not -90 <= geo.latitude <= 90 or not -180 <= geo.longitude <= 180 or geo.accuracy < 0:
            raise HTTPException(status_code=400, detail="Invalid geolocation values")
        if geo.accuracy > 5000:
            geolocation_risk = 1.0
            recommendations.append("Enable precise location services")
        elif geo.accuracy > 100:
            geolocation_risk = 0.5
            recommendations.append("Improve location accuracy")
        else:
            geolocation_risk = 0.0

    signals = {"liveness": liveness_risk, "face_match": face_risk, "device": device_risk, "network": network_risk, "geolocation": geolocation_risk}
    risk_score = round(sum(signals[name] * WEIGHTS[name] for name in WEIGHTS), 3)
    risk_level = "LOW" if risk_score < 0.3 else "MEDIUM" if risk_score < 0.5 else "HIGH" if risk_score < 0.7 else "CRITICAL"
    return risk_score, risk_level, signals, recommendations
