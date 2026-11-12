"""Spend calls on task completion, and stop when repeated reads add nothing."""
import json
from unittest.mock import AsyncMock

import pytest

from core.llm_meter import RequestMeter
from modules.ai_text.llm_service import LLMService
from modules.ai_text.tool_result import EvidenceText
from modules.ai_text.trusted_context import ResolvedTaskTargets


def call(name, args):
    return {'id': name, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


@pytest.mark.parametrize('first', ['设备清单', '设备列表', '库存', '监控', '告警'])
def test_ordered_multiple_tool_tasks_are_not_shortcut_into_only_the_last_field(first):
    from modules.ai_text.read_plan import initial_read
    targets = ResolvedTaskTargets([{'hostname': 'R3', 'device_id': 3}], [], [], 'now')
    assert initial_read(f'先查询{first}，再读取R3路由表。', 'live_evidence', targets,
                        ['query_devices', 'query_monitor_metrics', 'query_alarms', 'run_display_command']) is None


@pytest.mark.asyncio
async def test_standard_task_can_continue_after_inventory_to_actual_requested_field(monkeypatch):
    from modules.ai_text import agent_tools
    dispatched = []
    async def execute(db, name, args, *a, **k):
        dispatched.append(name)
        return EvidenceText('ACTUAL_ROUTE' if name == 'run_display_command' else 'INVENTORY_ONLY',
            status='ok', target='3', source='server_observed' if name == 'run_display_command' else 'database_snapshot',
            mode='sim', completeness='complete')
    class Provider:
        rounds = 0
        async def chat_completion(self, messages, tools=None):
            self.rounds += 1
            if self.rounds == 1:
                return {'tool_calls': [call('query_devices', {})]}
            assert 'INVENTORY_ONLY' in repr(messages)
            return {'tool_calls': [call('run_display_command', {'device_id': 3, 'command': 'display ip routing-table'})]}
        async def stream_parts(self, prompt, system=None):
            assert 'ACTUAL_ROUTE' in prompt
            yield {'kind': 'content', 'text': '本次实际取得R3路由字段；库存清单不替代该读取。'}
    monkeypatch.setattr(agent_tools, 'execute_tool', execute)
    service = LLMService(user_id=1, provider=Provider(), actor={'user_id': 1, 'role': 'user'})
    service._log_request = AsyncMock()
    events = [e async for e in service.copilot_chat_stream('再看看R3同样的路由字段。',
        history=[{'role': 'user', 'content': 'R1的路由表有啥？'}],
        ui_context={'skill_id': 'live_evidence', 'server_targets': ResolvedTaskTargets(
            [{'hostname': 'R3', 'device_id': 3}], [], [], 'now')},
        allowed_tools=['query_devices', 'run_display_command'], tier='standard')]
    assert dispatched == ['query_devices', 'run_display_command']
    assert events[-1]['trace']['model_calls'] == 3


@pytest.mark.asyncio
async def test_repeated_cached_reads_stop_without_exhausting_all_rounds(monkeypatch):
    from modules.ai_text import agent_tools
    dispatched = []
    async def execute(db, name, args, *a, _cached_result=None, **k):
        if _cached_result is not None:
            return EvidenceText(_cached_result, **{**_cached_result.metadata, 'reused': True})
        dispatched.append(name)
        return EvidenceText('SAME_INVENTORY', status='ok', mode='snapshot',
            source='database_snapshot', completeness='complete')
    class Provider:
        rounds = 0
        async def chat_completion(self, *a, **k):
            self.rounds += 1
            return {'tool_calls': [call('query_devices', {})]}
        async def stream_parts(self, *a, **k):
            yield {'kind': 'content', 'text': '重复清单没有补充所需现场证据。'}
    provider = Provider()
    monkeypatch.setattr(agent_tools, 'execute_tool', execute)
    service = LLMService(user_id=1, provider=provider, actor={'user_id': 1, 'role': 'user'})
    service._log_request = AsyncMock()
    events = [e async for e in service.copilot_chat_stream('排查当前情况',
        ui_context={'skill_id': 'troubleshooting'}, allowed_tools=['query_devices'], tier='diagnostic')]
    assert provider.rounds == 2 and dispatched == ['query_devices']
    assert events[-1]['trace']['evidence_stop_reason'] == 'no_new_evidence'


def test_meter_can_record_uncapped_transport_attempts_without_erasing_failures():
    meter = RequestMeter(None, {'scope': 'test'})
    class Endpoint:
        model = 'controlled'
        api_base_url = 'http://127.0.0.1/controlled'
    for _ in range(7):
        meter.record(Endpoint(), {'model': 'controlled', 'messages': []})
    assert meter.trace()['model_calls'] == 7
    assert meter.trace()['generation_limit'] is None
    assert meter.trace()['usage'] is None


@pytest.mark.asyncio
async def test_logical_operation_limit_does_not_count_http_failover_as_extra_step():
    import httpx
    from core.llm_meter import MeteredProvider, RequestBudgetExceeded
    from core.llm_provider import OpenAICompatibleProvider, FailoverProvider
    def respond(request):
        if json.loads(request.content)['model'] == 'first':
            return httpx.Response(503)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}}]})
    providers = [OpenAICompatibleProvider(base_url='http://controlled.invalid/v1', model=model, api_key='fixture')
                 for model in ['first', 'second']]
    for provider in providers:
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    meter = RequestMeter(None, {}, operation_limit=2)
    wrapped = MeteredProvider(FailoverProvider(*providers), meter)
    try:
        assert await wrapped.generate('first question') == 'ok'
        assert await wrapped.generate('next question') == 'ok'
        before = meter.trace()['model_calls']
        assert before >= 3 and len(meter.operations) == 2
        with pytest.raises(RequestBudgetExceeded, match='生成步骤'):
            await wrapped.generate('must not construct or dispatch')
        assert meter.trace()['model_calls'] == before
    finally:
        for provider in providers:
            await provider._client.aclose()
