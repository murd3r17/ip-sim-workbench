import json
from unittest.mock import AsyncMock
import pytest
from modules.ai_text.tool_result import classify,ToolOutcome


def test_structured_summary_retains_bounded_rows_and_explicit_overall_partial_scope():
    text='已保存范围统计:\n'+json.dumps({'ports_total':20,'ports_shown':8,'ports_truncated':True,'ports':[{'name':f'GE0/0/{i}','purpose':'unknown','assessment':'review_down'} for i in range(8)]})+'\n说明：'+'有限范围。'*240
    assert 1500<len(text)<4500
    outcome=ToolOutcome('query_device_detail','ok',text=text,completeness='partial',truncated=True)
    result=json.loads(outcome.as_json())
    assert result['text']==text and result['truncated'] and result['completeness']=='partial'
    large=classify('query_device_detail',{},text*4)
    assert large.truncated and large.completeness=='partial'
    assert len(json.loads(large.as_json())['text'])<=4500
    assert classify('query_devices',{},text).truncated  # generic budgets unchanged


@pytest.mark.asyncio
async def test_device_tool_counts_shown_total_and_omitted_ports(test_session_factory,monkeypatch):
    from tests.test_monitor.test_d06_ports import device
    from modules.ai_text.agent_tools import _query_device_detail
    from modules.monitor import port_service
    state={'fresh':False,'policy_changed':True,'mode_changed':False,'latest_attempt':None,
        'policy':{'ports':[{'name':f'GE0/0/{i}'} for i in range(11)],'valid':True},
        'observation':{'ports':[{'name':f'GE0/0/{i}','assessment':'review_down'} for i in range(20)],
            'missing_expected_ports':[f'GE1/0/{i}' for i in range(14)],'expected_down':0,'review_count':20,'complete':True}}
    monkeypatch.setattr(port_service,'get_port_state',AsyncMock(return_value=state))
    async with test_session_factory() as db:
        d=await device(db);text=await _query_device_detail(db,{'device_id':d.id})
    payload=json.loads(text.split('已保存端口观察（不新采集、不证明业务可达）: ')[1])
    assert (payload['ports_total'],payload['ports_shown'],len(payload['ports']))==(20,8,8)
    assert payload['expectations_total']==11 and payload['expectations_shown']==8 and payload['expectations_truncated']
    assert payload['missing_expected_ports_total']==14 and payload['missing_expected_ports_shown']==12 and payload['missing_expected_ports_truncated']
    assert payload['expected_down']==0 and payload['review_count']==20 and not payload['fresh']
    assert '分类数仅代表所示项' in payload['scope_note']
