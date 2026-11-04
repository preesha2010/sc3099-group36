from contextlib import contextmanager

import numpy as np
import pytest

from app.services import neural, antispoof
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from fastapi import HTTPException


@pytest.mark.parametrize("features", [np.zeros(128), np.ones(127), np.full(128, np.nan),
                                    np.full(128, np.inf), np.full(128, np.finfo(np.float32).max, np.float32)])
def test_invalid_identity_output_evicts_model_and_clears_buffers(monkeypatch, features):
    monkeypatch.setenv("FACE_MODEL_WORKERS", "1")

    class Recognizer:
        last_input = None

        def alignCrop(self, *_):
            return np.full((112, 112, 3), 77, dtype=np.uint8)

        def feature(self, image):
            self.last_input = image.copy()
            return features.copy() if image.any() else np.ones(128, np.float32)

    recognizer = Recognizer()
    instance = neural.ModelPool(lambda: recognizer)
    monkeypatch.setattr(neural, "pool", lambda _: instance)
    with np.errstate(over="ignore", invalid="ignore"), pytest.raises(HTTPException) as error:
        neural.neural_embedding(np.full((128, 128, 3), 77, np.uint8), {
            "alignment": np.array([20, 20, 60, 60, 35, 40, 65, 40, 50, 55, 35, 70, 65, 70, .99], np.float32)})
    assert error.value.status_code == 503
    assert instance.degraded_slots == 1 and instance.available.qsize() == 1
    assert not recognizer.last_input.any()
    assert instance.available.get_nowait() is None


def test_failed_model_is_discarded_instead_of_cached(monkeypatch):
    monkeypatch.setenv("FACE_MODEL_WORKERS", "1")
    objects = []

    def factory():
        model = object()
        objects.append(model)
        return model

    pool = neural.ModelPool(factory)
    with pytest.raises(RuntimeError):
        with pool.borrow() as model:
            assert model is objects[0]
            raise RuntimeError("simulated failure")
    with pool.borrow() as model:
        assert model is objects[1]


def test_slow_repair_does_not_hold_healthy_model_slots(monkeypatch):
    monkeypatch.setenv("FACE_MODEL_WORKERS", "2")
    rebuilding, release = Event(), Event()
    attempts = 0

    def factory():
        nonlocal attempts
        attempts += 1
        if attempts > 2:
            rebuilding.set()
            assert release.wait(4)
        return object()

    instance = neural.ModelPool(factory)
    with pytest.raises(RuntimeError):
        with instance.borrow():
            raise RuntimeError("inference failed")
    with ThreadPoolExecutor(1) as executor:
        repair = executor.submit(instance.repair)
        try:
            assert rebuilding.wait(2)
            with instance.borrow():
                pass
        finally:
            release.set()
        repair.result(3)
    assert instance.healthy and instance.available.qsize() == 2


def test_identity_model_buffers_are_overwritten_after_inference(monkeypatch):
    class Recognizer:
        last_input = None

        def alignCrop(self, image, _):
            return np.full((112, 112, 3), 77, dtype=np.uint8)

        def feature(self, image):
            self.last_input = image.copy()
            return np.ones((1, 128), dtype=np.float32)

    recognizer = Recognizer()

    class Pool:
        @contextmanager
        def borrow(self):
            yield recognizer

    monkeypatch.setattr(neural, "pool", lambda _: Pool())
    embedding = neural.neural_embedding(np.full((128, 128, 3), 77, dtype=np.uint8), {
        "alignment": np.array([20, 20, 60, 60, 35, 40, 65, 40, 50, 55, 35, 70, 65, 70, .99], dtype=np.float32)})
    assert np.linalg.norm(embedding) == pytest.approx(1)
    assert not recognizer.last_input.any()


def test_pad_models_clear_input_even_on_inference_failure(monkeypatch):
    class Detector:
        last_input = None

        def setInput(self, blob, *_):
            self.last_input = blob.copy()

        def forward(self, *_):
            return np.array([[[[0, 0, .99, .25, .25, .75, .75]]]], dtype=np.float32)

    class Net:
        last_input = None

        def setInput(self, blob):
            self.last_input = blob.copy()

        def forward(self):
            if self.last_input.any():
                raise RuntimeError("simulated neural failure")
            return np.zeros((1, 3), dtype=np.float32)

    detector, nets = Detector(), [Net(), Net()]

    class Pool:
        @contextmanager
        def borrow(self):
            yield detector, nets

    monkeypatch.setattr(antispoof, "pool", lambda _: Pool())
    with pytest.raises(RuntimeError):
        antispoof.assess_presentation(np.full((256, 256, 3), 77, dtype=np.uint8))
    assert all(net.last_input is not None and not net.last_input.any() for net in nets)
    # RetinaFace's blank-input preprocessing subtracts the fixed BGR means.
    assert np.allclose(detector.last_input[:, 0], -104)
    assert np.allclose(detector.last_input[:, 1], -117)
    assert np.allclose(detector.last_input[:, 2], -123)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -.1, 1.1])
def test_invalid_pad_probability_can_never_fall_back_to_heuristic_pass(monkeypatch, invalid):
    from app.services import liveness
    monkeypatch.setenv("LIVENESS_BACKEND", "minifasnet")
    monkeypatch.setattr(liveness, "calculate_quality_score", lambda *_: (1., "good"))
    monkeypatch.setattr(liveness, "analyze_face_mesh", lambda *_: {
        "depth_quality": "good", "face_mesh_complete": True, "landmark_count": 468, "nose_tip_z": -.06})
    monkeypatch.setattr(liveness, "analyze_texture", lambda *_: {
        "sharpness": 100, "texture_analysis_score": 1., "color_distribution_score": 1.})
    monkeypatch.setattr(liveness, "extract_face_embedding", lambda *_: np.ones(128))
    monkeypatch.setattr(liveness, "generate_face_hash", lambda *_: "a" * 64)
    monkeypatch.setattr(antispoof, "assess_presentation", lambda *_: (invalid, {}))
    with pytest.raises(HTTPException) as error:
        liveness.assess_passive_liveness(np.zeros((256, 256, 3), np.uint8), {"confidence": 1, "bbox": (0, 0, 256, 256)})
    assert error.value.status_code == 503


@pytest.mark.parametrize("logits", [np.array([float("nan"), 1, 0]), np.array([float("inf"), 0, 1]), np.ones(4)])
def test_invalid_raw_pad_logits_are_rejected_and_buffers_cleared(monkeypatch, logits):
    class Detector:
        def setInput(self, *_):
            pass

        def forward(self, *_):
            return np.array([0, 0, .99, .25, .25, .75, .75], np.float32)

    class Net:
        def setInput(self, data):
            self.last = data.copy()

        def forward(self):
            return logits.copy()

    nets = [Net(), Net()]

    class Pool:
        @contextmanager
        def borrow(self):
            yield Detector(), nets

    monkeypatch.setattr(antispoof, "pool", lambda _: Pool())
    with pytest.raises(HTTPException) as error:
        antispoof.assess_presentation(np.ones((256, 256, 3), np.uint8))
    assert error.value.status_code == 503
    assert all(not item.last.any() for item in nets)
