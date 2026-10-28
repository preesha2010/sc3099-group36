"""Documented multi-signal attendance-risk calculation."""

import base64
import binascii
import ipaddress
import re
from decimal import Decimal
from typing import Dict, List, Tuple

from fastapi import HTTPException
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from app.schemas import RiskAssessRequest
from app.risk_policy import WEIGHTS, LEVEL_BOUNDARIES


def detect_vpn_proxy(ip_address: str, user_agent: str) -> Tuple[bool, float]:
    """Flag documented private/loopback IPs and common VPN/proxy client labels."""
    reasons = []
    if not ip_address and not user_agent:
        return False, 0.5
    try:
        if ip_address:
            address = ipaddress.ip_address(ip_address)
            if address.is_private or address.is_loopback:
                reasons.append("private_or_loopback_ip")
    except ValueError:
        reasons.append("invalid_ip")
    if user_agent and re.search(r"\b(?:vpn|proxy|tor)\b", user_agent, flags=re.IGNORECASE):
        reasons.append("vpn_or_proxy_user_agent")
    return bool(reasons), min(1.0, 0.5 * len(reasons))


def device_risk(signature: str | None, public_key: str | None) -> float:
    """Reject malformed evidence; well-formed evidence is still unverified.

    The documented risk request has no signed message or server challenge.
    Merely receiving a signature and PEM key cannot establish device trust.
    """
    if signature is None and public_key is None:
        return 0.5
    if not signature or not public_key:
        return 1.0
    try:
        load_pem_public_key(public_key.encode("ascii"))
        if not base64.b64decode(signature, validate=True):
            return 1.0
    except (ValueError, TypeError, UnicodeError, binascii.Error, UnsupportedAlgorithm):
        return 1.0
    return 0.5


def assess_risk(request: RiskAssessRequest) -> Tuple[float, str, Dict[str, float], List[str]]:
    """Return a bounded score, documented risk level, signal breakdown, and advice."""
    recommendations: List[str] = []

    def inverted_score(score: float | None, name: str, recommendation: str) -> float:
        if score is None:
            return 0.5
        if not 0.0 <= score <= 1.0:
            raise HTTPException(status_code=400, detail=f"{name} must be between 0 and 1")
        risk = float(Decimal("1") - Decimal(str(score)))
        if risk >= 0.5:
            recommendations.append(recommendation)
        return risk

    liveness_risk = inverted_score(request.liveness_score, "liveness_score", "Improve lighting and face visibility")
    face_risk = inverted_score(request.face_match_score, "face_match_score", "Re-enroll face or improve image quality")
    device_score = device_risk(request.device_signature, request.device_public_key)
    recommendations.append("Device trust is unverified; verify a signed server challenge")
    is_vpn, network_risk = detect_vpn_proxy(request.ip_address or "", request.user_agent or "")
    if is_vpn:
        recommendations.append("Review network signals; private IP or client labels do not prove VPN use")

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

    raw_signals = {"liveness": liveness_risk, "face_match": face_risk, "device": device_score, "network": network_risk, "geolocation": geolocation_risk}
    # API specification defines these values as weighted contributions, so they
    # must add up to risk_score rather than exposing unweighted probabilities.
    signals = {name: float(Decimal(str(risk)) * Decimal(str(WEIGHTS[name])))
               for name, risk in raw_signals.items()}
    risk_score = float(sum(Decimal(str(value)) for value in signals.values()))
    risk_level = ("LOW" if risk_score < LEVEL_BOUNDARIES["MEDIUM"] else "MEDIUM"
                  if risk_score < LEVEL_BOUNDARIES["HIGH"] else "HIGH"
                  if risk_score < LEVEL_BOUNDARIES["CRITICAL"] else "CRITICAL")
    return risk_score, risk_level, signals, recommendations
