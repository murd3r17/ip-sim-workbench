import uuid
from unittest.mock import AsyncMock

import pytest

from modules.ai_text import router
from modules.ai_text.llm_service import LLMService
from modules.device.models import Device, DeviceType, Topology, TopologyType
from tests.test_c3_request_api import api_case, events
from tests.test_ai_text.test_c6_draft_environment import ready_environment


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
async def test_draft_target_follows_explicit_question_not_selection_and_survives_replay(api_case, test_session_factory, monkeypatch, path):
    client, headers, _, _ = api_case
    async with test_session_factory() as db:
        topology=Topology(name='draft-targets',topology_type=TopologyType.LAB)
        db.add(topology); await db.flush()
        devices=[Device(hostname=name,mgmt_ip=ip,device_type=DeviceType.ROUTER,topology_id=topology.id,model='CE6800' if name=='R3' else 'NE40E')
                 for name,ip in [('R-2','192.0.2.2'),('R3','192.0.2.3')]]
        db.add_all(devices);await db.commit()
        selected_id,target_id=[d.id for d in devices]
        await ready_environment(db,device_id=target_id)
    prompts=[]
    class Provider:
        model='offline-draft-target'
        async def stream_parts(self,prompt,system=None):
            prompts.append(prompt)
            yield {'kind':'content','text':'仅为R3生成草稿，未执行。'}
    monkeypatch.setattr(router.SystemService,'build_llm_provider',AsyncMock(return_value=Provider()))
    generate=AsyncMock(return_value={'commands':['interface LoopBack0','description test-only','quit'],'explanation':'草稿未执行'})
    monkeypatch.setattr(LLMService,'generate_and_validate',generate)
    payload={'message':'请给R3的LoopBack0添加描述，只生成草稿，不执行','want_draft':True,'request_id':uuid.uuid4().hex,
             'context':{'route':'/devices','selection':f'device | R-2 | id={selected_id}'}}
    response=await client.post('/api/v1/ai/copilot'+path,headers=headers,json=payload)
    assert response.status_code==200,response.text
    result=response.json() if path=='/chat' else next(e for e in events(response) if e['type']=='meta')
    assert result['draft_target']=={'device_id':target_id,'hostname':'R3'}
    assert generate.call_args.args[1]=='CE6800'
    assert '本次草稿目标' in prompts[0] and 'R3' in prompts[0]
    before=len(prompts)
    replay=await client.post('/api/v1/ai/copilot'+path,headers=headers,json=payload)
    saved=replay.json() if path=='/chat' else next(e for e in events(replay) if e['type']=='meta')
    assert saved['draft_target']==result['draft_target'] and len(prompts)==before
    payload.update(message='给R99的LoopBack0添加描述，只生成草稿',request_id=uuid.uuid4().hex)
    missing=await client.post('/api/v1/ai/copilot'+path,headers=headers,json=payload)
    missing_result=missing.json() if path=='/chat' else next(e for e in events(missing) if e['type']=='meta')
    assert missing_result.get('draft_target') is None
    assert missing_result['status']=='blocked_environment' and len(prompts)==before


@pytest.mark.asyncio
async def test_draft_binding_handles_custom_names_pointer_and_ambiguity_without_authorization(api_case, test_session_factory):
    from core.security import decode_access_token
    from modules.ai_text.trusted_context import resolve_draft_target
    from modules.auth.models import User
    _,headers,_,_=api_case
    claims=decode_access_token(headers['Authorization'][7:])
    actor={'user_id':int(claims['sub']),'role':claims['role'],'token_version':claims.get('token_version',0)}
    async with test_session_factory() as db:
        topology=Topology(name='draft-aliases',topology_type=TopologyType.LAB)
        db.add(topology);await db.flush()
        rows=[Device(hostname=name,mgmt_ip='192.0.2.2',device_type=DeviceType.ROUTER,topology_id=topology.id)
              for name in ['core-a','R3','R-3','R-14']]
        db.add_all(rows);await db.commit()
        selected=f'device | stale-label | id={rows[0].id}'
        target=await resolve_draft_target(db,'给这台设备添加描述',selected,actor)
        assert target.hostname=='core-a'
        assert (await resolve_draft_target(db,'给core-a添加描述','device | other | id=999',actor)).device_id==rows[0].id
        for question in ['给R3添加描述','给R99添加描述','不是R3，给当前设备添加描述','给core-missing添加描述','给core-a和R3添加描述']:
            assert await resolve_draft_target(db,question,selected,actor) is None
        assert await resolve_draft_target(db,'不是R14，给当前设备添加描述',selected,actor) is None
        from modules.monitor.models import Alarm
        alarm=Alarm(device_id=rows[0].id,alarm_type='fixture',severity='warning',message='fixture')
        db.add(alarm);await db.commit()
        alarm_selection=f'alarm | stale-label | id={alarm.id}'
        alarm_target=await resolve_draft_target(db,'给这个告警的设备添加描述',alarm_selection,actor)
        assert alarm_target.as_meta()=={'device_id':rows[0].id,'hostname':'core-a','alarm_id':alarm.id}
        assert (await resolve_draft_target(db,'给R14添加描述',alarm_selection,actor)).as_meta()=={'device_id':rows[3].id,'hostname':'R-14'}
        account=await db.get(User,actor['user_id']);account.token_version+=1;await db.commit()
        assert await resolve_draft_target(db,'给core-a添加描述',selected,actor) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('path',['/chat','/chat/stream'])
async def test_unsafe_draft_explanation_is_not_published_or_replayed(api_case,test_session_factory,monkeypatch,path):
    from modules.trust.models import EnvironmentProfile
    from modules.ai_text.protect_ports import load_protected_interfaces
    client,headers,_,_=api_case
    # The shared API fixture installs a fixed GE protection; this case exercises
    # the actual DB-backed dynamic LoopBack protection instead.
    monkeypatch.setattr(router,'load_protected_interfaces',load_protected_interfaces)
    async with test_session_factory() as db:
        topology=Topology(name='explanation-target',topology_type=TopologyType.LAB)
        db.add(topology);await db.flush()
        device=Device(hostname='R3',mgmt_ip='192.0.2.3',device_type=DeviceType.ROUTER,topology_id=topology.id,model='NE40E')
        db.add(device);await db.flush()
        await ready_environment(db,device_id=device.id)
    class Provider:
        model='offline-explanation-guard'
        async def stream_parts(self,*a,**k):
            yield {'kind':'content','text':'只读核对，不改配置。'}
    monkeypatch.setattr(router.SystemService,'build_llm_provider',AsyncMock(return_value=Provider()))
    monkeypatch.setattr(LLMService,'generate_and_validate',AsyncMock(return_value={
        'commands':['display interface LoopBack77'],
        'explanation':'对 LoopBack77 执行 description explanation-bypass。'}))
    payload={'message':'给R3生成接口描述草稿，不执行','want_draft':True,'request_id':uuid.uuid4().hex}
    for _ in range(2):
        response=await client.post('/api/v1/ai/copilot'+path,headers=headers,json=payload)
        assert response.status_code==200 and 'explanation-bypass' not in response.text
        if path=='/chat':
            assert response.json()['draft_refused_reason'] and not response.json()['draft_commands']
        else:
            frames=events(response)
            assert not any(frame['type']=='draft' for frame in frames)
            assert any(frame.get('draft_refused_reason') for frame in frames)
