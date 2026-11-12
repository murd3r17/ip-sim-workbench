import pytest
from modules.ai_text.retrieval import rerank, protocol_context

def test_rerank_prefers_lexical_overlap():
    hits = [
        {"filename": "a", "score": 0.9, "content": "无关的云安全内容"},
        {"filename": "b", "score": 0.5, "content": "VRRP Master 通告间隔与切换"},
    ]
    out = rerank(hits, "VRRP Master 通告间隔", 2)
    assert out[0]["filename"] == "b"

def test_rerank_empty_returns_empty():
    assert rerank([], "x", 5) == []
    assert rerank(None, "x", 5) == []

def test_rerank_limits_topk():
    hits = [{"filename": str(i), "score": 1 - i / 10, "content": "x"} for i in range(5)]
    assert len(rerank(hits, "x", 3)) == 3


def test_same_state_name_is_not_evidence_for_another_protocol():
    bfd = {"score": 1, "content": "# BFD 会话\n\nDown 表示会话尚未建立。"}
    ospf = {"score": .8, "content": "# OSPF 邻居\n\nDown：尚未收到邻居信息。"}
    assert rerank([bfd, ospf], "OSPF Down 状态", 5) == [ospf]
    assert protocol_context([bfd, ospf], "BFD Down 状态") == [bfd]
    assert protocol_context([bfd], "OSPF Down 状态") == []


def test_generic_comparison_and_cross_protocol_material_are_retained():
    generic = {"content": "# 网络故障\n\n只有协议信息不能确定物理故障。"}
    cross = {"content": "# BFD\n\nBFD 可以配合 OSPF 检测故障。"}
    bfd = {"content": "# BFD\n\nDown 与 Init。"}
    hits = [generic, cross, bfd]
    assert protocol_context(hits, "状态是什么意思") == hits
    assert protocol_context(hits, "比较 OSPF 和 BFD 的 Down") == hits
    assert protocol_context(hits, "OSPF Down") == [generic, cross]
    # Expansion's incidental vocabulary must not change the user's scope.
    assert len(rerank(hits, "状态 OSPF", 5, original_query="状态")) == 3


def test_protocol_families_and_fences_do_not_create_false_heading_context():
    stp = {"content": "# STP\n\n生成树基本原理。"}
    assert protocol_context([stp], "MSTP 原理") == [stp]
    cli = {"content": "```cli\n# BFD\nreturn\n```\n\n一般性说明。"}
    assert protocol_context([cli], "OSPF 原理") == [cli]
    assert protocol_context([{"text": "# OSPFv3\n\nIPv6"}], "OSPFv2")
    assert protocol_context([{"text": "# IS-IS\n\n链路状态"}], "ISIS")
