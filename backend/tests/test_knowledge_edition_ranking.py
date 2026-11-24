"""Regression checks for page-based scoring without dependencies on textbook cases."""
from hashlib import sha256

import pytest

from modules.knowledge.local_provider import LocalKnowledgeProvider, _edition_tokens, _priority_rank, _ranked_window
from modules.knowledge.edition import _page_texts, _source_excerpt, _source_table_rows


def _frozen_index(root, entries):
    frozen = {}
    for identifier, (title, text) in entries.items():
        raw = f'# {title}\n\n{text}\n'.encode()
        filename = f"{identifier}.md"
        (root / filename).write_bytes(raw)
        frozen[filename] = {"path": filename, "id": identifier, "book": 1, "title": title,
                            "sha256": sha256(raw).hexdigest()}
    return LocalKnowledgeProvider(root, corpus_only=True, frozen_documents=frozen)


@pytest.mark.asyncio
async def test_specific_observation_beats_a_query_matching_overview(tmp_path):
    index = _frozen_index(tmp_path, {
        "overview": ("整机测试", "### PDF 第 3 页\n\n"
                     "本章介绍校准探针的端口状态、探针读回和端口状态的测试范围。"),
        "evidence": ("整机测试", "### PDF 第 4 页\n\n"
                     "下表是校准探针的读回。\n\n"
                     "| 探针 | 端口状态 |\n| --- | --- |\n| A | Up |\n| B | Down |"),
    })
    available, hits = await index.search_pages("校准探针 A、B 的端口状态，分别在回显写了什么？", 2)
    assert available
    assert hits[0]["page"] == 4 and "| B | Down |" in hits[0]["text"]


@pytest.mark.asyncio
async def test_general_recall_reserves_results_for_multiple_physical_pages(tmp_path):
    repeated = "\n\n".join(f"#### 第{i}种配置\n\n环路保护由监视端口触发，仍需核对线路。" for i in range(5))
    index = _frozen_index(tmp_path, {
        "chapter": ("交换机", f"### PDF 第 7 页\n\n{repeated}\n\n"
                    "### PDF 第 8 页\n\n端口恢复时需要再次核对环路保护状态。"),
    })
    _, hits = await index.search_pages("环路保护怎样核对", 3)
    assert {hit["page"] for hit in hits[:2]} == {7, 8}


def test_labels_keep_physical_interfaces_addresses_and_single_letter_roles():
    short = _edition_tokens("A、B 的 GE 0/0/1，192.0.2.1/24 与 VLANIF 100", query=True)
    long = _edition_tokens("A 和 B 对接 GigabitEthernet0/0/1，192.0.2.1/24，VLANIF100")
    expected = {"letter=a", "letter=b", "label=ge0/0/1", "label=192.0.2.1/24", "label=vlanif100"}
    assert all(expected <= set(tokens) for tokens in (short, long))
    assert "label=ge0/0/1" not in _edition_tokens("Ethernet0/0/1")


def test_colloquial_and_technical_vocabulary_share_only_their_actual_concept():
    left = set(_edition_tokens("出口网口和从终端出去的下一站", query=True))
    right = set(_edition_tokens("出接口 及 NextHop 字段"))
    assert "concept=egress_interface" in left & right
    assert "concept=next_hop" in right
    assert "concept=ingress_interface" not in left | right


def test_page_attribution_for_split_table_retains_only_verified_consecutive_rows():
    header = "| 序号 | 等级 |\n| --- | --- |\n"
    original = header + "| 4 | 一等 |\n| 5 | 二等 |\n| 6 | 三等 |\n| 7 | 一等 |\n"
    expected = header + "| 6 | 三等 |\n| 7 | 一等 |"
    assert _source_table_rows("### PDF 第 8 页\n\n" + expected, original) == expected
    assert _source_table_rows(expected.replace("三等", "封存"), original) is None
    assert _source_table_rows(header + "| 5 | 二等 |\n| 7 | 一等 |", original) is None


def test_invalid_markdown_cannot_carry_next_physical_page_under_an_earlier_anchor():
    from modules.knowledge.reader import sections

    text = "# 第一节\n\n### PDF 第 22 页\n\n```text\n与第 22 页有关的内容。\n\n### PDF 第 23 页\n\n这段写在下一页。\n"
    heading = next(row for row in sections(text) if row["title"] == "PDF 第 22 页")
    pages = _page_texts({"content": text, "sections": sections(text), "original_pages": [
        {"section_id": heading["id"], "physical": 22, "evidence_eligible": True},
    ]})
    assert list(pages) == [22]
    assert "与第 22 页有关的内容。" in pages[22][1]
    assert "这段写在下一页。" not in pages[22][1]
    assert _source_excerpt("这段写在下一页。", pages[22][1]) is None


def test_contiguous_subject_phrase_can_promote_a_passage_without_changing_source():
    narrow = {"compact_body": "标准脉冲引起线路抖动。", "compact_headings": "线路抖动", "counts": {},
              "page_key": (1, 7), "role": (False, False, False, False, True)}
    scattered = {**narrow, "compact_body": "标准合格，脉冲信号沿线路传播，随后处理抖动。", "compact_headings": ""}
    ranked = [(1.0, scattered, "分散描述"), (.86, narrow, "同一关系")]
    score = _priority_rank(ranked, "标准脉冲怎么引起线路抖动？", {"脉冲": 2.0, "抖动": 2.0}, {})
    assert score[0][2] == "同一关系"


def test_same_page_excerpt_combines_complete_blocks_for_both_requested_objects(tmp_path):
    first = "### PDF 第 6 页\n\n#### R4\n\n```text\n[R4]display baseline\n标识编号：2001\n```"
    second = "#### R5\n\n```text\n[R5]display baseline\n标识编号：2002\n```"
    original = first + "\n\n" + second
    index = _frozen_index(tmp_path, {"results": ("读回基线", original)})
    index._ensure_index()
    evidence = index.improve_page_excerpt(original, first, "R4 和 R5 的回显标识编号各是多少？")
    assert "编号：2001" in evidence and "编号：2002" in evidence
    assert evidence in original and evidence.count("```") == 4


def test_display_budget_window_retains_complete_table_after_long_block():
    first = "旧拓扑讨论。" * 220
    table = "| 端口 | 采集周期 |\n| --- | --- |\n| 校准探针 | 10秒 |"
    text = f"{first}\n\n{table}\n"
    result = _ranked_window(text, {"校准": 5.0, "周期": 3.0})
    assert result == table and result in text
