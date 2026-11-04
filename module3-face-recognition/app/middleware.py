"""Bound request bodies before JSON parsing, including chunked uploads."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
import asyncio
import time
import uuid

from app.observability import metrics, ROUTES


MAX_REQUEST_BYTES = 10 * 1024 * 1024


class TelemetryMiddleware:
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in {"/health", "/ready", "/metrics"}:
            return await self.app(scope, receive, send)
        telemetry = scope["app"].state.telemetry
        route = scope["path"] if scope["path"] in ROUTES else "other"
        method = scope["method"] if scope["method"] in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} else "OTHER"
        status = 500

        async def observed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        with telemetry.request(route, method, scope.get("headers", [])) as span:
            try:
                return await self.app(scope, receive, observed_send)
            finally:
                if span is not None:
                    from opentelemetry import trace
                    span.set_attribute("http.status_code", status)
                    if status >= 500:
                        span.set_status(trace.Status(trace.StatusCode.ERROR))

    def __init__(self, app):
        self.app = app


class ServiceMiddleware:
    """Admission precedes body buffering; no cancellation of running inference."""

    VISUAL = {"/face/enroll", "/face/verify", "/face/match", "/liveness/check"}

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        status = 500
        request_id = uuid.uuid4().hex

        async def observed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = dict(message, headers=list(message.get("headers", [])) + [(b"x-request-id", request_id.encode())])
            await send(message)

        acquired = False
        waiting = False
        state = scope["app"].state
        try:
            if scope["method"] == "POST" and scope["path"] in self.VISUAL:
                settings = state.settings
                runtime = getattr(state, "runtime", None)
                if runtime is not None and not runtime.unchanged():
                    return await JSONResponse({"detail": "Model/key/configuration changed; restart service"}, 503)(scope, receive, observed_send)
                # All modifications here are on the event loop, without awaits.
                if state.admitted >= settings.concurrency + settings.pending:
                    metrics.rejected += 1
                    return await JSONResponse({"detail": "Inference capacity is busy; retry later"}, 503,
                                              headers={"Retry-After": "1"})(scope, receive, observed_send)
                state.admitted += 1
                waiting = True
                metrics.pending += 1
                begin = time.perf_counter()
                try:
                    await asyncio.wait_for(state.inference_slots.acquire(), timeout=settings.queue_seconds)
                    acquired = True
                except asyncio.TimeoutError:
                    metrics.rejected += 1
                    return await JSONResponse({"detail": "Inference queue deadline exceeded; retry later"}, 503,
                                              headers={"Retry-After": "1"})(scope, receive, observed_send)
                finally:
                    metrics.observe("admission_wait", time.perf_counter() - begin)
                    metrics.pending -= 1
                metrics.active += 1
                # Recheck after queuing: config/assets may have changed while
                # this caller waited. Do not read its image under mixed policy.
                if runtime is not None and not runtime.unchanged():
                    return await JSONResponse({"detail": "Model/key/configuration changed; restart service"}, 503)(scope, receive, observed_send)
            await self.app(scope, receive, observed_send)
        finally:
            if acquired:
                metrics.active -= 1
                state.inference_slots.release()
            if waiting:
                state.admitted -= 1
            metrics.request(scope["path"], status, time.perf_counter() - started)


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_REQUEST_BYTES, body_seconds=None):
        self.app = app
        self.max_bytes = max_bytes
        self.body_seconds = body_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
                if declared_length < 0:
                    raise ValueError
            except ValueError:
                return await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(scope, receive, send)
            if declared_length > self.max_bytes:
                return await JSONResponse({"detail": "Request body is too large"}, status_code=413)(scope, receive, send)

        parts = []
        length = 0
        # One absolute deadline for the WHOLE upload, not a fresh timeout on
        # each chunk. A trickle of bytes cannot renew an admission slot forever.
        budget = self.body_seconds
        if budget is None:
            budget = scope["app"].state.settings.body_seconds
        deadline = time.monotonic() + budget
        while True:
            remaining = deadline - time.monotonic()
            try:
                if remaining <= 0:
                    raise asyncio.TimeoutError
                message = await asyncio.wait_for(receive(), remaining)
            except asyncio.TimeoutError:
                # Only ASGI body reads are cancelled. Native inference has not
                # started and is never interrupted by this upload deadline.
                return await JSONResponse({"detail": "Request body read deadline exceeded"}, status_code=408,
                                          headers={"Connection": "close"})(scope, receive, send)
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            length += len(body)
            if length > self.max_bytes:
                return await JSONResponse({"detail": "Request body is too large"}, status_code=413)(scope, receive, send)
            parts.append(body)
            if not message.get("more_body", False):
                break
        buffered = b"".join(parts)
        delivered = False

        async def limited_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": buffered, "more_body": False}
            return await receive()

        await self.app(scope, limited_receive, send)
