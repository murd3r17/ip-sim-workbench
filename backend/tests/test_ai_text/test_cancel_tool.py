import asyncio, pytest
from unittest.mock import AsyncMock
from modules.ai_text import agent_tools
from modules.ai_text.llm_service import LLMService

class _Provider:
    async def chat_completion(self, messages, tools=None):
        return {"content": "", "tool_calls": [{"id": "c1", "function": {"name": "query_devices", "arguments": "{}"}}]}
    async def stream_parts(self, prompt, system=None):
        yield {"kind": "content", "text": "不应到达"}

@pytest.mark.asyncio
async def test_cancel_during_tool_execution(monkeypatch):
    started = asyncio.Event(); finished = False
    async def slow_tool(*a, **k):
        nonlocal finished
        started.set()
        try:
            await asyncio.sleep(10)
            finished = True
        except asyncio.CancelledError:
            finished = True
            raise
        return "late"
    monkeypatch.setattr(agent_tools, "execute_tool", slow_tool)
    svc = LLMService(db=None, user_id=1, provider=_Provider(), actor={"user_id": 1, "role": "user"})
    monkeypatch.setattr(svc, "_build_copilot_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(svc, "_log_request", AsyncMock())
    cancel = asyncio.Event()
    events = []
    async def consume():
        async for e in svc.copilot_chat_stream("排查", allowed_tools=None, tier="diagnostic", cancel_event=cancel):
            events.append(e)
    task = asyncio.create_task(consume())
    await started.wait()
    cancel.set()
    await asyncio.wait_for(task, timeout=3)
    assert any(e["type"] == "cancelled" for e in events), events
    assert finished, "工具读取未被取消"
