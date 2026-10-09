"""Bound request bodies before JSON parsing, including chunked uploads."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


MAX_REQUEST_BYTES = 10 * 1024 * 1024


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
