from contextlib import contextmanager

import numpy as np
import pytest

from app.services import neural, antispoof


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
    embedding = neural.neural_embedding(np.full((128, 128, 3), 77, dtype=np.uint8), {"alignment": None})
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
