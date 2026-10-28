"""Public numerical contract identity, without models, secrets or student data."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path


_MANIFEST = json.loads((Path(__file__).parent / "contracts" / "risk-v1.json").read_text(encoding="utf-8"))
RISK_POLICY_ID = _MANIFEST["policy_id"]
RISK_POLICY_SHA256 = hashlib.sha256(json.dumps(
    _MANIFEST, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
WEIGHTS = _MANIFEST["weights"].copy()
DEFAULT_THRESHOLD = _MANIFEST["default_threshold"]
LEVEL_BOUNDARIES = _MANIFEST["risk_level_boundaries"].copy()


def policy_document():
    # Do not let an in-process caller mutate the live definition accidentally.
    return {"policy_id": RISK_POLICY_ID, "policy_sha256": RISK_POLICY_SHA256,
            "manifest": deepcopy(_MANIFEST)}


def assess_payload(payload):
    """Pure JSON-callable reference for fallback conformance, NOT authorization.

    Same schema, numerical implementation and response model as the HTTP API.
    ValidationError (a ValueError) means invalid input; never substitute zero.
    """
    from app.schemas import RiskAssessRequest, RiskAssessResponse
    from app.services.risk import assess_risk
    request = RiskAssessRequest.model_validate(payload)
    score, level, breakdown, advice = assess_risk(request)
    return RiskAssessResponse(risk_score=score, risk_level=level, signal_breakdown=breakdown,
                              recommendations=advice, risk_threshold=DEFAULT_THRESHOLD,
                              pass_threshold=score < DEFAULT_THRESHOLD).model_dump()
