"""Product help for existing views uses no language model or operational tool."""
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from modules.ai_text import router
from modules.ai_text.question_intent import read_only_workbench_answer, workflow_question
from modules.ai_text.skills import select_skill
from tests.test_c3_request_api import api_case, events


CASES = [
    ('/training', '从哪看下一课实验的课前要求？我只预习，原来的会话要留着。', 'training_preview',
     ('实验名称', '实验步骤', '先修与环境', '我的实训会话', '进行中'), ('新建/启动实验', '课程名称/详情')),
    ('/knowledge', '已经从 PDF 复制原文了，怎么在知识库找到那张原页并回到结果？', 'original_quote_navigation',
     ('检索资料', '原书原句', '查看原页', '返回正文', '返回原页面', 'PDF 物理页'), ('先在「教材正文」',)),
    ('/knowledge', '老师发的原书那一页已经有命中，点开后怎么查看，读完如何回到原筛选的列表？', 'original_reader_return',
     ('查看原页', '返回正文', '返回原页面', '保留筛选条件和命中列表', '返回检索结果'), ('新标签页', '新窗口', '重新输入')),
    ('/dashboard', '我从历史对话打开原回答的引用，看完正文后怎样回到同一条答复？', 'copilot_citation_return',
     ('历史', '阅读同版正文', '返回原页面', '返回对话', '无需重发问题'), ('新标签页', '返回检索结果')),
    ('/monitor', '只想重新显示已有监控曲线，不再采样。点哪里，显示的是刷新时点还是原采样时点？', 'monitor_saved_samples',
     ('刷新已保存记录', '所选拓扑最近采样', '特定曲线点', '刷新观察', '不能替代样本自己的采样时点'),
     ('以查询窗口为准', '选「新建采样任务」')),
    ('/approvals', '模拟回执只留在课堂任务里，交接总结怎么写才能区分真实下发和设备回读？', 'simulation_report',
     ('同一任务', '详情', '查看结果', '生产执行与设备回读未核验'), ('点击「执行」', '点击「核对回读」')),
    ('/config-versions', '换页了，要打开已有某条历史快照看配置。现在点哪个按钮？', 'single_snapshot_view',
     ('配置快照', '「操作」列点「查看」', '设备', '来源', '时间'), ('点「AI 说明差异」', '详情类')),
    ('/config-versions', '只把一条以前保存的配置快照下载成文件，到哪里点？不用读设备。', 'snapshot_download',
     ('配置快照', '「操作」列点「导出」', '导出已选快照', '「查看」只打开内容弹窗', '采集并保存配置'),
     ('已经下载', '点「采集并保存配置」')),
    ('/deploy', '配置还没写完，我想暂存后离开页面再回来继续编辑。哪个动作只保留文字，怎样确认没建变更？', 'draft_staging',
     ('暂存草稿', '恢复暂存草稿', '与当前内容一致', '2 小时', '校验配置', '提交待确认', '配置批次'), ('已经保存你的草稿', '点「执行」')),
]


@pytest.mark.parametrize('route,question,workflow,needed,forbidden', CASES)
def test_readonly_workflow_is_named_before_knowledge_retrieval(route, question, workflow, needed, forbidden):
    assert workflow_question(question, route) == workflow
    answer = read_only_workbench_answer(question, route)
    assert all(text in answer for text in needed) and all(text not in answer for text in forbidden)
    skill = select_skill(question, route=route)
    assert skill.id == 'page_help' and not skill.needs_knowledge and not skill.tools


@pytest.mark.parametrize('route,question', [
    ('/training', '先修已经看完了，怎样开始实训？'),
    ('/approvals', '现在真实设备任务已执行待核对，如何发起核验？'),
    ('/knowledge', '请根据教材解释 GRE over IPsec 的分工，并给原页。'),
    ('/config-versions', 'A 与 B 两份配置快照有什么差异？'),
    ('/monitor', '预习笔记里 OSPF 的 LSA 是什么意思？'),
    ('/monitor', '请按教材解释 OSPF 邻居状态和百秒采样的关系，给出处。'),
    ('/knowledge', '请用原书原句查找“包含邻居保持时间和计数的那一行”出现在哪一页。'),
    ('/config-versions', '请现在读取 R4 的接口摘要。'),
])
def test_other_intents_do_not_get_canned_navigation(route, question):
    assert not read_only_workbench_answer(question, route)


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat','/chat/stream'])
@pytest.mark.parametrize('route,question,workflow,needed,forbidden', CASES)
async def test_product_help_delivers_exact_navigation_without_provider(api_case, monkeypatch, path, route, question, workflow, needed, forbidden):
    client, headers, _, retrieval = api_case
    provider = AsyncMock(side_effect=AssertionError('Navigation is available when the model is off'))
    monkeypatch.setattr(router.SystemService, 'build_llm_provider', provider)
    old_answer = 'Previous unrelated source: [1] OLD_BOOK_SENTINEL'
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'request_id': uuid4().hex, 'context': {'route': route}, 'message': question,
        'history': [{'role':'assistant','content':old_answer}],
    })
    assert response.status_code == 200
    if path == '/chat':
        body = response.json()
        answer, trace = body['answer'], body['trace']
        assert body['knowledge_status'] == 'not_requested' and body['sources'] == []
    else:
        frames = events(response)
        answer = ''.join(event['text'] for event in frames if event['type'] == 'token')
        trace = next(event['trace'] for event in frames if event['type'] == 'done')
        assert next(event['knowledge_status'] for event in frames if event['type'] == 'meta') == 'not_requested'
        assert next(event['sources'] for event in frames if event['type'] == 'references') == []
    assert trace['model_calls'] == trace['tool_dispatch_attempts'] == 0
    assert all(text in answer for text in needed)
    assert all(text not in answer for text in (*forbidden, 'OLD_BOOK_SENTINEL', '[1]'))
    provider.assert_not_awaited()
    retrieval.assert_not_awaited()
