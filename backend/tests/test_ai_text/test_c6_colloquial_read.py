"""Natural explicit reads still use the authenticated, bounded executor."""
import json
from unittest.mock import AsyncMock

import pytest

from modules.ai_text.read_plan import initial_followup_read, initial_read
from modules.ai_text.trusted_context import ResolvedTaskTargets


def target(hostname='R1', device_id=1):
    return ResolvedTaskTargets([{'hostname': hostname, 'device_id': device_id}], [], [], 'now')


@pytest.mark.parametrize('message,command', [
    ('帮我读一下 R1 的 OSPF 邻居。', 'display ospf peer'),
    ('请读一读 R1 的接口状态', 'display ip interface brief'),
    ('帮忙读下R1的路由表', 'display ip routing-table'),
])
def test_colloquial_explicit_read_selects_one_existing_command(message, command):
    plan = initial_read(message, 'live_evidence', target(), ['run_display_command'])
    assert plan is not None
    assert json.loads(plan['function']['arguments']) == {'device_id': 1, 'command': command}


@pytest.mark.parametrize('message', [
    '不要读一下R1的OSPF邻居，只解释原理',
    '别读R1接口状态，只查看说明',
    '不用再读一下R1的路由表，查看历史即可',
    '不读R1接口状态，查看字段含义',
    '读一下R1接口状态是什么意思？',
    '怎么读一下R1的OSPF邻居？',
    '解释“读一下R1的OSPF邻居”这个操作',
    '昨天读一下R1接口状态得到的结果还能用吗？',
    '读一下R1的接口状态，然后下发配置',
    '读一下R1和R99的OSPF邻居',
    '读一下R1的接口状态和路由表',
])
def test_colloquial_read_does_not_force_concepts_negation_history_writes_or_multiple_reads(message):
    assert initial_read(message, 'live_evidence', target(), ['run_display_command']) is None


def test_colloquial_field_followup_reads_new_target_only():
    plan = initial_followup_read('那R3呢？', 'live_evidence', target('R3', 3),
        ['run_display_command'], [{'role': 'user', 'content': '帮我读一下R1的OSPF邻居'}])
    assert plan is not None
    assert json.loads(plan['function']['arguments']) == {'device_id': 3, 'command': 'display ospf peer'}


@pytest.mark.asyncio
async def test_colloquial_busy_read_really_attempts_executor_and_preserves_failure(monkeypatch):
    from modules.ai_text import agent_tools
    from modules.ai_text.llm_service import LLMService
    from modules.ai_text.tool_result import EvidenceText

    class Provider:
        async def chat_completion(self, *args, **kwargs):
            raise AssertionError('A resolved explicit read does not need model planning')

        async def stream_parts(self, prompt, system=None):
            assert '设备终端占用中' in prompt
            yield {'kind': 'content', 'text': '本次读取因设备终端占用失败，未取得邻居观察。'}

    execute = AsyncMock(return_value=EvidenceText('设备终端占用中', status='failed',
        target='1', source='server_observed', mode='sim', completeness='none'))
    monkeypatch.setattr(agent_tools, 'execute_tool', execute)
    service = LLMService(user_id=1, provider=Provider(), actor={'user_id': 1, 'role': 'user'})
    monkeypatch.setattr(service, '_log_request', AsyncMock())
    events = [event async for event in service.copilot_chat_stream('帮我读一下R1的OSPF邻居。',
        ui_context={'skill_id': 'live_evidence', 'server_targets': target()},
        allowed_tools=['run_display_command'], tier='standard')]
    assert execute.await_count == 1
    trace = events[-1]['trace']
    assert trace['model_calls'] == 1 and trace['tool_dispatch_attempts'] == 1
    assert trace['read_plan_source'] == 'explicit_request'
    assert '占用失败' in ''.join(event.get('text', '') for event in events if event['type'] == 'token')
