"""Bound request bodies before JSON parsing, including chunked uploads."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
import asyncio
import time
import uuid

from app.observability import metrics


MAX_REQUEST_BYTES = 10 * 1024 * 1024


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
            await self.app(scope, receive, observed_send)
        finally:
            if acquired:
                metrics.active -= 1
                state.inference_slots.release()
            if waiting:
                state.admitted -= 1
            metrics.request(scope["path"], status, time.perf_counter() - started)


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_REQUEST_BYTES):
        self.app = app
        self.max_bytes = max_bytes

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
        while True:
            message = await receive()
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
