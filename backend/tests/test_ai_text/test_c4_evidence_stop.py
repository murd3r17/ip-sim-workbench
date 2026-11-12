"""A bounded/failed evidence loop must not look like complete observation."""
from unittest.mock import AsyncMock

import pytest

from modules.ai_text import agent_tools
from modules.ai_text.llm_service import LLMService
from modules.ai_text.budget_policy import limits_for


class Provider:
    model = 'offline-stop-fixture'

    def __init__(self, failure=False, extra=False):
        self.failure = failure
        self.extra = extra
        self.prompts = []
        self.plans = []

    async def chat_completion(self, messages, tools=None):
        self.plans.append(list(messages))
        if self.failure:
            raise RuntimeError('private failure detail must never reach prompt')
        return {'tool_calls': [{'id': str(i), 'function': {'name': 'query_devices', 'arguments': '{}'}}
                               for i in range(5 if self.extra else 1)]}

    async def stream_parts(self, prompt, system=None):
        self.prompts.append(prompt)
        yield {'kind': 'content', 'text': '仅依据已获得的证据，尚未核验的现场状态未知。'}


async def run(monkeypatch, provider, tier='standard', allowed=None):
    tool = AsyncMock(return_value='设备列表: R2')
    monkeypatch.setattr(agent_tools, 'execute_tool', tool)
    svc = LLMService(db=None, user_id=1, provider=provider, actor={'user_id': 1, 'role': 'admin'})
    monkeypatch.setattr(svc, '_log_request', AsyncMock())
    output = [e async for e in svc.copilot_chat_stream('核对 R2', tier=tier,
               allowed_tools=['query_devices'] if allowed is None else allowed)]
    return output[-1]['trace'], tool


@pytest.mark.asyncio
async def test_planning_failure_reaches_final_context_and_trace(monkeypatch):
    provider = Provider(failure=True)
    trace, tool = await run(monkeypatch, provider)
    tool.assert_not_awaited()
    assert trace['evidence_stop_reason'] == 'planner_failed'
    assert '工具规划失败' in provider.prompts[0]
    assert 'private failure' not in provider.prompts[0]
    assert trace['model_calls'] == 2


@pytest.mark.asyncio
async def test_omitted_tool_demand_is_explicit_but_not_counted_as_executed(monkeypatch):
    provider = Provider(extra=True)
    trace, tool = await run(monkeypatch, provider)
    limits = limits_for('standard')
    assert tool.await_count == trace['tool_calls'] == limits.max_reads
    omitted = limits.max_rounds * 5 - limits.max_reads
    assert trace['unexecuted_tool_calls'] == omitted
    assert trace['evidence_stop_reason'] == 'read_limit'
    assert f'另有 {omitted} 个工具请求未执行' in provider.prompts[0]
    assert trace['model_calls'] == limits.max_rounds + 1


@pytest.mark.asyncio
async def test_round_limit_is_visible_without_claiming_the_answer_is_wrong(monkeypatch):
    provider = Provider()
    trace, tool = await run(monkeypatch, provider, tier='diagnostic')
    assert trace['evidence_stop_reason'] == 'round_limit'
    assert '取证轮次上限' in provider.prompts[0]
    assert trace['model_calls'] == limits_for('diagnostic').max_rounds + 1
    assert tool.await_count == limits_for('diagnostic').max_rounds


@pytest.mark.asyncio
async def test_skipped_evidence_has_no_fake_failure_or_planning_call(monkeypatch):
    provider = Provider()
    trace, tool = await run(monkeypatch, provider, tier='direct', allowed=[])
    tool.assert_not_awaited()
    assert provider.plans == []
    assert trace['evidence_stop_reason'] == 'not_requested'
    assert trace['unexecuted_tool_calls'] == 0
    assert '工具规划失败' not in provider.prompts[0]
