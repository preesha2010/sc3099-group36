from typing import Any, Optional

import httpx

from app.core.config import get_settings

settings = get_settings()


class FaceClient:
    def __init__(self, base_url: Optional[str] = None, timeout: float = 5.0):
        self.base_url = (base_url or settings.FACE_SERVICE_URL).rstrip("/")
        self.timeout = timeout

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
            {"user_id": user_id, "image": image, "camera_consent": camera_consent},
        )

    def verify(self, image: str, reference_hash: str) -> Optional[dict[str, Any]]:
        return self._post(
            "/face/verify",
            {"image": image, "reference_template_hash": reference_hash},
        )

    def liveness(self, image: str, challenge_type: str = "passive") -> Optional[dict[str, Any]]:
        return self._post(
            "/liveness/check",
            {"challenge_response": image, "challenge_type": challenge_type},
        )

    def assess_risk(self, signals: dict[str, Any]) -> Optional[dict[str, Any]]:
        return self._post("/risk/assess", signals)


face_client = FaceClient()
