"""A role-transition answer needs arbitration, failure detection and failback evidence."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.ai_text import router
from modules.ai_text.retrieval import expand_query, rerank
from modules.knowledge.local_provider import LocalKnowledgeProvider
from modules.knowledge.service import KnowledgeService
from tests.test_c3_request_api import api_case, events


TICKET = ('你是园区网运维人员。请只根据下面给定的文字拓扑和回显分析，不要声称已经连接或读取真实设备；'
          '这些回显是工单中粘贴的样例，不是实时状态。\n'
          'VLAN10/20，S2 GE0/0/1 物理抖动，VRRP PriorityRun 120→90，OSPF Full，MSTP TC 增加。')
FOLLOWUP = '现场结论只依据工单样例，不读取设备。请另查本地教材，解释 VRRP 上行跟踪和抢占延时的机制，列出对应出处。'


@pytest.mark.parametrize('query', [
    '只根据本地教材解释 VRRP 上行口变成 Down 如何影响运行优先级，列出出处。',
    'VRRP 的上联链路故障会怎么影响运行优先级？',
])
def test_uplink_outage_questions_use_specific_vrrp_priority_evidence(query):
    from modules.ai_text.retrieval import vrrp_mechanism_queries

    assert [focus.facet for focus in vrrp_mechanism_queries(query)] == ['降低优先级']


def test_explicit_bfd_comparison_stays_multisubject():
    from modules.ai_text.retrieval import vrrp_mechanism_queries

    assert vrrp_mechanism_queries('VRRP 上行故障时的优先级变化，与 BFD 会话跟踪有什么区别？') == []


def test_firewall_group_priority_is_not_vrrp_uplink_support():
    from modules.ai_text.retrieval import supports_vrrp_mechanism

    related = {'title': 'VGMP 组管理多个 VRRP 备份组',
               'content': '上行接口故障后降低 VGMP 组优先级，防火墙各处 VRRP 备份组跟随该组切换。'}
    assert not supports_vrrp_mechanism(related, '降低优先级')
actual_retrieve = router._retrieve


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
async def test_ticket_followup_retains_user_sample_and_retrieves_only_vrrp_mechanisms(api_case, monkeypatch, path):
    client, headers, model, _ = api_case
    # Save the actual entry point before the common api_case fixture replaces it.
    monkeypatch.setattr(router, '_retrieve', actual_retrieve)
    tracking = 'VRRP 监视上行端口。发生上行接口故障时，按配置降低 VRRP 运行优先级。'
    delay = 'VRRP 主备回切：设置抢占延时定时器，待恢复设备状态稳定后才回切。'
    hrp = 'HRP 监视上行端口并增加优先级。HRP不支持VRRP。设置抢占延时减少震荡。'
    search = AsyncMock(return_value=[{'title': '防火墙 HRP', 'text': hrp, 'page': 803},
        {'title': 'VRRP 监视上行', 'text': tracking, 'page': 1179, 'edition_version': 'test-edition'},
        {'title': 'VRRP 主备回切', 'text': delay, 'page': 1176, 'edition_version': 'test-edition'}])
    monkeypatch.setattr(router, '_get_knowledge_service', lambda: type('LocalSearch', (), {'search': search})())
    monkeypatch.setattr(router, '_resolve_page_data', AsyncMock(side_effect=AssertionError('current selection is unrelated')))
    monkeypatch.setattr(router, 'resolve_task_targets', AsyncMock(side_effect=AssertionError('device is out of scope')))
    monkeypatch.setattr(model, 'chat_completion', AsyncMock(side_effect=AssertionError('no tool planning')))
    prompts = []

    async def stream(prompt, system=None):
        prompts.append((prompt, system))
        answer = '样例记录不代表实时设备。'
        if len(prompts) == 2:
            answer += '上行跟踪故障可降低运行优先级[1]。恢复回切可按设置延时[2]。'
        yield {'kind': 'content', 'text': answer}

    monkeypatch.setattr(model, 'stream_parts', stream)
    original = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'message': TICKET, 'request_id': uuid.uuid4().hex, 'context': {'route': '/devices', 'selection': 'R1'}})
    assert original.status_code == 200 and not search.await_count
    assert 'PriorityRun 120→90' in prompts[0][0]
    followup = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'message': FOLLOWUP, 'request_id': uuid.uuid4().hex, 'context': {'route': '/monitor', 'selection': 'WRONG_OBJECT'},
        'history': [{'role': 'user', 'content': TICKET}, {'role': 'assistant', 'content': 'UNVERIFIED_HISTORY_CLAIM'}]})
    assert followup.status_code == 200, followup.text
    prompt, system = prompts[-1]
    assert 'PriorityRun 120→90' in prompt and '先前工单' in prompt
    assert 'WRONG_OBJECT' not in prompt and 'UNVERIFIED_HISTORY_CLAIM' not in prompt
    assert tracking in prompt and delay in prompt and hrp not in prompt
    assert 'PDF 物理页：1179' in prompt and 'PDF 物理页：1176' in prompt
    assert '正式故障等级' in system and '无需设备连接' in system
    assert {call.args[0] for call in search.await_args_list} == {
        'VRRP 监视上行端口', 'VRRP 抢占延时', 'VRRP 上行接口故障 降低优先级'}
    if path == '/chat':
        sources = followup.json()['sources']
    else:
        sources = next(event['sources'] for event in events(followup) if event['type'] == 'references')
    assert [source['page'] for source in sources] == [1179, 1176]


@pytest.mark.asyncio
async def test_frozen_edition_preserves_explicit_source_scope_and_avoids_legacy_fusion(monkeypatch):
    query = '依据《指定教材》PDF 第1179页，解释 VRRP 上行跟踪和抢占延时。'
    hit = {'filename': '指定教材', 'text': 'VRRP 上行监视在该页有明确说明。', 'page': 1179}
    edition = SimpleNamespace(version='frozen', has_search_scope=lambda text: text == query)
    service = KnowledgeService.__new__(KnowledgeService)
    service.provider = SimpleNamespace(name='local')
    service.edition = lambda: edition
    search = AsyncMock(return_value=[hit])
    legacy = AsyncMock(side_effect=AssertionError('legacy corpus must not enter frozen scope'))
    monkeypatch.setattr(router, '_get_knowledge_service', lambda: service)
    monkeypatch.setattr(router, 'cached_search', search)
    monkeypatch.setenv('AI_DUAL_RETRIEVAL', '1')
    monkeypatch.setattr(router.lexical_index, 'search', legacy)
    assert await actual_retrieve(query, 6) == [hit]
    search.assert_awaited_once_with(service, query, 6)
    legacy.assert_not_called()


@pytest.mark.parametrize('question', [
    'VRRP 的 Master 和 Backup 是怎么切换的？',
    'VRRP主备选举与故障切换有什么关系？',
])
def test_actual_corpus_transition_top_five_covers_mechanisms(tmp_path, question):
    provider = LocalKnowledgeProvider(storage_dir=tmp_path)
    expanded = expand_query(question)
    candidates = [{**hit, 'content': hit['text']} for hit in provider._search(expanded, 24)]
    selected = rerank(candidates, expanded, 6, original_query=question)
    top = '\n'.join(hit['content'] for hit in selected[:5])
    assert '值越大越优先' in top  # original textbook rule, not an injected answer
    assert 'MASTER_DOWN' in top and '超时' in top
    assert '抢占模式' in top
    assert len(selected) == 6
    assert all(any(hit is candidate for candidate in candidates) for hit in selected)


@pytest.mark.parametrize('question', [
    'VRRP报文的目的IP地址是什么？', 'VRRP虚拟MAC格式是什么？',
    'BGP 的主备怎么切换？', 'MYVRRP 的主备切换',
])
def test_unrelated_intents_keep_existing_expansion_and_ranking(question):
    assert 'MASTER_DOWN' not in expand_query(question)
    candidates = [{'content': '无关', 'score': 1}, {'content': '其他', 'score': .5}]
    assert rerank(candidates, expand_query(question), 2, original_query=question) == candidates


def test_expansion_alone_cannot_trigger_transition_promotion():
    candidates = [
        {'content': '# VRRP\n\n普通解释', 'score': 1},
        {'content': '# VRRP\n\n**Priority**：优先级值是选举依据。', 'score': .3},
    ]
    assert rerank(candidates, expand_query('VRRP主备切换'), 1,
                  original_query='VRRP报文目的地址') == candidates[:1]
