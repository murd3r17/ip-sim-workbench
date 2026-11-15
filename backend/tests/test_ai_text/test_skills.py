from modules.ai_text.skills import select_skill

def test_draft_skill_wins():
    assert select_skill("帮我改接口", want_draft=True).id == "config_draft"

def test_troubleshooting_beats_page():
    assert select_skill("R2 访问不了 R3，怎么排查").id == "troubleshooting"

def test_page_help():
    assert select_skill("这个页面能做什么？").id == "page_help"

def test_live_evidence_when_page_data_present():
    assert select_skill("这些数字什么意思", page_data='{"source":"sim"}').id == "live_evidence"

def test_knowledge_default():
    assert select_skill("OSPF 的 LSA 有哪些类型").id == "knowledge_answer"

def test_lab_coach():
    assert select_skill("下一步怎么做", lab_steps=[{"id": "1"}]).id == "lab_coach"


def test_reading_persisted_workbench_state_stays_in_page_help():
    tasks = [
        ('/monitor', '我想看看早上保存的端口回显，应该在哪个页面点开？'),
        ('/training', '旧实验结束以后，从哪找我当时的记录和复盘？'),
        ('/knowledge', '我找到知识库片段了，怎么打开同版书页？'),
        ('/knowledge', '知识库搜索并打开片段详情，进入同版正文再返回的操作顺序是什么？'),
        ('/dashboard', '工作台重新加载会更新哪些内容，还是要采集？'),
        ('/approvals', '审批页面这条是已确认未执行，执行之后去哪回读？'),
        ('/dashboard', '回答尚未确认完成，真的没找到时如何把原提问填回输入框？'),
    ]
    for route, question in tasks:
        skill = select_skill(question, route=route)
        assert skill.id == 'page_help', (route, question)
        assert not skill.needs_knowledge and not skill.tools


def test_provided_inspection_record_can_be_read_without_implicit_device_calls():
    history = [{'role': 'user', 'content': '人工巡检报告里 R-2 跳过。'}]
    skill = select_skill('只依据那次巡检记录，R-2 当时正常吗？', route='/monitor', history=history)
    assert skill.id == 'live_evidence'
    assert not skill.tools and not skill.needs_knowledge


def test_question_about_the_next_field_in_an_owned_lab_reads_the_frozen_step():
    skill = select_skill('我刚开了实训新会话。第一步只读先观察哪个协议字段？',
                         route='/training', lab_steps=[{'id': '1'}])
    assert skill.id == 'lab_coach'
    assert not skill.tools and not skill.needs_knowledge
