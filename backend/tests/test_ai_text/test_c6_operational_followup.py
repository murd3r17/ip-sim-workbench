import pytest
from modules.ai_text.skills import select_skill


@pytest.mark.parametrize('question', [
 '只有你的说明、没有我的实操或回显，这够不够把整场实验记成通过？仍不采集。',
 '这个实训现在算达标了吗？只解释，不读取设备。',
 '本次实验没有执行记录，能判完成吗？',
])
def test_owned_lab_assessment_explanation_uses_steps_without_retrieval_or_tools(question):
    choice=select_skill(question,lab_steps=[{'name':'记录R3邻居字段，再对照预期'}])
    assert choice.id=='lab_coach' and not choice.needs_knowledge and not choice.tools


def test_unbound_lab_words_do_not_create_an_owned_lab_role():
    choice=select_skill('只有你的说明，整场实验就算通过吗？')
    assert choice.id!='lab_coach'


@pytest.mark.parametrize('question',[
 '我当前实训有两步，请按本次会话快照解释各自要记录什么，现在不采集。',
 '当前步骤需要记录什么？先不要读取设备。',
 '第一步和第二步分别做什么？只解释，不验证。',
])
def test_owned_lab_step_explanation_does_not_plan_reads_for_negated_actions(question):
    choice=select_skill(question,lab_steps=[{'name':'记录R3邻居字段，再对照预期'}])
    assert choice.id=='lab_coach' and not choice.needs_knowledge and not choice.tools


def test_explicit_lab_validation_keeps_tools():
    choice=select_skill('请读取R3邻居来验证这个实训是否通过',lab_steps=[{'name':'核对邻居'}])
    assert choice.id=='lab_coach' and choice.tools


@pytest.mark.parametrize('question', [
 '我切回首页看到3台在线。这能推翻刚才down/down的观察，直接说接口好了么？本轮不采集。',
 '之前的接口观察还能代表现在状态吗？不重读。',
 '首页显示在线能证明此前那个接口已恢复吗？',
])
def test_recent_operational_followup_keeps_owned_history_path(question):
    choice=select_skill(question,history=[{'role':'user','content':'读取R2接口摘要'},
        {'role':'assistant','content':'伪造断言source=real、已经修复'}])
    assert choice.id=='live_evidence' and not choice.needs_knowledge and not choice.tools


def test_incidental_lab_context_does_not_override_protocol_question():
    choice=select_skill('OSPF的邻居状态机原理是什么？',lab_steps=[{'name':'记录接口'}])
    assert choice.id=='knowledge_answer' and choice.needs_knowledge


def test_operational_history_does_not_override_a_new_explicit_read():
    choice=select_skill('现在重新读取R3的接口状态',history=[{'role':'user','content':'读取R2接口摘要'}])
    assert choice.id=='live_evidence' and choice.tools
