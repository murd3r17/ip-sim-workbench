"""Exercise API -> real executor -> observation parser/store -> feedback -> replay.

Only the model and device transport are deterministic fixtures. These prove the
execution contract, not real model reasoning quality or real network behaviour.
"""
import json
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from core.security import decode_access_token
from modules.ai_text import router
from modules.device.models import Device, DeviceType, Topology, TopologyType
from modules.trust.models import ReadOnlyObservation
from tests.test_c3_request_api import api_case, events


class FeedbackProvider:
    model = "offline-causal-execution"

    def __init__(self, device_id):
        self.device_id = device_id
        self.calls = 0
        self.feedback = []
        self.prompts = []

    async def chat_completion(self, messages, tools=None):
        self.calls += 1
        allowed = {t['function']['name'] for t in tools}
        assert 'run_display_command' in allowed and 'query_audit_logs' not in allowed
        feedback = [json.loads(m['content']) for m in messages if m['role'] == 'tool']
        self.feedback.append(feedback)
        if not feedback:
            command = 'display ip interface brief'
        else:
            observed = feedback[-1]
            assert observed['target'] == str(self.device_id)
            assert observed['evidence_id'] and observed['collected_at']
            assert observed['source'] == 'server_observed' and observed['mode'] == 'sim'
            # Choose based on *actual result*, never on a scenario flag.
            if observed['status'] != 'ok' or 'up up' not in observed['text']:
                return {'content': '', 'tool_calls': []}
            command = 'display ospf peer'
        return {'content': '', 'tool_calls': [{'id': str(self.calls), 'function': {
            'name': 'run_display_command',
            'arguments': json.dumps({'device_id': self.device_id, 'command': command}),
        }}]}

    async def stream_parts(self, prompt, system=None):
        self.calls += 1
        self.prompts.append(prompt)
        if 'Total Peer(s): 0' in prompt:
            answer = '接口已观察到 up/up，本次 OSPF 读取未发现邻居；还不能确定原因。'
        elif 'TimeoutError' in prompt:
            answer = '本次接口读取超时，现场状态未知；未继续读取邻居。'
        elif '---- More ----' in prompt:
            answer = '本次接口回显不完整，不能据此认定所有接口正常；未继续读取邻居。'
        else:
            assert 'down down' in prompt
            answer = '本次接口观察为 down/down，先检查该接口；未继续读取邻居。'
        yield {'kind': 'content', 'text': answer}


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('scenario', ['up', 'down', 'timeout', 'partial'])
async def test_real_execution_feedback_changes_next_read_and_replay_is_free(
    api_case, test_session_factory, monkeypatch, scenario, path,
):
    client, headers, _, _ = api_case
    user_id = int(decode_access_token(headers['Authorization'][7:])['sub'])
    async with test_session_factory() as db:
        topology = Topology(name='causal-test', topology_type=TopologyType.LAB)
        db.add(topology)
        await db.flush()
        device = Device(hostname='R2', mgmt_ip='192.0.2.2', device_type=DeviceType.ROUTER,
                        topology_id=topology.id)
        db.add(device)
        await db.commit()
        device_id = device.id
    provider = FeedbackProvider(device_id)
    monkeypatch.setattr(router.SystemService, 'build_llm_provider', AsyncMock(return_value=provider))
    reads = []
    adapters = []

    async def adapter_factory(device):
        assert device.id == device_id
        adapter = AsyncMock()

        async def read(command):
            reads.append(command)
            if command == 'display ospf peer':
                return '<R2>display ospf peer\nOSPF Process 1 with Router ID 10.0.0.2\nTotal Peer(s): 0\n'
            assert command == 'display ip interface brief'
            if scenario == 'timeout':
                raise TimeoutError('fixture read deadline')
            state = 'down down' if scenario == 'down' else 'up up'
            body = f'<R2>display ip interface brief\nInterface IP Address/Mask Physical Protocol VPN\nGigabitEthernet0/0/2 10.0.23.2/24 {state} --\n'
            return body + ('---- More ----\n' if scenario == 'partial' else '')

        adapter.run_command.side_effect = read
        adapters.append(adapter)
        return adapter

    monkeypatch.setattr('engines.device_adapter.get_device_adapter', adapter_factory)
    monkeypatch.setattr('engines.device_adapter.get_device_mode', lambda: 'sim')
    body = {'message': '请分层排查 R2 到 R3 不通，先核对接口，再根据证据决定是否读取邻居。',
            'request_id': uuid.uuid4().hex,
            'context': {'route': '/devices', 'selection': f'device | R2 | id={device_id}'}}
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json=body)
    assert response.status_code == 200, response.text
    result = response.json() if path == '/chat' else events(response)[-1]
    assert result['status'] == 'ok'
    trace = result['trace']
    assert trace['tier'] == 'diagnostic' and trace['model_calls'] == provider.calls == (4 if scenario == 'up' else 3)
    expected_reads = ['display ip interface brief'] + (['display ospf peer'] if scenario == 'up' else [])
    assert reads == expected_reads
    assert trace['tool_calls'] == trace['tool_dispatch_attempts'] == len(expected_reads)
    assert trace['tool_result_reuses'] == 0
    timing = trace['timings']
    assert timing['stages']['tool']['count'] == len(expected_reads)
    assert timing['stages']['tool']['elapsed_ms'] >= 0
    # Sync has no intermediate SSE evidence event; don't fabricate its timing.
    if path == '/chat/stream' and scenario != 'timeout':
        assert timing['first_evidence_event_ms'] >= 0
    else:
        assert timing['first_evidence_event_ms'] is None
    assert all(op['status'] == 'completed' for op in trace['provider_operations'])
    assert len(provider.feedback) == (3 if scenario == 'up' else 2) and provider.feedback[0] == []
    expected_status = {'up': 'ok', 'down': 'ok', 'timeout': 'timeout', 'partial': 'partial'}[scenario]
    assert provider.feedback[1][0]['status'] == expected_status
    async with test_session_factory() as db:
        observations = (await db.execute(select(ReadOnlyObservation).order_by(ReadOnlyObservation.id))).scalars().all()
        assert len(observations) == len(expected_reads)
        for observation, outcome in zip(observations, trace['tools']):
            assert observation.created_by == user_id and observation.device_id == device_id
            assert outcome['evidence_id'] == observation.id
            assert outcome['parser_version'] == observation.parser_version
            assert str(observation.id) in provider.prompts[-1]
        if scenario == 'up':
            assert observations[0].facts['interfaces'][0]['state'] == 'up'
            # Explicit process-scoped zero is evidence, unlike an empty reply.
            assert observations[1].status == 'ok'
            assert observations[1].completeness == 'complete'
            assert observations[1].facts['peers'] == []
            assert observations[1].facts['reported_peer_counts'] == [
                {'process_id': 1, 'router_id': '10.0.0.2', 'peer_count': 0},
            ]
        elif scenario == 'down':
            assert observations[0].facts['interfaces'][0]['state'] == 'down'
    for adapter in adapters:
        adapter.run_command.assert_awaited_once()
        adapter.close.assert_awaited_once()
    # Switch transport while retaining the original request identity.
    replay_path = '/chat/stream' if path == '/chat' else '/chat'
    replay = await client.post('/api/v1/ai/copilot' + replay_path, headers=headers, json=body)
    assert replay.status_code == 200
    recovered = await client.get('/api/v1/ai/copilot/requests/' + body['request_id'], headers=headers)
    assert recovered.json()['state'] == 'completed'
    assert recovered.json()['response']['trace']['tools'] == trace['tools']
    assert recovered.json()['response']['trace']['timings'] == timing
    assert provider.calls == trace['model_calls'] and reads == expected_reads
