"""V7-A A-06：AI 请求取消与迟到事件抑制。"""
import asyncio

import pytest

from modules.ai_text.cancel import registry
from modules.ai_text.llm_service import LLMService


class SlowStreamProvider:
    """可控慢流：记录上游生成器是否被关闭。"""

    def __init__(self) -> None:
        self.closed = False
        self.produced = 0

    async def stream_parts(self, prompt, system=None, max_tokens=None, temperature=None):
        try:
            for index in range(200):
                await asyncio.sleep(0.005)
                self.produced += 1
                yield {"kind": "content", "text": f"tok{index};"}
        finally:
            self.closed = True


@pytest.mark.asyncio
async def test_cancel_mid_stream_closes_upstream_and_never_completes():
    provider = SlowStreamProvider()
    service = LLMService(db=None, user_id=None, provider=provider, use_short_sessions=False)
    cancel_event = asyncio.Event()
    events: list[dict] = []

    async def consume():
        async for event in service.copilot_chat_stream(
            message="解释 OSPF 邻居状态",
            request_id="req-test-1",
            cancel_event=cancel_event,
        ):
            events.append(event)
            if event.get("type") == "token" and sum(1 for e in events if e.get("type") == "token") == 2:
                cancel_event.set()

    await asyncio.wait_for(consume(), timeout=5)

    assert any(event["type"] == "cancelled" for event in events)
    assert events[-1]["type"] == "done"
    assert events[-1]["status"] == "cancelled"
    assert not any(event.get("type") == "done" and event.get("status") == "ok" for event in events)
    # 上游生成器已关闭：不会在后台继续产出 token
    assert provider.closed is True
    produced_at_cancel = provider.produced
    await asyncio.sleep(0.05)
    assert provider.produced == produced_at_cancel


@pytest.mark.asyncio
async def test_cancel_before_first_token_returns_cancelled_immediately():
    provider = SlowStreamProvider()
    service = LLMService(db=None, user_id=None, provider=provider, use_short_sessions=False)
    cancel_event = asyncio.Event()
    cancel_event.set()
    events = [
        event
        async for event in service.copilot_chat_stream(
            message="你好", request_id="req-test-2", cancel_event=cancel_event
        )
    ]
    assert events[0]["type"] == "cancelled"
    assert events[-1]["status"] == "cancelled"
    assert provider.produced == 0


@pytest.mark.asyncio
async def test_cancel_registry_scopes_requests_by_user():
    user_event = registry.register(7, "req-a")
    other_event = registry.register(8, "req-a")

    found = registry.request_cancel(7, "req-a")
    assert found is True
    assert user_event.is_set() is True
    assert other_event.is_set() is False

    missing = registry.request_cancel(7, "req-unknown")
    assert missing is False
    registry.unregister(7, "req-a")
    registry.unregister(8, "req-a")


@pytest.mark.asyncio
async def test_cancel_endpoint_reports_upstream_abort_honestly():
    from modules.ai_text.router import cancel_copilot_request

    event = registry.register(11, "req-http")
    result = await cancel_copilot_request("req-http", {"user_id": 11})
    assert result["cancelled"] is True
    assert result["upstream"] == "abort_requested"
    assert event.is_set()
    registry.unregister(11, "req-http")

    missing = await cancel_copilot_request("req-http", {"user_id": 11})
    assert missing["cancelled"] is False
    assert missing["upstream"] == "not_found"
