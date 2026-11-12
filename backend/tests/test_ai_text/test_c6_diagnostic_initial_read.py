import json
from unittest.mock import AsyncMock
import pytest
from modules.ai_text.read_plan import initial_diagnostic_reads
from modules.ai_text.trusted_context import ResolvedTaskTargets
from modules.ai_text.tool_result import EvidenceText
from modules.ai_text.llm_service import LLMService


def targets():
    return ResolvedTaskTargets([{'device_id':2,'hostname':'R2'},{'device_id':3,'hostname':'R3'}],[],[],'now')


@pytest.mark.parametrize('question',['R2为什么访问不了R3？','R2到R3不通，先只读排查'])
def test_two_resolved_endpoints_start_with_readonly_summaries(question):
    calls=initial_diagnostic_reads(question,'troubleshooting',targets(),['run_display_command'])
    assert [json.loads(call['function']['arguments']) for call in calls]==[
        {'device_id':i,'command':'display ip interface brief'} for i in (2,3)]


@pytest.mark.parametrize('question',['不要读取，解释R2到R3不通的历史结论','R2到R3不通的原理是什么？',
                                     'R2为什么访问不了R99？','R2到R3不通，直接下发配置'])
def test_negation_concepts_unresolved_names_and_write_requests_keep_planning(question):
    assert not initial_diagnostic_reads(question,'troubleshooting',targets(),['run_display_command'])


@pytest.mark.asyncio
async def test_diagnostic_planning_receives_both_actual_initial_results(monkeypatch):
    from modules.ai_text import agent_tools
    reads=[];feedback=[]
    async def execute(db,name,args,*a,**k):
        reads.append(args['device_id'])
        return EvidenceText(f"R{args['device_id']} GE0/0/2 up up",target=str(args['device_id']),
            status='ok',completeness='complete',mode='sim',source='server_observed',collected_at='2026-11-06T00:00:00Z')
    class Provider:
        async def chat_completion(self,messages,tools=None):
            assert reads==[2,3]
            feedback.extend(json.loads(message['content']) for message in messages if message['role']=='tool')
            return {'tool_calls':[]}
        async def stream_parts(self,prompt,system=None):
            assert 'R2' in prompt and 'R3' in prompt
            yield {'kind':'content','text':'已读取两端摘要，业务是否可达仍需明确流量。'}
    monkeypatch.setattr(agent_tools,'execute_tool',execute)
    service=LLMService(user_id=1,provider=Provider(),actor={'user_id':1,'role':'user'})
    monkeypatch.setattr(service,'_log_request',AsyncMock())
    events=[e async for e in service.copilot_chat_stream('R2为什么访问不了R3？',
        ui_context={'skill_id':'troubleshooting','server_targets':targets()},allowed_tools=['run_display_command'],tier='diagnostic')]
    assert len(feedback)==2 and reads==[2,3]
    assert events[-1]['trace']['model_calls']==2
    assert events[-1]['trace']['read_plan_source']=='resolved_connectivity_summary'
