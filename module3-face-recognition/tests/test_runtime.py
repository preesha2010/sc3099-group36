import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
from threading import Event
import time

from fastapi import HTTPException
from fastapi.testclient import TestClient
import numpy as np
import pytest

from app.config import Settings
from app.main import app
from app.middleware import ServiceMiddleware
from app.observability import Metrics, rss_bytes
from app.runtime import Runtime, require_native_paths
from app.services.neural import ModelPool


@pytest.mark.parametrize("name,value", [
    ("FACE_TEMPLATE_MODE", "wrong"), ("LIVENESS_BACKEND", "wrong"),
    ("FACE_MODEL_WORKERS", "0"), ("FACE_MODEL_WORKERS", "9"),
    ("INFERENCE_CONCURRENCY", "17"), ("INFERENCE_CONCURRENCY", "NaN"),
    ("INFERENCE_PENDING", "-1"), ("INFERENCE_PENDING", "129"),
    ("INFERENCE_QUEUE_SECONDS", "inf"), ("INFERENCE_QUEUE_SECONDS", "nan"),
    ("INFERENCE_QUEUE_SECONDS", "0"),
    ("FACE_NATIVE_THREADS", "0"), ("FACE_NATIVE_THREADS", "5"),
    ("REQUEST_BODY_SECONDS", "0"), ("REQUEST_BODY_SECONDS", "nan"),
    ("REQUEST_BODY_SECONDS", "inf"), ("REQUEST_BODY_SECONDS", "31"),
    ("OTEL_EXPORTER_OTLP_ENDPOINT", "file:///private"),
    ("OTEL_EXPORTER_OTLP_ENDPOINT", "http://user:secret@localhost:4318"),
    ("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318/?token=secret"),
])
def test_invalid_configuration_fails_at_startup(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        with TestClient(app):
            pass


def test_windows_native_path_failures_are_explained_before_serving():
    require_native_paths("nt", "C:/runtime/mediapipe", "C:/models")
    require_native_paths("posix", "/runtime/模型", "/data/模型")
    with pytest.raises(ValueError, match="ASCII-only"):
        require_native_paths("nt", "C:/用户/runtime")
    with pytest.raises(ValueError, match="FACE_MODEL_DIR"):
        require_native_paths("nt", "C:/runtime", "C:/模型")


@pytest.mark.parametrize("failure", ["missing", "corrupt_model", "short_key"])
def test_enhanced_missing_assets_fail_before_serving(monkeypatch, tmp_path, failure):
    monkeypatch.setenv("FACE_TEMPLATE_MODE", "simhash")
    monkeypatch.setenv("FACE_MODEL_DIR", str(tmp_path))
    if failure == "corrupt_model":
        (tmp_path / "template.key").write_bytes(b"k" * 32)
        (tmp_path / "yunet.onnx").write_bytes(b"invalid-model")
    if failure == "short_key":
        (tmp_path / "template.key").write_bytes(b"too-short")
    with pytest.raises(HTTPException) as error:
        with TestClient(app):
            pass
    assert error.value.status_code == 503


def test_readiness_tracks_immutable_assets_and_key(tmp_path, monkeypatch):
    monkeypatch.setenv("FACE_MODEL_DIR", str(tmp_path))
    instance = Runtime(Settings.load())
    path = tmp_path / "asset"
    path.write_bytes(b"model")
    instance.assets["asset"] = (path.stat().st_size, path.stat().st_mtime_ns)
    key = tmp_path / "template.key"
    key.write_bytes(b"a" * 32)
    instance.key_digest = hashlib.sha256(key.read_bytes()).digest()
    assert instance.ready()
    key.write_bytes(b"b" * 32)
    assert not instance.ready()
    key.write_bytes(b"a" * 32)
    assert instance.ready()
    path.unlink()
    assert not instance.ready()


def test_pool_reconstruction_failure_preserves_capacity_and_original_error(monkeypatch):
    monkeypatch.setenv("FACE_MODEL_WORKERS", "1")
    attempts = 0

    def factory():
        nonlocal attempts
        attempts += 1
        if attempts in {2, 3}:
            raise RuntimeError("rebuild failed")
        return object()

    instance = ModelPool(factory)
    with pytest.raises(RuntimeError, match="original inference"):
        with instance.borrow():
            raise RuntimeError("original inference")
    assert not instance.healthy
    for _ in range(2):
        with pytest.raises(HTTPException) as error:
            with instance.borrow():
                pass
        assert error.value.status_code == 503
        assert instance.available.qsize() == 1
    with instance.borrow():
        pass
    assert instance.healthy and instance.available.qsize() == 1


def test_failed_pool_can_recover_without_an_inference_request(monkeypatch):
    monkeypatch.setenv("FACE_MODEL_WORKERS", "1")
    instance = ModelPool(object)
    with pytest.raises(RuntimeError):
        with instance.borrow():
            raise RuntimeError("failure")
    assert not instance.healthy
    instance.repair()
    assert instance.healthy
    with instance.borrow():
        pass


def test_readiness_recovers_in_background_while_health_stays_healthy(monkeypatch):
    monkeypatch.setenv("FACE_MODEL_WORKERS", "1")
    with TestClient(app) as client:
        instance = ModelPool(object)
        app.state.runtime.pools.append(instance)
        app.state.runtime.pool_names["sface"] = instance
        with pytest.raises(RuntimeError):
            with instance.borrow():
                raise RuntimeError("simulated failure")
        assert client.get("/ready").status_code == 503
        assert client.get("/health").status_code == 200
        assert 'module3_model_degraded_slots{model="sface"} 1' in client.get("/metrics").text
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and client.get("/ready").status_code != 200:
            time.sleep(.05)
        assert client.get("/ready").status_code == 200
        assert instance.healthy


@pytest.mark.parametrize("pending,queue_seconds", [(0, "2"), (1, "0.05")])
def test_overload_is_bounded_and_health_stays_responsive(monkeypatch, pending, queue_seconds):
    import app.main as api
    monkeypatch.setenv("INFERENCE_CONCURRENCY", "1")
    monkeypatch.setenv("INFERENCE_PENDING", str(pending))
    monkeypatch.setenv("INFERENCE_QUEUE_SECONDS", queue_seconds)
    started, release = Event(), Event()

    def slow_detection(_):
        started.set()
        assert release.wait(5)
        return None

    monkeypatch.setattr(api, "decode_base64_image", lambda _: np.zeros((32, 32, 3), np.uint8))
    monkeypatch.setattr(api, "detect_face", slow_detection)
    payload = {"image": "secret", "reference_template_hash": "0" * 64}
    with TestClient(app) as client, ThreadPoolExecutor(2) as executor:
        request = executor.submit(client.post, "/face/verify", json=payload)
        try:
            assert started.wait(3)
            rejected = client.post("/face/verify", json=payload)
            assert rejected.status_code == 503
            assert rejected.headers["retry-after"] == "1"
            assert client.get("/health").status_code == 200
            assert client.get("/ready").status_code == 200
        finally:
            release.set()
        assert request.result(3).status_code == 200
        assert app.state.admitted == 0
        assert client.post("/face/verify", json=payload).status_code == 200


@pytest.mark.asyncio
async def test_cancellation_releases_admission_without_reading_queued_body():
    from types import SimpleNamespace
    settings = Settings("sha256", "heuristic", 1, 1, 1, 2)
    state = SimpleNamespace(settings=settings, inference_slots=asyncio.Semaphore(0), admitted=0)
    async def unexpected(*_):
        raise AssertionError("Queued request must not read its body or run downstream")
    scope = {"type": "http", "method": "POST", "path": "/face/verify", "app": SimpleNamespace(state=state)}
    task = asyncio.create_task(ServiceMiddleware(unexpected)(scope, unexpected, unexpected))
    await asyncio.sleep(.01)
    assert state.admitted == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state.admitted == 0


def test_metrics_headers_and_readiness_do_not_expose_inputs(client):
    secret = "private-biometric-or-user-id"
    result = client.post("/face/enroll", headers={"X-Request-ID": secret}, json={
        "user_id": secret, "image": secret, "camera_consent": False})
    assert result.status_code == 400
    assert len(result.headers["x-request-id"]) == 32
    client.get("/unknown/" + secret)
    output = client.get("/metrics")
    assert output.status_code == 200
    assert "module3_http_requests_total" in output.text
    assert secret not in output.text
    assert "face_template_hash" not in output.text
    assert client.get("/ready").json()["status"] == "ready"
    assert client.get("/health").json() == {"status": "healthy", "service": "face-recognition"}


def test_histogram_is_cumulative_and_memory_is_optional():
    instance = Metrics()
    instance.observe("embedding", .075)
    text = instance.render()
    assert 'stage="embedding",le="0.05"} 0' in text
    assert 'stage="embedding",le="0.1"} 1' in text
    assert 'stage="embedding",le="+Inf"} 1' in text
    assert rss_bytes() is None or rss_bytes() > 0


def test_changed_runtime_rejects_visual_work_before_decoding_but_health_remains_live(client, monkeypatch):
    import app.main as api
    monkeypatch.setattr(app.state.runtime, "unchanged", lambda: False)
    monkeypatch.setattr(api, "decode_base64_image", lambda _: pytest.fail("Changed runtime must not decode a face"))
    result = client.post("/face/enroll", json={"user_id": "probe", "image": "private-marker", "camera_consent": True})
    assert result.status_code == 503 and "private-marker" not in result.text
    assert client.get("/health").status_code == 200 and client.get("/ready").status_code == 503
    assert app.state.admitted == 0


@pytest.mark.asyncio
async def test_queued_request_rechecks_runtime_before_reading_body():
    from types import SimpleNamespace
    checked = asyncio.Event()
    unchanged = True

    def consistency():
        checked.set()
        return unchanged

    state = SimpleNamespace(settings=Settings("sha256", "heuristic", 1, 1, 1, 2),
                            inference_slots=asyncio.Semaphore(0), admitted=0,
                            runtime=SimpleNamespace(unchanged=consistency))
    responses = []

    async def must_not_run(*_):
        pytest.fail("Queued image must not be read/processed after policy change")

    async def send(message):
        responses.append(message)

    scope = {"type": "http", "method": "POST", "path": "/face/verify", "app": SimpleNamespace(state=state)}
    task = asyncio.create_task(ServiceMiddleware(must_not_run)(scope, must_not_run, send))
    await asyncio.wait_for(checked.wait(), 1)
    assert state.admitted == 1
    unchanged = False
    state.inference_slots.release()
    await asyncio.wait_for(task, 1)
    assert responses[0]["status"] == 503 and state.admitted == 0 and state.inference_slots._value == 1
