import asyncio
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.middleware import BodySizeLimitMiddleware, ServiceMiddleware


def scope():
    state = SimpleNamespace(settings=Settings("sha256", "heuristic", 1, 1, 0, 2, body_seconds=.04),
                            admitted=0, inference_slots=asyncio.Semaphore(1))
    return {"type": "http", "method": "POST", "path": "/face/verify", "headers": [],
            "app": SimpleNamespace(state=state)}


@pytest.mark.asyncio
@pytest.mark.parametrize("trickle", [False, True])
async def test_absolute_upload_deadline_releases_capacity_and_cancels_only_read(trickle):
    request = scope()
    responses, calls = [], []
    read_cancelled = asyncio.Event()

    async def downstream(*_):
        raise AssertionError("Inference must not run on an unfinished body")

    async def receive():
        calls.append(True)
        try:
            await asyncio.sleep(.015 if trickle else 10)
            return {"type": "http.request", "body": b"private", "more_body": True}
        except asyncio.CancelledError:
            read_cancelled.set()
            raise

    async def send(message):
        responses.append(message)

    middleware = ServiceMiddleware(BodySizeLimitMiddleware(downstream))
    await asyncio.wait_for(middleware(request, receive, send), 1.)
    assert responses[0]["status"] == 408
    assert (b"connection", b"close") in responses[0]["headers"]
    assert b"private" not in responses[-1]["body"]
    assert read_cancelled.is_set()
    assert request["app"].state.admitted == 0
    assert request["app"].state.inference_slots._value == 1
    assert len(calls) <= 3


@pytest.mark.asyncio
@pytest.mark.parametrize("disconnect", [False, True])
async def test_disconnect_or_external_cancellation_releases_upload_slot(disconnect):
    request, messages = scope(), []
    entered = asyncio.Event()

    async def receive():
        entered.set()
        if disconnect:
            return {"type": "http.disconnect"}
        await asyncio.Event().wait()

    async def downstream(*_):
        raise AssertionError("Incomplete upload must not run inference")

    async def send(message):
        messages.append(message)

    task = asyncio.create_task(ServiceMiddleware(BodySizeLimitMiddleware(downstream))(request, receive, send))
    await entered.wait()
    if disconnect:
        await task
    else:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not messages
    assert request["app"].state.admitted == 0 and request["app"].state.inference_slots._value == 1


@pytest.mark.asyncio
async def test_completed_upload_is_replayed_once_and_slow_inference_is_not_cancelled():
    request, calls = scope(), []
    chunks = iter([{"type": "http.request", "body": b"123", "more_body": True},
                   {"type": "http.request", "body": b"456", "more_body": False}])

    async def receive():
        return next(chunks)

    async def downstream(_scope, body, _send):
        assert await body() == {"type": "http.request", "body": b"123456", "more_body": False}
        await asyncio.sleep(.08)  # Longer than the UPLOAD budget, after upload.
        calls.append(True)

    async def send(_):
        pass

    await ServiceMiddleware(BodySizeLimitMiddleware(downstream))(request, receive, send)
    assert calls == [True] and request["app"].state.admitted == 0
