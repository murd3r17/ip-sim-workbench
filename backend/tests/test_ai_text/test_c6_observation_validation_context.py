import json,uuid
from unittest.mock import AsyncMock

import pytest
from modules.ai_text import router
from modules.ai_text.skills import select_skill
from modules.ai_text.trusted_context import TrustedPageData
from tests.test_c3_request_api import api_case,events


@pytest.mark.parametrize('trusted',[False,True])
def test_snapshot_source_question_is_not_a_textbook_or_fresh_read_task(trusted):
    choice=select_skill('这个接口数据是真实设备还是模拟的？',route='/devices',
        page_data='{}',page_data_trusted=trusted)
    assert choice.id=='live_evidence' and not choice.needs_knowledge and not choice.tools


@pytest.mark.asyncio
@pytest.mark.parametrize('reason,needed',[('stale','证据已过期'),('mode_unknown','采集模式缺失或未知'),
                                         ('environment_version_drift','环境版本已变化')])
async def test_final_answer_keeps_actual_server_rejection_reason(api_case,monkeypatch,reason,needed):
    client,headers,provider,_=api_case;captured=[]
    page=TrustedPageData('{"device":"R2","mode":"sim"}',{'trusted':False,'reasons':[reason],'evidence_id':7})
    monkeypatch.setattr(router,'_resolve_page_data',AsyncMock(return_value=page))
    async def stream(prompt,system=None):
        provider.calls+=1;captured.append(prompt)
        yield {'kind':'content','text':'没有当前观察，不作状态结论。'}
    monkeypatch.setattr(provider,'stream_parts',stream)
    response=await client.post('/api/v1/ai/copilot/chat/stream',headers=headers,json={
        'message':'按刚才的采集，R2 的接口状态怎么样？','request_id':uuid.uuid4().hex,
        'context':{'route':'/devices','selection':'device | R2 | id=2'},'page_data':'{"evidence_id":7}'})
    assert response.status_code==200 and events(response)[-1]['type']=='done'
    assert captured and needed in captured[-1]


@pytest.mark.asyncio
async def test_evidence_id_without_text_keeps_server_validation_result(monkeypatch):
    from modules.ai_text.schemas import CopilotChatRequest
    monkeypatch.setattr(router,'load_verified_evidence',AsyncMock(return_value=TrustedPageData('{}',{
        'trusted':False,'reasons':['environment_version_drift'],'evidence_id':7})))
    data=CopilotChatRequest(message='读取',page_data='{"evidence_id":7}',context={'route':'/devices'})
    page=await router._resolve_page_data(object(),data,{'user_id':1,'role':'user'})
    assert page.meta['reasons']==['environment_version_drift']
