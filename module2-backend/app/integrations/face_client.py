from typing import Any, Optional

import httpx

from app.core.config import get_settings


def _strip_data_url(image: str) -> str:
    """API docs expect raw base64, but browsers often send a data URL prefix."""
    if image.startswith("data:") and "," in image:
        return image.split(",", 1)[1]
    return image


class FaceClient:
    """HTTP client for Module 3. Timeouts and 5xx/network errors return None so
    check-in can continue without face signals (INTEGRATION-GUIDE.md)."""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 5.0):
        settings = get_settings()
        self.base_url = (base_url or settings.FACE_SERVICE_URL).rstrip("/")
        self.timeout = timeout

    @staticmethod
    def is_success(result: Optional[dict[str, Any]]) -> bool:
        return result is not None and int(result.get("_status") or 200) < 400

    def _post(self, path: str, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(f"{self.base_url}{path}", json=payload)
                if response.status_code >= 500:
                    return None
                try:
                    return {"_status": response.status_code, **response.json()}
                except Exception:
                    return {"_status": response.status_code}
        except httpx.HTTPError:
            return None

    def enroll(self, user_id: str, image: str, camera_consent: bool) -> Optional[dict[str, Any]]:
        return self._post(
            "/face/enroll",
            {
                "user_id": user_id,
                "image": _strip_data_url(image),
                "camera_consent": camera_consent,
            },
        )

    def verify(self, image: str, reference_hash: str) -> Optional[dict[str, Any]]:
        return self._post(
            "/face/verify",
            {
                "image": _strip_data_url(image),
                "reference_template_hash": reference_hash,
            },
        )

    def liveness(self, image: str, challenge_type: str = "passive") -> Optional[dict[str, Any]]:
        return self._post(
            "/liveness/check",
            {
                "challenge_response": _strip_data_url(image),
                "challenge_type": challenge_type,
            },
        )

    def assess_risk(self, signals: dict[str, Any]) -> Optional[dict[str, Any]]:
        return self._post("/risk/assess", signals)


face_client = FaceClient()
