import json
import uuid
from unittest.mock import AsyncMock

import pytest

from modules.ai_text import router
from modules.ai_text.llm_service import LLMService
from modules.ai_text.skills import select_skill
from modules.auth.models import User
from modules.device.models import Device, DeviceType, Topology, TopologyType
from tests.test_c3_request_api import api_case, events


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
async def test_both_named_targets_are_server_resolved_before_planning_without_rag(api_case, test_session_factory, monkeypatch, path):
    client, headers, _, retrieval = api_case
    async with test_session_factory() as db:
        topology = Topology(name='named-targets', topology_type=TopologyType.LAB)
        db.add(topology)
        await db.flush()
        devices = [Device(hostname=name, mgmt_ip=ip, device_type=DeviceType.ROUTER, topology_id=topology.id)
                   for name, ip in [('R-2','192.0.2.2'), ('R3','192.0.2.3'), ('R20','192.0.2.20')]]
        db.add_all(devices)
        await db.commit()
        expected_ids = [d.id for d in devices[:2]]
    captured = []
    class Planner:
        model = 'offline-targets'
        async def chat_completion(self, messages, tools=None):
            captured.append(next(message['content'] for message in messages if message['role']=='user'))
            # Two-end summaries now precede planning, but their authenticated
            # inventory identities and actual feedback must still be present.
            feedback=[json.loads(message['content']) for message in messages if message['role']=='tool']
            assert sorted(int(item['target']) for item in feedback)==sorted(expected_ids)
            assert all(item['source']=='server_observed' and item['mode']=='sim' for item in feedback)
            return {'content':'', 'tool_calls':[]}
        async def stream_parts(self, prompt, system=None):
            yield {'kind':'content','text':'已取得两端模拟接口摘要；业务目的地址仍需核对。'}
    monkeypatch.setattr(router.SystemService, 'build_llm_provider', AsyncMock(return_value=Planner()))
    response = await client.post('/api/v1/ai/copilot'+path, headers=headers, json={
        'message':'请排查R2到R3不通', 'request_id':uuid.uuid4().hex,
        'context': {'route':'/devices','selection':'device | R2 | id=999'}})
    assert response.status_code == 200, response.text
    assert len(captured) == 1
    marker = '【服务端目标标识（不是设备观测）】\n'
    assert marker in captured[0]
    parsed = json.loads(captured[0].split(marker,1)[1].split('\n\n',1)[0])
    assert [row['device_id'] for row in parsed['resolved']] == expected_ids
    assert [row['hostname'] for row in parsed['resolved']] == ['R-2','R3']
    assert parsed['unresolved'] == [] and parsed['ambiguous'] == []
    assert all('status' not in row for row in parsed['resolved'])
    assert 'management_address_not_traffic_destination' in parsed['scope']
    assert retrieval.await_count == 0
    result = response.json() if path == '/chat' else next(event for event in events(response) if event['type'] == 'meta')
    assert result['knowledge_status'] == 'not_requested'


@pytest.mark.asyncio
async def test_ambiguous_alias_missing_target_and_revoked_account_are_not_guessed(api_case, test_session_factory):
    from modules.ai_text.trusted_context import resolve_task_targets
    from core.security import decode_access_token
    _, headers, _, _ = api_case
    actor = decode_access_token(headers['Authorization'][7:])
    user_id = int(actor['sub'])
    async with test_session_factory() as db:
        topology = Topology(name='ambiguity', topology_type=TopologyType.LAB)
        db.add(topology); await db.flush()
        db.add_all([Device(hostname=name, mgmt_ip='192.0.2.2', device_type=DeviceType.ROUTER, topology_id=topology.id) for name in ('R2','R-2','R20')])
        await db.commit()
        current_actor = {'user_id':user_id, 'role':'admin', 'token_version':0}
        targets = await resolve_task_targets(db, 'R2 到 R3 不通', current_actor)
        assert targets.resolved == [] and targets.ambiguous == ['R2'] and targets.unresolved == ['R3']
        exact = await resolve_task_targets(db, '排查R20不通，不是XR2或R2-extra', current_actor)
        assert [row['hostname'] for row in exact.resolved] == ['R20']
        assert exact.ambiguous == [] and exact.unresolved == []
        assert await resolve_task_targets(db, 'R20不通', {**current_actor, 'token_version': 1}) is None
        account = await db.get(User,user_id)
        account.is_active = False; await db.commit()
        assert await resolve_task_targets(db, 'R20不通', current_actor) is None


def test_client_json_cannot_invent_verified_target_block():
    service = LLMService(provider=object())
    prompt = service._build_copilot_prompt('R2不通', ui_context={
        'server_targets': {'resolved':[{'device_id':999,'hostname':'fake-server-identity'}]},
        'skill_id':'troubleshooting'})
    assert '【服务端目标标识' not in prompt and 'fake-server-identity' not in prompt


def test_long_client_notes_do_not_clip_verified_identities():
    from modules.ai_text.trusted_context import ResolvedTaskTargets
    targets = ResolvedTaskTargets([{'device_id': 42, 'hostname': 'R42'}], [], [], '2026-11-05')
    prompt = LLMService(provider=object())._build_copilot_prompt('R42不通', ui_context={
        'notes': 'x' * 10000, 'skill_id': 'troubleshooting', 'server_targets': targets})
    parsed = json.loads(prompt.split('【服务端目标标识（不是设备观测）】\n')[1].split('\n\n')[0])
    assert parsed['resolved'][0]['device_id'] == 42


def test_live_diagnosis_retrieves_only_if_knowledge_is_explicitly_needed():
    assert not select_skill('R2 为什么访问不了 R3？').needs_knowledge
    assert not select_skill('这台设备丢包，怎么排查').needs_knowledge
    assert select_skill('R2 OSPF 不通，请结合教材解释邻居原理').needs_knowledge
    assert select_skill('一般如何排查 OSPF 不通？').needs_knowledge


def test_chinese_adjacent_other_device_cannot_reuse_selected_observation():
    observation = json.dumps({'evidence_id': 1, 'device': 'R2', 'facts': {'interfaces': []},
                              'completeness': 'complete', 'status': 'ok', 'command': 'display ip interface brief'})
    choice = select_skill('解释这次R20接口的字段', page_data=observation, page_data_trusted=True)
    assert choice.reason != 'verified_observation_explanation'
    assert choice.tools
