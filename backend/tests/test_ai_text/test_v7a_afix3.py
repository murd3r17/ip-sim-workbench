# -*- coding: utf-8 -*-
"""AF3-01：真实 ASGI 断连在准备阶段与流式阶段都要触发生命周期清理。"""
import asyncio
import json
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.test_training.test_v7a_state_and_reports import _admin_token, auth_header


def _scope(payload: dict, token: str) -> dict:
    headers = [(b"host", b"test"), (b"content-type", b"application/json")]
    headers.extend((key.lower().encode(), value.encode()) for key, value in auth_header(token).items())
    return {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.0"},
        "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/api/v1/ai/copilot/chat/stream", "raw_path": b"/api/v1/ai/copilot/chat/stream",
        "query_string": b"", "root_path": "", "headers": headers,
        "client": ("127.0.0.1", 49201), "server": ("test", 80),
    }


class _ASGIHarness:
    def __init__(self, app, scope, payload):
        self.app = app
        self.scope = scope
        self.payload = payload
        self.disconnect = asyncio.Event()
        self.disconnect_consumed = 0
        self.messages = []
        self.task = None

    async def receive(self):
        if not getattr(self, "sent_request", False):
            self.sent_request = True
            return {"type": "http.request", "body": json.dumps(self.payload).encode(), "more_body": False}
        await self.disconnect.wait()
        self.disconnect_consumed += 1
        return {"type": "http.disconnect"}

    async def send(self, message):
        self.messages.append({"type": message["type"], "status": message.get("status")})

    def start(self):
        self.task = asyncio.create_task(self.app(self.scope, self.receive, self.send))
        return self.task

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
        if self.task:
            with suppress(BaseException):
                await asyncio.wait_for(self.task, 2)


@pytest.mark.asyncio
async def test_asgi_disconnect_during_retrieval_cleans_registration_and_task(client, test_session_factory, monkeypatch):
    from main import app
    from modules.ai_text import router
    from modules.ai_text.cancel import registry

    token = await _admin_token(test_session_factory)
    entered, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    request_id = "af3-asgi-retrieval"

    async def blocked(*args, **kwargs):
        entered.set()
        try:
            await release.wait()
            return {"sources": [], "status": "ok", "provider": "local"}
        finally:
            closed.set()

    monkeypatch.setattr(router, "_get_knowledge_service", lambda: SimpleNamespace(ask=blocked, search=blocked))
    provider = AsyncMock(side_effect=RuntimeError("must not be called"))
    monkeypatch.setattr(router.SystemService, "build_llm_provider", provider)
    harness = _ASGIHarness(app, _scope({}, token), {"message": "Explain a route", "request_id": request_id})
    harness.start()
    try:
        await asyncio.wait_for(entered.wait(), 3)
        harness.disconnect.set()
        await asyncio.wait_for(closed.wait(), 2)
        with suppress(Exception):
            await asyncio.wait_for(harness.task, 2)
        assert harness.task.done()
        assert harness.disconnect_consumed >= 1
        assert not [key for key in registry._events if key[1] == request_id]
        assert provider.await_count == 0
    finally:
        await harness.close()
        for key, event in list(registry._events.items()):
            if key[1] == request_id:
                registry.unregister(*key, event=event)


@pytest.mark.asyncio
async def test_asgi_disconnect_during_provider_initialization_cleans_up(client, test_session_factory, monkeypatch):
    from main import app
    from modules.ai_text import router
    from modules.ai_text.cancel import registry

    token = await _admin_token(test_session_factory)
    entered, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    request_id = "af3-asgi-provider"

    async def blocked_provider(*args, **kwargs):
        entered.set()
        try:
            await release.wait()
            return SimpleNamespace(model="fake")
        finally:
            closed.set()

    monkeypatch.setattr(router, "_get_knowledge_service", lambda: SimpleNamespace(ask=AsyncMock(return_value={"sources": [], "status": "ok"}), search=AsyncMock(return_value=[])))
    monkeypatch.setattr(router.SystemService, "build_llm_provider", blocked_provider)
    harness = _ASGIHarness(app, _scope({}, token), {"message": "Explain a route", "request_id": request_id})
    harness.start()
    try:
        await asyncio.wait_for(entered.wait(), 3)
        harness.disconnect.set()
        await asyncio.wait_for(closed.wait(), 2)
        with suppress(Exception):
            await asyncio.wait_for(harness.task, 2)
        assert harness.task.done()
        assert not [key for key in registry._events if key[1] == request_id]
    finally:
        await harness.close()
        for key, event in list(registry._events.items()):
            if key[1] == request_id:
                registry.unregister(*key, event=event)


@pytest.mark.asyncio
async def test_asgi_disconnect_after_headers_before_first_token_closes_stream(client, test_session_factory, monkeypatch):
    from main import app
    from modules.ai_text import router
    from modules.ai_text.cancel import registry

    token = await _admin_token(test_session_factory)
    entered, closed = asyncio.Event(), asyncio.Event()

    class BlockingStreamService:
        def __init__(self, **kwargs):
            pass

        def copilot_chat_stream(self, **kwargs):
            async def agen():
                entered.set()
                try:
                    await asyncio.sleep(30)
                    yield {"type": "token", "text": "late"}
                finally:
                    closed.set()

            return agen()

    request_id = "af3-asgi-stream"
    monkeypatch.setattr(router, "_get_knowledge_service", lambda: SimpleNamespace(ask=AsyncMock(return_value={"sources": [], "status": "ok"}), search=AsyncMock(return_value=[])))
    monkeypatch.setattr(router.SystemService, "build_llm_provider", AsyncMock(return_value=SimpleNamespace(model="fake")))
    monkeypatch.setattr(router, "LLMService", BlockingStreamService)
    harness = _ASGIHarness(app, _scope({}, token), {"message": "Explain a route", "request_id": request_id})
    harness.start()
    try:
        await asyncio.wait_for(entered.wait(), 3)
        harness.disconnect.set()
        await asyncio.wait_for(closed.wait(), 2)
        with suppress(Exception):
            await asyncio.wait_for(harness.task, 2)
        assert harness.task.done()
        assert any(message["type"] == "http.response.start" for message in harness.messages)
        assert not [key for key in registry._events if key[1] == request_id]
    finally:
        await harness.close()
        for key, event in list(registry._events.items()):
            if key[1] == request_id:
                registry.unregister(*key, event=event)


@pytest.mark.asyncio
async def test_disconnect_one_request_does_not_affect_other_and_id_can_be_reused(client, test_session_factory, monkeypatch):
    from main import app
    from modules.ai_text import router
    from modules.ai_text.cancel import registry

    token = await _admin_token(test_session_factory)
    first_entered, first_closed = asyncio.Event(), asyncio.Event()
    second_release = asyncio.Event()

    async def ask(message, *args, **kwargs):
        if message == "first":
            first_entered.set()
            try:
                await asyncio.sleep(30)
            finally:
                first_closed.set()
        await second_release.wait()
        return {"sources": [], "status": "ok"}

    monkeypatch.setattr(router, "_get_knowledge_service", lambda: SimpleNamespace(ask=ask, search=ask))
    monkeypatch.setattr(router.SystemService, "build_llm_provider", AsyncMock(return_value=SimpleNamespace(model="fake")))
    monkeypatch.setattr(router, "LLMService", lambda **kwargs: SimpleNamespace(copilot_chat_stream=lambda **kw: _empty_stream()))
    first = _ASGIHarness(app, _scope({}, token), {"message": "first", "request_id": "af3-one"})
    second = _ASGIHarness(app, _scope({}, token), {"message": "second", "request_id": "af3-two"})
    first.start()
    second.start()
    try:
        await asyncio.wait_for(first_entered.wait(), 3)
        first.disconnect.set()
        await asyncio.wait_for(first_closed.wait(), 2)
        second_release.set()
        await asyncio.wait_for(second.task, 3)
        assert second.task.done()
        assert not [key for key in registry._events if key[1] in {"af3-one", "af3-two"}]
        reused = registry.register(1, "af3-one")
        assert reused is not None
        registry.unregister(1, "af3-one", event=reused)
    finally:
        second_release.set()
        await first.close()
        await second.close()


async def _empty_stream():
    yield {"type": "meta"}
    yield {"type": "done", "status": "ok"}
