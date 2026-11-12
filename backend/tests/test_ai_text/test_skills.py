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
