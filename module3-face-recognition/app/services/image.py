"""In-memory image decoding and quality checks."""

import base64
import binascii
import re
from io import BytesIO
from typing import Any, Dict, Tuple

import numpy as np
from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_IMAGE_PIXELS = 12_000_000
MAX_IMAGE_SIDE = 4096
MAX_BASE64_CHARACTERS = 4 * ((MAX_IMAGE_BYTES + 2) // 3)


def decode_base64_image(base64_string: str) -> np.ndarray:
    """Decode a PNG/JPEG base64 payload without ever writing it to disk."""
    if not isinstance(base64_string, str) or not base64_string.strip():
        raise HTTPException(status_code=400, detail="Image must be a non-empty base64 string")

    encoded = re.sub(r"^data:image/[^;]+;base64,", "", base64_string.strip(), flags=re.IGNORECASE)
    if len(encoded) > MAX_BASE64_CHARACTERS:
        raise HTTPException(status_code=413, detail="Encoded image is too large")
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Image is too large")
        with Image.open(BytesIO(image_bytes)) as image:
            if image.format not in {"PNG", "JPEG"}:
                raise HTTPException(status_code=400, detail="Only PNG and JPEG images are supported")
            if getattr(image, "n_frames", 1) != 1:
                raise HTTPException(status_code=400, detail="Only single-frame images are supported")
            if max(image.size) > MAX_IMAGE_SIDE or image.width * image.height > MAX_IMAGE_PIXELS:
                raise HTTPException(status_code=413, detail="Image dimensions are too large")
            if image.width < 32 or image.height < 32:
                raise HTTPException(status_code=400, detail="Image resolution is too small")
            # Normalize camera orientation before detection; the returned array owns
            # its data and remains valid when the Pillow image and buffer are closed.
            return np.array(ImageOps.exif_transpose(image).convert("RGB"), copy=True)
    except Image.DecompressionBombError as exc:
        raise HTTPException(status_code=413, detail="Image dimensions are too large") from exc
    except (binascii.Error, ValueError, UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail="Invalid or corrupt image") from exc


def calculate_quality_score(image_array: np.ndarray, detection: Dict[str, Any]) -> Tuple[float, str]:
    """Score detection confidence, image resolution, and relative face size."""
    height, width = image_array.shape[:2]
    x1, y1, x2, y2 = detection["bbox"]
    face_ratio = ((x2 - x1) * (y2 - y1)) / float(width * height)
    resolution_score = min(1.0, (width * height) / float(640 * 480))
    face_size_score = min(1.0, face_ratio / 0.15)
    quality_score = round(
        0.50 * float(detection["confidence"]) + 0.25 * resolution_score + 0.25 * face_size_score,
        3,
    )
    image_quality = "good" if quality_score >= 0.75 else "acceptable" if quality_score >= 0.5 else "poor"
    return quality_score, image_quality
