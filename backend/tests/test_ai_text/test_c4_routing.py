"""Routing should follow the current question, not incidental page payload size."""
import pytest

from modules.ai_text.skills import select_skill
from modules.ai_text.budget_policy import select_tier


@pytest.mark.parametrize("question,skill,tier", [
    ("这个页面能做什么？", "page_help", "direct"),
    ("刷新状态按钮在哪里？", "page_help", "direct"),
    ("OSPF 为什么需要 DR 和 BDR？", "knowledge_answer", "standard"),
    ("OSPF 邻居的 Down 状态是什么意思？", "knowledge_answer", "standard"),
    ("OSPF 的 LSA 有哪些类型？", "knowledge_answer", "standard"),
    ("这些数字什么意思？", "live_evidence", "standard"),
    ("查看 R2 的接口状态", "live_evidence", "standard"),
    ("R2 访问不了 R3，怎么排查？", "troubleshooting", "diagnostic"),
    ("为什么 R2 到 R3 不通？", "troubleshooting", "diagnostic"),
    ("网络故障排查一般按什么顺序做？", "knowledge_answer", "standard"),
    ("丢包排查通常有哪些方法？", "knowledge_answer", "standard"),
    ("这台设备丢包，通常按什么顺序排查？", "troubleshooting", "diagnostic"),
])
def test_question_intent_is_stable_across_incidental_snapshots(question, skill, tier):
    for snapshot in (None, '{"source":"sim","device":"R2"}', "x" * 18000):
        choice = select_skill(question, page_data=snapshot)
        assert choice.id == skill
        assert select_tier(question, page_data=snapshot) == tier


def test_long_knowledge_question_does_not_buy_diagnostic_budget():
    assert select_tier("解释 OSPF 原理。" * 80) == "standard"


def test_page_help_has_no_live_tools_and_diagnostic_can_resolve_device_ids():
    assert select_skill("这个页面怎么用？").tools == []
    assert "query_devices" in select_skill("R2 不通，怎么排查？").tools


def test_explicit_knowledge_question_does_not_become_lab_coaching():
    assert select_skill("OSPF 的 LSA 有哪些类型？", lab_steps=[{"id": "1"}]).id == "knowledge_answer"
    assert select_skill("下一步怎么做？", lab_steps=[{"id": "1"}]).id == "lab_coach"


def test_skill_manifest_has_version_and_retrieval_requirements():
    for question in ("这个页面怎么用", "OSPF 原理", "R2 不通", "这些数字什么意思"):
        choice = select_skill(question)
        meta = choice.as_meta()
        assert meta["version"] and meta["reason"]
        assert isinstance(meta["needs_knowledge"], bool)
        assert meta["context_requirements"]
    assert not select_skill("这个页面怎么用").needs_knowledge
    assert select_skill("OSPF 原理").needs_knowledge
