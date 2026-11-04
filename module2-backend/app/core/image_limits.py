from typing import Optional

from app.core.config import get_settings
from app.core.exceptions import payload_too_large


def face_image_max_chars() -> int:
    """Base64 length that encodes FACE_IMAGE_MAX_BYTES, including padding."""
    max_bytes = get_settings().FACE_IMAGE_MAX_BYTES
    return ((max_bytes + 2) // 3) * 4


def _base64_payload(image: str) -> str:
    if image.startswith("data:") and "," in image:
        return image.split(",", 1)[1]
    return image


def ensure_face_image_within_limit(image: Optional[str]) -> None:
    """Reject oversized enroll/check-in images before Module 3 or persistence."""
    if not image:
        return
    if len(_base64_payload(image)) > face_image_max_chars():
        raise payload_too_large("Image payload too large")
