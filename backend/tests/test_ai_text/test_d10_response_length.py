import pytest
from modules.ai_text.response_length import character_limit,length_instruction

@pytest.mark.parametrize('question,expected',[
 ('150字以内。',150),('请用180字符内解释',180),('不超过100个字',100),
 ('最多200字，摘要120字以下',120),('详细解释，不限字数',None),('计数为150字，为什么',None),
 ('设备报错码1000，端口20，问题是什么',None),('10字内',None),('2001字以内',None)])
def test_explicit_limits_only(question,expected):
    assert character_limit(question)==expected
    assert bool(length_instruction(question))==(expected is not None)


def test_both_direct_and_live_context_get_budget_without_removing_question_or_evidence():
    from modules.ai_text.llm_service import LLMService
    from modules.ai_text.diagnostic_answer import build_answer_context
    q='R2接口是否正常？150字以内'
    direct=LLMService.__new__(LLMService)._build_copilot_prompt(q)
    live=build_answer_context(q,[{'tool':'read','text':'接口up','completeness':'complete'}])
    assert '约97字符' in direct and '约97字符' in live
    assert q in direct and q in live and '接口up' in live


def test_report_budget_counts_fields_separately_and_ignores_unrecognized_limits():
    from modules.ai_text.response_length import report_length_instruction
    plan=report_length_instruction({'summary':60,'report_text':300,'sources':1,'other':True})
    assert 'summary字段上限60字符' in plan and 'report_text字段上限300字符' in plan
    assert '约195字符' in plan and 'sources' not in plan
    assert report_length_instruction({'report_text':True})==''
