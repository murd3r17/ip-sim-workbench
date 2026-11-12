"""Request-local reuse must reduce reads without extending access or retry budgets."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.ai_text import agent_tools
from modules.ai_text.llm_service import LLMService
from modules.ai_text.tool_result import EvidenceText
from modules.ai_text.budget_policy import limits_for
from modules.auth.models import UserRole


class RepeatingProvider:
    model = "local-tool-loop-fixture"

    def __init__(self, before_second=None):
        self.rounds = 0
        self.before_second = before_second

    async def chat_completion(self, messages, tools=None):
        self.rounds += 1
        if self.rounds == 2 and self.before_second:
            self.before_second()
        return {"tool_calls": [
            {"id": f"{self.rounds}-{i}", "function": {
                "name": "query_devices", "arguments": "{}"}} for i in range(3)
        ]}

    async def stream_parts(self, prompt, system=None):
        yield {"kind": "content", "text": "按已采集证据说明；缺少证据时不判断现场正常。"}


async def run(monkeypatch, read, before_second=None):
    account = SimpleNamespace(id=17, role=UserRole.USER, is_active=True, token_version=0)
    db = SimpleNamespace(get=AsyncMock(return_value=account))
    provider = RepeatingProvider(lambda: before_second(account) if before_second else None)
    svc = LLMService(db=db, user_id=17, provider=provider,
                     actor={"user_id": 17, "role": "user", "token_version": 0})
    monkeypatch.setattr(svc, "_log_request", AsyncMock())
    monkeypatch.setattr(agent_tools, "_query_devices", read)
    events = [event async for event in svc.copilot_chat_stream(
        "排查设备状态", tier="diagnostic", allowed_tools=["query_devices"])]
    return events[-1]["trace"], db


@pytest.mark.asyncio
async def test_repeated_reads_reuse_original_provenance_and_recheck_authorization(monkeypatch):
    read = AsyncMock(return_value=EvidenceText("R2 状态待核对", evidence_id=42,
        collected_at="2026-11-05T04:00:00Z", source="database_snapshot", mode="snapshot"))
    trace, db = await run(monkeypatch, read)
    assert read.await_count == 1
    assert db.get.await_count == 6
    assert trace["tool_calls"] == 6 and trace["tool_dispatch_attempts"] == 1
    assert trace["tool_result_reuses"] == 5
    assert [tool["reused"] for tool in trace["tools"]] == [False] + [True] * 5
    assert all(tool["evidence_id"] == 42 and tool["collected_at"] == "2026-11-05T04:00:00Z"
               for tool in trace["tools"])
    # A new user request must collect again; this is not a global answer cache.
    await run(monkeypatch, read)
    assert read.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "busy"])
async def test_same_transient_failure_gets_at_most_one_retry(monkeypatch, failure):
    read = AsyncMock(return_value=EvidenceText("暂时无法读取", status=failure, retryable=True))
    trace, _ = await run(monkeypatch, read)
    assert read.await_count == 2
    assert trace["tool_dispatch_attempts"] == 2 and trace["tool_result_reuses"] == 4
    assert all(tool["status"] == failure for tool in trace["tools"])
    assert trace["tools"][-1]["retry_exhausted"] is True
    assert trace["tools"][-1]["retryable"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke", [
    lambda user: setattr(user, "is_active", False),
    lambda user: setattr(user, "token_version", 1),
    lambda user: setattr(user, "role", UserRole.ADMIN),
])
async def test_cached_result_is_not_released_after_account_changes(monkeypatch, revoke):
    read = AsyncMock(return_value="R2 restricted observation")
    trace, db = await run(monkeypatch, read, revoke)
    # Revoked results are never reusable; every remaining bounded attempt
    # must independently recheck access without releasing the cached content.
    assert read.await_count == 1 and db.get.await_count == limits_for('diagnostic').max_reads
    assert all(tool["status"] == "forbidden" and "restricted" not in tool["text"]
               and not tool["reused"] for tool in trace["tools"][3:])


@pytest.mark.asyncio
async def test_cache_does_not_bypass_skill_or_argument_guards():
    cached = EvidenceText("must not leak", source="server_observed")
    for kwargs in [
        {"name": "query_devices", "args": {}, "allowed": []},
        {"name": "query_devices", "args": {"unexpected": True}, "allowed": ["query_devices"]},
    ]:
        result = await agent_tools.execute_tool(None, user_id=17, _cached_result=cached, **kwargs)
        assert "must not leak" not in result
