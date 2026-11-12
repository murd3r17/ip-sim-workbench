"""Retrieval outcome is independent of generation success and survives replay."""
import uuid
from unittest.mock import AsyncMock
import pytest
from modules.ai_text import router
from tests.test_c3_request_api import api_case, events
ORIGINAL_RETRIEVE = router._retrieve


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('case,expected', [('skipped', 'not_requested'), ('empty', 'empty'), ('error', 'degraded'), ('hits', 'ok')])
async def test_retrieval_state_in_original_and_cross_transport_recovery(api_case, monkeypatch, path, case, expected):
    client, headers, provider, _ = api_case
    retrieval = AsyncMock(side_effect=RuntimeError('offline fixture failure')) if case == 'error' else AsyncMock(return_value=(
        [{'filename': 'ospf.md', 'text': 'OSPF 使用链路状态信息。'}] if case == 'hits' else []))
    monkeypatch.setattr(router, '_retrieve', retrieval)
    body = {'message': '这个设备页面怎么用？' if case == 'skipped' else 'OSPF 是什么？', 'request_id': uuid.uuid4().hex}
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json=body)
    assert response.status_code == 200
    meta = response.json() if path == '/chat' else events(response)[0]
    assert meta['knowledge_status'] == expected
    if case == 'skipped': retrieval.assert_not_awaited()
    else: retrieval.assert_awaited_once()
    calls = provider.calls
    recovery_path = '/chat/stream' if path == '/chat' else '/chat'
    recovered = await client.post('/api/v1/ai/copilot' + recovery_path, headers=headers, json=body)
    assert recovered.status_code == 200
    recovered_meta = recovered.json() if recovery_path == '/chat' else events(recovered)[0]
    assert recovered_meta['knowledge_status'] == expected
    assert recovered_meta['replayed'] is True and provider.calls == calls


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
async def test_real_retrieval_adapter_preserves_provider_failure(api_case, monkeypatch, path):
    client, headers, _, _ = api_case
    monkeypatch.setattr(router, '_retrieve', ORIGINAL_RETRIEVE)
    monkeypatch.setattr(router, 'cached_search', AsyncMock(side_effect=ConnectionRefusedError('fixture')))
    monkeypatch.delenv('AI_DUAL_RETRIEVAL', raising=False)
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'message': 'OSPF 是什么？', 'request_id': uuid.uuid4().hex})
    assert response.status_code == 200
    meta = response.json() if path == '/chat' else events(response)[0]
    assert meta['knowledge_status'] == 'degraded'


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
async def test_empty_model_answer_is_not_mislabelled_as_a_missing_corpus(api_case, monkeypatch, path):
    client, headers, provider, _ = api_case
    async def empty(*args, **kwargs):
        return
        yield
    monkeypatch.setattr(provider, 'stream_parts', empty)
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'message': '这个设备页面怎么用？', 'request_id': uuid.uuid4().hex})
    assert response.status_code == 200
    result = response.json() if path == '/chat' else events(response)[-1]
    assert result['status'] == 'failed'
    assert '未命中' not in response.text and '知识库管理' not in response.text
