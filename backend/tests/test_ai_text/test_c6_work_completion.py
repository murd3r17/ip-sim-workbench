"""Act on explicit comparisons; do not confuse current fields with concepts."""
import json
from unittest.mock import AsyncMock

import pytest

from modules.ai_text.skills import select_skill
from modules.ai_text.trusted_context import ResolvedTaskTargets
from modules.ai_text.tool_result import EvidenceText
from modules.ai_text.llm_service import LLMService


@pytest.mark.parametrize('message', ['R1 的 OSPF 邻居是什么状态？', 'R2 的接口地址是什么？'])
def test_exact_current_fields_do_not_need_textbook_retrieval(message):
    choice = select_skill(message)
    assert choice.id == 'live_evidence' and not choice.needs_knowledge


@pytest.mark.parametrize('message', ['R1 的 OSPF 邻居 Full 是什么意思？', 'R1 的 OSPF 邻居建立机制是什么？'])
def test_explanation_of_a_field_still_can_use_textbook_sources(message):
    assert select_skill(message).needs_knowledge


def targets():
    return ResolvedTaskTargets([{'device_id':1,'hostname':'R1'}, {'device_id':2,'hostname':'R2'}], [], [], 'now')


@pytest.mark.asyncio
async def test_explicit_two_device_comparison_really_reads_both_without_planning(monkeypatch):
    from modules.ai_text import agent_tools
    reads = []
    async def execute(db, name, args, *a, **kw):
        reads.append(args)
        return EvidenceText('AUTHORED_DEVICE_' + str(args['device_id']), target=str(args['device_id']),
                            status='ok', source='server_observed', mode='sim', completeness='complete')
    class Provider:
        async def chat_completion(self, *a, **kw):
            raise AssertionError('Explicit interface comparison must not spend a planning call')
        async def stream_parts(self, prompt, system=None):
            assert all('AUTHORED_DEVICE_' + str(i) in prompt for i in (1,2))
            yield {'kind':'content','text':'已取得两端本次实际结果。'}
    monkeypatch.setattr(agent_tools, 'execute_tool', execute)
    service = LLMService(user_id=1, provider=Provider(), actor={'user_id':1,'role':'user'})
    monkeypatch.setattr(service, '_log_request', AsyncMock())
    events = [e async for e in service.copilot_chat_stream('对比 R1 和 R2 的接口地址。',
        ui_context={'skill_id':'live_evidence','server_targets':targets()},
        allowed_tools=['run_display_command'], tier='standard')]
    assert reads == [{'device_id':i,'command':'display ip interface brief'} for i in (1,2)]
    trace = events[-1]['trace']
    assert trace['model_calls'] == 1 and trace['tool_calls'] == 2
    assert trace['read_plan_source'] == 'resolved_interface_comparison'
    assert trace['evidence_stop_reason'] == 'requested_read_complete'


@pytest.mark.parametrize('message', ['不要读取，对比刚才R1和R2的接口地址', '对比R1与R99的接口地址',
                                     '对比R1与R2接口和OSPF邻居', 'R1与R2接口地址的配置原理是什么'])
def test_comparison_short_path_never_widens_history_unknown_or_composite_requests(message):
    from modules.ai_text.read_plan import initial_comparison_reads
    assert not initial_comparison_reads(message, 'live_evidence', targets(), ['run_display_command'])


def test_ssh_algorithm_examples_are_not_an_unconditional_recommendation():
    from modules.ai_text.context_bundle import prepare_sources
    claim = 'SSH 使用的算法类别包括 MAC、加密、密钥交换、主机公钥（RSA/DSA）等。'
    source = prepare_sources([{'filename':'12-dhcpv6与防火墙基础.md','text':claim}])[0]
    assert source['content'] == claim
    assert source['reviewed_notes'] and 'OpenSSH' in source['reviewed_notes'][0]['reference']
    assert '不等同于' in source['reviewed_notes'][0]['content']


@pytest.mark.asyncio
async def test_new_device_followup_actually_reads_the_previous_user_requested_field(monkeypatch):
    from modules.ai_text import agent_tools
    reads=[]
    async def execute(db,name,args,*a,**kw):
        reads.append(args)
        return EvidenceText('FOLLOWUP_R3_INTERFACE',status='ok',target='3',source='server_observed',mode='sim')
    class Provider:
        async def chat_completion(self,*args,**kwargs):
            raise AssertionError('Explicit field followup does not need planning')
        async def stream_parts(self,prompt,system=None):
            assert 'FOLLOWUP_R3_INTERFACE' in prompt
            yield {'kind':'content','text':'R3本次实际接口结果。'}
    monkeypatch.setattr(agent_tools,'execute_tool',execute)
    service=LLMService(user_id=1,provider=Provider(),actor={'user_id':1,'role':'user'})
    monkeypatch.setattr(service,'_log_request',AsyncMock())
    current=ResolvedTaskTargets([{'device_id':3,'hostname':'R3'}],[],[],'now')
    rows=[e async for e in service.copilot_chat_stream('那 R3 呢？',
        history=[{'role':'user','content':'对比 R1 和 R2 的接口地址。'},
                 {'role':'assistant','content':'未经核验的历史主张不能决定新设备状态'}],
        ui_context={'skill_id':'live_evidence','server_targets':current},
        allowed_tools=['run_display_command'],tier='standard')]
    assert reads==[{'device_id':3,'command':'display ip interface brief'}]
    assert rows[-1]['trace']['model_calls']==1
    assert rows[-1]['trace']['read_plan_source']=='resolved_field_followup'


@pytest.mark.parametrize('prior',['解释R1的OSPF原理','不要读取R1接口状态','查看昨天R1接口地址',
                                  'R1为什么不通','生成R1接口配置','对比R1与R3的接口地址'])
def test_device_followup_never_turns_past_concepts_negation_or_writes_into_reads(prior):
    from modules.ai_text.read_plan import initial_followup_read
    current=ResolvedTaskTargets([{'device_id':3,'hostname':'R3'}],[],[],'now')
    assert not initial_followup_read('那R3呢？','live_evidence',current,['run_display_command'],
                                     [{'role':'user','content':prior}])
