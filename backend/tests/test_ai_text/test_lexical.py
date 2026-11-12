# -*- coding: utf-8 -*-
"""C-R2 5.4：独立词法召回与融合回归。"""
from pathlib import Path
from modules.ai_text import lexical_index


def _corpus(tmp: Path):
    (tmp / "a.md").write_text("# OSPF 邻居\nOSPF 邻居状态 Full 表示邻接建立完成。", encoding="utf-8")
    (tmp / "b.md").write_text("# VRRP\nVRRP Master 默认每秒发送通告，Backup 约 3 秒判失效。", encoding="utf-8")
    (tmp / "c.md").write_text("# 云安全\n云上数据加密与访问控制。", encoding="utf-8")


def test_lexical_recall_hits_protocol_terms(tmp_path):
    _corpus(tmp_path)
    lexical_index.build_index(tmp_path)
    hits = lexical_index.search("VRRP Master 通告间隔", 3, root=tmp_path)
    assert hits and hits[0]["filename"] == "b.md"
    assert hits[0]["retriever"] == "lexical"


def test_fusion_keeps_vector_precision_and_adds_lexical():
    vector = [{"filename": "a.md", "content": "OSPF neighbor", "score": 0.9}]
    lexical = [{"filename": "b.md", "content": "VRRP 通告", "score": 3.0}]
    fused = lexical_index.fuse(vector, lexical, 5, vector_weight=0.8)
    assert {h["filename"] for h in fused} == {"a.md", "b.md"}
    assert fused[0]["filename"] == "a.md"  # 向量高分优先
    assert all(h.get("retriever") != "hybrid" for h in fused)


def test_fusion_dedupes_same_chunk():
    vector = [{"filename": "a.md", "content": "same chunk", "score": 0.9}]
    lexical = [{"filename": "a.md", "content": "same chunk", "score": 9.0}]
    fused = lexical_index.fuse(vector, lexical, 5, vector_weight=0.8)
    assert len(fused) == 1 and fused[0]["retriever"] == "hybrid"
