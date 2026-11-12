from modules.ai_text.llm_service import LLMService
from modules.ai_text.skills import select_skill


def test_knowledge_question_ignores_incidental_training_operations():
    service = LLMService(db=None, user_id=1, provider=object())
    choice = select_skill("OSPF 为什么需要 DR？", lab_steps=[{"id": 1}])
    prompt = service._build_copilot_prompt("OSPF 为什么需要 DR？", ["[book]\n原文保持不变"],
        {"skill_id": choice.id, "skill": choice.label, "skill_prompt": choice.prompt},
        lab_steps=[{"id": 1, "config_hint": "UNRELATED_CONFIGURATION"}])
    assert "UNRELATED_CONFIGURATION" not in prompt
    assert "来源[1]\n[book]\n原文保持不变" in prompt
    assert "不额外展开配置" in prompt
    assert "知识类问题要覆盖机制、关键参数与默认值" not in prompt


def test_skill_system_rules_are_server_owned_and_simple_help_omits_telemetry():
    service = LLMService(db=None, user_id=1, provider=object())
    selected = select_skill("OSPF 是什么？")
    prompt = service._build_copilot_prompt("OSPF 是什么？", [],
        {"skill_id": selected.id, "skill": selected.label, "skill_prompt": selected.prompt},
        page_data='{"unverified": "INCIDENTAL_DEVICE_VALUE"}')
    assert "INCIDENTAL_DEVICE_VALUE" not in prompt
    system = service.copilot_system_prompt(with_guide=False, skill_id=selected.id)
    # The dedicated knowledge role deliberately avoids duplicating the full
    # skill paragraph. Check its behavioral contract, not the old concatenation.
    assert "本次是知识问答" in system and "不调用工具" in system
    assert selected.prompt in prompt
    assert "工作台操作手册（" not in system
    assert "INJECTED_INSTRUCTION" not in service.copilot_system_prompt(skill_id="INJECTED_INSTRUCTION")


def test_page_starter_is_not_a_knowledge_query():
    assert select_skill("设备页是做什么的？").id == "page_help"
