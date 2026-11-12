"""V7-A A-fix AF-01：请求全过程取消（检索 / 工具等待 / 首 token）。"""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from modules.ai_text.cancel import registry
from modules.ai_text.llm_service import LLMService


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


async def _actor(factory):
    from tests.test_training.test_v7a_state_and_reports import _admin_token
    from core.security import decode_access_token
    payload = decode_access_token(await _admin_token(factory))
    return {"user_id": int(payload["sub"]), "role": "admin", "token_version": 0}


@pytest.mark.asyncio
async def test_cancel_during_knowledge_retrieval_is_registered(client, test_session_factory, monkeypatch):
    from modules.ai_text import router
    from modules.ai_text.schemas import CopilotChatRequest

    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked_ask(*args):
        entered.set()
        await release.wait()
        return {"sources": [], "status": "ok", "provider": "local"}

    monkeypatch.setattr(router, "_retrieve", blocked_ask)
    monkeypatch.setattr("core.llm_provider.create_llm_provider", lambda: object())
    reqid, user = "afix-retrieval", await _actor(test_session_factory)
    frames: list[str] = []

    async def consume() -> None:
        response = await router.copilot_chat_stream(
            CopilotChatRequest(message="Explain OSPF", request_id=reqid), _request(), user
        )
        frames.extend([frame async for frame in response.body_iterator])

    task = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), 2)
    result = await router.cancel_copilot_request(reqid, user)
    release.set()
    await asyncio.wait_for(task, 2)
    assert result["cancelled"] is True
    assert result["upstream"] == "abort_requested"
    assert any('"status": "cancelled"' in frame for frame in frames)


@pytest.mark.asyncio
async def test_cancel_while_waiting_first_token_closes_upstream_within_300ms():
    entered, release = asyncio.Event(), asyncio.Event()
    cancelled = asyncio.Event()

    class WaitingProvider:
        closed = False

        async def chat_completion(self, *args, **kwargs):
            return {"content": "", "tool_calls": []}

        async def stream_parts(self, *args, **kwargs):
            try:
                entered.set()
                await release.wait()
                yield {"kind": "content", "text": "first"}
            finally:
                self.closed = True

    provider = WaitingProvider()
    service = LLMService(db=None, user_id=None, provider=provider, use_short_sessions=False)
    events: list[dict] = []

    async def consume():
        async for event in service.copilot_chat_stream(
            message="Explain OSPF", request_id="afix-wait", cancel_event=cancelled
        ):
            events.append(event)

    task = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), 2)
    started = time.monotonic()
    cancelled.set()
    done, _ = await asyncio.wait({task}, timeout=0.3)
    elapsed = time.monotonic() - started
    release.set()
    await asyncio.wait_for(task, 2)
    assert done, f"cancel took longer than 300ms ({elapsed:.3f}s)"
    assert provider.closed is True
    assert events[-1]["status"] == "cancelled"
    assert any(event["type"] == "cancelled" for event in events)


@pytest.mark.asyncio
async def test_cancel_during_tool_round_does_not_wait_for_provider():
    entered, release = asyncio.Event(), asyncio.Event()
    cancelled = asyncio.Event()

    class BlockingToolProvider:
        closed = False

        async def chat_completion(self, *args, **kwargs):
            entered.set()
            await release.wait()
            return {"content": "", "tool_calls": []}

        async def stream_parts(self, *args, **kwargs):
            yield {"kind": "content", "text": "should-not-arrive"}
            self.closed = True

    provider = BlockingToolProvider()
    service = LLMService(
        db=None, user_id=1, provider=provider, use_short_sessions=False,
        actor={"user_id": 1, "role": "admin", "username": "afix"},
    )
    events: list[dict] = []

    async def consume():
        async for event in service.copilot_chat_stream(
            message="查询设备状态", request_id="afix-tool", cancel_event=cancelled
        ):
            events.append(event)

    task = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), 2)
    started = time.monotonic()
    cancelled.set()
    done, _ = await asyncio.wait({task}, timeout=0.4)
    elapsed = time.monotonic() - started
    release.set()
    await asyncio.wait_for(task, 2)
    assert done, f"tool-round cancel took longer than 400ms ({elapsed:.3f}s)"
    assert events[-1]["status"] == "cancelled"
    assert not any(event.get("type") == "token" for event in events)


@pytest.mark.asyncio
async def test_registry_cleans_up_after_normal_stream(client, test_session_factory, monkeypatch):
    from modules.ai_text import router
    from modules.ai_text.schemas import CopilotChatRequest

    class QuickProvider:
        async def chat_completion(self, *args, **kwargs):
            return {"content": "", "tool_calls": []}

        async def stream_parts(self, *args, **kwargs):
            yield {"kind": "content", "text": "hello"}
            yield {"kind": "content", "text": " world"}

    monkeypatch.setattr(
        router, "_get_knowledge_service", lambda: SimpleNamespace(ask=_empty_ask, search=_empty_ask)
    )
    monkeypatch.setattr(router.SystemService, "build_llm_provider", AsyncMock(return_value=QuickProvider()))
    reqid, user = "afix-normal", await _actor(test_session_factory)
    response = await router.copilot_chat_stream(
        CopilotChatRequest(message="hi", request_id=reqid), _request(), user
    )
    frames = [frame async for frame in response.body_iterator]
    assert any('"type": "token"' in frame for frame in frames)
    assert registry.request_cancel(user["user_id"], reqid) is False


async def _empty_ask(*args, **kwargs):
    return {"sources": [], "status": "ok", "provider": "local"}
