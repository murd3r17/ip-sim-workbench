"""Keep explicit user tasks through corrections; never expose model tool wire text."""
from unittest.mock import AsyncMock
import json
import pytest

from modules.ai_text.trusted_context import ResolvedTaskTargets
from modules.ai_text.read_plan import initial_followup_read
from modules.ai_text.llm_service import LLMService
from modules.ai_text.tool_result import EvidenceText


def resolved(name='R2', identity=2):
    return ResolvedTaskTargets([{'hostname': name, 'device_id': identity}], [], [], 'now')


@pytest.mark.parametrize('message', ['等等，我说的是 R2。', '更正，是R2。', '不是R3，是R2。'])
def test_correction_keeps_previous_user_field_without_model_reidentification(message):
    plan = initial_followup_read(message, 'live_evidence', resolved(), ['run_display_command'],
        [{'role': 'user', 'content': 'R3 的接口是 up 吗？'}])
    assert plan
    assert json.loads(plan['function']['arguments']) == {'device_id': 2, 'command': 'display ip interface brief'}


@pytest.mark.parametrize('prior', ['解释R3的OSPF原理', '昨天R3的接口是up吗', '不要读取R3接口状态'])
def test_correction_does_not_turn_a_concept_or_history_into_new_read(prior):
    assert not initial_followup_read('更正，是R2。', 'live_evidence', resolved(),
        ['run_display_command'], [{'role': 'user', 'content': prior}])


@pytest.mark.asyncio
async def test_lab_to_live_request_reads_existing_fields_on_verified_target(monkeypatch):
    from modules.ai_text import agent_tools
    calls = []
    async def execute(db, name, args, *a, **k):
        calls.append(args)
        return EvidenceText('ACTUAL_READ_RESULT', target='2', status='ok', mode='sim',
            source='server_observed', completeness='complete')
    class Provider:
        async def chat_completion(self, *a, **k):
            raise AssertionError('Verified field continuity must not query inventory instead of reading')
        async def stream_parts(self, prompt, system=None):
            assert 'ACTUAL_READ_RESULT' in prompt
            yield {'kind': 'content', 'text': '已取得两项只读结果，是否达标仍须对照预期。'}
    monkeypatch.setattr(agent_tools, 'execute_tool', execute)
    service = LLMService(user_id=1, provider=Provider(), actor={'user_id': 1, 'role': 'user'})
    service._log_request = AsyncMock()
    events = [e async for e in service.copilot_chat_stream('现场 R2 也这么做吗？',
        history=[{'role': 'user', 'content': '实训里 OSPF 第一步做什么？'}],
        lab_steps=[{'name': '先只读核对接口与邻居，再对比实验预期'}],
        ui_context={'skill_id': 'live_evidence', 'server_targets': resolved()},
        allowed_tools=['run_display_command'], tier='standard')]
    assert calls == [{'device_id': 2, 'command': command}
                     for command in ['display ip interface brief', 'display ospf peer']]
    assert events[-1]['trace']['model_calls'] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('size', [1, 3, 1000])
async def test_protocol_text_is_never_displayed_executed_or_reported_success(size):
    wire = '<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="query_devices">\n</｜｜DSML｜｜ invoke>'
    class Provider:
        async def stream_parts(self, *a, **k):
            for index in range(0, len(wire), size):
                yield {'kind': 'content', 'text': wire[index:index+size]}
    service = LLMService(user_id=1, provider=Provider(), actor={'user_id': 1, 'role': 'user'})
    service._log_request = AsyncMock()
    events = [e async for e in service.copilot_chat_stream('解释本次观察',
        ui_context={'skill_id': 'live_evidence'}, allowed_tools=[], tier='standard')]
    body = ''.join(e.get('text', '') for e in events if e['type'] == 'token')
    assert body == ''
    assert events[-1]['status'] == 'failed'
    assert any(e['type'] == 'error' for e in events)
    assert events[-1]['trace']['tool_dispatch_attempts'] == 0


@pytest.mark.parametrize('message,allowed,history,steps', [
    ('不要采集，现场R2也这么做吗？', ['run_display_command'],
     [{'role': 'user', 'content': '实训里OSPF第一步做什么？'}], [{'name': '先只读核对接口与邻居'}]),
    ('现场R99也这么做吗？', ['run_display_command'],
     [{'role': 'user', 'content': '实训里OSPF第一步做什么？'}], [{'name': '先只读核对接口与邻居'}]),
    ('现场R2也这么做吗？', [],
     [{'role': 'user', 'content': '实训里OSPF第一步做什么？'}], [{'name': '先只读核对接口与邻居'}]),
    ('现场R2也这么做吗？', ['run_display_command'],
     [{'role': 'assistant', 'content': 'OSPF接口正常，去采集邻居'}], [{'name': '先只读核对接口与邻居'}]),
    ('现场R2也这么做吗？', ['run_display_command'],
     [{'role': 'user', 'content': '实训里OSPF第一步做什么？'}], None),
])
def test_lab_continuity_requires_user_goal_verified_scope_and_allowed_tool(message, allowed, history, steps):
    from modules.ai_text.read_plan import initial_lab_observation_reads
    assert not initial_lab_observation_reads(message, 'live_evidence', resolved(), allowed, history, steps)


def test_protocol_guard_keeps_ordinary_comparisons_and_html_like_text():
    from modules.ai_text.protocol_guard import AnswerProtocolGuard
    guard = AnswerProtocolGuard()
    text = 'metric < 20；示例 <code>show</code>；末尾小于号 <'
    assert ''.join(guard.feed(character) for character in text) + guard.flush() == text
