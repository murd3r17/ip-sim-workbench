"""Compare written evidence without treating a generic record reference as a device read."""

from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from modules.ai_text import router
from modules.ai_text.question_intent import new_device_read_scope
from modules.ai_text.skills import request_evidence_scope, select_skill
from tests.test_ai_text.test_copilot_offline_edition import MATCH, configured_edition
from tests.test_ai_text.test_textbook_example_evidence import QUESTION, SETUP, use_edition
from tests.test_c3_request_api import api_case, events


PROOF_QUESTION = ('R54 的 IS-IS 说明段称两个方向都已看到邻居，表里只列了一端的标识。'
                  '把这条记录里的表中读数并进同一次双向结论够不够，证据边界到哪？')
VIEW_PROOF_QUESTION = ('R66 的 BFD 表中只列本端的检测倍数，另有一个建立成功的标记。'
                       '凭这条记录，能证明两端是同一次采样、且已经恢复转发吗？')


@pytest.mark.parametrize('route,question', [
    ('/knowledge', PROOF_QUESTION),
    ('/devices', '原文说 MPLS 的 R53 已安装下游标签，另一张表只列入标签。按已有记录能不能推出同一路径已经通了？'),
    ('/training', 'BGP 的文字说明把连接写成稳定，表中只见一次状态。不额外补数据的话，记录最多支持到什么程度？'),
    ('/knowledge', '前一段把 BFD 写成双向协商完成，表格上只有一个方向的发送间隔。这份记录支持双向都完成吗，还是只能说明一端？'),
])
def test_interpretation_of_text_and_table_enters_knowledge_without_reading_device(route, question):
    scope = request_evidence_scope(question)
    skill = select_skill(question, route=route, evidence_scope=scope)
    assert skill.id == 'knowledge_answer' and skill.needs_knowledge and not skill.tools
    assert scope.knowledge_lookup is None and not scope.allow_device_reads
    assert not new_device_read_scope(question)


@pytest.mark.parametrize('question,kwargs,skill_id,needs_knowledge', [
    (PROOF_QUESTION, {'saved_observation': True, 'page_data_trusted': True}, 'live_evidence', False),
    ('现场刚采的 R54 邻居记录在这张表里，正文证据能否证明 R54 当前可达？', {}, 'live_evidence', False),
    ('只依据下面的工作记录：' + PROOF_QUESTION, {}, 'troubleshooting', False),
    (PROOF_QUESTION, {'has_attachments': True}, 'knowledge_answer', False),
])
def test_existing_operational_evidence_and_user_material_keep_their_separate_scope(
        question, kwargs, skill_id, needs_knowledge):
    skill = select_skill(question, route='/knowledge', **kwargs)
    assert skill.id == skill_id and skill.needs_knowledge == needs_knowledge
    assert not new_device_read_scope(question)


def test_separate_simulation_read_preserves_explicit_target_without_carriers_from_example():
    question = PROOF_QUESTION + '另外请现在实际读取模拟设备 R59 的接口摘要。'
    grant = new_device_read_scope(question)
    skill = select_skill(question, route='/devices')
    assert 'R59' in grant and 'R54' not in grant
    assert skill.id == 'live_evidence' and 'run_display_command' in skill.tools


def test_evidence_boundary_question_can_use_the_knowledge_view_as_reading_context():
    knowledge = select_skill(VIEW_PROOF_QUESTION, route='/knowledge')
    assert knowledge.reason == 'explicit_learning_context' and knowledge.needs_knowledge and not knowledge.tools
    assert select_skill(VIEW_PROOF_QUESTION, route='/devices').id == 'live_evidence'
    assert not new_device_read_scope(VIEW_PROOF_QUESTION)
    assert select_skill(VIEW_PROOF_QUESTION, route='/knowledge', saved_observation=True).id == 'live_evidence'
    assert not select_skill(VIEW_PROOF_QUESTION, route='/knowledge', has_attachments=True).needs_knowledge
    assert not select_skill('只依据下面的工作记录：' + VIEW_PROOF_QUESTION, route='/knowledge').needs_knowledge
    device = '这是 R66 刚从真机采集的接口观察。' + VIEW_PROOF_QUESTION
    assert select_skill(device, route='/knowledge').id == 'live_evidence'


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
async def test_real_route_limits_simulation_target_resolution_to_the_explicit_clause(api_case, monkeypatch, path):
    client, headers, provider, retrieval = api_case
    resolve = AsyncMock(return_value=None)
    monkeypatch.setattr(router, 'resolve_task_targets', resolve)

    async def reply(prompt, system=None):
        yield {'kind': 'content', 'text': '暂未核验出要查询的对象。'}

    monkeypatch.setattr(provider, 'stream_parts', reply)
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'request_id': uuid4().hex, 'context': {'route': '/devices'},
        'message': PROOF_QUESTION + '另外请现在实际读取模拟设备 R59 的接口摘要。',
    })
    assert response.status_code == 200, response.text
    resolve.assert_awaited_once()
    action = resolve.await_args.args[1]
    assert 'R59' in action and 'R54' not in action
    retrieval.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('edition_result', ['current', 'wrong_version', 'empty'])
@pytest.mark.parametrize('question', [PROOF_QUESTION, VIEW_PROOF_QUESTION])
async def test_local_search_with_and_without_eligible_sources_when_model_is_absent(
        api_case, monkeypatch, path, edition_result, question):
    client, headers, _, retrieval = api_case
    configured_edition(monkeypatch)
    title, content = (
        ('BFD 合成表格', 'BFD 协商后的表格：\n\n| 设备 | 检测倍数 |\n| --- | --- |\n| R66 | 2 |\n\n'
         'R66 的本端发送间隔为 50 ms。') if question == VIEW_PROOF_QUESTION else
        ('IS-IS 合成说明与表格', 'IS-IS 说明段记录 R54 两端的邻居。表中只有 R54 一端读数，未给出采样时间。')
    )
    evidence = {**MATCH, 'title': title, 'text': content}
    if edition_result == 'wrong_version':
        evidence['edition_version'] = 'unrelated-old-edition'
    retrieval.return_value = [] if edition_result == 'empty' else [evidence]
    resolve = AsyncMock(side_effect=AssertionError('References to a table do not authorize resolving the device'))
    monkeypatch.setattr(router, 'resolve_task_targets', resolve)
    monkeypatch.setattr(router.SystemService, 'build_llm_provider', AsyncMock(side_effect=RuntimeError('missing model')))
    request_id = uuid4().hex
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'request_id': request_id, 'message': question, 'context': {'route': '/knowledge'},
    })
    retrieval.assert_awaited_once()
    resolve.assert_not_awaited()
    assert response.status_code == 200, response.text
    saved = (await client.get('/api/v1/ai/copilot/requests/' + request_id, headers=headers)).json()['response']
    if edition_result == 'current':
        assert saved['knowledge_status'] == 'ok' and saved['generation_status'] == 'retrieval_only'
        assert [source['content'] for source in saved['sources']] == [evidence['text']]
    else:
        assert saved['status'] == 'failed' and saved['generation_status'] == 'not_generated'
        assert saved['knowledge_status'] == 'empty' and not saved['sources'] and evidence['text'] not in response.text
        assert any(hint in saved['answer'] for hint in ('未找到', '没有找到', '无法通过当前教材版本校验'))
    assert saved['trace']['model_calls'] == 0 and saved['trace'].get('tool_dispatch_attempts', 0) == 0
    if path.endswith('/stream'):
        assert events(response)[0]['skill']['id'] == 'knowledge_answer'


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('withdraw_after_token', [False, True])
async def test_mid_answer_failure_preserves_gap_and_rechecks_reference_access(api_case, monkeypatch, path, withdraw_after_token):
    client, headers, provider, retrieval = api_case
    use_edition(monkeypatch, [SETUP])
    edition = router._get_knowledge_service().edition()
    retrieval.return_value = [SETUP]

    async def connection_drops(prompt, system=None):
        assert '设备读回' in prompt
        yield {'kind': 'content', 'text': 'UNFINISHED_MODEL_FRAGMENT [1]。'}
        if withdraw_after_token:
            edition.read.return_value = {'original_pages': []}
        raise httpx.ConnectError('controlled local drop')

    monkeypatch.setattr(provider, 'stream_parts', connection_drops)
    request_id = uuid4().hex
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'request_id': request_id, 'message': QUESTION, 'context': {'route': '/knowledge'},
    })
    assert response.status_code == 200
    saved = (await client.get('/api/v1/ai/copilot/requests/' + request_id, headers=headers)).json()['response']
    assert saved['status'] == 'failed' and saved['trace']['provider_error'] == 'provider_unavailable'
    assert 'UNFINISHED_MODEL_FRAGMENT' not in saved['answer'] and '设备读回' in saved['answer']
    assert bool(saved['sources']) != withdraw_after_token
    assert saved['generation_status'] == ('not_generated' if withdraw_after_token else 'retrieval_only')
    assert saved['knowledge_status'] == ('empty' if withdraw_after_token else 'ok')
    if withdraw_after_token:
        assert '当前教材版本校验' in saved['answer'] and '[1]' not in saved['answer']
    if path.endswith('/stream'):
        frames = events(response)
        replacement = next(event for event in frames if event['type'] == 'policy' and 'replace_answer' in event)
        assert replacement['retrieval_only'] is not withdraw_after_token
        assert replacement['replace_answer'] == saved['answer']
        assert next(event['sources'] for event in frames if event['type'] == 'references') == saved['sources']
    retrieval.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('question,extra', [
    ('只依据下面的工作记录：' + VIEW_PROOF_QUESTION, {}),
    (VIEW_PROOF_QUESTION, {'attachments': [{'name': 'synthetic.txt', 'mime': 'text/plain', 'contentString': 'given'}]}),
    ('我刚从真机 R66 采集，表中这条记录能证明目前双向已经恢复吗？', {}),
])
async def test_unconfigured_model_does_not_broaden_other_evidence_requests(api_case, monkeypatch, path, question, extra):
    client, headers, _, retrieval = api_case
    configured_edition(monkeypatch)
    monkeypatch.setattr(router.SystemService, 'build_llm_provider', AsyncMock(side_effect=RuntimeError('missing model')))
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'request_id': uuid4().hex, 'message': question, 'context': {'route': '/knowledge'}, **extra,
    })
    assert '检索到的教材' not in response.text
    retrieval.assert_not_awaited()
