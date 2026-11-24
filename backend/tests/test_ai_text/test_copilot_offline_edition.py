"""Typed textbook locators remain useful even when model generation cannot run."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest

from modules.ai_text import router
from modules.knowledge.service import KnowledgeService
from tests.test_c3_request_api import api_case, events


QUESTION = '只依据教材说明 STP 的桥 ID 是怎样构成的。'
MATCH = {'document_id': 'edition:stp', 'document_version': 'current-version', 'edition_version': 'frozen-edition',
         'section_id': 'physical-page-7', 'filename': 'stp-textbook.md', 'title': '生成树', 'book_title': 'STP 教材',
         'page': 7, 'text': '桥 ID 以优先级作为其中一个字段。'}


def configured_edition(monkeypatch):
    edition = SimpleNamespace(version='frozen-edition', search_scope=lambda query: ('', [], None, None, ()),
        read=Mock(return_value={'original_pages': [
        {'physical': 7, 'section_id': 'physical-page-7', 'evidence_eligible': True},
        {'physical': 8, 'section_id': 'physical-page-8', 'evidence_eligible': False},
    ]}))
    service = object.__new__(KnowledgeService)
    monkeypatch.setattr(service, 'edition', lambda: edition)
    monkeypatch.setattr(service, 'list_documents', AsyncMock(side_effect=AssertionError('No external source read')))
    monkeypatch.setattr(router, '_get_knowledge_service', lambda: service)
    return edition


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('failure', ['initialization', 'connection', 'locator', 'concepts', 'explicit_lookup'])
async def test_local_edition_sources_are_clickable_recoverable_and_not_called_generated(api_case, monkeypatch, path, failure):
    client, headers, provider, retrieval = api_case
    edition = configured_edition(monkeypatch)
    retrieval.return_value = [
        {**MATCH, 'edition_version': 'old-version', 'text': 'OLD_EDITION'}, MATCH,
        {**MATCH, 'page': 8, 'section_id': 'physical-page-8', 'text': 'FORBIDDEN_PAGE'},
    ]
    create = AsyncMock(return_value=provider)
    if failure in {'initialization', 'concepts', 'explicit_lookup'}:
        create.side_effect = RuntimeError('private-setting-value')
    monkeypatch.setattr(router.SystemService, 'build_llm_provider', create)

    async def disconnected(*args, **kwargs):
        provider.calls += 1
        yield {'kind': 'content', 'text': 'MODEL_UNFINISHED [1]。'}
        raise httpx.ConnectError('private-provider-detail')

    monkeypatch.setattr(provider, 'stream_parts', disconnected)
    request_id = uuid4().hex
    message = '在教材里查 STP 桥 ID，只要出处和物理页，不需要归纳。' if failure == 'locator' else QUESTION
    if failure == 'concepts':
        message = '只讲原理，解释 STP 如何确定根桥。'
    elif failure == 'explicit_lookup':
        message = '查教材解释 STP 的桥 ID，列出证据。'
    body = {'message': message, 'request_id': request_id, 'context': {'route': '/knowledge'}}
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json=body)
    assert response.status_code == 200
    expected_status = 'ok' if failure == 'locator' else 'failed'
    if path == '/chat/stream':
        frames = events(response)
        assert frames[0]['knowledge_status'] == 'ok' and frames[-1]['status'] == expected_status
        refs = next(frame for frame in frames if frame['type'] == 'references')
        if failure != 'locator':
            assert frames[-1]['reason'] == 'provider_unavailable'
            assert frames.index(refs) < next(index for index, frame in enumerate(frames) if frame.get('code') == 'provider_unavailable')
        if failure == 'connection':
            assert any(frame.get('retrieval_only') and '检索到的教材' in frame['replace_answer'] for frame in frames)
    else:
        refs = response.json()
    assert refs['generation_status'] == 'retrieval_only' and len(refs['sources']) == 1
    assert refs['sources'][0]['page'] == 7 and 'prompt_text' not in refs['sources'][0]
    assert all(value not in response.text for value in ('OLD_EDITION', 'FORBIDDEN_PAGE', 'private-provider-detail', 'private-setting-value'))

    recovery = await client.get(f'/api/v1/ai/copilot/requests/{request_id}', headers=headers)
    assert recovery.status_code == 200 and recovery.json()['state'] == ('completed' if failure == 'locator' else 'failed')
    saved = recovery.json()['response']
    assert saved['generation_status'] == 'retrieval_only' and saved['sources'] == refs['sources']
    assert saved['trace']['tool_dispatch_attempts'] == 0 and saved['trace']['model_calls'] == int(failure == 'connection')
    assert '[1] STP 教材 · PDF 物理第 7 页' in saved['answer'] and '阅读同版正文' in saved['answer']
    assert 'MODEL_UNFINISHED' not in saved['answer']
    if failure != 'locator':
        assert saved['trace']['provider_error'] == 'provider_unavailable' and '未完成对教材的归纳' in saved['answer']
    else:
        create.assert_not_awaited()

    replay = await client.post('/api/v1/ai/copilot/chat/stream', headers=headers, json=body)
    replayed = events(replay)
    assert replayed[0]['replayed'] and next(frame for frame in replayed if frame['type'] == 'references')['generation_status'] == 'retrieval_only'
    if failure != 'locator':
        assert replayed[-1]['reason'] == 'provider_unavailable'
    retrieval.assert_awaited_once()
    source = saved['sources'][0]
    locator = {'filename': source['filename'], 'request_id': request_id, 'source_id': source['source_id']}
    excerpt = await client.get('/api/v1/ai/copilot/citations/read', params=locator, headers=headers)
    assert excerpt.status_code == 200 and excerpt.json()['scope'] == 'retrieval_excerpt'
    assert excerpt.json()['document_version'] == MATCH['document_version'] and excerpt.json()['page'] == 7
    edition.version = 'new-edition'
    revoked = await client.get('/api/v1/ai/copilot/citations/read', params=locator, headers=headers)
    assert revoked.status_code == 410


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('message,extra', [
    ('查教材原理，同时归纳这份工单的现场结论。', {}),
    ('查教材中的 OSPF 原理，并请现在读取设备 R7 的邻居状态。', {}),
    (QUESTION, {'attachments': [{'name': 'notes.txt', 'mime': 'text/plain', 'contentString': 'provided notes'}]}),
    (QUESTION, {'want_draft': True}),
    ('查教材中的 STP 原理，然后编写可执行配置下发到 R7。', {}),
    ('你好，聊两句。', {}),
])
async def test_provider_absence_does_not_start_offline_search_for_mixed_tasks(api_case, monkeypatch, path, message, extra):
    client, headers, _, retrieval = api_case
    configured_edition(monkeypatch)
    retrieval.return_value = [MATCH]
    monkeypatch.setattr(router.SystemService, 'build_llm_provider', AsyncMock(side_effect=RuntimeError('not configured')))
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'message': message, 'request_id': uuid4().hex, **extra})
    retrieval.assert_not_awaited()
    assert 'retrieval_only' not in response.text and MATCH['filename'] not in response.text
