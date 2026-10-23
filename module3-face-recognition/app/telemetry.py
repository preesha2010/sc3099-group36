"""Opt-in, allowlisted OTLP traces. Never use generic request auto-capture.

Own a provider per app lifespan (not a process-global provider). Only fixed
route/method/status/stage attributes are exported; no headers, bodies, URLs,
queries, peer IPs, identities, scores, templates, exceptions or baggage.
"""

from contextlib import contextmanager
from contextvars import ContextVar

import httpx
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import encode_spans
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_active = ContextVar("module3_telemetry", default=None)
STAGES = {"admission_wait", "image_decode", "face_detect", "embedding", "template", "similarity", "mesh", "anti_spoof",
          "model_wait", "model_rebuild", "detector_cleanup", "embedding_cleanup"}


class PrivateOTLPExporter(SpanExporter):
    """Single attempt, bounded network timeouts; never log collector bodies.

    The pinned stock exporter retries for extended periods and logs unsuccessful
    response text. This adapter reuses its protobuf encoder without that policy.
    A stream checks only status and does not buffer an untrusted response body.
    """
    def __init__(self, endpoint, failed=lambda: None):
        self.endpoint = endpoint if endpoint.endswith("/v1/traces") else endpoint + "/v1/traces"
        self.failed = failed

    def export(self, spans):
        try:
            payload = encode_spans(spans).SerializeToString()
            # No inherited proxy credentials, exporter headers, redirects or
            # long retry loops. This runs on the SDK batch worker, not inference.
            with httpx.Client(timeout=1., trust_env=False, follow_redirects=False) as client:
                with client.stream("POST", self.endpoint, content=payload,
                                   headers={"Content-Type": "application/x-protobuf"}) as response:
                    if response.status_code in {200, 202}:
                        return SpanExportResult.SUCCESS
        except Exception:
            pass
        self.failed()
        return SpanExportResult.FAILURE

    def shutdown(self):
        pass


class Telemetry:
    def __init__(self, endpoint="", *, exporter=None, batch=True, failed=lambda: None):
        self.provider = self.tracer = None
        if not endpoint and exporter is None:
            return
        self.provider = TracerProvider(
            resource=Resource({"service.name": "saiv-module3-face-recognition", "service.version": "1.0.0"}),
            sampler=ParentBased(ALWAYS_ON), shutdown_on_exit=False)
        exporter = exporter if exporter is not None else PrivateOTLPExporter(endpoint, failed)
        processor = (BatchSpanProcessor(exporter, max_queue_size=256, max_export_batch_size=32,
                                        schedule_delay_millis=1000, export_timeout_millis=1500)
                     if batch else SimpleSpanProcessor(exporter))
        self.provider.add_span_processor(processor)
        self.tracer = self.provider.get_tracer("module3.internal")

    @contextmanager
    def request(self, route, method, headers):
        if self.tracer is None:
            yield None
            return
        # Only W3C traceparent is accepted. Ignore tracestate and baggage, which
        # can contain arbitrary user-provided strings. Never propagate them.
        parent = next((value for name, value in headers if name.lower() == b"traceparent"), b"")
        carrier = {}
        if len(parent) == 55:
            try:
                carrier["traceparent"] = parent.decode("ascii")
            except UnicodeError:
                pass
        context = TraceContextTextMapPropagator().extract(carrier=carrier)
        token = _active.set(self)
        try:
            with self.tracer.start_as_current_span(
                f"{method} {route}", context=context, kind=trace.SpanKind.SERVER,
                attributes={"http.route": route, "http.method": method},
                record_exception=False, set_status_on_exception=False,
            ) as span:
                yield span
        finally:
            _active.reset(token)

    def close(self):
        if self.provider is not None:
            self.provider.shutdown()


@contextmanager
def trace_stage(name):
    active = _active.get()
    if active is None or active.tracer is None or name not in STAGES:
        yield
        return
    with active.tracer.start_as_current_span(name, record_exception=False, set_status_on_exception=False) as span:
        try:
            yield
        except BaseException:
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            raise
