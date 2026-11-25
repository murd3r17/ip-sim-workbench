import uuid
from unittest.mock import AsyncMock
import pytest
from modules.ai_text import router
from tests.test_c3_request_api import api_case, events


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


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('endpoint', ['https://api.deepseek.com', 'http://127.0.0.1:1'])
async def test_unconfigured_model_without_local_hits_skips_remote_retrieval(api_case, monkeypatch, path, endpoint):
    from core.llm_provider import FallbackProvider, OpenAICompatibleProvider
    from modules.knowledge.service import KnowledgeService

    client, headers, _, retrieval = api_case
    local_search = AsyncMock(return_value=[])
    monkeypatch.setattr(KnowledgeService, 'search_bundled_excerpt', local_search)
    provider = OpenAICompatibleProvider(base_url=endpoint, model='fixture-no-credential')
    provider.api_key = ''
    outbound = AsyncMock(side_effect=AssertionError('no request to an unconfigured model'))
    monkeypatch.setattr(provider, 'stream_parts', outbound)
    monkeypatch.setattr(router.SystemService, 'build_llm_provider', AsyncMock(return_value=FallbackProvider(provider)))
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'message': '查教材解释 STP 的桥 ID，列出证据。', 'request_id': uuid.uuid4().hex})
    if path.endswith('/stream'):
        assert response.status_code == 200
        frames = events(response)
        assert frames[0]['knowledge_status'] == 'not_requested'
        assert frames[-1]['status'] == 'failed' and frames[-1]['reason'] == 'provider_unavailable'
    else:
        assert response.status_code == 503
        assert response.json()['detail']['code'] == 'provider_unavailable'
    local_search.assert_awaited_once()
    retrieval.assert_not_awaited()
    outbound.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('failure,expected', [(False, 'empty'), (True, 'degraded')])
async def test_textbook_only_uses_local_notice_and_never_generates_without_sources(api_case, monkeypatch, path, failure, expected):
    client, headers, provider, _ = api_case
    retrieve = AsyncMock(side_effect=TimeoutError('controlled retrieval interruption')) if failure else AsyncMock(return_value=[])
    monkeypatch.setattr(router, '_retrieve', retrieve)
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'message': '只使用教材说明为什么链路聚合需要考虑哪些端口为成员；若资料没有，请直接告诉我。',
        'request_id': uuid.uuid4().hex, 'context': {'route': '/training'}, 'lab_id': 999999,
    })
    assert response.status_code == 200
    if path.endswith('/stream'):
        frames = events(response)
        assert frames[0]['knowledge_status'] == expected
        assert frames[-1]['status'] == 'degraded'
        refs = next(event for event in frames if event['type'] == 'references')
        answer = ''.join(event.get('text', '') for event in frames if event['type'] == 'token')
        trace = frames[-1]['trace']
    else:
        refs = response.json()
        assert refs['knowledge_status'] == expected and refs['status'] == 'degraded'
        answer = refs['answer']
        trace = refs['trace']
    assert ('知识服务暂不可用' if failure else '本次检索没有找到可引用') in answer
    assert refs['sources'] == [] and refs['generation_status'] == 'not_generated'
    assert trace['model_calls'] == trace['tool_calls'] == provider.calls == 0
    retrieve.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
async def test_textbook_only_with_sources_keeps_direct_support_requirement_in_both_transports(api_case, monkeypatch, path):
    client, headers, provider, retrieval = api_case
    retrieval.return_value = [{'filename': '合成教材.md', 'content': 'STP 的桥 ID 含优先级和 MAC 地址。'}]
    captured = []

    async def stream(prompt, system=None):
        captured.append((prompt, system))
        yield {'kind': 'content', 'text': 'STP 的桥 ID 含优先级和 MAC 地址。[1]'}

    monkeypatch.setattr(provider, 'stream_parts', stream)
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'message': '仅依据教材说明 STP 的桥 ID 有哪些字段。', 'request_id': uuid.uuid4().hex,
    })
    assert response.status_code == 200 and len(captured) == 1
    prompt, system = captured[0]
    assert 'STP 的桥 ID 含优先级和 MAC 地址。' in prompt
    assert '教材原文直接支持，并逐项引用' in system and '不要补充通用知识' in system


@pytest.mark.asyncio
async def test_explicit_permission_for_general_knowledge_keeps_normal_fallback(api_case, monkeypatch):
    client, headers, provider, _ = api_case
    monkeypatch.setattr(router, '_retrieve', AsyncMock(side_effect=TimeoutError))
    response = await client.post('/api/v1/ai/copilot/chat/stream', headers=headers, json={
        'message': '先只用教材，检索失败也可补充通用知识。解释一下 STP 的桥 ID。',
        'request_id': uuid.uuid4().hex,
    })
    assert response.status_code == 200 and provider.calls == 1
    assert events(response)[0]['knowledge_status'] == 'degraded'
