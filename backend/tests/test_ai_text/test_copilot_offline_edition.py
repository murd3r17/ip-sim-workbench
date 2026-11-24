"""Typed textbook locators remain useful even when model generation cannot run."""
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest

from modules.ai_text import router
from modules.ai_text.schemas import CopilotChatRequest
from modules.knowledge.facet_evidence import FacetEvidenceRef
from modules.knowledge.ranked_evidence import PreciseCase, RankedEvidence
from modules.ai_text.skills import select_skill
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


def test_same_page_expansion_retains_the_existing_proof():
    from modules.ai_text.router import _preserves_edition_sources

    original = {'edition_version': 'edition-a', 'document_id': 'doc-a', 'document_version': 'rev-a',
                'page': 12, 'section_id': 'section-a', 'content': '两端角色已记录。'}
    expanded = {**original, 'content': '两端角色已记录。\n\n回显列出备端转发状态。'}
    assert _preserves_edition_sources([original], [expanded])
    assert not _preserves_edition_sources([original], [{**expanded, 'page': 13}])
    assert not _preserves_edition_sources([original], [{**expanded, 'document_version': 'rev-b'}])
    assert not _preserves_edition_sources([original], [{**original, 'content': '角色已记录。'}])


def test_ranked_complement_replaces_only_a_clearly_foreign_source(monkeypatch):
    edition = configured_edition(monkeypatch)
    edition.read.return_value = {'original_pages': [
        {'physical': page, 'section_id': f'physical-page-{page}', 'evidence_eligible': True}
        for page in (7, 8, 9)
    ]}
    question = 'OSPF 如何发现邻居？数据库摘要由谁发送？'
    first = {**MATCH, 'title': 'OSPF 邻居发现', 'text': 'OSPF 使用 Hello 报文发现邻居。'}
    second = {**first, 'page': 8, 'section_id': 'physical-page-8', 'text': 'OSPF 对等路由器交换各自的数据库摘要。'}
    foreign = {**first, 'page': 9, 'section_id': 'physical-page-9', 'title': 'BGP 会话', 'text': 'BGP 保持对等体会话。'}
    reference = RankedEvidence(sha256(question.encode()).hexdigest(), edition.version,
                               ((1, '发现邻居', 'mechanism'), (2, '发送数据库摘要', 'mechanism')),
                               ((1, FacetEvidenceRef.from_hit(first)), (2, FacetEvidenceRef.from_hit(second))), ())
    hits = router._FacetHits([first, foreign], None, reference, [first, second])
    sources, notice = router._prepare_ranked_facets(question, hits, edition, router.prepare_sources(hits), 2)
    assert [source['page'] for source in sources] == [8, 7] and not notice
    related = {**foreign, 'title': 'OSPF 拓扑变化', 'text': 'OSPF 按链路状态计算最短路径。'}
    assert router._prepare_ranked_facets(question, hits, edition, router.prepare_sources([first, related]), 2) is None


def test_ranked_complement_can_expand_a_proven_same_page_within_budget(monkeypatch):
    edition = configured_edition(monkeypatch)
    question = 'STP 先比较哪些字段？同优先级时怎么决定？'
    short = {**MATCH, 'text': '先比较桥优先级。'}
    full = {**MATCH, 'text': '先比较桥优先级。\n\n桥优先级相同，再比较 MAC 地址。'}
    reference = FacetEvidenceRef.from_hit(full)
    ranked = RankedEvidence(sha256(question.encode()).hexdigest(), edition.version,
                            ((1, '比较字段', 'mechanism'), (2, '相同优先级', 'mechanism')),
                            ((1, reference), (2, reference)), ())
    hits = router._FacetHits([short], None, ranked, [full])
    sources, notice = router._prepare_ranked_facets(question, hits, edition, router.prepare_sources(hits), 1)
    assert len(sources) == 1 and '比较 MAC 地址' in sources[0]['content'] and not notice


def test_precise_case_uses_only_verified_observations_and_asks_on_conflict(monkeypatch):
    edition = configured_edition(monkeypatch)
    question = '教材这次互测中 R1 到 R2 和 R2 到 R1 的回显分别收到几次回复？'
    proof = {**MATCH, 'title': '端点互测', 'text': 'R1 到 R2 实测 2 发 2 收，R2 到 R1 实测 2 发 0 收。'}
    other = {**MATCH, 'page': 8, 'section_id': 'physical-page-8', 'text': '另一次测试记录。'}
    ref = FacetEvidenceRef.from_hit(proof)
    matches = ((1, ref), (2, ref))
    ranked = RankedEvidence(sha256(question.encode()).hexdigest(), edition.version,
                             ((1, 'R1 到 R2', 'readback'), (2, 'R2 到 R1', 'readback')), matches, (),
                             PreciseCase(('page', 'edition:stp', '7'), matches, ((1, (('r1', 'r2'),)), (2, (('r2', 'r1'),)))))
    data = CopilotChatRequest(message=question, context={'route': '/knowledge'})
    skill = select_skill(question, route='/knowledge')
    hits = router._FacetHits([other], None, ranked, [proof, other])
    chosen, notice = router._prepare_copilot_sources(data, hits, skill, '')
    assert [item['page'] for item in chosen] == [7] and not notice
    conflicted = router._FacetHits([other], None, replace(ranked, ambiguous_precise_case=True), [proof, other])
    chosen, notice = router._prepare_copilot_sources(data, conflicted, skill, '')
    assert chosen == [] and '多处' in notice


def test_one_verified_observation_survives_without_borrowing_the_missing_stage(monkeypatch):
    configured_edition(monkeypatch)
    question = '教材实验里 SW-A 调整前显示什么角色？SW-B 调整后又显示什么角色？'
    proof = {**MATCH, 'text': '调整前，SW-A 的回显记录为指定端口。'}
    other = {**MATCH, 'page': 8, 'section_id': 'physical-page-8', 'text': 'SW-B 在另一项实验显示为备用端口。'}
    ranked = SimpleNamespace(
        query_sha256=sha256(question.encode()).hexdigest(),
        observation_facets=(1, 2), verified_observation=((1, FacetEvidenceRef.from_hit(proof)),),
        facets=((1, 'SW-A 调整前', 'readback'), (2, 'SW-B 调整后', 'readback')),
        select_verified_observations=lambda query, pool: [proof] if query == question and proof in pool else None,
    )
    data = CopilotChatRequest(message=question, context={'route': '/knowledge'})
    skill = select_skill(question, route='/knowledge')
    chosen, notice = router._prepare_copilot_sources(data, router._FacetHits([other], None, ranked, [other, proof]), skill, '')
    assert [source['page'] for source in chosen] == [7]
    assert '第 2 项' in notice and 'SW-B 调整后' in notice
    assert chosen[0]['query_focus'] == '问题的第 1 项'

    ranked.verified_observation = ()
    ranked.ambiguous_observation_facets = (1, 2)
    ranked.select_verified_observations = lambda query, pool: None
    chosen, notice = router._prepare_copilot_sources(data, router._FacetHits([other], None, ranked, [other, proof]), skill, '')
    assert chosen == [] and '不止一处' in notice and '实验阶段' in notice


def test_mixed_question_explains_proven_mechanism_without_guessing_an_ambiguous_readback(monkeypatch):
    configured_edition(monkeypatch)
    question = '教材里 SW-A 调整后显示什么角色？角色变化能说明终端数据已经恢复吗？'
    explanation = {**MATCH, 'text': '端口角色应与数据面的独立读回分别核对。'}
    other = {**MATCH, 'page': 8, 'section_id': 'physical-page-8', 'text': 'SW-A 在一个可能的实验显示为备用端口。'}
    ranked = SimpleNamespace(
        query_sha256=sha256(question.encode()).hexdigest(), observation_facets=(1,),
        verified_observation=(), ambiguous_observation_facets=(1,),
        verified_explanation=((2, FacetEvidenceRef.from_hit(explanation)),),
        facets=((1, 'SW-A 调整后的角色', 'readback'), (2, '恢复证据是否充分', 'evidence_limit')),
        select_verified_observations=lambda query, pool: None,
        select_verified_explanations=lambda query, pool: [explanation],
    )
    data = CopilotChatRequest(message=question, context={'route': '/knowledge'})
    skill = select_skill(question, route='/knowledge')
    chosen, notice = router._prepare_copilot_sources(data, router._FacetHits([other], None, ranked, [other, explanation]), skill, '')
    assert [item['page'] for item in chosen] == [7]
    assert '第 1 项' in notice and '多处可能' in notice
    assert chosen[0]['query_focus'] == '问题的第 2 项'


def test_verified_comparison_keeps_the_other_side_when_the_budget_is_full(monkeypatch):
    configured_edition(monkeypatch)
    question = '模式 Alpha 和 Beta 分别如何处理同步？还想知道结果由谁确认。'
    proof = {**MATCH, 'text': '模式 Beta 由服务端启动，接收端确认同步结果。'}
    other = {**MATCH, 'page': 8, 'section_id': 'physical-page-8', 'text': '模式 Alpha 由客户端发起。'}
    background = {**MATCH, 'page': 9, 'section_id': 'physical-page-9', 'text': '课堂使用两台模拟设备。'}
    ref = FacetEvidenceRef.from_hit(proof)
    ranked = SimpleNamespace(
        observation_facets=(), verified_explanation=((2, ref),),
        facets=((1, 'Alpha 同步', 'mechanism'), (2, 'Beta 同步', 'mechanism'), (3, '结果确认', 'concept')),
        comparison_topics=((1, 'Alpha'), (2, 'Beta')), matches=((3, ref),),
        select_verified_explanations=lambda query, pool: [proof],
    )
    baseline = router.prepare_sources([other, background])
    sources, _ = router._prepare_verified_claims(question, ranked, [proof], baseline, 2)
    assert [item['page'] for item in sources] == [7, 8]
    ranked.matches = ()
    assert router._prepare_verified_claims(question, ranked, [proof], baseline, 2) is None


@pytest.mark.asyncio
async def test_scoped_recovery_completes_verified_sources_from_a_larger_pool(api_case, monkeypatch):
    edition = configured_edition(monkeypatch)
    edition.has_search_scope = lambda query: False
    edition.read.return_value = {'original_pages': [
        {'physical': 7, 'section_id': 'physical-page-7', 'evidence_eligible': True},
        {'physical': 8, 'section_id': 'physical-page-8', 'evidence_eligible': True},
    ]}
    base = {**MATCH, 'title': 'VXLAN 试验', 'text': 'VXLAN 的 R4 与 R7 同组。\n\nR4 从远端 R7 学到对端 MAC 地址。'}
    extra = {**base, 'page': 8, 'section_id': 'physical-page-8',
             'text': 'VXLAN 的 R4 与 R7 同组。\n\n抓包显示报文外层地址为 192.0.2.4，内层地址为 198.51.100.8。'}
    request = CopilotChatRequest(context={'route': '/knowledge'},
        message='图中 VXLAN 的 R4 与 R7 实验，哪些表项是从远端学到的？抓包的内层与外层字段能读出什么？')
    broader = AsyncMock(return_value=[{**extra, 'edition_version': 'expired'}])
    monkeypatch.setattr(router, 'cached_search', broader)
    assert await router._recover_scoped_observations(request, [base]) == [base]
    broader.return_value = [extra]
    assert await router._recover_scoped_observations(request, [base]) == [base, extra]
    assert all(call.args[2] == 18 for call in broader.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('failure', ['initialization', 'connection', 'locator', 'concepts', 'explicit_lookup', 'textbook_readback'])
async def test_local_edition_sources_are_clickable_recoverable_and_not_called_generated(api_case, monkeypatch, path, failure):
    client, headers, provider, retrieval = api_case
    edition = configured_edition(monkeypatch)
    retrieval.return_value = [
        {**MATCH, 'edition_version': 'old-version', 'text': 'OLD_EDITION'}, MATCH,
        {**MATCH, 'page': 8, 'section_id': 'physical-page-8', 'text': 'FORBIDDEN_PAGE'},
    ]
    create = AsyncMock(return_value=provider)
    if failure in {'initialization', 'concepts', 'explicit_lookup', 'textbook_readback'}:
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
    elif failure == 'textbook_readback':
        message = '只看教材。STP 教材实验的实测记录里，哪一项是桥 ID？'
    route = '/' if failure == 'textbook_readback' else '/knowledge'
    body = {'message': message, 'request_id': request_id, 'context': {'route': route}}
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
    ('查教材中的 STP 原理，再到设备 R7 上重新实测根桥状态。', {}),
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
