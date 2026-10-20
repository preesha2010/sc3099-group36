from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from app.main import app
from app.middleware import TelemetryMiddleware
from app.observability import Metrics
from app.telemetry import Telemetry, PrivateOTLPExporter


def test_disabled_telemetry_never_constructs_exporter(monkeypatch):
    import app.telemetry as module
    monkeypatch.setattr(module, "PrivateOTLPExporter", lambda *_: pytest.fail("Telemetry is disabled"))
    telemetry = Telemetry()
    with telemetry.request("/face/verify", "POST", []) as span:
        assert span is None
    telemetry.close()


def test_trace_parent_and_thread_stage_context_are_preserved_without_baggage(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "private=secret-marker")
    exporter = InMemorySpanExporter()
    telemetry = Telemetry(exporter=exporter, batch=False)
    trace_id = "1234567890abcdef1234567890abcdef"
    headers = [(b"traceparent", f"00-{trace_id}-1234567890abcdef-01".encode()),
               (b"baggage", b"student=secret-marker"), (b"tracestate", b"private=secret-marker")]
    try:
        with telemetry.request("/face/verify", "POST", headers) as request:
            # Like anyio, explicitly carry the request Context into a worker.
            import contextvars
            context = contextvars.copy_context()
            with ThreadPoolExecutor(1) as worker:
                worker.submit(context.run, lambda: list_stage()).result()
            request.set_attribute("http.status_code", 200)
        spans = exporter.get_finished_spans()
        assert {span.name for span in spans} == {"POST /face/verify", "embedding"}
        child = next(span for span in spans if span.name == "embedding")
        parent = next(span for span in spans if span.name.startswith("POST"))
        assert child.parent.span_id == parent.context.span_id
        assert parent.context.trace_id == int(trace_id, 16)
        assert parent.parent.span_id == int("1234567890abcdef", 16)
        for span in spans:
            assert not span.context.trace_state
            assert set(span.resource.attributes) == {"service.name", "service.version"}
            assert "secret-marker" not in span.to_json()
    finally:
        telemetry.close()


def list_stage():
    with Metrics().stage("embedding"):
        pass


def test_every_production_timed_decorator_has_a_fixed_trace_stage():
    import ast
    from pathlib import Path
    from app.telemetry import STAGES
    names = set()
    for path in (Path(__file__).resolve().parents[1] / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "timed":
                names.add(ast.literal_eval(node.args[0]))
    assert names and names <= STAGES


def test_response_traces_only_allowlist_routes_status_and_safe_methods():
    exporter = InMemorySpanExporter()
    telemetry = Telemetry(exporter=exporter, batch=False)
    with TestClient(app) as client:
        app.state.telemetry = telemetry
        secret = "private-marker"
        result = client.post("/face/enroll?image=" + secret,
                             headers={"Authorization": secret, "Baggage": secret},
                             json={"user_id": secret, "image": secret, "camera_consent": False})
        assert result.status_code == 400
        assert client.get("/unknown/" + secret).status_code == 404
        for path in ("/health", "/ready", "/metrics"):
            assert client.get(path).status_code == 200
        spans = exporter.get_finished_spans()
        assert len(spans) == 2
        assert {span.name for span in spans} == {"POST /face/enroll", "GET other"}
        for span in spans:
            assert set(span.attributes) == {"http.route", "http.method", "http.status_code"}
            assert not span.events
            assert secret not in span.to_json()


@pytest.mark.asyncio
async def test_native_exception_is_not_recorded_as_a_trace_event_or_description():
    exporter = InMemorySpanExporter()
    telemetry = Telemetry(exporter=exporter, batch=False)

    async def fail(*_):
        raise RuntimeError("private-native-error-with-template")

    request = {"type": "http", "path": "/face/verify", "method": "POST", "headers": [],
               "app": SimpleNamespace(state=SimpleNamespace(telemetry=telemetry))}
    try:
        with pytest.raises(RuntimeError):
            await TelemetryMiddleware(fail)(request, fail, fail)
        span, = exporter.get_finished_spans()
        assert span.attributes["http.status_code"] == 500
        assert span.status.is_ok is False and span.status.description is None
        assert not span.events and "private-native" not in span.to_json()
    finally:
        telemetry.close()


@pytest.mark.parametrize("fault", ["unavailable", "redirect", "timeout", "encoding"])
def test_export_failure_is_single_attempt_redacted_and_does_not_raise(monkeypatch, fault, caplog):
    import app.telemetry as module
    calls, failures = [], []

    def transport(request):
        calls.append(request)
        if fault == "timeout":
            raise httpx.ReadTimeout("private-error-marker", request=request)
        return httpx.Response(503 if fault == "unavailable" else 307, text="private-response-marker")

    original = httpx.Client

    def client(**options):
        assert options == {"timeout": 1., "trust_env": False, "follow_redirects": False}
        return original(transport=httpx.MockTransport(transport), **options)

    monkeypatch.setattr(module.httpx, "Client", client)
    if fault == "encoding":
        monkeypatch.setattr(module, "encode_spans", lambda _: (_ for _ in ()).throw(RuntimeError("private-encoding-marker")))
    exporter = PrivateOTLPExporter("http://127.0.0.1:4318", lambda: failures.append(True))
    assert exporter.export([]) == SpanExportResult.FAILURE
    assert len(calls) == (0 if fault == "encoding" else 1) and failures == [True]
    assert "private-" not in caplog.text


def test_export_uses_otlp_protobuf_and_never_copies_environment_credentials(monkeypatch):
    import app.telemetry as module
    saved = []

    def transport(request):
        saved.append(request)
        return httpx.Response(200)

    original = httpx.Client
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=private-token")
    monkeypatch.setattr(module.httpx, "Client", lambda **options: original(transport=httpx.MockTransport(transport), **options))
    memory = InMemorySpanExporter()
    telemetry = Telemetry(exporter=memory, batch=False)
    try:
        with telemetry.request("/face/enroll", "POST", []):
            pass
        assert PrivateOTLPExporter("http://127.0.0.1:4318/v1/traces").export(memory.get_finished_spans()) == SpanExportResult.SUCCESS
        request, = saved
        assert request.url.path == "/v1/traces" and request.headers["content-type"] == "application/x-protobuf"
        assert "authorization" not in request.headers
        message = ExportTraceServiceRequest.FromString(request.content)
        assert message.resource_spans[0].scope_spans[0].spans[0].name == "POST /face/enroll"
    finally:
        telemetry.close()
