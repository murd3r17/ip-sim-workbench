"""Protection scope is a server decision, not a browser version selector."""
from unittest.mock import AsyncMock
import json
import uuid
from datetime import datetime,timezone
import pytest

from modules.ai_text import router
from modules.ai_text.llm_service import LLMService
from modules.ai_text.protect_ports import load_protected_interfaces
from modules.device.models import Device,DeviceType,Topology,TopologyType
from modules.trust.models import EnvironmentProfile
from modules.trust.service import environment_hash
from tests.test_c3_request_api import api_case,events


@pytest.mark.asyncio
@pytest.mark.parametrize('path',['/chat','/chat/stream'])
@pytest.mark.parametrize('hostname,claimed_version,blocked',[
    ('R3','weak-v1',True),('R3','strong-v1',True),
    ('R2','strong-v1',False),('R2','weak-v1',False),
])
async def test_page_version_cannot_weaken_or_cross_device_protection(api_case,test_session_factory,monkeypatch,path,hostname,claimed_version,blocked):
    client,headers,_,_=api_case
    monkeypatch.setattr(router,'load_protected_interfaces',load_protected_interfaces)
    async with test_session_factory() as db:
        topology=Topology(name='environment-scope-fixture',topology_type=TopologyType.LAB)
        db.add(topology);await db.flush()
        devices=[Device(hostname=name,mgmt_ip=ip,model='NE40E',device_type=DeviceType.ROUTER,topology_id=topology.id)
            for name,ip in [('R3','192.0.2.3'),('R2','192.0.2.2')]]
        db.add_all(devices);await db.flush()
        ids={device.hostname:device.id for device in devices}
        profiles=[
            EnvironmentProfile(name='R3-protected',version='strong-v1',status='ready',revision=2,
                devices=[{'device_id':ids['R3']}],protections=[{'kind':'management','target':'R3:LoopBack77'}]),
            EnvironmentProfile(name='other-device',version='weak-v1',status='ready',revision=1,
                devices=[{'device_id':ids['R2']}],protections=[]),
        ]
        db.add_all(profiles);await db.flush()
        for profile in profiles:
            profile.last_preflight_status='ready';profile.last_preflight_mode='sim';profile.last_preflight_at=datetime.now(timezone.utc)
            profile.content_hash=environment_hash(profile)
        await db.commit()
    class Provider:
        model='offline-protection-scope'
        async def stream_parts(self,*a,**k):
            yield {'kind':'content','text':'请求草稿未执行。'}
    monkeypatch.setattr(router.SystemService,'build_llm_provider',AsyncMock(return_value=Provider()))
    monkeypatch.setattr(LLMService,'generate_and_validate',AsyncMock(return_value={
        'commands':['interface LoopBack77','description target-safety-test','quit'],'explanation':'仅为描述草稿，未执行'}))
    payload={'message':f'给{hostname}的LoopBack77添加描述 target-safety-test','want_draft':True,'request_id':uuid.uuid4().hex,
        'context':{'route':'/devices','selection':f'device | {hostname} | id={ids[hostname]}'},
        'page_data':json.dumps({'device':hostname,'source':'real','environment_version':claimed_version})}
    response=await client.post('/api/v1/ai/copilot'+path,headers=headers,json=payload)
    assert response.status_code==200,response.text
    if path=='/chat':
        commands=response.json()['draft_commands']
    else:
        commands=next((frame['draft_commands'] for frame in events(response) if frame['type']=='draft'),[])
    assert bool(commands) is not blocked
    if blocked:
        assert 'description target-safety-test' not in response.text
