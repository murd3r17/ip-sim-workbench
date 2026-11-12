from unittest.mock import AsyncMock

import pytest

from modules.ai_text.trusted_context import ResolvedTaskTargets


def targets(**changes):
    values=dict(resolved=[{'device_id':2,'hostname':'R12'}],unresolved=[],ambiguous=[],read_at='now')
    values.update(changes)
    return ResolvedTaskTargets(**values)


@pytest.mark.parametrize('question,command', [
    ('请只读查看这台R12的接口摘要，说明本次观察的接口状态，不改配置。','display ip interface brief'),
    ('更正，现在核对R13的接口摘要，请重新读取，不沿用旧观察。','display ip interface brief'),
    ('请读取R12的OSPF邻居摘要','display ospf peer'),
    ('查询R12的IP路由表','display ip routing-table'),
    ('R12 现在的接口地址是什么？','display ip interface brief'),
    ('R12 的 OSPF 邻居是 Full 吗？','display ospf peer'),
    ('R12 的接口是 up 吗？','display ip interface brief'),
])
def test_explicit_read_uses_one_unique_server_target(question,command):
    from modules.ai_text.read_plan import initial_read
    identity=targets(resolved=[{'device_id':3,'hostname':'R13'}]) if 'R13' in question else targets()
    plan=initial_read(question,'live_evidence',identity,['run_display_command'])
    assert plan['function']['name']=='run_display_command'
    import json
    assert json.loads(plan['function']['arguments'])=={'device_id':identity.resolved[0]['device_id'],'command':command}


@pytest.mark.parametrize('question,skill,identity,allowed', [
    ('不要采集新数据，解释历史接口摘要','live_evidence',targets(),['run_display_command']),
    ('查看R99的接口摘要','live_evidence',targets(unresolved=['R99']),['run_display_command']),
    ('查看接口摘要','live_evidence',targets(ambiguous=['R12']),['run_display_command']),
    ('查看两端接口摘要','live_evidence',targets(resolved=[{'device_id':2},{'device_id':3}]),['run_display_command']),
    ('查看接口摘要','live_evidence',{'resolved':[{'device_id':2}]},['run_display_command']),
    ('查看接口摘要','live_evidence',targets(),[]),
    ('查看接口摘要的命令是什么意思','knowledge_answer',targets(),['run_display_command']),
    ('接口Up为何仍不通，请排查','troubleshooting',targets(),['run_display_command']),
    ('不是R12，查看R13的接口摘要','live_evidence',targets(),['run_display_command']),
    ('读取接口摘要和OSPF邻居摘要','live_evidence',targets(),['run_display_command']),
    ('R12的OSPF邻居Full能证明业务正常吗？','live_evidence',targets(),['run_display_command']),
    ('不要查询R12的OSPF邻居是Full吗','live_evidence',targets(),['run_display_command']),
    ('R12接口是什么类型？','live_evidence',targets(),['run_display_command']),
])
def test_other_requests_keep_existing_planning(question,skill,identity,allowed):
    from modules.ai_text.read_plan import initial_read
    assert initial_read(question,skill,identity,allowed) is None


@pytest.mark.asyncio
async def test_actual_executor_read_happens_without_planning_generation(monkeypatch):
    from modules.ai_text import agent_tools
    from modules.ai_text.llm_service import LLMService
    from modules.ai_text.tool_result import EvidenceText
    class Provider:
        model='controlled-explicit-read'
        async def chat_completion(self,*a,**k):
            raise AssertionError('An explicit read must not depend on model planning')
        async def stream_parts(self,prompt,system=None):
            assert 'up up' in prompt and '模拟' in prompt
            yield {'kind':'content','text':'本次模拟接口摘要显示该接口up/up。'}
    execute=AsyncMock(return_value=EvidenceText('GE0/0/1 up up',status='ok',completeness='complete',
        source='server_observed',mode='sim',target='2',collected_at='2026-11-06T00:00:00Z'))
    monkeypatch.setattr(agent_tools,'execute_tool',execute)
    service=LLMService(db=None,user_id=1,provider=Provider(),actor={'user_id':1,'role':'user'})
    monkeypatch.setattr(service,'_log_request',AsyncMock())
    stream=[e async for e in service.copilot_chat_stream('请只读查看R12的接口摘要，不改配置。',
        ui_context={'skill_id':'live_evidence','server_targets':targets()},allowed_tools=['run_display_command'])]
    assert execute.await_count==1
    trace=stream[-1]['trace']
    assert trace['model_calls']==1 and trace['tool_dispatch_attempts']==1
    assert trace['read_plan_source']=='explicit_request'
    assert trace['evidence_stop_reason']=='requested_read_complete'
    assert ''.join(e.get('text','') for e in stream if e['type']=='token')=='本次模拟接口摘要显示该接口up/up。'
