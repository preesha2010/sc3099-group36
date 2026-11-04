"""Validated process configuration. Changing model/key policy requires a restart."""

from dataclasses import dataclass
import math
import os
from urllib.parse import urlsplit


def integer(name, default, low, high):
    try:
        value = int(os.getenv(name, str(default)))
        if not low <= value <= high:
            raise ValueError
        return value
    except ValueError as exc:
        raise ValueError(f"{name} must be between {low} and {high}") from exc


def seconds(name, default):
    try:
        value = float(os.getenv(name, str(default)))
        if not math.isfinite(value) or not .01 <= value <= 30:
            raise ValueError
        return value
    except ValueError as exc:
        raise ValueError(f"{name} must be between 0.01 and 30") from exc


def telemetry_endpoint():
    value = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment or parsed.port == 0
                or any(character.isspace() for character in value)):
            raise ValueError
    except ValueError as exc:
        raise ValueError("OTEL_EXPORTER_OTLP_ENDPOINT must be an HTTP(S) base URL without credentials, query or fragment") from exc
    return value.rstrip("/")


@dataclass(frozen=True)
class Settings:
    template_mode: str
    liveness_backend: str
    workers: int
    concurrency: int
    pending: int
    queue_seconds: float
    native_threads: int = 1
    body_seconds: float = 3.
    otel_endpoint: str = ""

    @classmethod
    def load(cls):
        mode = os.getenv("FACE_TEMPLATE_MODE", "sha256")
        backend = os.getenv("LIVENESS_BACKEND", "heuristic")
        if mode not in {"sha256", "simhash"}:
            raise ValueError("Invalid FACE_TEMPLATE_MODE")
        if backend not in {"heuristic", "minifasnet"}:
            raise ValueError("Invalid LIVENESS_BACKEND")
        return cls(mode, backend, integer("FACE_MODEL_WORKERS", 4, 1, 8),
                   integer("INFERENCE_CONCURRENCY", 8, 1, 16),
                   integer("INFERENCE_PENDING", 32, 0, 128), seconds("INFERENCE_QUEUE_SECONDS", 2),
                   integer("FACE_NATIVE_THREADS", 1, 1, 4), seconds("REQUEST_BODY_SECONDS", 3),
                   telemetry_endpoint())
