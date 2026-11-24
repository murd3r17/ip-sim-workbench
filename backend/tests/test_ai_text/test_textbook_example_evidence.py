"""Public synthetic evidence boundaries for textbook examples and mixed real reads."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest

from modules.ai_text import router
from modules.ai_text.question_intent import new_device_read_scope
from modules.ai_text.skills import request_evidence_scope, select_skill
from modules.knowledge.service import KnowledgeService
from tests.test_c3_request_api import api_case, events


EDITION = 'public-example-edition'
QUESTION = ('看课件上的 OSPF 案例 8。R42 的配置步骤和 `display ospf peer` 的读回各能核对什么？')
ROUTE_FIELDS = ('教材的 OSPF 案例 8，R42 的路由表里 203.0.113.64/26 的下一跳和路由类型各是什么？')


def hit(page, text, *, case=8, doc='public-ospf-example', title='OSPF 实验记录'):
    return {'page': page, 'filename': f'{doc}.md', 'title': title, 'book_title': '公开合成教材',
            'document_id': doc, 'document_version': f'{doc}-sha', 'section_id': f'page-{page}',
            'edition_version': EDITION, 'text': f'### PDF 第 {page} 页\n\n**案例 {case}。**\n\n{text}'}


SETUP = hit(112, 'R42 的 OSPF 配置步骤。先配置区域，再核对该区域下的接口。')
OUTPUT = hit(114, 'R42 的 OSPF 验证记录。\n\n```text\n<R42>display ospf peer\nNeighbor State: Full\n```')
GUIDANCE = hit(115, 'R42 的 OSPF 验证说明。\n\n```text\n<R42>display ospf peer\n```\n执行后再看邻居状态。')
OTHER_CASE = hit(118, 'R42 的 OSPF 验证记录。\n\n```text\n<R42>display ospf peer\nNeighbor State: Down\n```',
                 case=9, doc='different-case')
OTHER_DEVICE = hit(119, 'R42 的 OSPF 地址规划。\n\n```text\n<R43>display ospf peer\nNeighbor State: Full\n```')
ROUTE_HOP = hit(116, 'R42 的 OSPF 路由表中，203.0.113.64/26 的下一跳为 192.0.2.72。')
OTHER_HOP = hit(120, 'R42 的 OSPF 路由表中，203.0.113.64/26 的下一跳为 192.0.2.73，类型为 E2。', case=9)


@pytest.mark.parametrize('route,question', [
    ('/devices', '课件截图里 FW9 的 read-only 显示命令写的是哪条？'),
    ('/knowledge', '请查看 R42 在本节的回显，哪一步才检查结果？'),
    ('/knowledge', '知识库这个 BGP 例子写 R53 配置后检查哪个回显字段？'),
    ('/training', '教材里样例设备 R43 的验证步骤与表中回显冲突，以哪段证据为准？'),
    ('/devices', '照讲义图解释 R44 为什么先写命令而后看结果？'),
])
def test_explicit_study_is_not_an_instruction_to_read_devices(route, question):
    skill = select_skill(question, route=route)
    assert skill.id == 'knowledge_answer' and skill.needs_knowledge
    assert not skill.tools and not new_device_read_scope(question)


def test_explicit_new_act_in_a_separate_clause_keeps_the_original_tool_gate():
    question = '先解释教材里的 OSPF 命令。请现在读取 R42 真机的接口状态。'
    action = new_device_read_scope(question)
    assert 'R42' in action and '教材' not in action and request_evidence_scope(question).allow_device_reads
    assert select_skill(question, route='/devices').id != 'knowledge_answer'
    quote = '教材里写“请现在读取 R42 真机的接口状态”。这条命令有什么含义？'
    assert not new_device_read_scope(quote)
    assert not select_skill(quote, route='/devices').tools


def use_edition(monkeypatch, rows):
    edition = SimpleNamespace(version=EDITION, documents={
        row['document_id']: {'sha256': row['document_version']} for row in rows
    }, read=Mock(return_value={'original_pages': [
        {'physical': row['page'], 'section_id': row['section_id'], 'evidence_eligible': True} for row in rows
    ]}))
    service = object.__new__(KnowledgeService)
    monkeypatch.setattr(service, 'edition', lambda: edition)
    monkeypatch.setattr(service, 'legacy_locator', AsyncMock(return_value={}))
    monkeypatch.setattr(service, 'list_documents',
                        AsyncMock(return_value=[{'id': 'public-ospf-example', 'filename': 'public-ospf-example.md'}]))
    monkeypatch.setattr(router, '_get_knowledge_service', lambda: service)


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('case,question,hits,pages,gap', [
    ('complete', QUESTION, [OTHER_CASE, SETUP, GUIDANCE, OUTPUT], [112, 114], ''),
    ('setup_only', QUESTION, [OTHER_CASE, GUIDANCE, SETUP, OTHER_DEVICE], [112], '设备读回'),
    ('no_case', QUESTION, [OTHER_CASE], [], '一致的教材例证'),
    ('only_instruction', '课件 OSPF 案例 8，R42 的 `display ospf peer` 实际回显在哪段？',
     [GUIDANCE, OTHER_CASE], [], '只找到同例的只读命令示例'),
    ('route_partial', ROUTE_FIELDS, [OTHER_HOP, ROUTE_HOP], [116], '路由类型'),
])
@pytest.mark.parametrize('provider_mode', ['available', 'unconfigured', 'connect_failed'])
async def test_same_example_selection_in_each_application_mode(api_case, monkeypatch, path, case, question, hits, pages, gap, provider_mode):
    client, headers, provider, retrieval = api_case
    use_edition(monkeypatch, hits)
    retrieval.return_value = hits
    prompts = []
    if provider_mode == 'unconfigured':
        monkeypatch.setattr(router.SystemService, 'build_llm_provider', AsyncMock(side_effect=RuntimeError('no model')))

    async def respond(prompt, system=None):
        provider.calls += 1
        prompts.append(prompt)
        if provider_mode == 'connect_failed':
            raise httpx.ConnectError('local substitute failure')
        yield {'kind': 'content', 'text': '同例证据见[1]。'}

    monkeypatch.setattr(provider, 'stream_parts', respond)
    request_id = uuid4().hex
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'request_id': request_id, 'message': question, 'context': {'route': '/knowledge'}
    })
    assert response.status_code == 200, response.text
    saved = (await client.get('/api/v1/ai/copilot/requests/' + request_id, headers=headers)).json()['response']
    assert [item['page'] for item in saved['sources']] == pages
    assert saved['knowledge_status'] == ('ok' if pages else 'empty')
    expected_status = 'failed' if provider_mode == 'unconfigured' or pages and provider_mode == 'connect_failed' else 'ok' if pages else 'degraded'
    assert saved['status'] == expected_status
    assert saved['generation_status'] == ('not_generated' if not pages else
                                          'generated' if provider_mode == 'available' else 'retrieval_only')
    assert saved['trace']['tool_dispatch_attempts'] == 0
    assert provider.calls == int(bool(pages) and provider_mode != 'unconfigured')
    if gap:
        assert gap in saved['answer']
    if not pages:
        assert '检索到的教材' not in saved['answer'] and '[1]' not in saved['answer']
    if path == '/chat/stream':
        assert next(frame['sources'] for frame in events(response) if frame['type'] == 'references') == saved['sources']
    if prompts:
        prompt, = prompts
        assert all(str(f'PDF 物理页：{page}。') not in prompt for page in (115, 118, 119, 120))
        if gap:
            assert '未核对的字段只说明缺口' in prompt
    for source in saved['sources']:
        read = await client.get('/api/v1/ai/copilot/citations/read', headers=headers, params={
            'request_id': request_id, 'filename': source['filename'], 'source_id': source['source_id'],
        })
        assert read.status_code == 200 and read.json()['content'] == source['content']
        if prompts:
            assert read.json()['content'] in prompts[0]
