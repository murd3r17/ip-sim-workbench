"""Direct evidence must belong to the asked object and cover each requested field."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from modules.ai_text import router
from modules.ai_text.context_bundle import prepare_sources
from modules.ai_text.evidence_refinement import direct_evidence_limit, refine_sources
from modules.ai_text.question_intent import new_device_read_scope
from modules.ai_text.skills import request_evidence_scope, select_skill
from modules.knowledge.service import KnowledgeService
from tests.test_c3_request_api import api_case, events


EDITION = 'public-synthetic-edition'
DOC = 'example-routing'
PREFIX = '198.51.100.64/26'
QUESTION = f'教材案例 4 中，R12 的 BGP 路由表里 {PREFIX} 的下一跳和类型各是什么？'
NEXT_HOP = '192.0.2.6'
ROUTE_TYPE = 'eBGP'


def hit(page, body, *, doc=DOC, title='BGP 路由读回', edition=EDITION):
    return {'page': page, 'filename': f'{doc}.md', 'title': title, 'book_title': '公开合成读本',
            'document_id': doc, 'document_version': f'{doc}-sha', 'section_id': f'page-{page}',
            'edition_version': edition, 'text': f'### PDF 第 {page} 页\n\n{body}'}


def test_sign_off_question_keeps_the_observation_and_its_documented_limit():
    question = '只依据教材，这条 BGP 回显能给“业务已恢复”这一项打勾吗？还差什么记录？'
    direct = hit(62, 'BGP 会话状态为 Established。不能据此确认业务已恢复。还需另外测量业务恢复情况。')
    irrelevant = hit(69, 'BGP 会话状态为 Established。未记录其他会话。')
    sources = prepare_sources([direct, irrelevant])
    support, message = direct_evidence_limit(question, sources)
    assert support == sources[:1] and '业务已恢复' in message
    assert direct_evidence_limit(question, sources[1:]) is None
    assert direct_evidence_limit(question.replace('教材', '现场'), sources) is None


@pytest.mark.parametrize('intro', ['教材目前只看到一条接口记录。', '做练习只看到一条接口记录。'])
def test_one_rate_table_cannot_measure_service_continuity_or_elapsed_time(intro):
    question = (intro + '能不能把“业务全程连续”和“事件耗时低于10秒”这两项都打勾？'
                '这能证明什么，还差什么？')
    record = hit(61, '```text\n<R8>display interface summary\nTime       Link Speed\n06:10:31   Up   1000 Mbps\n```')
    plan = hit(63, '```text\n[R8]interface GigabitEthernet0/0/1\n[R8-GigabitEthernet0/0/1]speed 1000\n```')
    overview = hit(67, '业务探测和事件计时采用独立的测量窗口。')
    sources = prepare_sources([plan, record, overview])
    support, notice = direct_evidence_limit(question, sources)
    assert support == [sources[1]]
    assert '连续业务探测' in notice and '起止记录' in notice
    alternative = hit(68, '```text\n<R9>display test-results\nElapsed: 3.1 s\nPacket Loss: 0%\n```')
    assert direct_evidence_limit(question, prepare_sources([plan, record, alternative])) is None
    assert direct_evidence_limit(question, prepare_sources([plan, overview])) is None


def route_hop():
    return hit(64, f'''#### 案例 4

```text
<R12>display ip routing-table protocol bgp
Destination/Mask     Type     Cost      NextHop
{PREFIX}     --       50        {NEXT_HOP}
```''')


def route_type():
    return hit(65, f'**案例 4 的后续回显。** R12 的 BGP 路由表中，{PREFIX} 的 Type 为 {ROUTE_TYPE}。')


def other_material():
    return [
        hit(70, f'**案例 5。** R12 的 BGP 路由表中，{PREFIX} 的下一跳为 192.0.2.64，Type 为 iBGP。'),
        hit(71, f'**案例 4。** R12 的 BGP 路由表规划为 {PREFIX} 下一跳 192.0.2.74。', doc='address-plan'),
        hit(72, f'**案例 4。** 这一段提到了 BGP。R12 的 OSPF 路由表参考 BGP 引入说明，'
                f'{PREFIX} 的下一跳为 192.0.2.9，Type 为 E2。', title='OSPF 和 BGP 读回对照', doc='other-protocol'),
        hit(73, f'**案例 4。** R99 的 BGP 路由表中，{PREFIX} 的下一跳为 192.0.2.10，Type 为 iBGP。',
            doc='other-owner'),
        hit(74, 'R12 的 BGP 路由表中，198.51.100.128/26 的下一跳为 192.0.2.22，Type 为 iBGP。'),
    ]


def test_typed_evidence_keeps_both_needed_pages_and_drops_concrete_mismatches():
    sources = prepare_sources([*other_material()[:3], route_hop(), route_type()])
    chosen, reason = refine_sources(QUESTION, sources, EDITION)
    assert reason == 'direct_route_record'
    assert chosen == sources[-2:]
    assert NEXT_HOP in chosen[0]['content'] and ROUTE_TYPE in chosen[1]['content']


def test_vrrp_requires_attributable_evidence_for_each_mechanism():
    question = '只用教材解释 VRRP 的上行接口跟踪和抢占延时各起什么作用，分别给依据。'
    weak = hit(155, 'VRRP 上行接口跟踪可以监视上游故障，运行优先级需要核对。\n\n'
                    'HRP 检测到端口故障后可降低优先级，HRP 的切换延时让设备等待。',
               title='VRRP 和 HRP 的资料对照')
    tracking = hit(156, 'VRRP 上行接口跟踪。上行接口故障后，已启用跟踪的设备可降低运行优先级。',
                   title='VRRP 主备机制')
    delay = hit(157, 'VRRP 抢占延时为恢复后重新接管预留稳定时间。', title='VRRP 主备机制')
    pool = prepare_sources([weak, tracking, delay])
    selected, decision = refine_sources(question, pool, EDITION)
    assert decision == 'direct_mechanism' and selected == pool[1:]
    insufficient = prepare_sources([weak, delay])
    assert refine_sources(question, insufficient, EDITION)[0] is insufficient
    extra_question = question.replace('抢占延时', '抢占延时以及虚拟 MAC')
    assert refine_sources(extra_question, pool, EDITION)[0] is pool


@pytest.mark.parametrize('mode', ['missing', 'no_observation', 'ambiguous', 'unknown_field', 'multi_task', 'unverified', 'mixed_phase'])
def test_inconclusive_evidence_keeps_existing_candidates(mode):
    sources = [route_hop(), route_type(), *other_material()[:3]]
    query = QUESTION
    if mode == 'missing':
        sources.pop(1)
    elif mode == 'no_observation':
        sources[1] = hit(65, f'**案例 4。** R12 的 BGP 路由表中未显示 {PREFIX} 的 Type，可能是 eBGP。')
    elif mode == 'ambiguous':
        sources.append(hit(80, f'**案例 4。** R12 的 BGP 路由表中，{PREFIX} 的下一跳为 192.0.2.19，Type 为 iBGP。',
                           doc='competing-example'))
    elif mode == 'unknown_field':
        query = query.replace('下一跳和类型', '下一跳、出接口和类型')
    elif mode == 'multi_task':
        query += '另外请说明它能否用作实际业务验收。'
    elif mode == 'unverified':
        sources[1]['edition_version'] = 'old'
    elif mode == 'mixed_phase':
        query = query.replace('案例 4 中', '案例 4 故障前后')
    prepared = prepare_sources(sources)
    selected, reason = refine_sources(query, prepared, EDITION)
    assert selected is prepared and reason.startswith('unchanged')


def test_explicit_classroom_record_uses_knowledge_without_granting_device_reads():
    scope = request_evidence_scope(QUESTION)
    skill = select_skill(QUESTION, route='/knowledge', evidence_scope=scope)
    assert skill.id == 'knowledge_answer' and skill.needs_knowledge and not skill.tools and not scope.allow_device_reads
    fresh = f'请现在读取 R12 真实设备上 {PREFIX} 的路由表。'
    assert new_device_read_scope(fresh) and request_evidence_scope(fresh).allow_device_reads
    mixed = QUESTION + '请现在读取 R12 的真机接口状态。'
    assert new_device_read_scope(mixed) and request_evidence_scope(mixed).allow_device_reads


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
async def test_prompt_and_recoverable_references_share_only_the_verified_experiment(api_case, monkeypatch, path):
    client, headers, provider, retrieval = api_case
    retrieved = [*other_material()[:3], route_hop(), route_type()]
    retrieval.return_value = retrieved
    edition = SimpleNamespace(version=EDITION, documents={row['document_id']: {'sha256': row['document_version']} for row in retrieved},
                              read=Mock(return_value={'original_pages': [
                                  {'physical': row['page'], 'section_id': row['section_id'], 'evidence_eligible': True} for row in retrieved
                              ]}))
    service = object.__new__(KnowledgeService)
    monkeypatch.setattr(service, 'edition', lambda: edition)
    monkeypatch.setattr(service, 'legacy_locator', AsyncMock(return_value={}))
    monkeypatch.setattr(service, 'list_documents', AsyncMock(return_value=[{'id': DOC, 'filename': f'{DOC}.md'}]))
    monkeypatch.setattr(router, '_get_knowledge_service', lambda: service)
    prompts = []

    async def model(prompt, system=None):
        provider.calls += 1
        prompts.append(prompt)
        yield {'kind': 'content', 'text': '下一跳见[1]，类型见[2]。'}

    monkeypatch.setattr(provider, 'stream_parts', model)
    request_id = uuid4().hex
    reply = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'request_id': request_id, 'message': QUESTION, 'context': {'route': '/knowledge'}
    })
    assert reply.status_code == 200
    saved = (await client.get(f'/api/v1/ai/copilot/requests/{request_id}', headers=headers)).json()['response']
    assert saved['generation_status'] == 'generated' and saved['trace']['tool_dispatch_attempts'] == 0
    assert provider.calls == 1
    sources = (reply.json()['sources'] if path == '/chat' else
               next(frame['sources'] for frame in events(reply) if frame['type'] == 'references'))
    assert saved['sources'] == sources and [item['page'] for item in sources] == [64, 65]
    prompt, = prompts
    assert all(value not in prompt for value in ('192.0.2.64', '192.0.2.74', '192.0.2.9'))
    for index, source in enumerate(sources, 1):
        read = await client.get('/api/v1/ai/copilot/citations/read', headers=headers, params={
            'request_id': request_id, 'filename': source['filename'], 'source_id': source['source_id'],
        })
        assert read.status_code == 200 and read.json()['scope'] == 'answer_excerpt'
        assert read.json()['content'] == source['content']
        assert f'来源[{index}]' in prompt and source['content'] in prompt
