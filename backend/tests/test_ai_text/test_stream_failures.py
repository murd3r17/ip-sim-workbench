# -*- coding: utf-8 -*-
"""CF-05：模型超时/空流/半截输出的终态语义。"""
import pytest

from modules.ai_text.llm_service import LLMService


class _Provider:
    def __init__(self, mode: str):
        self.mode = mode

    async def stream_parts(self, prompt, system=None):
        if self.mode == "empty":
            return
            yield  # pragma: no cover
        if self.mode == "partial_error":
            yield {"kind": "content", "text": "已经生成一半"}
            raise TimeoutError("upstream timeout")
        yield {"kind": "content", "text": "正常回答"}


@pytest.fixture
def service(monkeypatch):
    svc = LLMService(db=None, user_id=1, provider=_Provider("empty"), actor={"user_id": 1, "role": "admin"})
    monkeypatch.setattr(svc, "_build_copilot_prompt", lambda *a, **k: "prompt")

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(svc, "_log_request", noop)
    return svc


@pytest.mark.asyncio
async def test_empty_stream_reports_failed(service):
    service.provider = _Provider("empty")
    events = [e async for e in service.copilot_chat_stream("hi", allowed_tools=[])]
    types = [e["type"] for e in events]
    assert "error" in types and "done" in types
    assert events[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_partial_then_timeout_is_error_not_success(service):
    service.provider = _Provider("partial_error")
    events = [e async for e in service.copilot_chat_stream("hi", allowed_tools=[])]
    types = [e["type"] for e in events]
    assert "token" in types  # 半截内容曾输出
    visible = "".join(e.get("text", "") for e in events if e["type"] == "token")
    assert visible == "已经生成一半", visible  # 失败时安全尾部不截断
    assert "error" in types
    assert events[-1]["type"] == "done" and events[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_normal_stream_done_ok(service):
    service.provider = _Provider("ok")
    events = [e async for e in service.copilot_chat_stream("hi", allowed_tools=[])]
    assert events[-1]["type"] == "done" and events[-1]["status"] == "ok"
    assert any(e["type"] == "token" and "正常" in e.get("text", "") for e in events)


@pytest.mark.asyncio
async def test_done_carries_trace(service):
    service.provider = _Provider("ok")
    events = [e async for e in service.copilot_chat_stream("hi", allowed_tools=[])]
    done = events[-1]
    assert done["trace"]["model_calls"] >= 1
    assert done["trace"]["tool_calls"] == 0
    assert "elapsed_ms" in done["trace"]
    assert done["trace"]["usage"] is None  # 未知用量不冒充 0
