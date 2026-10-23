"""Versioned, authenticated 64-bit SimHash templates in 64 hexadecimal characters.

The 128-D SFace vector exists only during inference. Templates carry an 8-byte
SimHash plus version/key ID and a 16-byte HMAC, not a raw floating-point vector.
"""

import hashlib
import hmac
import math
import os
from functools import lru_cache

import numpy as np
from fastapi import HTTPException
from app.observability import timed

from app.model_assets import ASSETS, model_directory

PREFIX = b"SF\x01\x00"
SCORE_POLICY = "gaussian_query_margin_agreement_v3"


def score_distance(distance: int, bits: int = 64) -> float:
    """Unshipped bit-only cosine diagnostic, NOT the live query-margin policy."""
    if type(distance) is not int or type(bits) is not int or bits <= 0 or not 0 <= distance <= bits:
        raise ValueError("Invalid SimHash distance")
    return round(max(0., math.cos(math.pi * distance / bits)), 6)


@timed("similarity")
def match_query_to_template(embedding: np.ndarray, reference: str) -> float:
    """Compare transient query margins to authenticated reference sign bits.

    For unit u/v and a standard Gaussian plane a,
      E[sign(a.v) * (a.u)] = sqrt(2/pi) * dot(u,v).
    Thus sqrt(pi/2)*mean(reference_sign*query_margin) estimates cosine without
    quantizing the query a second time. Map [-1,1] to agreement [0,1] explicitly.
    No learned fit, template re-encoding, reference vector or new key is needed.
    Finite 64-plane estimation still needs independent accuracy validation.
    """
    key = template_key()
    code = decode_simhash(reference, key)
    vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
    norm = np.linalg.norm(vector)
    if vector.shape != (128,) or not np.isfinite(vector).all() or not np.isfinite(norm) or norm < 1e-8:
        raise HTTPException(status_code=503, detail="Invalid local identity features for similarity")
    signs = np.unpackbits(np.frombuffer(code, dtype=np.uint8)).astype(np.float64) * 2. - 1.
    margins = np.einsum("ij,j->i", projection(key), vector / norm, optimize=False)
    estimated_cosine = math.sqrt(math.pi / 2.) * float(np.mean(signs * margins))
    if not math.isfinite(estimated_cosine):
        raise HTTPException(status_code=503, detail="Invalid local similarity model output")
    return round(float(np.clip((1. + estimated_cosine) / 2., 0., 1.)), 6)


def template_mode() -> str:
    mode = os.getenv("FACE_TEMPLATE_MODE", "sha256")
    if mode not in {"sha256", "simhash"}:
        raise HTTPException(status_code=503, detail="Invalid face template configuration")
    return mode


@lru_cache(maxsize=2)
def _key_for_directory(directory: str) -> bytes:
    try:
        from pathlib import Path
        key = (Path(directory) / "template.key").read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Private template key is missing; run model bootstrap") from exc
    if len(key) != 32:
        raise HTTPException(status_code=503, detail="Invalid private template key")
    return key


def template_key() -> bytes:
    # Configuration is immutable during a server run; key rotation requires a
    # restart and fresh enrollments. This caches a key, never a biometric vector.
    return _key_for_directory(str(model_directory()))


@lru_cache(maxsize=2)
def projection(key: bytes) -> np.ndarray:
    seed = int.from_bytes(hmac.digest(key, b"sface-simhash-v1-projection", "sha256")[:8], "big")
    planes = np.random.default_rng(seed).standard_normal((64, 128)).astype(np.float32)
    planes.setflags(write=False)
    return planes


def key_id(key: bytes) -> bytes:
    model_version = ASSETS["sface.onnx"][1].encode("ascii")
    return hmac.digest(key, b"sface-simhash-v1-key-id" + model_version, "sha256")[:4]


def encode_simhash(embedding: np.ndarray) -> str:
    vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
    if vector.shape != (128,) or not np.isfinite(vector).all() or np.linalg.norm(vector) < 1e-8:
        raise HTTPException(status_code=400, detail="Invalid face features")
    key = template_key()
    # This tiny projection must not spin up a large BLAS thread team for every
    # concurrent request; direct einsum keeps the work within the model slot.
    code = np.packbits(np.einsum("ij,j->i", projection(key), vector, optimize=False) >= 0).tobytes()
    payload = PREFIX + key_id(key) + code
    return (payload + hmac.digest(key, payload, "sha256")[:16]).hex()


def decode_simhash(value: str, key: bytes) -> bytes:
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid face template") from exc
    if (len(raw) != 32 or raw[:4] != PREFIX or raw[4:8] != key_id(key)
            or not hmac.compare_digest(raw[16:], hmac.digest(key, raw[:16], "sha256")[:16])):
        raise HTTPException(status_code=400, detail="Template version/key mismatch or invalid authentication; re-enrollment is required")
    return raw[8:16]


def match_templates(current: str, reference: str) -> float:
    """Legacy exact-image compatibility only; never downgrade SimHash matching."""
    if template_mode() != "sha256":
        raise HTTPException(status_code=503, detail="Similarity requires transient query features; hash-only fallback is disabled")
    return 1.0 if hmac.compare_digest(current, reference) else 0.0


def diagnostic_hash_cosine(current: str, reference: str) -> float:
    """Authenticated hash-only diagnostic retained for reproducible comparisons."""
    key = template_key()
    left, right = decode_simhash(current, key), decode_simhash(reference, key)
    distance = (int.from_bytes(left, "big") ^ int.from_bytes(right, "big")).bit_count()
    return score_distance(distance)


def validate_reference(reference: str) -> None:
    """Reject unauthenticated enhanced references before expensive image work."""
    if template_mode() == "simhash":
        decode_simhash(reference, template_key())
