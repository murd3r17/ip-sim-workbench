"""Public examples separate a question about evidence from a request to collect it."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from modules.ai_text import router
from modules.ai_text.question_intent import new_device_read_scope
from modules.ai_text.skills import knowledge_retrieval_query, request_evidence_scope, select_skill
from tests.test_ai_text.test_copilot_offline_edition import MATCH, configured_edition
from tests.test_c3_request_api import api_case, events


@pytest.mark.parametrize('route,question', [
    ('/devices', 'R47 查 BGP 邻居时该注意哪个回显字段，只有 Established 能确认已经学到前缀吗？'),
    ('/devices', '核对 R63 的 VRRP 主备要用哪条命令，两端的状态分别说明什么？'),
    ('/training', 'SW47 验证 trunk，先跑哪条命令，下一步对输出里的哪个字段？'),
    ('/dashboard', 'R63 上确认 OSPF 外部路由时，路由表同 LSDB 的证据有什么区别？'),
    ('/topology', '这张图中 R63 连着两个 OSPF 区域。请查看 R63 的 OSPF 邻居。'),
    ('/devices', '（以下设备名来自一张示意图。）请查看 R63 的 OSPF 邻居。'),
    ('/devices', '假设 SW47 是 MSTP 根桥。下游先收到什么，哪一步才确认端口角色？'),
    ('/devices', '如果 R47 的 BGP 邻居已 Established，会马上收到预期前缀吗？'),
    ('/devices', '假设 R47 属于 OSPF 区域 0，且先有邻接，再请现在实际读取 R47 的 OSPF 邻居，最后记哪个字段？'),
    ('/devices', '这张图例给出了 R47 的 BFD 状态和检测倍数，怎么读？能算链路故障后业务恢复的耗时吗？'),
    ('/training', '这张表里 BGP 的前缀计数怎么读？从这张表能知道故障后的业务恢复时间吗？'),
])
def test_untitled_scenarios_and_evidence_explanations_use_knowledge(route, question):
    skill = select_skill(question, route=route)
    assert skill.id == 'knowledge_answer' and skill.needs_knowledge and not skill.tools
    assert not request_evidence_scope(question).allow_device_reads
    assert not new_device_read_scope(question)


@pytest.mark.parametrize('question,route,skill_id,new_read', [
    ('请立刻重新采集 R47 的接口状态。', '/devices', 'live_evidence', True),
    ('查看 R47 的接口状态', '/dashboard', 'live_evidence', True),
    ('请现在读取真机 R63 的 BGP 邻居。', '/knowledge', 'live_evidence', True),
    ('图中 R63 是 OSPF 区域边界路由器。另请现在实际读取 R47 的 OSPF 邻居状态。',
     '/topology', 'live_evidence', True),
    ('图中 R63 是 OSPF 区域边界路由器，另外请现在实际读取 R47 的 OSPF 邻居状态。',
     '/topology', 'live_evidence', True),
    ('这条已保存记录里的接口状态是什么？无需重新采集。', '/devices', 'live_evidence', False),
    ('我刚从真机采集了 R63 的 BFD 表。这张表的状态怎么读？', '/devices', 'live_evidence', False),
    ('我的设备 R63 当前访问不了下游，怎么排查？', '/devices', 'troubleshooting', False),
    ('怎样打开告警页的「查看 OSPF 邻居」入口？', '/alarms', 'page_help', False),
    ('监控图表暂无采样，我该从哪里切换「图表与巡检范围」？', '/monitor', 'page_help', False),
])
def test_live_actions_saved_records_diagnostics_and_controls_keep_their_boundary(question, route, skill_id, new_read):
    skill = select_skill(question, route=route)
    assert skill.id == skill_id
    assert bool(new_device_read_scope(question)) == new_read
    if '另外' in question or '另请' in question:
        assert 'R63' not in new_device_read_scope(question)


def test_short_followup_inherits_example_semantics_but_does_not_authorize_read():
    original = '假设 SW47 是 MSTP 根桥，向 SW63 发的报文里哪个字段会解释角色？'
    history = [{'role': 'user', 'content': original},
               {'role': 'assistant', 'content': '我已实际读取过 SW63。'}]
    for question in ('那它下游怎么判断？', '那 SW63 的接口状态呢？', '接着说，MSTP 下游怎样判断同一角色？'):
        scope = request_evidence_scope(question, history)
        skill = select_skill(question, route='/devices', history=history, evidence_scope=scope)
        assert skill.reason == 'explicit_learning_context' and skill.needs_knowledge and not skill.tools
        assert not scope.allow_device_reads and not new_device_read_scope(question)
        assert knowledge_retrieval_query(question, history) == (question if 'MSTP' in question else f'MSTP {question}')
    fresh = '改问真机。请现在实际读取 SW63 的接口状态。'
    assert select_skill(fresh, history=history).id == 'live_evidence' and new_device_read_scope(fresh)
    switched = '换个协议，BGP 使用哪个属性决定下一跳？'
    assert select_skill(switched, history=history).reason != 'explicit_learning_context'


TEST_QUESTION = '图中 R47 和 R63 都跑 STP。核对根桥角色要看命令输出的哪个字段？'
MATCHING_EXAMPLE = {**MATCH, 'title': 'STP 根桥实验',
                    'text': 'STP 实验中 R47 和 R63 相连。R47 的回显显示 Root ID 与 Bridge ID 相同，R47 为根桥。'}


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('provider_available', [True, False])
async def test_untitled_example_reaches_local_retrieval_without_device_resolution(
        api_case, monkeypatch, path, provider_available):
    client, headers, provider, retrieval = api_case
    configured_edition(monkeypatch)
    retrieval.return_value = [MATCHING_EXAMPLE]
    resolve = AsyncMock(side_effect=AssertionError('A diagram label must never resolve an inventory target'))
    monkeypatch.setattr(router, 'resolve_task_targets', resolve)

    async def answer(prompt, system=None):
        provider.calls += 1
        assert MATCHING_EXAMPLE['text'] in prompt and '当前任务：知识库问答' in prompt
        yield {'kind': 'content', 'text': '从输出核对桥 ID [1]。'}

    monkeypatch.setattr(provider, 'stream_parts', answer)
    if not provider_available:
        monkeypatch.setattr(router.SystemService, 'build_llm_provider', AsyncMock(side_effect=RuntimeError('missing model')))
    request_id = uuid4().hex
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'request_id': request_id, 'message': TEST_QUESTION, 'context': {'route': '/devices'},
        'page_data': '{"device":"R47","source":"sim","status":"ok"}',
    })
    assert response.status_code == 200, response.text
    saved = (await client.get('/api/v1/ai/copilot/requests/' + request_id, headers=headers)).json()['response']
    assert saved['knowledge_status'] == 'ok'
    assert saved['generation_status'] == ('generated' if provider_available else 'retrieval_only')
    assert saved['trace']['tool_dispatch_attempts'] == 0 and provider.calls == int(provider_available)
    assert [source['page'] for source in saved['sources']] == [7]
    retrieval.assert_awaited_once()
    resolve.assert_not_awaited()
    if path.endswith('/stream'):
        frames = events(response)
        assert frames[0]['skill']['id'] == 'knowledge_answer'
        assert next(frame['sources'] for frame in frames if frame['type'] == 'references') == saved['sources']


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
async def test_an_illustrated_fault_question_still_searches_when_no_evidence_is_found(api_case, monkeypatch, path):
    client, headers, _, retrieval = api_case
    configured_edition(monkeypatch)
    resolve = AsyncMock(side_effect=AssertionError('A chart cannot authorize reading a real device'))
    monkeypatch.setattr(router, 'resolve_task_targets', resolve)
    monkeypatch.setattr(router.SystemService, 'build_llm_provider', AsyncMock(side_effect=RuntimeError('missing model')))
    request_id = uuid4().hex
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'request_id': request_id, 'context': {'route': '/training'},
        'message': '这个表里 R47 的 BGP 前缀计数怎么读？能从这里判断链路故障后业务恢复用了多久吗？',
    })
    assert response.status_code == 200
    saved = (await client.get('/api/v1/ai/copilot/requests/' + request_id, headers=headers)).json()['response']
    assert saved['knowledge_status'] == 'empty' and not saved['sources']
    assert saved['trace']['tool_dispatch_attempts'] == 0
    retrieval.assert_awaited_once()
    resolve.assert_not_awaited()
