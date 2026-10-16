"""Validated process configuration. Changing model/key policy requires a restart."""

from dataclasses import dataclass
import math
import os


def integer(name, default, low, high):
    try:
        value = int(os.getenv(name, str(default)))
        if not low <= value <= high:
            raise ValueError
        return value
    except ValueError as exc:
        raise ValueError(f"{name} must be between {low} and {high}") from exc


@dataclass(frozen=True)
class Settings:
    template_mode: str
    liveness_backend: str
    workers: int
    concurrency: int
    pending: int
    queue_seconds: float

    @classmethod
    def load(cls):
        mode = os.getenv("FACE_TEMPLATE_MODE", "sha256")
        backend = os.getenv("LIVENESS_BACKEND", "heuristic")
        if mode not in {"sha256", "simhash"}:
            raise ValueError("Invalid FACE_TEMPLATE_MODE")
        if backend not in {"heuristic", "minifasnet"}:
            raise ValueError("Invalid LIVENESS_BACKEND")
        try:
            seconds = float(os.getenv("INFERENCE_QUEUE_SECONDS", "2"))
            if not math.isfinite(seconds) or not .01 <= seconds <= 30:
                raise ValueError
        except ValueError as exc:
            raise ValueError("INFERENCE_QUEUE_SECONDS must be between 0.01 and 30") from exc
        return cls(mode, backend, integer("FACE_MODEL_WORKERS", 4, 1, 8),
                   integer("INFERENCE_CONCURRENCY", 8, 1, 16),
                   integer("INFERENCE_PENDING", 32, 0, 128), seconds)
