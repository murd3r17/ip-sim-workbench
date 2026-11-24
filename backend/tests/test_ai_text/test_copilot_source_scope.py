"""The model and saved citations use the same bounded textbook excerpts."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest

from core.llm_provider import OpenAICompatibleProvider
from modules.ai_text import router
from modules.ai_text.context_bundle import prepare_sources
from modules.ai_text.source_scope import prepare_scoped_sources
from modules.knowledge.query_focus import lookup_parts
from modules.knowledge.service import KnowledgeService
from tests.test_c3_request_api import api_case, events


BOOK = '公开的路由选择实验'
DOC = 'reviewed-lesson'
FILENAME = 'public-route-selection.md'
VERSION = 'current-sha'
EDITION = 'signed-lesson-edition'
QUESTION = f'只讲原理。仅依据教材《{BOOK}》PDF 第 71 页和第 73 页，分别解释边界代价和恢复窗口。'
SUPPORT = '边界代价为 25，只有路由可用时才比较代价。'
POINTER = '第 77–78 页有后续状态和原始命令的读回实例。'
SAME_SCOPE = '第 73 页给出恢复观察的示例。'
FENCE = '```text\n第 79 页有原始样例。\n```'


def hit(page, text, *, document_id=DOC, edition=EDITION, version=VERSION):
    return {'document_id': document_id, 'document_version': version, 'edition_version': edition,
            'section_id': f'physical-{page}', 'filename': FILENAME, 'title': BOOK, 'book_title': BOOK,
            'page': page, 'text': f'### PDF 第 {page} 页\n\n{text}'}


@pytest.fixture
def edition():
    def scope(question):
        return '', [], {DOC} if BOOK in question else None, lookup_parts(question)[2], lookup_parts(question)[1]

    return SimpleNamespace(version=EDITION, search_scope=scope, documents={
        DOC: {'sha256': VERSION, 'book': 11, 'page_start': 66, 'page_end': 75},
        'other-lesson': {'sha256': VERSION, 'book': 11, 'page_start': 76, 'page_end': 89},
    })


def test_explicit_range_removes_only_whole_outside_navigation_sentences(edition):
    text = SUPPORT + SAME_SCOPE + POINTER + '\n\n' + FENCE
    selected, notice = prepare_scoped_sources(QUESTION, [hit(71, text), hit(73, '恢复后先等待窗口结束。')], 6, edition, '')
    assert [item['page'] for item in selected] == [71, 73] and not notice
    assert selected[0]['truncated']
    assert all(value in selected[0]['content'] for value in (SUPPORT, SAME_SCOPE, FENCE))
    assert POINTER not in selected[0]['content'] and POINTER not in selected[0]['prompt_text']
    assert selected[1]['content'] == prepare_sources([hit(73, '恢复后先等待窗口结束。')])[0]['content']


def test_contiguous_physical_range_does_not_demand_an_excerpt_on_every_page(edition):
    question = f'只查教材《{BOOK}》PDF 第 71 页至第 73 页，解释边界代价。'
    selected, notice = prepare_scoped_sources(question, [hit(71, SUPPORT + POINTER), hit(77, '范围外的例子。')], 6, edition, '')
    assert [item['page'] for item in selected] == [71]
    assert not notice and POINTER not in selected[0]['content'] and SUPPORT in selected[0]['content']


@pytest.mark.parametrize('question', [
    '这章节的代价是怎样比较的？',
    '依据教材《公开的路由选择实验》印刷第 71 页解释路由。',
    '依据教材《公开的路由选择实验》PDF 第 71 页，哪一页还有读回实例？',
    '查教材《公开的路由选择实验》PDF 第 71 页的原句“第 77–78 页有后续状态和原始命令的读回实例”',
])
def test_concepts_ambiguous_pages_and_navigation_keep_original_excerpts(edition, question):
    base = hit(71, SUPPORT + POINTER)
    scoped, notice = prepare_scoped_sources(question, [base], 6, edition, '')
    assert not notice and len(scoped) == 1 and POINTER in scoped[0]['prompt_text']


def test_only_the_reopened_chapter_sets_scope_for_continuation(edition):
    rows = [hit(71, SUPPORT + SAME_SCOPE + POINTER), hit(79, '另一个实验的状态。', document_id='other-lesson')]
    chapter, notice = prepare_scoped_sources('继续沿用刚才同一章，解释这个阶段是什么。', rows, 6, edition, 'chapter')
    assert not notice and [row['page'] for row in chapter] == [71]
    assert SAME_SCOPE in chapter[0]['content'] and POINTER not in chapter[0]['content']
    page, notice = prepare_scoped_sources('继续只用刚才同一页，解释这个阶段。', rows, 6, edition, 'page')
    assert not notice and SAME_SCOPE not in page[0]['content'] and POINTER not in page[0]['content']


def use_frozen_reader(monkeypatch, edition, pages):
    rows = [hit(71, SUPPORT + POINTER), hit(73, '恢复后先等待窗口结束。')]
    content = '\n\n'.join(row['text'] for row in rows)
    sections = [{'level': 3, 'title': f'PDF 第 {row["page"]} 页', 'id': row['section_id'],
                 'line': content[:content.index(row['text'])].count('\n') + 1} for row in rows]
    edition.documents[DOC]['ingest'] = True
    edition.read = Mock(return_value={'content': content, 'sections': sections, 'original_pages': [
        {'physical': row['page'], 'section_id': row['section_id'], 'evidence_eligible': row['page'] in pages}
        for row in rows
    ]})
    edition._bound_hit = lambda context, record, text, section, page: hit(page, '') | {'text': text}
    service = object.__new__(KnowledgeService)
    monkeypatch.setattr(service, 'edition', lambda: edition)
    monkeypatch.setattr(router, '_get_knowledge_service', lambda: service)
    return rows


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('pages', [(71, 73), (71,), ()])
async def test_absent_model_and_connection_failure_preserve_the_same_verified_sources(api_case, edition, monkeypatch, path, pages):
    client, headers, provider, retrieval = api_case
    retrieval.return_value = use_frozen_reader(monkeypatch, edition, pages)
    unconfigured = object.__new__(OpenAICompatibleProvider)
    unconfigured.base_url = 'http://127.0.0.1:1'

    async def connection_failure(prompt, system=None):
        provider.calls += 1
        assert POINTER not in prompt
        yield {'kind': 'content', 'text': 'UNFINISHED_MODEL_OUTPUT [1]。'}
        raise httpx.ConnectError('private fixture failure')

    monkeypatch.setattr(provider, 'stream_parts', connection_failure)
    versions = []
    for configured in (False, True):
        monkeypatch.setattr(router.SystemService, 'build_llm_provider', AsyncMock(return_value=provider if configured else unconfigured))
        request_id = uuid4().hex
        response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
            'request_id': request_id, 'message': QUESTION, 'context': {'route': '/knowledge'},
        })
        assert response.status_code == 200
        recovery = (await client.get('/api/v1/ai/copilot/requests/' + request_id, headers=headers)).json()
        saved = recovery['response']
        assert recovery['state'] == 'failed' and saved['status'] == 'failed'
        assert saved['knowledge_status'] == ('ok' if pages else 'empty')
        assert saved['generation_status'] == ('retrieval_only' if pages else 'not_generated')
        assert saved['trace']['provider_error'] == 'provider_unavailable'
        assert saved['trace']['model_calls'] == int(configured) and saved['trace']['tool_dispatch_attempts'] == 0
        assert '模型服务暂不可用' in saved['answer'] and 'UNFINISHED_MODEL_OUTPUT' not in saved['answer']
        assert ('检索到的教材' in saved['answer']) == bool(pages)
        missing = '、'.join(str(page) for page in (71, 73) if page not in pages)
        if missing:
            assert f'物理页（{missing}）' in saved['answer']
        else:
            assert '未核对到所选同版 PDF 物理页' not in saved['answer']
        if path == '/chat/stream':
            frames = events(response)
            assert frames[-1]['reason'] == 'provider_unavailable'
            assert next(frame for frame in frames if frame['type'] == 'references')['sources'] == saved['sources']
        for source in saved['sources']:
            assert POINTER not in source['content']
            if source['page'] == 71:
                assert SUPPORT in source['content']
            excerpt = await client.get('/api/v1/ai/copilot/citations/read', headers=headers, params={
                'request_id': request_id, 'source_id': source['source_id'], 'filename': source['filename'],
            })
            assert excerpt.status_code == 200 and excerpt.json()['scope'] == 'retrieval_excerpt'
            assert excerpt.json()['content'] == source['content']
        assert [source['page'] for source in saved['sources']] == list(pages)
        versions.append((saved['answer'], [source['prompt_sha256'] for source in saved['sources']]))
    assert versions[0] == versions[1]


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('pages', [(71, 73), (71,), ()])
async def test_locator_keeps_same_edition_reading_material_without_a_model(api_case, edition, monkeypatch, path, pages):
    client, headers, provider, retrieval = api_case
    raw = use_frozen_reader(monkeypatch, edition, pages)
    retrieval.return_value = raw if pages else []
    create = AsyncMock(side_effect=AssertionError('Source location requires no model'))
    monkeypatch.setattr(router.SystemService, 'build_llm_provider', create)
    request_id = uuid4().hex
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'request_id': request_id, 'context': {'route': '/knowledge'},
        'message': f'只要教材《{BOOK}》PDF 第 71 页和第 73 页的原页出处，不需要归纳。'
    })
    assert response.status_code == 200
    saved = (await client.get('/api/v1/ai/copilot/requests/' + request_id, headers=headers)).json()['response']
    assert saved['status'] == ('ok' if pages else 'degraded')
    assert saved['knowledge_status'] == ('ok' if pages else 'empty')
    assert [source['page'] for source in saved['sources']] == list(pages)
    if pages:
        assert POINTER in saved['sources'][0]['content'] and '阅读同版正文' in saved['answer']
        retrieval.assert_not_awaited()
    else:
        assert '物理页（71、73）' in saved['answer'] and '检索到的教材' not in saved['answer']
    create.assert_not_awaited()
    assert provider.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('scenario', ['both', 'partial', 'unavailable'])
async def test_exact_pages_govern_product_prompt_and_saved_references(api_case, edition, monkeypatch, path, scenario):
    client, headers, provider, retrieval = api_case
    retrieved = [hit(72, 'OUTSIDE_SAME_DOCUMENT'), hit(73, 'OTHER_EXPERIMENT', document_id='other-lesson'),
                 hit(73, 'STALE_EDIT', edition='old')]
    if scenario != 'unavailable':
        retrieved.append(hit(71, SUPPORT + POINTER))
    if scenario == 'both':
        retrieved.append(hit(73, '恢复后先等待窗口结束。'))
    retrieval.return_value = retrieved
    knowledge = object.__new__(KnowledgeService)
    monkeypatch.setattr(knowledge, 'edition', lambda: edition)
    monkeypatch.setattr(knowledge, 'legacy_locator', AsyncMock(return_value={}))
    monkeypatch.setattr(knowledge, 'list_documents', AsyncMock(return_value=[{'id': DOC, 'filename': FILENAME}]))
    monkeypatch.setattr(router, '_get_knowledge_service', lambda: knowledge)
    seen_prompts = []

    async def generate(prompt, system=None):
        provider.calls += 1
        seen_prompts.append(prompt)
        yield {'kind': 'content', 'text': '代价见[1]。' + ('恢复窗口见[2]。' if scenario == 'both' else '')}

    monkeypatch.setattr(provider, 'stream_parts', generate)
    request_id = uuid4().hex
    reply = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'request_id': request_id, 'message': QUESTION, 'context': {'route': '/knowledge'},
    })
    assert reply.status_code == 200
    saved = (await client.get('/api/v1/ai/copilot/requests/' + request_id, headers=headers)).json()['response']
    references = (reply.json()['sources'] if path == '/chat' else
                  next(frame['sources'] for frame in events(reply) if frame['type'] == 'references'))
    assert references == saved['sources']
    assert [item['page'] for item in references] == {'both': [71, 73], 'partial': [71], 'unavailable': []}[scenario]
    assert provider.calls == int(scenario != 'unavailable')
    assert saved['trace']['tool_calls'] == 0
    assert ('未核对到所选同版 PDF 物理页（73）' in saved['answer']) == (scenario == 'partial')
    if scenario == 'unavailable':
        assert '物理页（71、73）' in saved['answer'] and saved['status'] == 'degraded'
    else:
        prompt, = seen_prompts
        assert ('缺失页不写入出处' in prompt) == (scenario == 'partial')
        assert all(missing not in prompt for missing in (POINTER, 'OUTSIDE_SAME_DOCUMENT', 'OTHER_EXPERIMENT', 'STALE_EDIT'))
        for number, source in enumerate(references, 1):
            excerpt = await client.get('/api/v1/ai/copilot/citations/read', headers=headers, params={
                'request_id': request_id, 'source_id': source['source_id'], 'filename': source['filename'],
            })
            assert excerpt.status_code == 200
            citation = excerpt.json()
            assert citation['scope'] == 'answer_excerpt' and citation['content'] == source['content']
            assert citation['page'] == source['page'] and citation['document_version'] == VERSION
            assert f'来源[{number}]' in prompt and citation['content'] in prompt
