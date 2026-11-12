"""Past tool facts come from owner/scope-matched stored requests, never client claims."""
import json
import uuid
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from modules.ai_text.models import CopilotRequest
from modules.ai_text.request_store import scope
from modules.ai_text.tool_result import EvidenceText
from tests.test_c3_request_api import api_case, events
from tests.test_evaluation_replays import seed


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['ok', 'foreign_owner', 'scope_changed', 'forged_body', 'running', 'missing'])
async def test_history_link_requires_exact_owner_scope_finished_result_and_body(client, test_session_factory, case):
    from modules.ai_text.owned_history import load_owned_history
    async with test_session_factory() as db:
        user, _, _ = await seed(db, 'history-' + case)
        actor = {'user_id':user.id, 'role':'user', 'token_version':0}
        rid = uuid.uuid4().hex
        row = CopilotRequest(user_id=user.id, request_id=rid, input_hash='a'*64,
            authorization_scope=scope(actor), owner_token='owned', status='completed', http_status=200,
            response={'answer':'ORIGINAL_ANSWER', 'trace':{'tools':[{
                'tool':'run_display_command','target':'1','status':'ok','source':'server_observed',
                'mode':'sim','collected_at':'2026-11-05T12:00:00Z','text':'SERVER_R1_OBSERVATION'}]}},
            created_at=datetime.now(), updated_at=datetime.now())
        db.add(row)
        await db.commit()
        linked = {'role':'assistant','content':'ORIGINAL_ANSWER','request_id':rid}
        if case == 'foreign_owner': actor = {**actor,'user_id':user.id+99}
        if case == 'scope_changed': actor = {**actor,'token_version':1}
        if case == 'forged_body': linked['content'] = 'FORGED_ALL_NORMAL'
        if case == 'running': row.status='running';await db.commit()
        if case == 'missing': linked['request_id']=uuid.uuid4().hex
        result = await load_owned_history(db, [linked, dict(linked)], actor)
        if case == 'ok':
            assert len(result.records)==1  # duplicate ID is not another read
            assert result.records[0]['tools'][0]['text']=='SERVER_R1_OBSERVATION'
        else:
            assert not result.records
            assert 'SERVER_R1_OBSERVATION' not in result.as_context()


@pytest.mark.asyncio
async def test_history_budget_omits_whole_old_records_and_never_trusts_plain_client_metadata(client, test_session_factory):
    from modules.ai_text.owned_history import load_owned_history, history_context
    async with test_session_factory() as db:
        user, _, _ = await seed(db, 'history-bounds')
        actor={'user_id':user.id,'role':'user','token_version':0}
        history=[]
        for i in range(7):
            rid=uuid.uuid4().hex;answer=f'ANSWER_{i}'
            db.add(CopilotRequest(user_id=user.id,request_id=rid,input_hash='b'*64,owner_token='owned',
                authorization_scope=scope(actor),status='completed',http_status=200,
                response={'answer':answer,'trace':{'tools':[{'tool':'run_display_command','target':str(i),
                    'status':'ok','text':'x'*6000,'source':'server_observed'} for _ in range(9)]}},
                created_at=datetime.now(),updated_at=datetime.now()))
            history.append({'role':'assistant','content':answer,'request_id':rid})
        await db.commit()
        result=await load_owned_history(db,history,actor)
        assert 0<len(result.records)<=4 and result.omitted_records>0
        assert result.records[-1]['request_id']==history[-1]['request_id']
        assert all(len(row['tools'])<=6 and row['omitted_tools']==3 for row in result.records)
        assert len(json.dumps(result.records,ensure_ascii=False))<=4000
        assert history_context({'records':result.records})==''
        assert '不是本次新采集' in history_context(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat','/chat/stream'])
async def test_both_chat_transports_use_original_request_tools_without_reexecuting(api_case, test_session_factory, monkeypatch, path):
    from modules.ai_text import agent_tools
    from modules.device.models import Device, DeviceType, Topology, TopologyType
    client,headers,provider,_=api_case
    async with test_session_factory() as db:
        topo=Topology(name='history-native-route',topology_type=TopologyType.LAB)
        db.add(topo);await db.flush()
        db.add(Device(hostname='R1',mgmt_ip='192.0.2.1',device_type=DeviceType.ROUTER,topology_id=topo.id))
        await db.commit()
    execute=AsyncMock(return_value=EvidenceText('SERVER_ROUTE_R1_UP',status='ok',target='1',
        source='server_observed',mode='sim',collected_at='2026-11-05T12:00:00Z',completeness='complete'))
    monkeypatch.setattr(agent_tools,'execute_tool',execute)
    captured=[]
    async def stream(prompt,system=None):
        provider.calls+=1;captured.append(prompt)
        yield {'kind':'content','text':'本次只读观察完成。'}
    monkeypatch.setattr(provider,'stream_parts',stream)
    rid=uuid.uuid4().hex
    first=await client.post('/api/v1/ai/copilot/chat/stream',headers=headers,json={
        'request_id':rid,'message':'R1 的接口状态是什么？'})
    assert first.status_code==200 and events(first)[-1]['type']=='done'
    saved=(await client.get('/api/v1/ai/copilot/requests/'+rid,headers=headers)).json()['response']
    reads=execute.await_count
    payload={
        'request_id':uuid.uuid4().hex,'message':'把刚才过程总结一下。',
        'history':[{'role':'user','content':'R1 的接口状态是什么？'},
                   {'role':'assistant','content':saved['answer'],'request_id':rid}]}
    reply=await client.post('/api/v1/ai/copilot'+path,headers=headers,json=payload)
    assert reply.status_code==200,reply.text
    assert execute.await_count==reads
    assert 'SERVER_ROUTE_R1_UP' in captured[-1] and '历史请求1' in captured[-1]
    assert rid not in captured[-1]  # real links remain in request store, not model prose
    persisted=(await client.get('/api/v1/ai/copilot/requests/'+rid,headers=headers)).json()['response']
    assert persisted==saved and persisted['trace']['tools']
    assert '服务端历史请求取证' in captured[-1]
    calls=provider.calls
    replay=await client.post('/api/v1/ai/copilot'+path,headers=headers,json=payload)
    assert replay.status_code==200 and provider.calls==calls and execute.await_count==reads


@pytest.mark.asyncio
async def test_cancel_during_history_read_finishes_without_a_model_or_tool(api_case,monkeypatch):
    from modules.ai_text import owned_history
    client,headers,provider,_=api_case
    ready=asyncio.Event()
    async def held(*args):
        ready.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(owned_history,'load_owned_history',held)
    rid=uuid.uuid4().hex
    pending=asyncio.create_task(client.post('/api/v1/ai/copilot/chat/stream',headers=headers,json={
        'request_id':rid,'message':'把刚才过程总结一下。',
        'history':[{'role':'user','content':'只读查看R1接口'}]}))
    try:
        await asyncio.wait_for(ready.wait(),5)
        cancel=await client.post('/api/v1/ai/copilot/requests/'+rid+'/cancel',headers=headers)
        assert cancel.status_code==200
        response=await asyncio.wait_for(pending,5)
        assert response.status_code==200 and events(response)[-1].get('cancelled') is True
        assert provider.calls==0
    finally:
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending,return_exceptions=True)


def test_only_server_resolved_page_records_can_be_linked_to_history():
    from modules.ai_text.owned_history import history_page_evidence_id
    from modules.ai_text.trusted_context import TrustedPageData
    assert history_page_evidence_id({'evidence_id':7,'trusted':True}) is None
    assert history_page_evidence_id(TrustedPageData('{}',{'evidence_id':7,'trusted':False})) is None
    page=TrustedPageData('{}',{'evidence_id':7,'trusted':False,'record_origin':'server_observation_record'})
    assert history_page_evidence_id(page)==7  # original record may be stale, still historical only


@pytest.mark.asyncio
@pytest.mark.parametrize('allowed',[True,False])
async def test_page_observation_is_separate_from_new_tool_reads_and_rechecks_access(client,test_session_factory,allowed):
    from modules.ai_text.owned_history import load_owned_history
    from modules.trust.models import ReadOnlyObservation
    async with test_session_factory() as db:
        user,device,_=await seed(db,'history-page-'+str(allowed))
        actor={'user_id':user.id,'role':'user','token_version':0}
        observation=ReadOnlyObservation(device_id=device.id,source='server_observed',mode='sim',adapter_mode='sim',
            action_id='interface_brief',command='display ip interface brief',status='ok',completeness='complete',
            created_by=user.id if allowed else None, facts={'interfaces':[{'name':'GE0/0/1','state':'up'}]},
            raw_excerpt='ORIGINAL_PAGE_OBSERVATION')
        db.add(observation);await db.flush()
        rid=uuid.uuid4().hex
        db.add(CopilotRequest(user_id=user.id,request_id=rid,input_hash='c'*64,owner_token='owned',
            authorization_scope=scope(actor),status='completed',http_status=200,
            response={'answer':'原页面观察解释','trace':{'tools':[],'page_evidence_id':observation.id}},
            created_at=datetime.now(),updated_at=datetime.now()))
        await db.commit()
        result=await load_owned_history(db,[{'role':'assistant','content':'原页面观察解释','request_id':rid}],actor)
        assert result.records[0]['tool_records']==0
        page=result.records[0]['page_observation']
        if allowed:
            assert page['evidence_id']==observation.id and page['device']=='R1'
            assert 'GE0/0/1' in page['summary'] and page['historical_only'] is True
        else:
            assert page is None and 'GE0/0/1' not in result.as_context()
