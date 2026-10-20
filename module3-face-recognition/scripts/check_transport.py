"""Real loopback upload-deadline and private OTLP delivery checks.

No backend, real Collector, camera data, Docker or remote export is involved.
Only synthetic marker payloads are sent. Reports contain booleans/counts only.
"""

import argparse
from datetime import datetime, timezone
from http.client import HTTPResponse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
from threading import Event, Lock, Thread
import time
from urllib.parse import urlsplit

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from support import local_service, metric_value, report_target, save_report


def require(value):
    if not value:
        raise AssertionError("Transport contract expectation failed")


def slow_upload(client, chunked=False, trickle=False):
    address = urlsplit(str(client.base_url))
    stop = Event()
    with socket.create_connection((address.hostname, address.port), timeout=3) as connection:
        connection.settimeout(3)
        framing = "Transfer-Encoding: chunked" if chunked else "Content-Length: 1000"
        connection.sendall((f"POST /face/enroll HTTP/1.1\r\nHost: localhost\r\n{framing}\r\n"
                            "Content-Type: application/json\r\n\r\n").encode())
        connection.sendall(b"7\r\nprivate\r\n" if chunked else b"private")

        def drip():
            while not stop.wait(.03):
                try:
                    connection.sendall(b"1\r\nx\r\n" if chunked else b"x")
                except OSError:
                    return

        writer = Thread(target=drip, daemon=True) if trickle else None
        if writer:
            writer.start()
        try:
            require(client.get("/health").status_code == 200)
            response = HTTPResponse(connection)
            response.begin()
            require(response.status == 408 and response.getheader("Connection").lower() == "close")
            require(b"private" not in response.read(1024))
        finally:
            stop.set()
            if writer:
                writer.join(timeout=1)
    # After 408, a normal request must be admitted rather than stuck behind an
    # abandoned upload. Consent false avoids running any biometric inference.
    require(client.post("/face/enroll", json={"user_id": "probe", "image": "unused", "camera_consent": False}).status_code == 400)
    text = client.get("/metrics").text
    require(metric_value(text, "module3_inference_active") == metric_value(text, "module3_inference_pending") == 0)


def check_uploads():
    results = []
    with local_service("sha256", {"REQUEST_BODY_SECONDS": ".2", "INFERENCE_CONCURRENCY": "1",
                                  "INFERENCE_PENDING": "0"}) as client:
        for chunked in (False, True):
            for trickle in (False, True):
                slow_upload(client, chunked, trickle)
                results.append({"chunked": chunked, "trickle": trickle, "passed": True})
        # A closed socket is a disconnect, not a completed request or inference.
        address = urlsplit(str(client.base_url))
        with socket.create_connection((address.hostname, address.port), timeout=2) as connection:
            connection.sendall(b"POST /face/enroll HTTP/1.1\r\nHost: localhost\r\nContent-Length: 1000\r\n\r\nprivate")
        time.sleep(.1)
        require(client.get("/health").status_code == 200)
        require(client.post("/face/enroll", json={"user_id": "probe", "image": "unused", "camera_consent": False}).status_code == 400)
    return results


def check_otlp():
    batches, lock = [], Lock()

    class Collector(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            if self.path != "/v1/traces" or not 0 < length <= 262144:
                self.send_error(400)
                return
            message = ExportTraceServiceRequest.FromString(self.rfile.read(length))
            with lock:
                batches.append(message)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    collector = ThreadingHTTPServer(("127.0.0.1", 0), Collector)
    worker = Thread(target=collector.serve_forever, daemon=True)
    worker.start()
    try:
        endpoint = f"http://127.0.0.1:{collector.server_port}"
        with local_service("sha256", {"OTEL_EXPORTER_OTLP_ENDPOINT": endpoint}) as client:
            secret = "private-transport-marker"
            trace_id = "1234567890abcdef1234567890abcdef"
            parent_id = "1234567890abcdef"
            require(client.post("/face/enroll?image=" + secret, headers={
                "Traceparent": f"00-{trace_id}-{parent_id}-01", "Tracestate": "private=" + secret,
                "Baggage": "student=" + secret, "Authorization": secret}, json={
                    "user_id": secret, "image": secret, "camera_consent": True}).status_code == 400)
            require(client.get("/unknown/" + secret).status_code == 404)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with lock:
                    received = sum(len(scope.spans) for batch in batches for resource in batch.resource_spans
                                   for scope in resource.scope_spans)
                if received >= 3:
                    break
                time.sleep(.05)
            require(received >= 3)
            require(client.get("/health").status_code == client.get("/ready").status_code == 200)
        spans = [span for batch in batches for resource in batch.resource_spans
                 for scope in resource.scope_spans for span in scope.spans]
        require(all(secret.encode() not in batch.SerializeToString() for batch in batches))
        require(all(not span.events and not span.trace_state and not span.status.message for span in spans))
        require(all({field.key for field in span.attributes} <= {"http.route", "http.method", "http.status_code"} for span in spans))
        roots = [span for span in spans if span.name == "POST /face/enroll"]
        require(len(roots) == 1 and roots[0].trace_id.hex() == trace_id and roots[0].parent_span_id.hex() == parent_id)
        require(any(span.name == "image_decode" and span.parent_span_id == roots[0].span_id for span in spans))
        return {"passed": True, "batches_received": len(batches), "spans_received": len(spans),
                "parent_continuity": True, "worker_stage_continuity": True, "sensitive_marker_absent": True}
    finally:
        collector.shutdown()
        collector.server_close()
        worker.join(timeout=2)


def check_collector_failure():
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        endpoint = f"http://127.0.0.1:{reservation.getsockname()[1]}"
        # Bound but not listening: a controlled unavailable destination.
        with local_service("sha256", {"OTEL_EXPORTER_OTLP_ENDPOINT": endpoint}) as client:
            require(client.post("/face/enroll", json={"user_id": "probe", "image": "unused", "camera_consent": False}).status_code == 400)
            deadline = time.monotonic() + 5
            failures = 0
            while time.monotonic() < deadline:
                failures = metric_value(client.get("/metrics").text, "module3_trace_export_failures_total")
                if failures:
                    break
                time.sleep(.05)
            require(failures >= 1)
            require(client.get("/health").status_code == client.get("/ready").status_code == 200)
    return {"passed": True, "export_failure_observed": True, "health_and_readiness_unchanged": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="evaluation/transport.json")
    args = parser.parse_args()
    target = report_target(args.report)
    record = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "completed": False, "passed": False,
              "limitations": ["Loopback diagnostic receiver, not the actual Module 4 Collector or complete backend trace.",
                              "No inference accuracy, external proxy/header deadlines or production network certification."]}
    try:
        record["uploads"] = check_uploads()
        record["otlp"] = check_otlp()
        record["collector_failure"] = check_collector_failure()
        record["completed"] = record["passed"] = True
    except Exception as exc:
        record["failure_type"] = type(exc).__name__
    finally:
        save_report(target, record)
    print(f"Loopback transport checks passed={record['passed']}; report={target}", flush=True)
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
