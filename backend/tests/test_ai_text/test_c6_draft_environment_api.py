from unittest.mock import AsyncMock
import uuid
import pytest

from modules.ai_text import router
from modules.ai_text.llm_service import LLMService
from modules.ai_text.protect_ports import load_protected_interfaces
from modules.device.models import Device,DeviceType,Topology,TopologyType
from modules.trust.models import EnvironmentProfile
from modules.trust.service import environment_hash
from tests.test_c3_request_api import api_case,events
from tests.test_ai_text.test_c6_draft_environment import ready_environment


async def setup_target(factory,case='ready'):
    async with factory() as db:
        topology=Topology(name='draft-env-api',topology_type=TopologyType.LAB)
        db.add(topology);await db.flush()
        device=Device(hostname='R3',mgmt_ip='192.0.2.3',model='NE40E',device_type=DeviceType.ROUTER,topology_id=topology.id)
        db.add(device);await db.flush();await db.commit()
        row=None
        if case!='missing':
            row=await ready_environment(db,device_id=device.id,status='draft' if case=='draft' else 'ready')
            if case=='hash':row.content_hash='changed';await db.commit()
            if case=='ambiguous':await ready_environment(db,device_id=device.id,version='v2')
        return device.id,row.id if row else None


class Provider:
    model='offline-draft-env'
    def __init__(self):self.calls=0
    async def stream_parts(self,*a,**k):
        self.calls+=1
        yield {'kind':'content','text':'只生成描述草稿，未执行。'}


@pytest.mark.asyncio
@pytest.mark.parametrize('path',['/chat','/chat/stream'])
@pytest.mark.parametrize('case',['missing','draft','hash','ambiguous','ready'])
async def test_environment_gate_precedes_generation_and_replays_without_calls(api_case,test_session_factory,monkeypatch,path,case):
    client,headers,_,_=api_case
    device_id,_=await setup_target(test_session_factory,case)
    provider=Provider()
    monkeypatch.setattr(router.SystemService,'build_llm_provider',AsyncMock(return_value=provider))
    monkeypatch.setattr(router,'load_protected_interfaces',load_protected_interfaces)
    generate=AsyncMock(return_value={'commands':['interface LoopBack0','description env-ready-only','quit'],'explanation':'草稿未执行'})
    monkeypatch.setattr(LLMService,'generate_and_validate',generate)
    payload={'message':'给R3的LoopBack0添加描述 env-ready-only','want_draft':True,'request_id':uuid.uuid4().hex,
        'context':{'route':'/devices','selection':f'device | R3 | id={device_id}'}}
    for attempt in range(2):
        response=await client.post('/api/v1/ai/copilot'+path,headers=headers,json=payload)
        assert response.status_code==200,response.text
        frames=events(response) if path.endswith('stream') else []
        commands=next((event['draft_commands'] for event in frames if event['type']=='draft'),[]) if frames else response.json()['draft_commands']
        assert bool(commands)==(case=='ready')
        assert provider.calls==(1 if case=='ready' else 0) and generate.await_count==(1 if case=='ready' else 0)
        if case!='ready':
            assert 'description env-ready-only' not in response.text
            result=frames[0] if frames else response.json()
            assert result.get('draft_target') is None and result['status']=='blocked_environment'


@pytest.mark.asyncio
@pytest.mark.parametrize('path',['/chat','/chat/stream'])
@pytest.mark.parametrize('phase',['answer','commands'])
async def test_generation_time_revision_drift_clears_binding_before_draft_publication(api_case,test_session_factory,monkeypatch,path,phase):
    client,headers,_,_=api_case
    device_id,env_id=await setup_target(test_session_factory)
    async def change_environment():
        async with test_session_factory() as db:
            row=await db.get(EnvironmentProfile,env_id)
            row.revision+=1;row.content_hash=environment_hash(row)
            await db.commit()
    class DriftProvider(Provider):
        async def stream_parts(self,*a,**k):
            self.calls+=1
            yield {'kind':'content','text':'已按提问生成草稿，尚未执行。'}
            if phase=='answer':await change_environment()
    provider=DriftProvider()
    monkeypatch.setattr(router.SystemService,'build_llm_provider',AsyncMock(return_value=provider))
    monkeypatch.setattr(router,'load_protected_interfaces',load_protected_interfaces)
    async def draft(*a,**k):
        if phase=='commands':await change_environment()
        return {'commands':['interface LoopBack0','description must-not-publish','quit'],'explanation':'未执行'}
    generate=AsyncMock(side_effect=draft);monkeypatch.setattr(LLMService,'generate_and_validate',generate)
    rid=uuid.uuid4().hex
    payload={'message':'给R3的LoopBack0添加描述 must-not-publish','want_draft':True,'request_id':rid,
        'context':{'route':'/devices','selection':f'device | R3 | id={device_id}'}}
    for attempt in range(2):
        response=await client.post('/api/v1/ai/copilot'+path,headers=headers,json=payload)
        assert response.status_code==200 and 'description must-not-publish' not in response.text
        if path.endswith('stream'):
            frames=events(response)
            assert not any(frame['type']=='draft' for frame in frames)
            assert frames[-1]['status']=='blocked_environment'
        else:
            assert response.json()['draft_target'] is None and not response.json()['draft_commands']
        recovery=await client.get('/api/v1/ai/copilot/requests/'+rid,headers=headers)
        assert recovery.json()['response']['draft_target'] is None
        # A later authoritative invalidation must replace provisional prose,
        # rather than preserve a contradictory claim in history/recovery.
        assert '已按提问生成草稿' not in recovery.json()['response']['answer']
        assert '生成期间环境映射或核验状态已变化' in recovery.json()['response']['answer']
        if not path.endswith('stream'):
            assert '已按提问生成草稿' not in response.json()['answer']
        assert provider.calls==1 and generate.await_count==(0 if phase=='answer' else 1)
