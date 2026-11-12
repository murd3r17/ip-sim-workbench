import uuid
from unittest.mock import AsyncMock
import pytest
from modules.ai_text import router
from tests.test_c3_request_api import api_case


@pytest.mark.asyncio
@pytest.mark.parametrize('path',['/chat','/chat/stream'])
async def test_actual_retrieval_failure_is_distinct_from_no_hits_in_generation(api_case,monkeypatch,path):
    client,headers,provider,_=api_case;prompts=[]
    monkeypatch.setattr(router,'_retrieve',AsyncMock(side_effect=ConnectionError('controlled unavailable')))
    async def stream(prompt,system=None):
        provider.calls+=1;prompts.append(prompt)
        yield {'kind':'content','text':'本次知识检索失败，可以先一般解释。'}
    monkeypatch.setattr(provider,'stream_parts',stream)
    response=await client.post('/api/v1/ai/copilot'+path,headers=headers,json={
        'message':'知识库现在能用吗？帮我查个概念。','request_id':uuid.uuid4().hex})
    assert response.status_code==200
    assert len(prompts)==1 and '知识服务调用失败' in prompts[0] and '不是未命中' in prompts[0]
