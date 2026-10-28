from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import httpx

from app.core.config import get_settings

FaceKind = Literal["ok", "client_error", "unavailable", "malformed"]

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _strip_data_url(image: str) -> str:
    """API docs expect raw base64, but browsers often send a data URL prefix."""
    if image.startswith("data:") and "," in image:
        return image.split(",", 1)[1]
    return image


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _finite_unit_score(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or number > 1.0:
        return None
    return number


def _optional_hash_string(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    if value == "" or _HASH_RE.fullmatch(value):
        return value
    return None


@dataclass
class FaceCall:
    """Classified Module 3 HTTP outcome. Check-in status logic uses `ok` data only."""

    kind: FaceKind
    status: Optional[int] = None
    data: dict[str, Any] = field(default_factory=dict)
    detail: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.kind == "ok"


def _unavailable(status: Optional[int] = None) -> FaceCall:
    return FaceCall(kind="unavailable", status=status)


def _malformed(status: Optional[int] = None, detail: Optional[str] = None) -> FaceCall:
    return FaceCall(kind="malformed", status=status, detail=detail)


def _client_error(status: int, body: Any) -> FaceCall:
    detail = None
    data: dict[str, Any] = {}
    if isinstance(body, dict):
        data = body
        raw = body.get("detail")
        if isinstance(raw, str):
            detail = raw
    return FaceCall(kind="client_error", status=status, data=data, detail=detail)


def _parse_enroll_body(body: Any, status: int) -> FaceCall:
    if not isinstance(body, dict):
        return _malformed(status, "non-object enroll body")
    successful = body.get("enrollment_successful")
    if not _is_bool(successful):
        return _malformed(status, "enrollment_successful must be a boolean")
    if not successful:
        return FaceCall(kind="ok", status=status, data={"enrollment_successful": False})
    template = body.get("face_template_hash")
    quality = _finite_unit_score(body.get("quality_score"))
    if not isinstance(template, str) or not _HASH_RE.fullmatch(template) or quality is None:
        return _malformed(status, "successful enroll missing valid hash or quality_score")
    return FaceCall(
        kind="ok",
        status=status,
        data={
            "enrollment_successful": True,
            "face_template_hash": template,
            "quality_score": quality,
        },
    )


def _parse_verify_body(body: Any, status: int) -> FaceCall:
    if not isinstance(body, dict):
        return _malformed(status, "non-object verify body")
    passed = body.get("match_passed")
    detected = body.get("face_detected")
    score = _finite_unit_score(body.get("match_score"))
    template = _optional_hash_string(body.get("current_template_hash"))
    if not _is_bool(passed) or not _is_bool(detected) or score is None or template is None:
        return _malformed(status, "verify response missing typed fields")
    return FaceCall(
        kind="ok",
        status=status,
        data={
            "match_passed": passed,
            "match_score": score,
            "face_detected": detected,
            "current_template_hash": template,
        },
    )


def _parse_liveness_body(body: Any, status: int) -> FaceCall:
    if not isinstance(body, dict):
        return _malformed(status, "non-object liveness body")
    passed = body.get("liveness_passed")
    score = _finite_unit_score(body.get("liveness_score"))
    if not _is_bool(passed) or score is None:
        return _malformed(status, "liveness response missing typed fields")
    if "face_embedding_hash" not in body:
        return _malformed(status, "liveness response missing face_embedding_hash")
    parsed_hash = _optional_hash_string(body.get("face_embedding_hash"))
    if parsed_hash is None:
        return _malformed(status, "liveness face_embedding_hash is not a valid template")
    return FaceCall(
        kind="ok",
        status=status,
        data={
            "liveness_passed": passed,
            "liveness_score": score,
            "face_embedding_hash": parsed_hash,
        },
    )


_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def _parse_risk_body(body: Any, status: int) -> FaceCall:
    """Accept only typed advisory fields. pass_threshold is parsed, never applied."""
    if not isinstance(body, dict):
        return _malformed(status, "non-object risk body")
    score = _finite_unit_score(body.get("risk_score"))
    level = body.get("risk_level")
    passed = body.get("pass_threshold")
    breakdown = body.get("signal_breakdown")
    if score is None or not isinstance(level, str) or level not in _RISK_LEVELS:
        return _malformed(status, "risk response missing typed score or level")
    if not _is_bool(passed):
        return _malformed(status, "pass_threshold must be a boolean")
    if not isinstance(breakdown, dict):
        return _malformed(status, "signal_breakdown must be an object")
    parsed_breakdown: dict[str, float] = {}
    for key, value in breakdown.items():
        if not isinstance(key, str):
            return _malformed(status, "signal_breakdown keys must be strings")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return _malformed(status, "signal_breakdown values must be numbers")
        number = float(value)
        if not math.isfinite(number):
            return _malformed(status, "signal_breakdown values must be finite")
        parsed_breakdown[key] = number
    return FaceCall(
        kind="ok",
        status=status,
        data={
            "risk_score": score,
            "risk_level": level,
            "pass_threshold": passed,
            "signal_breakdown": parsed_breakdown,
        },
    )


class FaceClient:
    """HTTP client for Module 3. Timeouts and 5xx/network errors return unavailable
    so check-in can continue without face signals (INTEGRATION-GUIDE.md)."""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 5.0):
        settings = get_settings()
        self.base_url = (base_url or settings.FACE_SERVICE_URL).rstrip("/")
        self.timeout = timeout

    @staticmethod
    def is_success(result: Any) -> bool:
        if isinstance(result, FaceCall):
            return result.ok
        return False

    def _request(self, path: str, payload: dict[str, Any]) -> tuple[Optional[int], Any, bool]:
        """Return (status, parsed_json_or_None, json_ok). Network/5xx → (None, None, False)."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(f"{self.base_url}{path}", json=payload)
        except httpx.HTTPError:
            return None, None, False
        status = response.status_code
        if status >= 500:
            return status, None, False
        try:
            return status, response.json(), True
        except Exception:
            return status, None, False

    def _classify(self, path: str, payload: dict[str, Any], parser) -> FaceCall:
        status, body, json_ok = self._request(path, payload)
        # 408 is an upload/read deadline, not an invalid biometric decision.
        if status is None or status >= 500 or status == 408:
            return _unavailable(status)
        if status >= 400:
            return _client_error(status, body if json_ok else None)
        if status < 200 or not json_ok:
            return _malformed(status, "non-JSON or non-success HTTP")
        return parser(body, status)

    def enroll(self, user_id: str, image: str, camera_consent: bool) -> FaceCall:
        return self._classify(
            "/face/enroll",
            {
                "user_id": user_id,
                "image": _strip_data_url(image),
                "camera_consent": camera_consent,
            },
            _parse_enroll_body,
        )

    def verify(self, image: str, reference_hash: str) -> FaceCall:
        return self._classify(
            "/face/verify",
            {
                "image": _strip_data_url(image),
                "reference_template_hash": reference_hash,
            },
            _parse_verify_body,
        )

    def liveness(self, image: str, challenge_type: str = "passive") -> FaceCall:
        return self._classify(
            "/liveness/check",
            {
                "challenge_response": _strip_data_url(image),
                "challenge_type": challenge_type,
            },
            _parse_liveness_body,
        )

    def assess_risk(self, signals: dict[str, Any]) -> FaceCall:
        """POST /risk/assess. Advisory only; 408/5xx/timeout are unavailable."""
        return self._classify("/risk/assess", signals, _parse_risk_body)


face_client = FaceClient()
