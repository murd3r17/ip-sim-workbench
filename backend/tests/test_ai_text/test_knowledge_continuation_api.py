"""Fresh textbook references after a page change, using the product request endpoints."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from core.security import decode_access_token
from modules.ai_text import router
from modules.ai_text.models import CopilotConversation, CopilotRequest
from modules.ai_text.request_store import digest
from modules.ai_text.schemas import CopilotChatRequest
from modules.knowledge.query_focus import lookup_parts
from modules.knowledge.service import KnowledgeService
from tests.test_c3_request_api import api_case, events
from tests.test_copilot_session_idor import _make_user, auth_header


FOLLOWUP = '切到工作台了。继续刚才那条教材引用，同一个要点再解释一下，带上本轮出处。'
SENTINEL = 'CLIENT_AND_OLD_ANSWER_NOT_EVIDENCE'


class MiniEdition:
    version = 'test-edition'
    documents = {'synthetic-chapter': {'id': 'synthetic-chapter', 'sha256': 'chapter-v1', 'ingest': True,
                                       'book': 1, 'title': '蓝色端口复核实验', 'page_start': 21, 'page_end': 24},
                 'other-chapter': {'id': 'other-chapter', 'sha256': 'other-v1', 'ingest': True,
                                   'book': 2, 'title': '橙色端口复核实验', 'page_start': 20, 'page_end': 25}}

    def __init__(self):
        self.reads = []
        self.keyword_index = SimpleNamespace(search_pages=AsyncMock(return_value=(True, [self.hit('other-chapter', 21)])))

    def has_search_scope(self, question):
        return False

    def search_scope(self, question):
        title, phrases, pages, remainder = lookup_parts(question)
        named = {'Synthetic manual', '受限原图权限公开教材'}
        doc_ids = {'synthetic-chapter'} if named.intersection(title) else None
        return remainder, [], doc_ids, pages, phrases

    def hit(self, doc, page, text=None):
        return {'title': f'{doc}.md', 'document_id': doc, 'document_version': self.documents[doc]['sha256'],
                'edition_version': self.version, 'section_id': f'p{page}', 'book_title': 'Synthetic manual',
                'page': page, 'text': text or f'### PDF 第 {page} 页\n\n当前受控教材正文 {doc} 的页位 {page}。'}

    def read(self, doc, version, *, include_original_status=False):
        self.reads.append((doc, version))
        assert self.documents[doc]['sha256'] == version
        return {'content': '### PDF 第 21 页\n\n当前独立页 21 的帧选择说明。\n### PDF 第 24 页\n\n当前独立页 24 的端口练习。',
                'sections': [{'id': 'p21', 'line': 1, 'level': 3, 'title': 'PDF 第 21 页'},
                             {'id': 'p24', 'line': 4, 'level': 3, 'title': 'PDF 第 24 页'}],
                'original_pages': [{'physical': page, 'section_id': f'p{page}', 'evidence_eligible': True}
                                   for page in (21, 24)]}

    def _bound_hit(self, extra, record, text, section, page):
        return {**self.hit(record['id'], page, text), **extra}

    def resolve_hits(self, hits, *_args, **_kwargs):
        return hits


async def conversation(factory, headers, id_=None):
    owner = int(decode_access_token(headers['Authorization'][7:])['sub'])
    id_ = id_ or uuid4().hex
    async with factory() as db:
        db.add(CopilotConversation(id=id_, user_id=owner, title='Local synthetic conversation', messages=[]))
        await db.commit()
    return id_


def complete_with_fixture(provider, monkeypatch, edition, *, references=('[1]',)):
    prompts = []
    async def stream(prompt, system=None):
        prompts.append(prompt)
        yield {'kind': 'content', 'text': '合成夹具答复。' + (SENTINEL + ' '.join(references) if len(prompts) == 1 else '[1]')}
    monkeypatch.setattr(provider, 'stream_parts', stream)
    service = object.__new__(KnowledgeService)
    monkeypatch.setattr(service, 'edition', lambda: edition)
    monkeypatch.setattr(router, '_get_knowledge_service', lambda: service)
    return prompts


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('case', ['visible_page', 'stale_version', 'different_title', 'unrelated_question', 'explicit_page'])
async def test_open_reading_page_bounds_only_intended_followup(api_case, test_session_factory, monkeypatch, path, case):
    client, headers, provider, retrieval = api_case
    edition = MiniEdition()
    prompts = complete_with_fixture(provider, monkeypatch, edition)
    session = await conversation(test_session_factory, headers)
    page = {'kind': 'original_page', 'document_id': 'synthetic-chapter', 'version': 'chapter-v1', 'page': 24}
    question = '我在目录打开了蓝色端口复核实验。这个实验的端口记录是什么？'
    retrieval.return_value = [edition.hit('other-chapter', 21, 'GLOBAL_WRONG_CASE')]
    if case == 'stale_version':
        page['version'] = 'old-version'
    elif case == 'different_title':
        question = '我在目录打开了橙色端口复核实验。这个实验的端口记录是什么？'
    elif case == 'unrelated_question':
        question = '教材里的生成树帧选择机制是什么？'
    elif case == 'explicit_page':
        question = '只依据《Synthetic manual》PDF 第 21 页解释帧选择。'
        retrieval.return_value = [edition.hit('synthetic-chapter', 21)]
    _, answer = await ask(client, headers, path, session, question, page_record=page, route='/knowledge')
    if case == 'visible_page':
        assert answer['trace']['source_continuity'] == 'page'
        assert [(s['document_id'], s['page']) for s in answer['sources']] == [('synthetic-chapter', 24)]
        assert len(prompts) == 1 and '当前独立页 24' in prompts[0] and 'GLOBAL_WRONG_CASE' not in prompts[0]
        retrieval.assert_not_awaited()
    elif case == 'stale_version':
        assert answer['trace']['source_continuity'] == 'unavailable' and not answer['sources'] and not prompts
        retrieval.assert_not_awaited()
    else:
        retrieval.assert_awaited_once()
        assert '当前独立页 24' not in prompts[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('case', ['selected', 'stale', 'manual_first', 'manual_other_page'])
async def test_guided_question_rechecks_the_reader_version_without_changing_independent_lookup(
    api_case, test_session_factory, monkeypatch, path, case
):
    client, headers, provider, retrieval = api_case
    edition = MiniEdition()
    prompts = complete_with_fixture(provider, monkeypatch, edition)
    session = await conversation(test_session_factory, headers)
    requested_page = 21 if case == 'manual_other_page' else 24
    question = (f'请只根据本地教材《Synthetic manual》PDF 第 {requested_page} 页回答。'
                '本页没有依据的内容请指出。\n\n这份教材观察显示什么？')
    page = None if case == 'manual_first' else {
        'kind': 'original_page', 'document_id': 'synthetic-chapter',
        'version': 'old-edition' if case == 'stale' else 'chapter-v1', 'page': 24,
    }
    retrieval.return_value = [edition.hit('synthetic-chapter', requested_page)]
    _, answer = await ask(client, headers, path, session, question, page_record=page, route='/knowledge')
    if case == 'stale':
        assert answer['trace']['source_continuity'] == 'unavailable'
        assert not answer['sources'] and not prompts
        retrieval.assert_not_awaited()
    else:
        assert [(source['page'], source['document_version']) for source in answer['sources']] == [(requested_page, 'chapter-v1')], answer['answer']
        assert len(prompts) == 1
        if case == 'selected':
            retrieval.assert_not_awaited()
            assert answer['trace']['source_continuity'] == 'page' and '当前独立页 24' in prompts[0]
        else:
            retrieval.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('original,found', [
    ('这项读回能支持「设备已经保持完整的业务转发」这一验收判断吗？', True),
    ('这项读回能核对 `Unverified service flow state` 吗？', True),
    ('请从教材说明「设备已经保持完整的业务转发」能否因此成立。', True),
    ('请在本页查找原句“当前独立页 24 的端口练习”，并标明出处。', True),
    ('请在本页查找原句“当前独立页 21 的帧选择说明”，并标明出处。', False),
])
async def test_guide_prefix_does_not_turn_quoted_claims_or_fields_into_verbatim_searches(
    api_case, test_session_factory, monkeypatch, path, original, found
):
    client, headers, provider, retrieval = api_case
    edition = MiniEdition()
    prompts = complete_with_fixture(provider, monkeypatch, edition)
    session = await conversation(test_session_factory, headers)
    question = '请只根据本地教材《Synthetic manual》PDF 第 24 页回答。本页没有依据的内容请指出。\n\n' + original
    page = {'kind': 'original_page', 'document_id': 'synthetic-chapter', 'version': 'chapter-v1', 'page': 24}
    _, answer = await ask(client, headers, path, session, question, page_record=page, route='/knowledge')
    retrieval.assert_not_awaited()
    if found:
        assert [(source['page'], source['document_version']) for source in answer['sources']] == [(24, 'chapter-v1')]
        assert len(prompts) == 1 and original in prompts[0] and '当前独立页 24 的端口练习' in prompts[0]
        assert '当前独立页 21 的帧选择说明' not in prompts[0]
    else:
        assert not prompts and not answer['sources']
        assert answer['trace']['source_continuity'] == 'missing_quote'


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
async def test_quoted_book_title_never_acts_as_an_original_image_request(api_case, test_session_factory, monkeypatch, path):
    client, headers, provider, retrieval = api_case
    edition = MiniEdition()
    prompts = complete_with_fixture(provider, monkeypatch, edition)
    session = await conversation(test_session_factory, headers)
    retrieval.return_value = []
    question = '只依据《受限原图权限公开教材》PDF 第 21 页，指出这一页支持的范围并给出处。'
    _, answer = await ask(client, headers, path, session, question, route='/knowledge')
    assert [(s['document_id'], s['page']) for s in answer['sources']] == [('synthetic-chapter', 21)]
    assert len(prompts) == 1
    assert edition.reads == [('synthetic-chapter', 'chapter-v1')]


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('found', [False, True])
@pytest.mark.parametrize('configured', [False, True])
async def test_exact_quote_within_current_page_does_not_search_other_pages(
    api_case, test_session_factory, monkeypatch, path, found, configured
):
    client, headers, provider, retrieval = api_case
    edition = MiniEdition()
    prompts = complete_with_fixture(provider, monkeypatch, edition)
    session = await conversation(test_session_factory, headers)
    page = {'kind': 'original_page', 'document_id': 'synthetic-chapter', 'version': 'chapter-v1', 'page': 24}
    phrase = '当前独立页 24 的端口练习' if found else '当前独立页 21 的帧选择说明'
    retrieval.return_value = [edition.hit('other-chapter', 21, phrase)]
    if not configured:
        monkeypatch.setattr(router, '_has_copilot_model_configuration', lambda provider: False)
    question = f'请在本页核对教材原句“{phrase}”，并标明出处。'
    _, answer = await ask(client, headers, path, session, question, page_record=page, route='/knowledge')
    retrieval.assert_not_awaited()
    if found:
        assert [(source['document_id'], source['page']) for source in answer['sources']] == [('synthetic-chapter', 24)]
        assert len(prompts) == int(configured)
        assert phrase in (prompts[0] if configured else answer['sources'][0]['content'])
    else:
        assert not answer['sources'] and not prompts
        assert answer['trace']['source_continuity'] == 'missing_quote' and '没有找到这段原句' in answer['answer']


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
async def test_exact_quote_cannot_escape_previous_owned_citation(api_case, test_session_factory, monkeypatch, path):
    client, headers, provider, retrieval = api_case
    edition = MiniEdition()
    prompts = complete_with_fixture(provider, monkeypatch, edition)
    session = await conversation(test_session_factory, headers)
    retrieval.return_value = [edition.hit('synthetic-chapter', 21)]
    request_id, first = await ask(client, headers, '/chat', session, '教材里的生成树帧选择机制是什么？', route='/knowledge')
    assert first['sources'][0]['page'] == 21
    retrieval.return_value = [edition.hit('synthetic-chapter', 24, '当前独立页 24 的端口练习')]
    retrieval.reset_mock()
    question = '继续刚才的教材引用，在同一页查找原句“当前独立页 24 的端口练习”。'
    _, answer = await ask(client, headers, path, session, question, previous=request_id, route='/knowledge')
    assert answer['trace']['source_continuity'] == 'missing_quote'
    assert not answer['sources'] and '没有找到这段原句' in answer['answer'] and len(prompts) == 1
    retrieval.assert_not_awaited()


async def ask(client, headers, transport, conv, question, *, previous=None, source=None, page_record=None, route='/dashboard'):
    request_id = uuid4().hex
    payload = {'request_id': request_id, 'conversation_id': conv, 'message': question, 'context': {'route': route},
               'history': [{'role': 'assistant', 'content': SENTINEL, 'request_id': previous}] if previous else []}
    if source:
        payload['context']['knowledge_source'] = source
    if page_record:
        payload['context']['page_record'] = page_record
    result = await client.post('/api/v1/ai/copilot' + transport, json=payload, headers=headers)
    assert result.status_code == 200
    if transport == '/chat':
        return request_id, result.json()
    frames = events(result)
    return request_id, {'answer': ''.join(e['text'] for e in frames if e['type'] == 'token'),
                        'sources': next(e['sources'] for e in frames if e['type'] == 'references'),
                        'trace': next(e['trace'] for e in frames if e['type'] == 'done')}


@pytest.mark.asyncio
@pytest.mark.parametrize('paths', [('/chat','/chat/stream'), ('/chat/stream','/chat')])
async def test_same_conversation_cross_page_reopens_only_cited_physical_page(api_case, test_session_factory, monkeypatch, paths):
    client, headers, provider, retrieval = api_case
    edition = MiniEdition()
    prompts = complete_with_fixture(provider, monkeypatch, edition)
    session = await conversation(test_session_factory, headers)
    retrieval.return_value = [edition.hit('synthetic-chapter', 21), edition.hit('other-chapter', 24)]
    first_id, first = await ask(client, headers, paths[0], session, '教材里的生成树帧选择机制是什么？', route='/knowledge')
    assert len(first['sources']) == 2
    saved = await client.get('/api/v1/ai/copilot/requests/' + first_id, headers=headers)
    assert '_workbench_conversation' not in saved.text
    # No citation selected in either transport; one caller supplies no history at all.
    _, answer = await ask(client, headers, paths[1], session, FOLLOWUP, previous=first_id if paths[0] == '/chat/stream' else None)
    assert [item['page'] for item in answer['sources']] == [21]
    assert answer['trace']['source_continuity'] == 'page' and answer['trace']['tool_dispatch_attempts'] == 0
    assert edition.reads == [('synthetic-chapter', 'chapter-v1')]
    assert '当前独立页 21' in prompts[-1] and SENTINEL not in prompts[-1]
    assert '当前独立页 24' not in prompts[-1]
    retrieval.assert_awaited_once()


@pytest.mark.asyncio
async def test_public_session_endpoint_accepts_longer_id_and_continues_over_sse_without_click(api_case, monkeypatch):
    client, headers, provider, retrieval = api_case
    edition = MiniEdition()
    prompts = complete_with_fixture(provider, monkeypatch, edition)
    session = 'local-source-check-' + uuid4().hex
    assert len(session) == 51
    saved = await client.put('/api/v1/ai/copilot/sessions/' + session, json={'title':'课本页摘记','messages':[]}, headers=headers)
    assert saved.status_code == 200
    retrieval.return_value = [edition.hit('synthetic-chapter', 21)]
    await ask(client, headers, '/chat/stream', session, '请只根据教材《Synthetic manual》PDF 第 21 页解释生成树的端口选择。请标出处。', route='/knowledge')
    _, answer = await ask(client, headers, '/chat/stream', session,
        '继续只用刚才引用的同一页，说明选路有什么边界，没写计时时请说缺依据。请附原页出处。')
    assert answer['trace']['source_continuity'] == 'page' and [item['page'] for item in answer['sources']] == [21]
    assert '当前独立页 21' in prompts[-1] and SENTINEL not in prompts[-1]
    retrieval.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('transport', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('availability,expected', [
    ('current', '「阅读同版正文」由阅读器核对版次'),
    ('archive-only', '没有可核对的同版原页位置'),
    ('exact-page-locator', '查阅核对过的原页位置'),
    ('revoked', '引用已失效或已撤权'),
    ('cleared', '已清除引用选择'),
    ('other_conversation', '无法核对同一对话'),
])
async def test_previous_citation_readback_uses_original_sources_without_reopening_search(
        api_case, test_session_factory, monkeypatch, transport, availability, expected):
    client, headers, provider, retrieval = api_case
    edition = MiniEdition()
    prompts = complete_with_fixture(provider, monkeypatch, edition)
    session = await conversation(test_session_factory, headers)
    retrieval.return_value = [edition.hit('synthetic-chapter', 21)]
    first_id, first = await ask(client, headers, '/chat', session, '请解释教材里的生成树端口选择，带上出处。', route='/knowledge')
    source = first['sources'][0]
    locator = AsyncMock(return_value={'status': availability, 'message': 'fixture status'})
    documents = AsyncMock(return_value=[] if availability == 'revoked' else [
        {'filename': source['filename'], 'id': source['document_id']},
    ])
    monkeypatch.setattr(router, '_get_knowledge_service', lambda: SimpleNamespace(legacy_locator=locator, list_documents=documents))
    source_ref = {'mode': 'cleared'} if availability == 'cleared' else {
        'mode': 'selected', 'request_id': first_id, 'source_id': source['source_id'],
    }
    if availability == 'other_conversation':
        session = await conversation(test_session_factory, headers)
    _, result = await ask(client, headers, transport, session,
        '上一回复的引用 [1] 仍能查看吗？打开后如何返回同一条答复？', source=source_ref, previous=first_id)
    assert expected in result['answer'] and '返回对话' in result['answer']
    assert SENTINEL not in result['answer'] and '新标签页' not in result['answer']
    assert result['trace']['model_calls'] == result['trace']['tool_dispatch_attempts'] == 0
    assert not result['sources'] and len(prompts) == 1
    if availability in {'cleared', 'other_conversation'}:
        locator.assert_not_awaited()
    else:
        locator.assert_awaited_once_with(source['document_id'], source['document_version'], source['section_id'])
    retrieval.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('selected', [False, True])
async def test_same_chapter_or_explicit_citation_never_uses_other_chapters(api_case, test_session_factory, monkeypatch, selected):
    client, headers, provider, retrieval = api_case
    edition = MiniEdition()
    complete_with_fixture(provider, monkeypatch, edition, references=('[1]', '[2]'))
    session = await conversation(test_session_factory, headers)
    retrieval.return_value = [edition.hit('synthetic-chapter', 21), edition.hit('synthetic-chapter', 24)]
    first_id, first = await ask(client, headers, '/chat', session, '教材里生成树这两种端口怎么理解？', route='/knowledge')
    source = {'mode': 'selected', 'request_id': first_id, 'source_id': first['sources'][1]['source_id']} if selected else None
    _, answer = await ask(client, headers, '/chat/stream', session, FOLLOWUP, previous=first_id, source=source)
    assert [item['page'] for item in answer['sources']] == ([24] if selected else [21, 24]), {
        'continuity': answer['trace'].get('source_continuity'), 'first_model_answer': first['answer'], 'rechecked': edition.reads,
    }
    assert {item['document_id'] for item in answer['sources']} == {'synthetic-chapter'}
    assert answer['trace']['source_continuity'] == ('page' if selected else 'chapter')
    assert edition.keyword_index.search_pages.await_count == (0 if selected else 1)
    retrieval.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('actor', ['other_user', 'administrator', 'own_other_conversation'])
async def test_previous_request_id_never_grants_cross_conversation_or_account_access(api_case, test_session_factory, monkeypatch, actor):
    client, admin, provider, retrieval = api_case
    edition = MiniEdition()
    prompts = complete_with_fixture(provider, monkeypatch, edition)
    owner = auth_header(await _make_user(test_session_factory, 'source-conversation-owner', 'user'))
    session = await conversation(test_session_factory, owner)
    retrieval.return_value = [edition.hit('synthetic-chapter', 21)]
    first_id, first = await ask(client, owner, '/chat', session, '教材里生成树的端口角色怎么解释？', route='/knowledge')
    if actor == 'other_user':
        challenger = auth_header(await _make_user(test_session_factory, 'unrelated-role-user', 'user'))
        other_session = await conversation(test_session_factory, challenger)
    elif actor == 'administrator':
        challenger, other_session = admin, session
    else:
        challenger, other_session = owner, await conversation(test_session_factory, owner)
    pointer = {'mode': 'selected', 'request_id': first_id, 'source_id': first['sources'][0]['source_id']}
    _, answer = await ask(client, challenger, '/chat/stream', other_session, FOLLOWUP, source=pointer, previous=first_id)
    assert answer['trace']['source_continuity'] == 'unavailable' and answer['trace']['model_calls'] == 0
    assert not answer['sources'] and '无法核验' in answer['answer']
    assert len(prompts) == 1 and edition.reads == []
    retrieval.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', ['cleared', 'different_page', 'later_answer', 'version_changed', 'conflicting_citations', 'changed_question'])
async def test_newer_objects_and_changed_sources_never_reuse_previous_excerpt(api_case, test_session_factory, monkeypatch, invalid):
    client, headers, provider, retrieval = api_case
    edition = MiniEdition()
    if invalid == 'later_answer':
        monkeypatch.setattr('modules.ai_text.request_store.now', lambda: datetime(2026, 7, 4, 10, 0))
    refs = ('[1]', '[2]') if invalid == 'conflicting_citations' else ('[1]',)
    prompts = complete_with_fixture(provider, monkeypatch, edition, references=refs)
    session = await conversation(test_session_factory, headers)
    retrieval.return_value = [edition.hit('synthetic-chapter', 21), edition.hit('other-chapter', 24)]
    first_id, first = await ask(client, headers, '/chat', session, '教材里生成树帧转发怎么解释？', route='/knowledge')
    retrieval.return_value = []
    source, page, question, expected = None, None, FOLLOWUP, 'independent'
    if invalid == 'cleared':
        source = {'mode': 'cleared'}
    elif invalid == 'different_page':
        page = {'kind': 'original_page', 'document_id': 'other-chapter', 'version': 'other-v1', 'page': 24}
    elif invalid == 'changed_question':
        question = '刚才那条教材引用先不看，我现在看到的是另一章那页。请解释帧的优先级。'
    else:
        expected = 'unavailable'
        if invalid == 'version_changed':
            edition.version = 'new-edition'
        if invalid == 'later_answer':
            await ask(client, headers, '/chat', session, '现在换个问题，以太网优先级是什么？')
            source = {'mode': 'selected', 'request_id': first_id, 'source_id': first['sources'][0]['source_id']}
    old_calls = len(prompts)
    _, answer = await ask(client, headers, '/chat/stream', session, question, previous=first_id, source=source, page_record=page)
    assert answer['trace']['source_continuity'] == expected and not answer['sources'] and edition.reads == []
    if expected == 'unavailable':
        assert '无法核验' in answer['answer'] and len(prompts) == old_calls
    else:
        assert len(prompts) == old_calls + 1 and SENTINEL not in prompts[-1]


@pytest.mark.asyncio
async def test_omitted_preexisting_context_field_preserves_retry_identity(api_case, test_session_factory):
    client, headers, provider, _ = api_case
    session = await conversation(test_session_factory, headers)
    request_id = uuid4().hex
    payload = {'request_id': request_id, 'conversation_id': session, 'message': '请解释端口角色。', 'context': {'route': '/knowledge'}}
    first = await client.post('/api/v1/ai/copilot/chat', headers=headers, json=payload)
    assert first.status_code == 200
    calls = provider.calls
    old_format = CopilotChatRequest(**payload).model_dump(mode='json', exclude={'request_id'})
    old_format['context'].pop('knowledge_source')
    user_id = int(decode_access_token(headers['Authorization'][7:])['sub'])
    async with test_session_factory() as db:
        row = await db.get(CopilotRequest, (user_id, request_id))
        assert row.input_hash == digest(old_format)
    replay = await client.post('/api/v1/ai/copilot/chat', headers=headers, json=payload)
    assert replay.status_code == 200 and replay.json()['replayed'] and provider.calls == calls
