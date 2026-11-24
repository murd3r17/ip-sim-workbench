"""Synthetic frozen-edition regressions, independent of production corpus and providers."""
from base64 import b64decode
from contextlib import closing
import asyncio
from hashlib import sha256
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from modules.ai_text.context_bundle import prepare_sources
from modules.knowledge.edition import KnowledgeEdition, literal_excerpt
from modules.knowledge.local_provider import LocalKnowledgeProvider
from modules.knowledge.query_focus import compact_text, lookup_parts, separate_pdf_pages
from modules.knowledge.reader import DocumentReadError
from modules.knowledge.service import KnowledgeService, UploadPolicy, _blend_same_edition


_SENTENCE = "收到完整状态记录后，观察节点才开始校验。"
_PREVIOUS_SENTENCE = "旧章在状态记录采集完成初步校验。"
_FIGURE = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1wAAAAASUVORK5CYII=")
_NESTED_EVIDENCE = "逐项归档控制信号对应的独立通道编号。"


def _write_json(path, value):
    raw = json.dumps(value, ensure_ascii=False).encode()
    path.write_bytes(raw)
    return sha256(raw).hexdigest()


def _edition(root, *, archived=False, reviewed_page=None, nested=False, blocked=None, attached_caption=None,
             local_ids=False, keep_crlf=False, chapter_heading=None):
    corpus = root / "corpus"
    corpus.mkdir(parents=True)
    documents = []
    edition = "previous-edition" if archived else "synthetic-edition"
    entries = [
        ("audited-1", 1, "1.3 状态记录与校验", "首先采集空白记录。",
         _PREVIOUS_SENTENCE if archived else reviewed_page or _SENTENCE),
        ("audited-2", 2, "2.3 状态记录与校验", _SENTENCE, "这里记录另一个观察结果。"),
    ]
    if archived:
        entries.append(("audited-3", 3, "已从当前目录撤回的章节", "历史目录中的信息。", "第四页附录。"))
    children = {}
    if nested:
        entries.extend((
            ("audited-1a", 1, "1.3.1 审计导读", "从细目了解后续证据。", "本节记录审计导读。"),
            ("audited-1b", 1, "1.3.1.1 存储细目", "首先读取本节说明。", _NESTED_EVIDENCE),
        ))
        children = {"audited-1": ["audited-1a"], "audited-1a": ["audited-1b"]}
    for identity, book, title, first, second in entries:
        if identity == "audited-1" and attached_caption:
            first = attached_caption
        chapter = f"## {chapter_heading}\r\n\r\n" if identity == "audited-1" and chapter_heading else ""
        path = corpus / f"{identity}.md"
        raw = (f'---\r\ndoc_id: "{identity}"\r\ntitle: "{title}"\r\ningest: "true"\r\n---\r\n'
               f"# {title}\r\n\r\n{chapter}### PDF 第 3 页\r\n\r\n{first}\r\n\r\n"
               f"### PDF 第 4 页\r\n\r\n{second}\r\n\r\n## 原页查阅\r\n").encode()
        if local_ids and not keep_crlf:
            raw = raw.replace(b"\r\n", b"\n")
        path.write_bytes(raw)
        version = sha256(raw).hexdigest()
        page_map = f"{identity}.json"
        pages = []
        for page in (3, 4):
            role = (blocked or {}).get((identity, page))
            row = {"physical": page, "role": role or "instruction", "preview": archived and page == 4}
            if role:
                row["original_access"] = "render"
            pages.append(row)
        pages_hash = _write_json(root / page_map, {"version": version, "doc_id": identity, "pages": pages})
        documents.append({
            "id": f"corpus-{sha256(path.name.encode()).hexdigest()[:24]}" if local_ids else identity,
            "doc_id": identity, "path": path.name, "book": book, "title": title,
            "sha256": version, "page_map": page_map, "page_map_sha256": pages_hash,
            "edition": "V1", "ingest": True, "anchor": 1, "page_start": 3, "page_end": 4,
            "subsections": children.get(identity, []),
        })
    (corpus / "unlisted.md").write_text(f"# 旧版\n\n### PDF 第 4 页\n\n{_SENTENCE}", encoding="utf-8")
    legacy = [{"old_doc_id": "old-logical-id", "verified_anchors": [], "related": [{"doc_id": "audited-1"}]}]
    legacy_hash = _write_json(root / "legacy-identity.json", legacy)
    manifest_hash = _write_json(root / "manifest.json", {
        "version": edition, "documents": documents, "legacy_sha256": legacy_hash,
        "books": [{"book": n, "title": title} for n, title in enumerate(
            ("状态记录基础手册", "状态记录进阶手册", "已撤回手册"), 1
        )],
    })
    freeze = {
        "status": "FROZEN", "edition": edition, "reading_manifest_sha256": manifest_hash,
        "anythingllm": {"workspace": "textbook-audit", "documents": {}},
    }
    if archived:
        (root / "old-page.png").write_bytes(_FIGURE)
        figures_hash = _write_json(root / "figures.json", {"edition": edition, "figures": [{
            "book": 1, "physical": 4, "file": "old-page.png", "sha256": sha256(_FIGURE).hexdigest(),
        }]})
        freeze["figures"] = {"manifest_sha256": figures_hash}
    _write_json(root / "freeze.json", freeze)
    return KnowledgeEdition(root)


@pytest.fixture
def frozen(tmp_path):
    return _edition(tmp_path / "active")


@pytest.fixture
def service(frozen, monkeypatch):
    settings = SimpleNamespace(knowledge_top_k=5, knowledge_workspace_slug="ip-ops-kb", knowledge_workspace_id="1",
                               knowledge_similarity_threshold=.2)
    monkeypatch.setattr("modules.knowledge.service.get_settings", lambda: settings)
    provider = SimpleNamespace(
        name="anythingllm", search=AsyncMock(return_value=[{"text": "旧版片段"}]),
        ask=AsyncMock(return_value={"answer": "历史工作区回答", "sources": []}),
        list_documents=AsyncMock(return_value=[]), get_workspace=AsyncMock(return_value={"id": "ip-ops-kb"}),
        health_check=AsyncMock(return_value={"available": True}),
        _default_storage_dir=lambda: "",
    )
    svc = KnowledgeService(provider, UploadPolicy([], [], 10, 10))
    monkeypatch.setattr(svc, "edition", lambda: frozen)
    return svc


@pytest.mark.asyncio
async def test_caption_attached_to_cli_keeps_physical_pages_and_exact_source(service, tmp_path, monkeypatch):
    caption = "**查看游标。**```text\r\n# 代码行仍属于回显\r\nmode cursor\r\n```"
    statement = "确认游标状态后再比较两个已保存的记录。"
    frozen = _edition(tmp_path / "imported-caption", reviewed_page=statement, attached_caption=caption)
    monkeypatch.setattr(service, "edition", lambda: frozen)

    reading = frozen.read("audited-1")
    page = next(row for row in reading["original_pages"] if row["physical"] == 4)
    heading = next(section for section in reading["sections"] if section["id"] == page["section_id"])
    assert caption in reading["content"] and not reading["warnings"]
    assert reading["content"].splitlines()[heading["line"] - 1] == "### PDF 第 4 页"
    assert all(section["title"] != "代码行仍属于回显" for section in reading["sections"])

    [hit] = await service.search(f'在《状态记录基础手册》第 4 页查找原句“{statement}”')
    assert hit["page"] == 4 and hit["section_id"] == page["section_id"]
    assert hit["text"].splitlines()[-1] == statement and "查看游标" not in hit["text"]
    assert await service.search(f'在《状态记录基础手册》第 3 页查找原句“{statement}”') == []


@pytest.mark.asyncio
async def test_mstp_mapping_uses_one_verified_table_for_both_vlans(service, tmp_path, monkeypatch):
    table = ("```text\r\nOper configuration\r\nInstance   VLANs Mapped\r\n"
             "   0       1 to 76, 78 to 88, 90 to\r\n           4094\r\n"
             "   4       77, 777\r\n   5       89, 889\r\n```")
    decoy = "MSTP 示例涉及 VLAN 77 和 VLAN 89。运行记录分别查看实例和映射。"
    frozen = _edition(tmp_path / "mstp-table", reviewed_page=table, attached_caption=decoy)
    monkeypatch.setattr(service, "edition", lambda: frozen)

    hits = await service.search("在教材里核对 MSTP，VLAN 77 和 VLAN 89 分别映射到哪个实例？")

    assert hits[0]["page"] == 4 and hits[0]["document_version"] == frozen.documents["audited-1"]["sha256"]
    assert hits[0]["text"] == table


@pytest.mark.parametrize(('query', 'expected', 'pages'), [
    ('“观察节点”', ['观察节点'], None),
    ('找出“观察节点”所在的原句。', ['观察节点'], None),
    ('《状态记录基础手册》第 4 页“先取得记录再开始交叉校验”', ['先取得记录再开始交叉校验'], (4, 4)),
    ('《状态记录基础手册》第 3–4 页如何理解“节点先等齐记录才开始交叉比对”？不用逐字。', [], (3, 4)),
    ('检索“节点先等齐记录才开始交叉比对”这个做法的作用。', [], None),
    ('查“节点先等齐记录才开始交叉比对”所在原意，再说明条件。', [], None),
    ('在 PDF 第 4 页“采集锁”有何作用？', [], (4, 4)),
])
def test_source_quote_distinguishes_literal_text_from_topic(query, expected, pages):
    _, phrases, scope, _ = lookup_parts(query)
    assert phrases == expected and scope == pages


@pytest.mark.parametrize('query', [
    '核对《1.3 状态记录与校验》PDF 第 3–4 页。',
    '核对《1.3 状态记录与校验》印刷第 3 页和 PDF 第 4 页。',
    '核对《1.3 状态记录与校验》PDF 第 4 页或第 3 页。',
    '核对《1.3 状态记录与校验》PDF 第 4 页，不要引用第 3 页。',
    '核对《1.3 状态记录与校验》PDF 第 4 页和第 4 页。',
    '核对“PDF 第 4 页和第 3 页”这句话。',
])
def test_discrete_scope_requires_an_explicit_pdf_page_list(query):
    assert separate_pdf_pages(query) is None


@pytest.mark.asyncio
async def test_explicit_pdf_page_list_keeps_request_order_and_exact_page_boundaries(service, frozen):
    query = '请分别核对《1.3 状态记录与校验》PDF 物理第 4 页、PDF 第 6 页和第 3 页的记录。'
    hits = await service.search(query)
    assert [(hit['document_id'], hit['page']) for hit in hits] == [('audited-1', 4), ('audited-1', 3)]
    for hit in hits:
        actual = frozen.read(hit['document_id'], hit['document_version'])
        entry = next(page for page in actual['original_pages'] if page['physical'] == hit['page'])
        assert hit['section_id'] == entry['section_id'] and hit['text'] in actual['content']
    service.provider.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_discrete_scope_does_not_assign_pages_across_different_books(service):
    query = '核对《状态记录基础手册》和《状态记录进阶手册》的 PDF 第 4 页和第 3 页中的记录。'
    assert await service.search(query) == []


@pytest.mark.asyncio
async def test_bare_protocol_starts_with_mechanism_in_frozen_edition(service, tmp_path, monkeypatch):
    example = '```text\r\n[R1]ospf 1\r\n[R1-ospf-1]display ospf peer\r\n```'
    explanation = 'OSPF 是一种链路状态路由协议。它在同一区域内交换链路状态信息。'
    frozen = _edition(tmp_path / 'protocol-introduction', reviewed_page=explanation, attached_caption=example)
    monkeypatch.setattr(service, 'edition', lambda: frozen)

    hits = await service.search('OSPF')

    assert hits[0]['page'] == 4 and explanation in hits[0]['text']


@pytest.mark.asyncio
async def test_default_workspace_uses_reader_edition_for_a_literal_with_scope(service, frozen):
    hits = await service.search(f'在《状态记录基础手册》第 3–4 页查找原句“{_SENTENCE}”')
    assert len(hits) == 1
    hit = hits[0]
    assert hit["page"] == 4
    assert hit["document_id"] == "audited-1"
    assert hit["edition_version"] == "synthetic-edition"
    reading = frozen.read(hit["document_id"], hit["document_version"])
    assert hit["text"] in reading["content"] and _SENTENCE in hit["text"]
    assert hit["section_id"] == next(p["section_id"] for p in reading["original_pages"] if p["physical"] == 4)
    service.provider.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_title_and_page_range_select_the_numbered_chapter(service, frozen):
    title = await service.search("打开《1.3 状态记录与校验》")
    assert [hit["document_id"] for hit in title] == ["audited-1"]
    assert title[0]["retriever"] == "edition_title"
    assert title[0]["section_id"] in {s["id"] for s in frozen.read("audited-1")["sections"]}
    pages = await service.search("1.3 状态记录与校验 PDF 第 4 页")
    assert [(hit["document_id"], hit["page"]) for hit in pages] == [("audited-1", 4)]
    assert frozen.has_search_scope("在《并不存在的手册》第 3 页找原句“校验”")
    assert await service.search("在《并不存在的手册》第 3 页找原句“校验”") == []


@pytest.mark.asyncio
async def test_chapter_scope_searches_nested_evidence_but_title_opens_the_chapter(service, tmp_path, monkeypatch):
    edition = _edition(tmp_path / "nested", nested=True)
    monkeypatch.setattr(service, "edition", lambda: edition)
    [chapter] = await service.search("打开《1.3 状态记录与校验》")
    assert chapter["document_id"] == "audited-1" and chapter["retriever"] == "edition_title"

    [hit] = await service.search(f'在《1.3 状态记录与校验》PDF 第 4 页查找原句“{_NESTED_EVIDENCE}”')
    assert hit["document_id"] == "audited-1b" and hit["page"] == 4
    assert _NESTED_EVIDENCE in hit["text"]


@pytest.mark.asyncio
async def test_wrong_page_or_mismatched_excerpt_never_falls_back_to_old_bank(service):
    assert await service.search(f'在《状态记录基础手册》第 3 页查找原句“{_SENTENCE}”') == []
    hits = await service.search(_SENTENCE, workspace_id="textbook-audit", top_k=5)
    assert hits and all(hit["edition_version"] == "synthetic-edition" for hit in hits)
    assert all(hit["document_id"] in {"audited-1", "audited-2"} for hit in hits)
    service.provider.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_readonly_lsdb_selection_keeps_verified_physical_page_and_exact_row(service, tmp_path, monkeypatch):
    from tests.test_readonly_cli_tables import HEADER, MATCH, OTHER, QUERY, observed_table

    edition = _edition(tmp_path / "lsdb", reviewed_page=observed_table().replace("\r\n", "\n"))
    monkeypatch.setattr(service, "edition", lambda: edition)
    hits = await service.search(QUERY)
    selected = next(hit for hit in hits if hit["document_id"] == "audited-1" and hit["page"] == 4)
    assert selected["partial_readonly_table"]
    document = edition.read(selected["document_id"], selected["document_version"])
    page = next(page for page in document["original_pages"] if page["physical"] == 4)
    assert selected["section_id"] == page["section_id"]
    assert selected["edition_version"] == edition.version
    assert HEADER.rstrip() in selected["text"]
    assert MATCH.rstrip() in selected["text"]
    assert MATCH.rstrip() in document["content"]
    assert OTHER.rstrip() not in selected["text"]
    [displayed] = prepare_sources([selected], max_document_chars=1300)
    assert MATCH.rstrip() in displayed["content"]
    assert prepare_sources([selected], max_document_chars=120) == []
    assert edition.improve_page_excerpts([selected], QUERY) == [selected]

    # An already cropped, annotated provider payload cannot prove its place
    # on its own. The contiguous source had to pass version and page checks.
    keyword = edition.keyword_index
    assert edition.resolve_hits([selected], keyword, "ip-ops-kb", query=QUERY) == []

    monkeypatch.setattr("modules.knowledge.reviewed_source_notes.notes_for_excerpt",
                        lambda _name, text, _version: [{"id": "qualified"}] if OTHER.rstrip() in text else [])
    [full] = [hit for hit in await service.search(QUERY) if hit["document_id"] == "audited-1" and hit["page"] == 4]
    assert "partial_readonly_table" not in full and OTHER.rstrip() in full["text"]


@pytest.mark.asyncio
async def test_readout_anchor_recovers_deep_verified_page_without_changing_first_three(service, tmp_path, monkeypatch):
    from tests.test_readonly_cli_tables import HEADER, MATCH, QUERY, observed_table

    edition = _edition(tmp_path / "deep-anchor", reviewed_page=observed_table())
    monkeypatch.setattr(service, "edition", lambda: edition)
    keyword = edition.keyword_index
    _, raw = await keyword.search_pages(QUERY, 64)
    deep_hit = next(hit for hit in raw if hit["document_id"] == "audited-1" and hit["page"] == 4)
    ordinary = [{"book": 2, "page": page, "text": f"普通候选 {page}"} for page in range(7, 13)]
    raw_regular = [{"ordinary": True, "text": "普通候选"}] * 30
    verified = edition.resolve_hits

    def resolve_hits(hits, provider, workspace, *, query=""):
        if hits and hits[0].get("ordinary"):
            return ordinary.copy()
        return verified(hits, provider, workspace, query=query)

    # The distractors precede the actual page at both ordinary and deep depths.
    mocked_search = AsyncMock(return_value=(True, [*raw_regular, deep_hit]))
    monkeypatch.setattr(keyword, "search_pages", mocked_search)
    monkeypatch.setattr(edition, "resolve_hits", resolve_hits)
    monkeypatch.setattr(edition, "learning_hits", lambda *_: [])
    monkeypatch.setattr(service, "_focused_originals", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "_reviewed_learning_hits", AsyncMock(return_value=[]))

    result = await service.search(QUERY, top_k=6)
    assert mocked_search.await_args.args == (edition.search_scope(QUERY)[0], 64)
    assert result[:3] == ordinary[:3]
    hit = result[3]
    assert hit["book"] == 1 and hit["page"] == 4 and hit["edition_version"] == edition.version
    assert hit["partial_readonly_table"] and HEADER.strip() in hit["text"] and MATCH.strip() in hit["text"]
    assert result[4:] == ordinary[3:5]
    service.provider.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_device_column_anchor_requires_one_device_and_distinct_complete_fields(tmp_path):
    from modules.knowledge.evidence_anchors import evidence_anchor_request, verified_evidence_anchor

    table = ("BFD 只读表格的实际回显。\n\n| 字段 | S9 样例 | S90 样例 |\n| --- | --- | --- |\n"
             "| 发送间隔 | 31 ms | 38 ms |\n| 接收间隔 | 41 ms | 48 ms |\n| 检测倍数 | 5 | 6 |")
    edition = _edition(tmp_path / "matrix-anchor", reviewed_page=table)
    keyword = edition.keyword_index
    query = "BFD 回显表格里 S9 的发送间隔、接收间隔和检测倍数是什么？"
    request = evidence_anchor_request(query)
    _, candidates = await keyword.search_pages(query, 64)
    hit = verified_evidence_anchor(edition, keyword, "ip-ops-kb", candidates, query, request)
    assert (hit["page"], hit["edition_version"]) == (4, edition.version)
    assert "| 发送间隔 | 31 ms | 38 ms |" in hit["text"]
    assert "| 字段 | S9 样例 | S90 样例 |" in hit["text"]
    assert evidence_anchor_request(query.replace("S9", "S9 与 S90")) is None
    absent = query.replace("S9", "S91")
    assert verified_evidence_anchor(edition, keyword, "ip-ops-kb", candidates, absent, evidence_anchor_request(absent)) is None
    assert evidence_anchor_request(query.replace("回显表格", "故障后回显表格")) is None
    competing = _edition(tmp_path / "matrix-competing", reviewed_page=table + "\n\n" + table.replace("31 ms", "37 ms"))
    _, ambiguous = await competing.keyword_index.search_pages(query, 64)
    assert verified_evidence_anchor(competing, competing.keyword_index, "ip-ops-kb", ambiguous, query, request) is None
    duplicate = _edition(tmp_path / "matrix-duplicate-column", reviewed_page=table.replace("S90 样例", "S9 备用样例"))
    _, duplicate_columns = await duplicate.keyword_index.search_pages(query, 64)
    assert verified_evidence_anchor(duplicate, duplicate.keyword_index, "ip-ops-kb", duplicate_columns, query, request) is None


@pytest.mark.asyncio
async def test_same_page_coverage_preserves_condition_and_the_retrieved_anchor(tmp_path):
    from modules.knowledge.page_evidence import coverage_request

    readback = ("```text\n<R7>display interface GigabitEthernet 0/0/9\n"
                "GigabitEthernet0/0/9 current state : UP\nLine protocol current state : UP\n```")
    limitation = "从回显信息可以确认该接口当时为 UP。业务恢复还需另测。"
    body = readback + "\n\n" + limitation
    edition = _edition(tmp_path / "coverage", reviewed_page=body)
    keyword = edition.keyword_index
    query = "R7 的 GE0/0/9 回显显示什么状态？这能证明业务已经恢复吗？"
    request = coverage_request(query)
    _, candidates = await keyword.search_pages(query, 8)
    raw = next(hit for hit in candidates if hit["page"] == 4 and hit["document_id"] == "audited-1")
    [excerpt] = edition.resolve_hits([{**raw, "text": readback}], keyword, "ip-ops-kb")
    [combined] = edition.cover_page_excerpts([{**excerpt, "retriever": "focused_original"}], request)
    assert combined["text"] == body
    assert all(combined[name] == excerpt[name] for name in ("page", "section_id", "document_version", "edition_version"))
    assert prepare_sources([combined], max_document_chars=1300)[0]["content"] == body

    denied = _edition(tmp_path / "coverage-denied", reviewed_page=body, blocked={("audited-1", 4): "non-instruction"})
    assert denied.cover_page_excerpts([excerpt], request) == [excerpt]


def test_same_page_coverage_rejects_empty_commands_phase_mismatch_and_lost_caveats():
    from modules.knowledge.page_evidence import coverage_request, paired_excerpt

    query = "R7 故障后的 GE0/0/9 回显显示什么状态？这能证明业务已经恢复吗？"
    request = coverage_request(query)
    exhibit = ("```text\n<R7>display interface GigabitEthernet 0/0/9\n"
               "GigabitEthernet0/0/9 current state : UP\n```")
    limitation = "从输出信息只能读出接口状态，仍需独立测量业务恢复。"
    empty = "```text\n<R7>display interface GigabitEthernet 0/0/9\n```"
    assert paired_excerpt(empty + "\n\n" + limitation, empty, request) is None
    assert paired_excerpt(exhibit + "\n\n从回显信息可见恢复后为 UP，但不能判断业务。", exhibit, request) is None
    assert paired_excerpt(exhibit + "\n\n从回显信息对照故障前与故障后状态，仍需独立观察。", exhibit, request) is None
    assert paired_excerpt(exhibit + "\n\n#### 下一组实验\n\n" + limitation, exhibit, request) is None
    qualifier = "从回显信息可见故障后为 UP，但不能判断业务。"
    visible = "上一次计时还需独立确认。\n\n" + exhibit
    page = visible + "\n\n" + qualifier
    assert paired_excerpt(page, visible, request, max_chars=len(exhibit) + len(qualifier) + 4) is None
    empty_notice = "R7 的 GE0/0/9 当时没有任何回显。\n\n" + empty
    assert paired_excerpt(empty_notice + "\n\n" + exhibit + "\n\n" + qualifier, empty_notice, request) is None


def test_same_page_coverage_keeps_the_complete_table_with_its_legend():
    from modules.knowledge.page_evidence import coverage_request, paired_excerpt

    table = "| 路径 | 标识 |\n| --- | --- |\n| 测试链路 | 青色 |\n| 备用链路 | 灰色 |"
    legend = "图中颜色只说明该次试验的记录类型。还需独立验证备用链路是否可用。"
    body = table + "\n\n" + legend
    request = coverage_request("这张图的表中备用链路标了什么？这能证明备用链路可用吗？")
    assert paired_excerpt(body, table, request) == body
    assert paired_excerpt(body, table, request, max_chars=len(body) - 1) is None


@pytest.mark.asyncio
async def test_complementary_facets_fill_only_distinct_verified_evidence_slots():
    from modules.knowledge.complementary_facets import complementary_request, expand_complementary

    query = "10.23.64.0/24 的这次实验，R17 的下一跳和出接口是什么？R21 的 FEC 标签广告对应哪一个上游？"
    plan = complementary_request(query)
    assert plan and len(plan.facets) == 2

    def hit(page, text):
        return {"book": 1, "document_id": "case-doc", "section_id": str(page), "page": page,
                "edition_version": "fixture", "text": text, "retriever": "edition_local"}

    first = hit(21, "10.23.64.0/24，R17 发往 R21，下一跳见回显，出接口为甲端口。")
    second = hit(22, "R21 和 R17 的 10.23.64.0/24 记录，FEC 标签广告由上游设备发布。")
    regular = [hit(page, f"默认片段 {page}") for page in range(31, 37)]
    regular[-3] = {**regular[-3], "partial_readonly_table": True}
    keyword = SimpleNamespace(search_pages=AsyncMock(side_effect=[(True, [first]), (True, [second])]))
    edition = SimpleNamespace(version="fixture", keyword_index=keyword, resolve_hits=lambda rows, *_args, **_kwargs: rows)
    results = await expand_complementary(edition, "test", plan, regular, [], 6)
    assert results == [*regular[:4], first, second]
    assert keyword.search_pages.await_args_list[1].args[0] == plan.facets[1].query

    for incompatible in ({**second, "document_id": "other case"}, {**second, "edition_version": "previous"},
                         {**second, "text": second["text"].replace("R21", "R20")},
                         {**second, "text": "10.23.64.0/24 的配置。\n\nR21 和 R17 的 FEC 标签广告由上游发布。"}):
        keyword.search_pages.side_effect = [(True, [first]), (True, [incompatible])]
        assert await expand_complementary(edition, "test", plan, regular, [], 6) == regular
    keyword.search_pages.side_effect = [(True, [{**first, "text": first["text"] + "这是故障前记录。"}]),
                                        (True, [{**second, "text": second["text"] + "这是故障后记录。"}])]
    assert await expand_complementary(edition, "test", plan, regular, [], 6) == regular


def test_complementary_facet_parser_keeps_explicit_case_scope():
    from modules.knowledge.complementary_facets import complementary_request

    query = "VLAN 316 的同一轮观察，R17 的下一跳和出接口是什么？R21 的客户端和服务端各是谁？"
    plan = complementary_request(query)
    assert plan.keys == {"vlan316"}
    assert plan.facets[0].devices == {"r17"}
    assert plan.facets[1].devices == {"r21"}
    assert complementary_request(query.replace("R21 的", "另外一组实验的 R21 的")) is None
    assert complementary_request("请逐字核对“VLAN 316”，客户端是谁？接着看服务端是谁？") is None
    assert complementary_request("VLAN 316 以及 VLAN 317 是什么？") is None


def test_symbolic_device_alias_boundaries_and_explicit_scope():
    from modules.knowledge.complementary_facets import complementary_request
    from modules.knowledge.device_alias_facets import AliasRequest, _leading_windows, device_aliases

    assert device_aliases("FW_A、CE-A、Leaf_B、AR2-A、FW_AA") == {"fw_a", "ce-a", "leaf_b", "ar2-a", "fw_aa"}
    assert device_aliases("Leaf-list, Spine-Leaf, PE-CE, router-id, Edge_1_VPN_10_20") == set()
    assert device_aliases("[FW_A-zone] display status\n<FW_B>display state") == {"fw_a", "fw_b"}
    question = "透明模式中 FW_A 和 FW_B 的主备角色和优先级如何配置？两台的邻居读回是什么状态，接收多少条？"
    assert isinstance(complementary_request(question), AliasRequest)
    assert isinstance(complementary_request(question.replace("的主备角色", "分别把主备角色")), AliasRequest)
    assert complementary_request(question.replace("的主备角色", "别把主备角色")) is None
    assert complementary_request(question.replace("透明模式中", "")) is None
    phased = complementary_request(question.replace("透明模式中", "切换后"))
    assert isinstance(phased, AliasRequest) and phased.shared_phases == {("切换", "后")}
    assert complementary_request(question.replace("FW_B", "FW-A")) is not None
    assert device_aliases("FW-A") != device_aliases("FW_A")
    assert complementary_request(question.replace("两台的", "另一组实验的")) is None
    assert _leading_windows("### PDF 第 4 页\n\n说明。\n\n#### 另一组实验\n\n```text\n另一段内容\n```") == ["说明。"]


@pytest.mark.asyncio
async def test_symbolic_devices_require_two_verified_compatible_role_and_readback_pages(tmp_path):
    from modules.knowledge.device_alias_facets import alias_request, expand_alias

    first = "透明模式的 FW_A 和 FW_B 配置：FW_A 为主设备，FW_B 为备设备。两侧优先级分开核对。"
    second = "透明模式的 FW_A 和 FW_B 对等体回显：双方 Established，各收到 3 条。"
    query = "透明模式下 FW_A 和 FW_B 的主备角色和优先级如何配置？两台邻居读回是什么状态，接收多少条？"
    request = alias_request(query)
    assert request
    regular = [{"document_id": "unrelated", "section_id": str(page), "page": page, "text": f"普通候选 {page}",
                "retriever": "edition_local"} for page in range(11, 17)]

    edition = _edition(tmp_path / "symbolic-device-pair", attached_caption=first, reviewed_page=second)
    hits = await expand_alias(edition, "test", request, regular, [], 6)
    assert hits[:4] == regular[:4]
    assert [(hit["page"], hit["document_id"]) for hit in hits[-2:]] == [(3, "audited-1"), (4, "audited-1")]

    note = "透明模式两台对等体回显为 Established，各收到 3 条。"
    framed = note + "\n\n```text\n[FW_A] display state\n[FW_B] display state\n```"
    already = _edition(tmp_path / "symbolic-existing-proof", attached_caption=first, reviewed_page=framed)
    _, indexed = await already.keyword_index.search_pages(query, 48)
    candidate = next(hit for hit in indexed if hit["document_id"] == "audited-1" and hit["page"] == 4)
    [visible] = already.resolve_hits([{**candidate, "text": note}], already.keyword_index, "test")
    preserved = [*regular[:3], visible, *regular[4:]]
    results = await expand_alias(already, "test", request, preserved, [], 6)
    assert results[3] == visible
    assert [hit["page"] for hit in results if hit["document_id"] == "audited-1"] == [4, 3]

    conflicts = _edition(tmp_path / "symbolic-phase-mismatch", attached_caption="故障前，" + first, reviewed_page="故障后，" + second)
    assert await expand_alias(conflicts, "test", request, regular, [], 6) == regular
    wrong = _edition(tmp_path / "symbolic-wrong-owner", attached_caption=first.replace("FW_B", "FW_BB"),
                     reviewed_page=second.replace("FW_B", "FW_BB"))
    assert await expand_alias(wrong, "test", request, regular, [], 6) == regular


@pytest.mark.asyncio
async def test_search_facets_return_request_local_proof_without_changing_hits(service, frozen, monkeypatch):
    from dataclasses import FrozenInstanceError

    from modules.knowledge import complementary_facets
    from modules.knowledge.edition import _page_texts
    from modules.knowledge.facet_evidence import FacetEvidence

    query = "VLAN 316 的同一轮观察，R17 的下一跳和出接口是什么？R21 的客户端和服务端各是谁？"
    record = frozen.documents["audited-1"]
    reading = frozen.read(record["id"], record["sha256"], include_original_status=False)
    selected = [frozen._bound_hit({"retriever": "edition_local"}, record, text, section, page)
                for page, (section, text) in _page_texts(reading).items()]
    assert [hit["page"] for hit in selected] == [3, 4]
    assert all(hit["text"].strip() for hit in selected)

    async def choose(*_args, on_pair=None):
        if on_pair is not None:
            on_pair(("case_key", (selected[1], selected[0])))
        return selected

    mocked = AsyncMock(side_effect=choose)
    monkeypatch.setattr(complementary_facets, "expand_complementary", mocked)

    hits, evidence = await service.search_with_facet_evidence(query, top_k=6)
    assert mocked.await_count == 1
    assert evidence.kind == "case_key" and evidence.select_hits(query, hits) == selected
    with pytest.raises(FrozenInstanceError):
        evidence.references[0].page = 12
    assert evidence.select_hits(query.lower(), hits) is None
    assert evidence.select_hits(query, hits[:1]) is None
    assert evidence.select_hits(query, [{**hits[0], "text": hits[0]["text"] + "不同正文"}, hits[1]]) is None
    assert evidence.select_hits(query, [{**hits[0], "document_version": "other edition"}, hits[1]]) is None
    assert evidence.select_hits(query, [hits[0], hits[0]]) is None
    wrong_page = {**hits[0], "page": hits[1]["page"], "section_id": hits[1]["section_id"]}
    assert FacetEvidence.capture(frozen, query, "case_key", (wrong_page, hits[1])) is None
    assert await service.search(query, top_k=6) == hits
    assert mocked.await_args.kwargs["on_pair"] is None
    assert not any("facet_evidence" in hit for hit in hits)


@pytest.mark.asyncio
async def test_ranked_evidence_recovers_full_facets_from_a_shared_labeled_experiment(service, monkeypatch, tmp_path):
    first = "在这次透明模式探测中，FW_A→FW_B 的回显显示 2 发 1 收，持续观察时各状态单独记录。"
    second = "透明模式的日志记录 FW_B→FW_A 的实际探测结果为 3 发 2 收，与其他案例不共用配置。"
    edition = _edition(tmp_path / "ranked", attached_caption=first, reviewed_page=second, chapter_heading="案例 1：透明模式探测")
    monkeypatch.setattr(service, "edition", lambda: edition)
    query = "同一轮透明模式探测，FW_A→FW_B 的回显是什么？FW_B→FW_A 的回显又是什么？"

    ordinary = await service.search(query, top_k=6)
    real_search = edition.keyword_index.search_pages
    spy = AsyncMock(wraps=real_search)
    monkeypatch.setattr(edition.keyword_index, "search_pages", spy)
    outcome = await service.search_ranked_evidence(query, top_k=6)
    assert outcome.hits == ordinary
    assert outcome.ranked is not None and outcome.ranked.missing == ()
    assert [facet[2] for facet in outcome.ranked.facets] == ["readback", "readback"]
    selected = outcome.ranked.select_hits(query, outcome.pool)
    assert selected and [hit["page"] for hit in selected] == [3, 4]
    assert selected[0]["source_experiment_key"] == selected[1]["source_experiment_key"]
    assert selected[0]["source_heading_path"][-1] == "案例 1：透明模式探测"
    assert [hit["facet_ids"] for hit in selected] == [(1,), (2,)]
    assert outcome.ranked.precise_case.scope[0] == "experiment"
    assert outcome.ranked.precise_case.directions == ((1, (("fw_a", "fw_b"),)), (2, (("fw_b", "fw_a"),)))
    assert outcome.ranked.select_precise_hits(query, outcome.pool) == selected
    assert spy.await_count == 1
    assert outcome.ranked.select_hits(query + " ", outcome.pool) is None
    tampered = [{**hit, "text": value + "!"} if hit == selected[0] else hit
                for hit in outcome.pool if isinstance(value := hit.get("text"), str)]
    assert outcome.ranked.select_hits(query, tampered) is None
    assert outcome.ranked.select_precise_hits(query, tampered) is None


@pytest.mark.asyncio
async def test_ranked_evidence_keeps_partial_scope_and_rejects_wrong_direction(service, monkeypatch, tmp_path):
    first = "#### 案例 1：不同场景\n\nFW_A→FW_B 的日志显示 2 发 1 收，接口选择应随后复核。"
    second = "#### 案例 2：另一个场景\n\nFW_B→FW_A 的日志显示 3 发 2 收，旁边还记录 FW_B 的配置。"
    edition = _edition(tmp_path / "partial-ranked", attached_caption=first, reviewed_page=second)
    monkeypatch.setattr(service, "edition", lambda: edition)
    query = "同一轮观察，FW_A→FW_B 的日志是什么？FW_B→FW_A 的日志又是什么？"
    result = await service.search_ranked_evidence(query, top_k=6)
    assert result.ranked is not None
    assert len(result.ranked.missing) == 1
    assert result.ranked.precise_case is None and not result.ranked.ambiguous_precise_case
    assert len(result.ranked.select_hits(query, result.pool)) == 1
    candidates = [hit for hit in result.pool if hit["facet_ids"]]
    assert {hit["facet_ids"] for hit in candidates} == {(1,), (2,)}
    assert len({hit["source_experiment_key"] for hit in candidates}) == 2

    explicit = "《1.3 状态记录与校验》PDF 第 4 页"
    scoped = await service.search_ranked_evidence(explicit, top_k=6)
    assert scoped.hits == await service.search(explicit, top_k=6)
    assert scoped.ranked is None and scoped.pool == []


@pytest.mark.asyncio
async def test_ranked_evidence_uses_actual_ordinary_mechanism_text(service, monkeypatch, tmp_path):
    first = "流量监管用于约束进入的流量，超过速率时在入接口标记或丢弃报文。"
    second = "流量整形用于平滑出口速率，当暂时超速时先缓存到队列，等待令牌后再发送。"
    decoy = "流量整形和流量监管使用相同的名词。关于处理动作请参见后续说明。"
    edition = _edition(tmp_path / "ranked-concepts", attached_caption=first, reviewed_page=f"{decoy}\n\n{second}")
    monkeypatch.setattr(service, "edition", lambda: edition)
    question = "流量监管和流量整形分别如何处理临时超速的报文？我只问教材原理。给图表文字。"
    result = await service.search_ranked_evidence(question, top_k=6)
    assert result.ranked and result.ranked.missing == ()
    selected = result.ranked.select_hits(question, result.pool)
    assert [hit["text"] for hit in selected] == [first, second]
    assert not any(hit.get("source_experiment_key") for hit in selected)


@pytest.mark.asyncio
async def test_ranked_evidence_preserves_page_continuation_and_distinct_source_steps(service, monkeypatch, tmp_path):
    first = "#### 2.1 双机读回实验\n\n##### 步骤 1 隔离验证\n\nFW_A→FW_B 的回显显示 2 发 1 收。"
    continuation = "FW_B→FW_A 的回显显示 3 发 2 收。"
    other_step = "##### 步骤 2 连通验证\n\nFW_B→FW_A 的回显显示 2 发 2 收。"
    edition = _edition(tmp_path / "ranked-steps", attached_caption=first,
                       reviewed_page=f"{continuation}\n\n{other_step}")
    monkeypatch.setattr(service, "edition", lambda: edition)
    request = "同一轮隔离验证，FW_A→FW_B 的回显是什么？FW_B→FW_A 的回显又是什么？"
    result = await service.search_ranked_evidence(request, top_k=6)
    assert result.ranked and result.ranked.missing == ()
    selected = result.ranked.select_hits(request, result.pool)
    assert [hit["page"] for hit in selected] == [3, 4]
    assert continuation in selected[1]["text"]
    assert selected[0]["source_phase_key"] == selected[1]["source_phase_key"]
    assert selected[0]["source_experiment_key"] == selected[1]["source_experiment_key"]
    assert all(hit["source_heading_path"][-1] == "步骤 1 隔离验证" for hit in selected)
    assert result.ranked.precise_case.scope == ("phase", selected[0]["source_phase_key"])


@pytest.mark.asyncio
async def test_ranked_evidence_precise_case_preserves_ambiguity_across_real_scopes(service, monkeypatch, tmp_path):
    first = "#### 案例 1：接入设备\n\nFW_A→FW_B 的回显显示 2 发 1 收。FW_B→FW_A 的回显显示 3 发 2 收。"
    second = "#### 案例 2：核心设备\n\nFW_A→FW_B 此次显示 5 发 5 收。FW_B→FW_A 此次显示 4 发 4 收。"
    edition = _edition(tmp_path / "ranked-ambiguous", attached_caption=first, reviewed_page=second)
    monkeypatch.setattr(service, "edition", lambda: edition)
    query = "同一轮探测，FW_A→FW_B 的回显是什么？FW_B→FW_A 的回显又是什么？"
    outcome = await service.search_ranked_evidence(query, top_k=6)
    assert outcome.ranked is not None and outcome.ranked.ambiguous_precise_case
    assert outcome.ranked.precise_case is None and outcome.ranked.select_precise_hits(query, outcome.pool) is None
    assert {hit["page"] for hit in outcome.pool if hit["facet_ids"]} == {3, 4}
    assert outcome.hits == await service.search(query, top_k=6)


@pytest.mark.asyncio
async def test_ranked_evidence_respects_explicit_independent_readbacks_and_keeps_same_case_constraints(service, monkeypatch, tmp_path):
    from modules.knowledge.ranked_evidence import _plan

    first = "#### 案例 1：接入场景\n\n在 OSPF 验证中，R7→R8 的探测回显显示 2 发 1 收。"
    second = "#### 案例 2：边界场景\n\n在 BGP 验证中，R9→R10 的探测回显显示 4 发 4 收。"
    edition = _edition(tmp_path / "ranked-independent", attached_caption=first, reviewed_page=second)
    monkeypatch.setattr(service, "edition", lambda: edition)
    query = "先看 OSPF 的 R7→R8 探测回显，再看 BGP 的 R9→R10 探测回显是多少？"
    independent = await service.search_ranked_evidence(query, top_k=6)
    assert independent.ranked and independent.ranked.missing == ()
    assert not independent.ranked.precise_case
    assert [hit["page"] for hit in independent.ranked.select_hits(query, independent.pool)] == [3, 4]

    coupled_query = f"同一案例，{query}"
    coupled = await service.search_ranked_evidence(coupled_query, top_k=6)
    assert coupled.ranked and len(coupled.ranked.missing) == 1
    assert not coupled.ranked.precise_case
    assert not _plan("比较两个不同实验，R7→R8 的回显如何？R9→R10 的回显如何？").same_experiment
    assert _plan("查看 R7→R8 配置前的回显，再看 R7→R8 配置后的回显。").same_experiment


@pytest.mark.asyncio
async def test_ranked_evidence_distinguishes_source_limits_from_positive_measurements(service, monkeypatch, tmp_path):
    from modules.knowledge.evidence_limits import evidence_limit_target, evidence_limit_witnesses

    observation = "R7→R8 的探测回显显示 2 发 2 收。会话读回仅记录这条邻接。"
    additional = "业务丢包与时延需要另按业务探测记录。"
    unrelated = "R7→R8 的回显显示 3 发 3 收。如果怀疑业务丢包，需要另行检查。"
    edition = _edition(tmp_path / "ranked-limits", attached_caption=f"{observation}\n\n{additional}", reviewed_page=unrelated)
    monkeypatch.setattr(service, "edition", lambda: edition)
    query = "R7→R8 的探测回显怎样，能当业务无丢包的证明吗？"
    outcome = await service.search_ranked_evidence(query, top_k=6)
    assert outcome.ranked and outcome.ranked.missing == ()
    assert [facet[2] for facet in outcome.ranked.facets] == ["readback", "evidence_limit"]
    assert outcome.ranked.precise_case is None
    measured, limit = outcome.ranked.select_hits(query, outcome.pool)
    assert measured["page"] == limit["page"] == 3
    assert limit["text"] == additional and limit["facet_witnesses"] == ((2, "required_observation"),)
    assert not measured.get("facet_witnesses")
    target = evidence_limit_target("这条日志能证明终端未续租吗？")
    assert evidence_limit_witnesses(target, "这条日志不能证明终端未续租。") == ("excluded_inference",)


def test_natural_evidence_limit_requires_an_explicit_statement_in_the_source():
    from modules.knowledge.evidence_limits import evidence_limit_target, evidence_limit_witnesses

    target = evidence_limit_target('只看会话 Up，够不够认定业务已经恢复？')
    assert target == '业务已经恢复'
    assert evidence_limit_witnesses(target, '不能只看会话状态就确定业务已恢复。') == ('excluded_inference',)
    assert evidence_limit_witnesses(target, '还得通过端到端探测记录业务恢复情况。') == ('required_observation',)
    assert not evidence_limit_witnesses(target, '这里的会话回显写着 Up，业务仍待观察。')
    assert not evidence_limit_witnesses(target, '不能据此认定管理会话已恢复。')
    assert evidence_limit_witnesses(target, "这条日志不能证明终端续租。") == ()


@pytest.mark.asyncio
async def test_ranked_evidence_keeps_complete_output_with_its_own_contiguous_caption(service, monkeypatch, tmp_path):
    caption = "**FW_A 处理完成后，查看本设备记录，实际回显如下：**"
    output = "```text\ndisplay recorded state\nLast exit reason: normal\nTransitions: 2\n```"
    foreign = f"FW_B 执行相同动作后的实际回显如下：\n\n{output.replace('normal', 'down')}"
    source = f"{caption}\n\n{output}"
    edition = _edition(tmp_path / "ranked-caption", attached_caption=source, reviewed_page=foreign)
    monkeypatch.setattr(service, "edition", lambda: edition)
    query = "FW_A 的 Last exit reason 回显是什么？"
    result = await service.search_ranked_evidence(query, top_k=6)
    assert result.ranked and result.ranked.missing == ()
    [selected] = result.ranked.select_hits(query, result.pool)
    assert selected["page"] == 3 and selected["text"] == source

    split_edition = _edition(tmp_path / "ranked-detached-caption", attached_caption=caption,
                             reviewed_page=f"{output}\n\n{foreign}")
    monkeypatch.setattr(service, "edition", lambda: split_edition)
    detached = await service.search_ranked_evidence(query, top_k=6)
    assert detached.ranked and detached.ranked.observation_facets == (1,)
    assert detached.ranked.missing == (1,) and detached.ranked.select_verified_observations(query, detached.pool) is None


@pytest.mark.asyncio
async def test_ranked_evidence_keeps_figures_and_their_own_adjacent_explanations(service, monkeypatch, tmp_path):
    figure = "图 3-8 双机链路方向"
    explanation = "从图中可见，FW_A→FW_B 发起状态协商，通过独立控制链路发送请求。"
    other = "图 3-9 中，FW_A→FW_B 利用管理链路发送另一类通告。"
    edition = _edition(tmp_path / "ranked-figure", attached_caption=f"{figure}\n\n{explanation}",
                       reviewed_page=f"{figure}\n\n{other}")
    monkeypatch.setattr(service, "edition", lambda: edition)
    question = "图 3-8 中 FW_A→FW_B 的箭头表示什么？"
    result = await service.search_ranked_evidence(question, top_k=6)
    [selected] = result.ranked.select_hits(question, result.pool)
    assert selected["page"] == 3 and selected["text"] == f"{figure}\n\n{explanation}"
    assert not any(hit["page"] == 4 and hit["facet_ids"] for hit in result.pool)


@pytest.mark.asyncio
async def test_ranked_evidence_combines_only_individually_proven_phases_of_one_original_case(service, monkeypatch, tmp_path):
    first = "##### 步骤 1 配置前链路验证\n\nR7→R8 的回显显示 2 发 0 收。"
    second = "##### 步骤 2 配置后链路验证\n\nR7→R8 的回显显示 2 发 2 收。"
    source = _edition(tmp_path / "ranked-phase-pair", chapter_heading="案例 1：端点连通",
                      attached_caption=first, reviewed_page=second)
    monkeypatch.setattr(service, "edition", lambda: source)
    question = "同一案例中 R7→R8 配置前回显是什么？R7→R8 配置后回显是什么？"
    result = await service.search_ranked_evidence(question, top_k=6)
    assert result.ranked and result.ranked.precise_case
    selected = result.ranked.select_precise_hits(question, result.pool)
    assert [hit["page"] for hit in selected] == [3, 4]
    assert [hit["facet_phase_ids"] for hit in selected] == [(1,), (2,)]
    assert len({hit["source_phase_key"] for hit in selected}) == 2
    assert result.ranked.precise_case.scope == ("experiment", selected[0]["source_experiment_key"])

    different = _edition(tmp_path / "ranked-phase-pair-foreign", chapter_heading="案例 1：端点连通",
                         attached_caption=first, reviewed_page=f"#### 案例 2：独立链路\n\n{second}")
    monkeypatch.setattr(service, "edition", lambda: different)
    outside = await service.search_ranked_evidence(question, top_k=6)
    assert outside.ranked and len(outside.ranked.missing) == 1
    assert outside.ranked.precise_case is None


@pytest.mark.asyncio
async def test_ranked_evidence_keeps_unbound_single_concept_in_ordinary_results(service, monkeypatch, tmp_path):
    first = "配置抢占延时后，VRRP 主用设备切换时延迟发出新的公告。"
    edition = _edition(tmp_path / "ranked-single-concept", attached_caption=first)
    monkeypatch.setattr(service, "edition", lambda: edition)
    query = "教材里 VRRP 抢占延时为什么会影响切换？我只问教材原理。"
    result = await service.search_ranked_evidence(query, top_k=6)
    assert result.hits == await service.search(query, top_k=6)
    assert result.pool and result.ranked is None


@pytest.mark.asyncio
async def test_ranked_evidence_selects_only_the_complete_definition_for_a_plain_concept(service, monkeypatch, tmp_path):
    definition = "演示协议是一种用于同步两端控制信息的通信框架。"
    extra = "图中 R2 最后收到了两条请求，演示协议配置记录列在下一页。"
    decoy = "**演示协议的实机示例。** R17 展示了该协议的状态和回显，仅用于操作演练。"
    candidate = _edition(tmp_path / "plain-principle", attached_caption=definition + extra, reviewed_page=decoy)
    monkeypatch.setattr(service, "edition", lambda: candidate)
    query = "只问教材原理。演示协议是什么？"
    result = await service.search_ranked_evidence(query, top_k=6)
    assert result.hits == await service.search(query, top_k=6)
    assert result.ranked and result.ranked.missing == ()
    [selected] = result.ranked.select_verified_explanations(query, result.pool)
    assert selected["text"] == definition and selected["page"] == 3

    scoped = "R17 的演示协议实际回显是什么？"
    observed = await service.search_ranked_evidence(scoped, top_k=6)
    assert not observed.ranked or not observed.ranked.select_verified_explanations(scoped, observed.pool)


@pytest.mark.asyncio
async def test_ranked_evidence_does_not_choose_between_distinct_principle_definitions(service, monkeypatch, tmp_path):
    first = "端点观察是一套测量通信切换间隔的方法。"
    second = "端点观察是一项正在运行的状态回传功能。"
    candidate = _edition(tmp_path / "ambiguous-principle", attached_caption=first, reviewed_page=second)
    monkeypatch.setattr(service, "edition", lambda: candidate)
    query = "教材中端点观察是什么？"
    result = await service.search_ranked_evidence(query, top_k=6)
    assert result.hits == await service.search(query, top_k=6)
    assert result.ranked and result.ranked.select_verified_explanations(query, result.pool) is None


@pytest.mark.asyncio
async def test_ranked_evidence_verifies_each_named_principle_on_its_own_page(service, monkeypatch, tmp_path):
    first = "消息通道是一种传递格式化控制信息的通信机制。"
    second = "邻接索引主要用于快速查找相邻端点的存储记录。"
    third = "事件模型指把状态变化和通知内容映射成标准记录。"
    candidate = _edition(tmp_path / "independent-principles", attached_caption=f"**消息通道。** {first} {third}",
                         reviewed_page=f"**邻接索引。** {second}")
    monkeypatch.setattr(service, "edition", lambda: candidate)
    query = "只问教材原理。消息通道是什么？邻接索引的作用是什么？何谓事件模型？"
    result = await service.search_ranked_evidence(query, top_k=6)
    assert result.hits == await service.search(query, top_k=6)
    assert result.ranked and result.ranked.missing == ()
    chosen = result.ranked.select_verified_explanations(query, result.pool)
    assert [(hit["page"], hit["text"]) for hit in chosen] == [(3, first), (4, second), (3, third)]
    assert result.ranked.select_verified_explanations(query.replace("何谓", "什么是"), result.pool) is None
    for hit in chosen:
        assert hit["text"] in candidate.read(hit["document_id"], hit["document_version"])["content"]

    too_few = await service.search_ranked_evidence(query, top_k=2)
    assert not too_few.ranked or not too_few.ranked.select_verified_explanations(query, too_few.pool)


@pytest.mark.asyncio
async def test_uncertain_multi_principles_retain_previous_selection(service, monkeypatch, tmp_path):
    from modules.knowledge import ranked_evidence

    first = "端点观察是一套测量通信切换间隔的方法。"
    second = "端点观察是一项正在运行的状态回传功能。"
    purpose = "邻接索引用于快速查找相邻端点的存储记录。"
    candidate = _edition(tmp_path / "uncertain-principles", attached_caption=f"{first} {purpose}", reviewed_page=second)
    monkeypatch.setattr(service, "edition", lambda: candidate)
    questions = (
        "只问教材原理。端点观察是什么？邻接索引有什么作用？",
        "只问教材原理。端点观察是什么？查找协议有什么作用？",
        "只问教材原理。端点观察是什么？这个东西有什么作用？",
        "只问教材原理。端点观察是什么？R17 的邻接索引回显是什么？",
        "端点观察是什么？邻接索引有什么作用？",
    )
    for query in questions:
        result = await service.search_ranked_evidence(query, top_k=6)
        with monkeypatch.context() as baseline:
            baseline.setattr(ranked_evidence, "_independent_principles", lambda terms, plan: None)
            previous = await service.search_ranked_evidence(query, top_k=6)
        assert result == previous, query


@pytest.mark.asyncio
async def test_ranked_evidence_reports_partial_verified_observation_without_using_a_plan_as_readback(service, monkeypatch, tmp_path):
    question = "同一份 MSTP 课堂记录里，SW-A 在动手之前显示哪一类端口角色？做完这步后，SW-B 又显示哪一类端口角色？"
    before = "##### 步骤 1 动手之前的原记录\n\nMSTP 实际回显中，SW-A 的端口角色为 ROOT，状态列为 FORWARDING。"
    after = "##### 步骤 2 做完这步后的复核\n\n规划里预计 SW-B 的端口角色为 Alternate，后续才看实际配置。"
    source = _edition(tmp_path / "verified-observation", chapter_heading="案例 1：端口角色观察",
                      attached_caption=before, reviewed_page=after)
    monkeypatch.setattr(service, "edition", lambda: source)
    ordinary = await service.search(question, top_k=6)
    outcome = await service.search_ranked_evidence(question, top_k=6)
    assert outcome.hits == ordinary
    assert outcome.ranked and outcome.ranked.observation_facets == (1, 2)
    assert [facet[2] for facet in outcome.ranked.facets] == ["readback", "readback"]
    assert [number for number, _ in outcome.ranked.verified_observation] == [1]
    assert outcome.ranked.missing == (2,)
    assert outcome.ranked.ambiguous_observation_facets == ()
    [witness] = outcome.ranked.select_verified_observations(question, outcome.pool)
    assert witness["page"] == 3 and witness["facet_readback_ids"] == (1,)
    assert "角色为 ROOT" in witness["text"] and "预计" not in witness["text"]
    assert outcome.ranked.select_verified_observations(question + "。", outcome.pool) is None


@pytest.mark.asyncio
async def test_ranked_evidence_withholds_observation_proof_when_actual_readbacks_have_different_origins(service, monkeypatch, tmp_path):
    first = "#### 案例 1：接入侧\n\n实际回显中，SW-A 的端口角色为 Root，状态为 Forwarding。"
    second = "#### 案例 2：另一处接入\n\n实际回显中，SW-A 的端口角色为 Alternate，状态为 Discarding。"
    source = _edition(tmp_path / "verified-ambiguous", attached_caption=first, reviewed_page=second)
    monkeypatch.setattr(service, "edition", lambda: source)
    question = "SW-A 的实际回显显示哪一类端口角色？"
    outcome = await service.search_ranked_evidence(question, top_k=6)
    assert outcome.ranked and outcome.ranked.observation_facets == (1,)
    assert not outcome.ranked.verified_observation
    assert outcome.ranked.ambiguous_observation_facets == (1,)
    assert outcome.ranked.select_verified_observations(question, outcome.pool) is None
    assert {hit["page"] for hit in outcome.pool if hit.get("facet_readback_ids")} == {3, 4}


@pytest.mark.asyncio
async def test_ranked_evidence_does_not_confirm_conflicting_observations_under_one_original_heading(service, monkeypatch, tmp_path):
    first = "实际回显中，SW-A 的端口角色为 Root，状态为 Forwarding。"
    second = "实际回显中，SW-A 的端口角色为 Alternate，状态为 Discarding。"
    question = "SW-A 的实际回显显示哪一类端口角色？"
    conflict = _edition(tmp_path / "same-heading-conflict", chapter_heading="案例 1：接入侧",
                        attached_caption=f"{first}\n\n{second}")
    monkeypatch.setattr(service, "edition", lambda: conflict)
    outcome = await service.search_ranked_evidence(question, top_k=6)
    assert outcome.ranked and outcome.ranked.ambiguous_observation_facets == (1,)
    assert outcome.ranked.select_verified_observations(question, outcome.pool) is None

    duplicate = _edition(tmp_path / "same-heading-duplicate", chapter_heading="案例 1：接入侧",
                         attached_caption=f"{first}\n\n{first}")
    monkeypatch.setattr(service, "edition", lambda: duplicate)
    outcome = await service.search_ranked_evidence(question, top_k=6)
    assert outcome.ranked and outcome.ranked.ambiguous_observation_facets == ()
    [source] = outcome.ranked.select_verified_observations(question, outcome.pool)
    assert source["page"] == 3 and source["text"] == first


@pytest.mark.asyncio
async def test_ranked_evidence_preserves_a_complete_long_cli_table_for_one_explicit_row(service, monkeypatch, tmp_path):
    query = 'MSTP 教材中 SW-A 的实际回显显示 GigabitEthernet0/0/28 是哪一类端口角色？'
    rows = [f'GE0/0/{index:<2}    0    {"Alternate" if index == 28 else "Root"}    Forwarding' for index in range(32)]
    header = '```text\n<SW-A> display stp brief\nPort    Instance    Role    State\n'
    actual = header + '\n'.join(rows) + '\n```'
    assert 1080 < len(actual) < 2450
    edition = _edition(tmp_path / 'single-anchored-row', chapter_heading='MSTP 端口角色', attached_caption=actual)
    monkeypatch.setattr(service, 'edition', lambda: edition)
    result = await service.search_ranked_evidence(query, top_k=6)
    assert result.ranked and result.ranked.observation_facets == (1,)
    [proof] = result.ranked.select_verified_observations(query, result.pool)
    assert proof['text'] == actual and proof['page'] == 3

    duplicate = header + '\n'.join([*rows, 'GE0/0/28    0    Root    Forwarding']) + '\n```'
    conflicting = _edition(tmp_path / 'duplicate-anchored-row', chapter_heading='MSTP 端口角色', attached_caption=duplicate)
    monkeypatch.setattr(service, 'edition', lambda: conflicting)
    result = await service.search_ranked_evidence(query, top_k=6)
    assert result.ranked and result.ranked.select_verified_observations(query, result.pool) is None

    wrong_column = '```text\n<SW-A> display stp brief\nPort    Role    Remark\nGE0/0/28    Unknown    Root\n```'
    invalid = _edition(tmp_path / 'unrelated-column', chapter_heading='MSTP 端口角色', attached_caption=wrong_column)
    monkeypatch.setattr(service, 'edition', lambda: invalid)
    result = await service.search_ranked_evidence(query, top_k=6)
    assert result.ranked and result.ranked.select_verified_observations(query, result.pool) is None


@pytest.mark.asyncio
async def test_ranked_evidence_distinguishes_the_reporting_device_from_the_row_peer(service, monkeypatch, tmp_path):
    query = 'OSPF 实验里 R4 的回显中 R5 这条记录显示什么状态？'
    table = 'Neighbor    State    Area\n'
    direct = f'```text\n<R4> display ospf peer brief\n{table}R5    Full    0\n```'
    reverse = f'```text\n<R5> display ospf peer brief\n{table}R4    Down    0\n```'
    edition = _edition(tmp_path / 'observer-and-row-peer', attached_caption=reverse, reviewed_page=direct)
    monkeypatch.setattr(service, 'edition', lambda: edition)
    result = await service.search_ranked_evidence(query, top_k=6)
    assert result.ranked and result.ranked.observation_facets == (1,)
    [proof] = result.ranked.select_verified_observations(query, result.pool)
    assert proof['text'] == direct and proof['page'] == 4

    incomplete = 'OSPF 实验里 R4 的回显中除了 R5，其他邻居显示什么状态？'
    result = await service.search_ranked_evidence(incomplete, top_k=6)
    assert result.ranked and result.ranked.select_verified_observations(incomplete, result.pool) is None


@pytest.mark.asyncio
async def test_ranked_evidence_explanation_binds_a_named_title_to_its_actual_role_direction(service, monkeypatch, tmp_path):
    primary = "**RADIUS。** NAS 请求服务器验证，根据响应完成这次认证。"
    matched = "**HWTACACS。** 设备建立到集中服务端的连接，随后独立发送授权请求。"
    reverse = "**HWTACACS。** 集中服务端向设备建立连接，设备接收授权请求。"
    query = "RADIUS 和 HWTACACS 分别由谁发起到服务端？"
    edition = _edition(tmp_path / "explanation-role", attached_caption=primary, reviewed_page=matched)
    monkeypatch.setattr(service, "edition", lambda: edition)
    outcome = await service.search_ranked_evidence(query, top_k=6)
    assert outcome.ranked and outcome.ranked.observation_facets == ()
    assert [hit["text"] for hit in outcome.ranked.select_verified_explanations(query, outcome.pool)] == [primary, matched]
    assert outcome.ranked.select_verified_explanations(query + "！", outcome.pool) is None

    decoy = _edition(tmp_path / "explanation-reverse", attached_caption=primary, reviewed_page=reverse)
    monkeypatch.setattr(service, "edition", lambda: decoy)
    outcome = await service.search_ranked_evidence(query, top_k=6)
    assert [hit["text"] for hit in outcome.ranked.select_verified_explanations(query, outcome.pool)] == [primary]


@pytest.mark.asyncio
async def test_ranked_evidence_limit_points_to_independent_evidence_without_stating_the_result(service, monkeypatch, tmp_path):
    output = "```text\n[R3]display mpls lsp\nFEC                 Out-interface\n10.10.10.4/32       GE0/0/2\n```"
    boundary = "MPLS 的 LSP 已显示出接口。业务 VPNv4 对等体状态独立见下一页。"
    question = "R3 的 MPLS 标签表里 10.10.10.4/32 的出口在哪？这份输出是否能证明 VPNv4 对等体已经建立？"
    edition = _edition(tmp_path / "separate-observation", attached_caption=f"{output}\n\n{boundary}")
    monkeypatch.setattr(service, "edition", lambda: edition)
    outcome = await service.search_ranked_evidence(question, top_k=6)
    assert outcome.ranked and outcome.ranked.missing == () and outcome.ranked.observation_facets == (1,)
    readback, limit = outcome.ranked.select_hits(question, outcome.pool)
    assert readback["page"] == limit["page"] == 3
    assert readback["text"] == output and limit["text"] == boundary
    assert limit["facet_witnesses"] == ((2, "separate_observation"),)
    assert not limit.get("facet_readback_ids")
    assert outcome.ranked.select_verified_explanations(question, outcome.pool) == [limit]


@pytest.mark.asyncio
async def test_ranked_evidence_explanation_verifies_a_named_field_independently_from_a_cli_result(service, monkeypatch, tmp_path):
    output = "```text\n[R2]display bgp routing-table 172.17.0.0 22\nPrefix : 172.17.0.0/22\nDirect Out-interface: NULL0\nAS-path Nil\n```"
    reason = "从这个 BGP 输出能看到 AS_Path 值为 Nil。BGP 依赖 AS_Path 实现防环，因此聚合时丢失该字段可能造成路由环。"
    query = "R2 的 BGP 回显中，172.17.0.0/22 的 Direct Out-interface 写了什么？AS_PATH 变空为什么有防环风险？"
    edition = _edition(tmp_path / "field-explanation", attached_caption=f"{output}\n\n{reason}")
    monkeypatch.setattr(service, "edition", lambda: edition)
    outcome = await service.search_ranked_evidence(query, top_k=6)
    assert outcome.ranked and outcome.ranked.observation_facets == (1,)
    [proved] = outcome.ranked.select_verified_explanations(query, outcome.pool)
    assert proved["text"] == reason and proved["page"] == 3 and proved["facet_explanation_ids"] == (2,)
    assert not proved.get("facet_readback_ids")


@pytest.mark.asyncio
async def test_ranked_evidence_reuses_complete_named_output_with_linked_field_explanation(service, monkeypatch, tmp_path):
    output = ("```text\n[R1]display ospf lsdb network\nAttached Router    10.0.1.1\n"
              "Attached Router    10.0.2.2\nAttached Router    10.0.3.3\n```")
    note = "从输出信息可以看到，Attached Router 描述了 DR 所在网段的邻居。"
    question = ("R1 的 OSPF Network-LSA 读回里面，Attached Router 实际列了哪三个地址？"
                "这字段说明的是哪一范围的邻居？要同一次输出和解释。")
    edition = _edition(tmp_path / "linked-field", attached_caption=f"{output}\n\n{note}")
    monkeypatch.setattr(service, "edition", lambda: edition)
    normal = await service.search(question, top_k=6)
    result = await service.search_ranked_evidence(question, top_k=6)
    assert result.hits == normal
    assert result.ranked and result.ranked.missing == () and result.ranked.observation_facets == (1,)
    [selected] = result.ranked.select_verified_observations(question, result.pool)
    assert result.ranked.select_verified_explanations(question, result.pool) == [selected]
    assert selected["page"] == 3 and selected["text"] == f"{output}\n\n{note}"

    disconnected = _edition(tmp_path / "unlinked-field", attached_caption=output, reviewed_page=note)
    monkeypatch.setattr(service, "edition", lambda: disconnected)
    other_page = await service.search_ranked_evidence(question, top_k=6)
    assert other_page.ranked and other_page.ranked.missing == (2,)
    assert other_page.ranked.select_verified_explanations(question, other_page.pool) is None


@pytest.mark.asyncio
async def test_ranked_evidence_does_not_borrow_field_explanation_from_another_show_output(service, monkeypatch, tmp_path):
    question = "R1 的 OSPF 回显里 Attached Router 列了哪三个地址？这个字段描述什么？"
    first = ("```text\n[R1]display ospf lsdb network\nAttached Router    10.0.1.1\n"
             "Attached Router    10.0.2.2\nAttached Router    10.0.3.3\n```")
    other = "```text\n[R2]display ospf lsdb router\nAdvertised Router    10.0.5.5\n```"
    note = "从输出信息可以看到 Attached Router 描述了另一份表的范围。"
    source = _edition(tmp_path / "wrong-field-record", attached_caption="\n\n".join((first, other, note)))
    monkeypatch.setattr(service, "edition", lambda: source)
    result = await service.search_ranked_evidence(question, top_k=6)
    assert result.ranked and result.ranked.select_verified_explanations(question, result.pool) is None
    assert result.ranked.select_verified_observations(question, result.pool)


@pytest.mark.asyncio
async def test_ranked_evidence_binds_field_spelling_to_the_single_output_record(service, monkeypatch, tmp_path):
    command = "<R2>display bgp routing-table 172.17.0.0 22"
    record = "BGP routing table entry information of 172.17.0.0/22:\nAS-path Nil"
    note = "从输出信息可以看到 AS_Path 值为 Nil，表示 AS_Path 属性为空。"
    question = "R2 的 BGP 回显里 172.17.0.0/22 的 AS_PATH 写了什么？这个字段表示什么？"
    bounded = f"```text\n{command}\n{record}\n```\n\n{note}"
    original = _edition(tmp_path / "single-output-object", attached_caption=bounded)
    monkeypatch.setattr(service, "edition", lambda: original)
    hit = await service.search_ranked_evidence(question, top_k=6)
    assert hit.ranked and hit.ranked.missing == ()
    [source] = hit.ranked.select_verified_explanations(question, hit.pool)
    assert source["text"] == bounded and source["page"] == 3

    adjacent = "BGP routing table entry information of 172.18.0.0/22:\nAS-path 64512"
    multiple = _edition(tmp_path / "multiple-output-objects",
                        attached_caption=f"```text\n{command}\n{record}\n{adjacent}\n```\n\n{note}")
    monkeypatch.setattr(service, "edition", lambda: multiple)
    ambiguous = await service.search_ranked_evidence(question, top_k=6)
    assert ambiguous.ranked and ambiguous.ranked.select_verified_explanations(question, ambiguous.pool) is None


@pytest.mark.asyncio
async def test_route_readback_reaches_prepared_context_with_exact_device_binding(service, tmp_path, monkeypatch):
    from tests.test_readonly_route_tables import ROUTING_QUERY, R17_ROWS, R19_ROWS, route_page

    edition = _edition(tmp_path / "routing", reviewed_page=route_page().strip())
    monkeypatch.setattr(service, "edition", lambda: edition)
    hit = next(hit for hit in await service.search(ROUTING_QUERY) if hit["document_id"] == "audited-1" and hit["page"] == 4)
    [display] = prepare_sources([hit], max_document_chars=1300)
    reading = edition.read(hit["document_id"], hit["document_version"])
    actual = next(page for page in reading["original_pages"] if page["physical"] == 4)

    assert hit["partial_readonly_table"] and not display["truncated"]
    assert display["section_id"] == actual["section_id"]
    assert all(row in display["content"] and row in reading["content"] for row in R17_ROWS)
    assert not any(row in display["content"] for row in R19_ROWS)
    assert edition.resolve_hits([hit], edition.keyword_index, "ip-ops-kb", query=ROUTING_QUERY) == []


@pytest.mark.asyncio
async def test_upper_rr_uses_its_own_complete_instructions_not_adjacent_tier(service, tmp_path, monkeypatch):
    first = "在园区骨干中，R40 是一级 RR，R23 和 R29 是二级 RR。"
    different_level = "将 R11、R40 配置为 R23 的反射器客户端。"
    target = "R40 作为一级 RR，需要和两台边界设备交换路由，将 R23、R29 配置为 R40 的\n\n反射器客户端。"
    source = f"{first}\n\n#### 实验步骤\n\n3.\n\n{different_level}\n\n4.\n\n{target}\n\n5.\n\n核对链路状态。"
    edition = _edition(tmp_path / "rr-tiers", reviewed_page=source)
    monkeypatch.setattr(service, "edition", lambda: edition)
    query = "两台二级 RR 向上一层学习。一级 RR 是谁，这两台反射器客户端又是谁？"
    hit = next(hit for hit in await service.search(query) if hit["document_id"] == "audited-1" and hit["page"] == 4)
    [display] = prepare_sources([hit], max_document_chars=1300)

    assert display["section_id"] == hit["section_id"] and not display["truncated"]
    assert target in display["content"] and "4.\n\n" in display["content"]
    assert different_level not in display["content"]


@pytest.mark.asyncio
async def test_frozen_vector_needs_membership_and_literal_page_match(service, frozen, tmp_path, monkeypatch):
    record = frozen.documents["audited-1"]
    alias = "ipsim-0123456789abcdef-001.md"
    imported = "custom-documents/audited-1.json"
    freeze_path = frozen.root / "freeze.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    freeze["anythingllm"]["documents"][record["path"]] = {
        "logical_id": record["doc_id"], "source_sha256": record["sha256"], "alias": alias,
        "provider_id": "collector-one", "document_id": imported,
    }
    _write_json(freeze_path, freeze)
    current = KnowledgeEdition(frozen.root)
    monkeypatch.setattr(service, "edition", lambda: current)
    storage = tmp_path / "vector-storage"
    documents = storage / "documents"
    (documents / "uploads").mkdir(parents=True)
    (documents / "custom-documents").mkdir()
    raw = (frozen.root / "corpus" / record["path"]).read_bytes()
    (documents / "uploads" / alias).write_bytes(raw)
    _write_json(documents / imported, {"pageContent": raw.decode()})
    with closing(sqlite3.connect(storage / "anythingllm.db")) as db:
        db.executescript("""
            CREATE TABLE workspaces (id INTEGER, slug TEXT);
            CREATE TABLE workspace_documents (workspaceId INTEGER, docId TEXT, docpath TEXT);
            CREATE TABLE document_vectors (vectorId TEXT, docId TEXT);
            INSERT INTO workspaces VALUES (1, 'textbook-audit');
            INSERT INTO workspace_documents VALUES (1, 'collector-one', 'custom-documents/audited-1.json');
            INSERT INTO document_vectors VALUES ('current-vector', 'collector-one');
        """)
    service.provider._default_storage_dir = lambda: str(storage)
    service.provider.search.return_value = [
        {"title": alias, "raw": {"id": "unregistered"}, "text": _SENTENCE},
        {"title": alias, "raw": {"id": "current-vector"}, "text": "片段声称原文中并不存在的旧结果。"},
        {"title": alias, "raw": {"id": "current-vector"}, "text": _SENTENCE},
    ]
    hits = current.resolve_hits(service.provider.search.return_value, service.provider, "textbook-audit")
    assert len(hits) == 1
    hit = hits[0]
    assert (hit["retriever"], hit["document_id"], hit["page"], hit["text"]) == (
        "edition_vector", "audited-1", 4, _SENTENCE,
    )
    assert hit["section_id"] and hit["document_version"] == record["sha256"]


def test_fusion_boosts_confirmed_pages_and_limits_vector_only_candidates():
    def passage(page, retriever):
        return {"book": 1, "page": page, "retriever": retriever}

    local = [passage(page, "edition_local") for page in (1, 2, 3, 4, 5)]
    vector = [passage(page, "edition_vector") for page in (6, 7, 3, 8, 9)]
    hits = _blend_same_edition(local, vector, 5)
    assert hits[0]["page"] == 3
    assert hits[0]["retriever"] == "edition_fused" and hits[0]["fusion"] == {"lexical_rank": 3, "vector_rank": 3}
    assert len(hits) == 5 and len([hit for hit in hits if hit["retriever"] == "edition_vector"]) == 1


@pytest.mark.asyncio
async def test_frozen_natural_query_considers_vectors_despite_full_local_results(service, frozen, monkeypatch):
    frozen.aliases["available-edition-import"] = True
    literal = "首先采集空白记录。"
    matches = [
        {"raw": {"id": "weak"}, "text": literal},
        {"raw": {"id": "strong"}, "text": _SENTENCE},
    ]
    service.provider.search.return_value = matches
    document = frozen.documents["audited-1"]
    body = frozen.read(document["id"], document["sha256"])["content"]
    monkeypatch.setattr(frozen, "_vector_members", lambda *_: {
        identifier: {"document_id": document["id"], "stored_text": body} for identifier in ("weak", "strong")
    })
    hits = await service.search("观察节点要怎样校验完整的内容？", "textbook-audit", 2)
    service.provider.search.assert_awaited_once_with("观察节点要怎样校验完整的内容？", "textbook-audit", 6)
    assert len(hits) == 2 and hits[0]["page"] == 4 and hits[0]["retriever"] == "edition_fused"
    assert all(hit.get("retriever") != "edition_vector" for hit in hits)

    service.provider.search.reset_mock()
    await service.search(f'逐字查找原句“{_SENTENCE}”', "textbook-audit", 2)
    await service.search('逐字查找原句“未登记的合成句子”', "textbook-audit", 2)
    await service.search("在《状态记录基础手册》第 4 页怎样校验？", "textbook-audit", 2)
    service.provider.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_vector_timeout_keeps_original_local_order(service, frozen, monkeypatch):
    from modules.knowledge import service as knowledge_service_module

    query = "观察节点要怎样校验完整的内容？"
    local = await service.search(query, "textbook-audit", 2)
    frozen.aliases["available-edition-import"] = True
    monkeypatch.setattr(knowledge_service_module, "_EDITION_VECTOR_TIMEOUT", .01)

    async def wait_for_index(*_args):
        await asyncio.sleep(1)

    service.provider.search.side_effect = wait_for_index
    assert await service.search(query, "textbook-audit", 2) == local
    service.provider.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_default_same_workspace_is_local_without_an_explicit_vector_choice(service, frozen, monkeypatch):
    from modules.knowledge import service as knowledge_service_module

    settings = knowledge_service_module.get_settings()
    monkeypatch.setattr(settings, "knowledge_workspace_slug", "textbook-audit")
    frozen.aliases["available-edition-import"] = True
    query = "观察节点要怎样校验完整的内容？"
    hits = await service.search(query)
    assert hits and all(hit["retriever"] != "edition_vector" for hit in hits)
    assert (await service.ask(query))["sources"] == hits
    service.provider.search.assert_not_awaited()


@pytest.mark.parametrize("role", ["navigation", "non-instruction"])
@pytest.mark.asyncio
async def test_original_access_does_not_grant_factual_retrieval(service, tmp_path, monkeypatch, role):
    explicit = "首先采集空白记录。"
    edition = _edition(tmp_path / "non-evidence-page", reviewed_page=explicit, blocked={("audited-1", 4): role})
    edition.originals = SimpleNamespace(page_status=lambda _book: "available", render=lambda _book, _page: _FIGURE)
    monkeypatch.setattr(service, "edition", lambda: edition)
    record = edition.documents["audited-1"]
    reading = await service.read_document(record["id"], None, record["sha256"])
    blocked = next(page for page in reading["original_pages"] if page["physical"] == 4)
    assert blocked["preview"] and not blocked["evidence_eligible"]
    assert await service.original_figure(record["id"], record["sha256"], 4) == _FIGURE
    assert await service.search(f'在《状态记录基础手册》第 4 页查找原句“{explicit}”') == []
    [match] = await service.search(f'在《状态记录基础手册》查找原句“{explicit}”')
    assert match["page"] == 3

    member = {"document_id": record["id"], "stored_text": reading["content"]}
    monkeypatch.setattr(edition, "_vector_members", lambda *_args: {"valid-vector": member})
    same_text = {"raw": {"id": "valid-vector"}, "text": explicit}
    located_blocked = {**same_text, "text": f"### PDF 第 4 页\r\n\r\n{explicit}"}
    located_allowed = {**same_text, "text": f"### PDF 第 3 页\r\n\r\n{explicit}"}
    matched = edition.resolve_hits([same_text, located_blocked, located_allowed], service.provider, "textbook-audit")
    assert len(matched) == 1 and matched[0]["page"] == 3


@pytest.mark.asyncio
async def test_unavailable_edition_and_explicit_historical_workspace(service, frozen):
    for document in frozen.documents.values():
        (frozen.root / "corpus" / document["path"]).write_text("已变更，摘要与冻结版本不符。", encoding="utf-8")
    with pytest.raises(DocumentReadError, match="当前教材版本暂不可检索"):
        await service.search("状态记录与校验过程是什么？")
    degraded = await service.ask("状态记录与校验过程是什么？")
    assert degraded["status"] == "degraded" and not degraded["sources"]
    service.provider.search.assert_not_awaited()
    service.provider.ask.assert_not_awaited()

    assert await service.search("状态记录", "history") == [{"text": "旧版片段"}]
    historic = await service.ask("状态记录", "history")
    assert historic["answer"] == "历史工作区回答"
    assert (await service.legacy_locator("old-logical-id", "old-version", None))["status"] == "archive-only"


@pytest.mark.asyncio
async def test_ask_passes_same_edition_sources_to_existing_answer_path(service):
    result = await service.ask(_SENTENCE, top_k=1)
    assert result["answer"] == "" and result["status"] == "ok"
    assert result["provider"] == "local"
    assert len(result["sources"]) == 1 and _SENTENCE in result["sources"][0]["text"]
    service.provider.ask.assert_not_awaited()


@pytest.mark.asyncio
async def test_history_is_only_reopened_by_authorized_id_and_matching_version(service, frozen, tmp_path, monkeypatch):
    from modules.knowledge import service as knowledge_service_module

    previous = _edition(tmp_path / "archive", archived=True)
    settings = knowledge_service_module.get_settings()
    monkeypatch.setattr(settings, "knowledge_previous_edition_dir", str(previous.root), raising=False)
    current_hash = frozen.documents["audited-1"]["sha256"]
    old_hash = previous.documents["audited-1"]["sha256"]
    current = await service.read_document("audited-1", None, None)
    history = await service.read_document("audited-1", None, old_hash)
    assert current["version"] == current_hash and _SENTENCE in current["content"]
    assert history["version"] == old_hash and _PREVIOUS_SENTENCE in history["content"]
    assert history["historical_edition"] and history["edition_version"] == "previous-edition"
    assert await service.original_figure("audited-1", old_hash, 4) == _FIGURE
    with pytest.raises(DocumentReadError) as unavailable:
        await service.original_figure("audited-1", current_hash, 4)
    assert unavailable.value.code == "preview_unavailable"
    with pytest.raises(DocumentReadError) as changed:
        await service.read_document("audited-1", None, "0" * 64)
    assert changed.value.code == "document_changed"
    removed_hash = previous.documents["audited-3"]["sha256"]
    with pytest.raises(DocumentReadError):
        await service.read_document("audited-3", None, removed_hash)
    with pytest.raises(DocumentReadError) as withdrawn:
        await service.original_figure("audited-3", removed_hash, 4)
    assert withdrawn.value.code == "document_revoked"
    assert await service.search(f'查找原句“{_PREVIOUS_SENTENCE}”') == []


@pytest.mark.asyncio
async def test_health_and_catalog_name_configured_provider_and_effective_fallback(service):
    for result in (await service.health_check(), await service.document_catalog()):
        assert result["provider"] == "anythingllm"
        assert result["active_edition"] == "synthetic-edition"
        assert result["search_provider"] == "local"
        assert result["search_available"] and result["search_fallback"]
        assert result["search_fallback_reason"] == "workspace_mismatch"


@pytest.mark.asyncio
async def test_shared_local_catalog_and_health_reuse_frozen_index(service, tmp_path, monkeypatch):
    active = _edition(tmp_path / "same-root", local_ids=True)
    older = _edition(tmp_path / "historical", archived=True, local_ids=True)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "reader.md").write_text("# 本地上传\n\n用户材料正文。", encoding="utf-8")
    (uploads / "hidden.md").write_text("---\ningest: false\n---\n隐藏资料正文。", encoding="utf-8")
    (uploads / "empty.txt").touch()
    corpus = active.root / "corpus"
    service.provider = LocalKnowledgeProvider(corpus, uploads)
    exact_workspace = await LocalKnowledgeProvider(corpus, uploads).get_workspace("ip-ops-kb")
    inventory_read = Mock(wraps=service.provider._read_inventory)
    monkeypatch.setattr(service.provider, "_read_inventory", inventory_read)
    monkeypatch.setattr(service, "edition", lambda: active)
    from modules.knowledge import service as service_module
    monkeypatch.setattr(service_module.get_settings(), "knowledge_previous_edition_dir", str(older.root), raising=False)

    health, catalog = await asyncio.gather(service.health_check(), service.document_catalog())
    assert health["available"] and health["provider_available"] and health["workspace"] == exact_workspace
    assert catalog["active_edition"] == "synthetic-edition" and catalog["search_provider"] == "local"
    assert {row["filename"] for row in catalog["documents"]} == {"audited-1.md", "audited-2.md", "unlisted.md", "reader.md"}
    assert all(row["readable"] for row in catalog["documents"])
    assert service.provider._signature is None and active.keyword_index._signature is not None
    assert inventory_read.call_count == 1
    await service.document_catalog()
    assert inventory_read.call_count == 1
    old = older.by_doc_id["audited-1"]
    history = await service.read_document(old["id"], None, old["sha256"])
    assert history["historical_edition"] and _PREVIOUS_SENTENCE in history["content"]
    assert service.provider._signature is None

    (uploads / "reader.md").write_text("# 已修改的本地上传\n\n本地更新。", encoding="utf-8")
    revised = await service.document_catalog()
    assert revised["catalog_version"] != catalog["catalog_version"] and service.provider._signature is None
    assert inventory_read.call_count == 2
    row = next(item for item in revised["documents"] if item["filename"] == "reader.md")
    reading = await service.read_document(row["id"], None, row["version"])
    assert "本地更新" in reading["content"]


@pytest.mark.asyncio
async def test_custom_local_corpus_and_missing_edition_keep_regular_provider(service, tmp_path, monkeypatch):
    active = _edition(tmp_path / "edition", local_ids=True)
    corpus = tmp_path / "manual"
    corpus.mkdir()
    (corpus / "custom.md").write_text("# 自定义资料\n\n自定义目录正文。", encoding="utf-8")
    service.provider = LocalKnowledgeProvider(corpus, tmp_path / "uploads")
    monkeypatch.setattr(service, "edition", lambda: active)
    health, catalog = await asyncio.gather(service.health_check(), service.document_catalog())
    assert health["workspace"]["document_count"] == 1 and service.provider._signature is not None
    assert {row["filename"] for row in catalog["documents"]} == {"custom.md", "audited-1.md", "audited-2.md"}
    monkeypatch.setattr(service, "edition", lambda: None)
    health, catalog = await asyncio.gather(service.health_check(), service.document_catalog())
    assert health["search_available"] and health["active_edition"] is None
    assert [row["filename"] for row in catalog["documents"]] == ["custom.md"]


@pytest.mark.asyncio
async def test_incomplete_shared_index_uses_ordinary_health_and_preserves_faults(service, tmp_path, monkeypatch):
    active = _edition(tmp_path / "incomplete", local_ids=True)
    corpus = active.root / "corpus"
    (corpus / "audited-1.md").write_text("# 已偏离冻结校验的正文\n\n仍是可索引本地文件。", encoding="utf-8")
    service.provider = LocalKnowledgeProvider(corpus, tmp_path / "uploads")
    monkeypatch.setattr(service, "edition", lambda: active)
    health = await service.health_check()
    assert service.provider._signature is not None and health["workspace"]["document_count"] == 3
    with pytest.raises(DocumentReadError) as raised:
        await service.read_document(active.by_doc_id["audited-1"]["id"], None, None)
    assert raised.value.code == "source_version_changed"

    def invalid_edition():
        raise ValueError("bad pin")

    monkeypatch.setattr(service, "edition", invalid_edition)
    unavailable = await service.health_check()
    assert unavailable["provider_available"] and not unavailable["search_available"] and unavailable["search_provider"] is None
    with pytest.raises(ValueError, match="bad pin"):
        await service.document_catalog()


@pytest.mark.asyncio
async def test_crlf_custom_frozen_files_keep_regular_workspace_counts(service, tmp_path, monkeypatch):
    active = _edition(tmp_path / "with-crlf", local_ids=True, keep_crlf=True)
    service.provider = LocalKnowledgeProvider(active.root / "corpus", tmp_path / "uploads")
    monkeypatch.setattr(service, "edition", lambda: active)
    health = await service.health_check()
    assert service.provider._signature is not None
    assert health["workspace"] == await service.provider.get_workspace("ip-ops-kb")


@pytest.mark.asyncio
async def test_shared_inventory_fault_falls_back_without_hiding_uploads(service, tmp_path, monkeypatch):
    active = _edition(tmp_path / "inventory-fault", local_ids=True)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "from-user.md").write_text("# 用户资料\n\n仍可从普通目录读取。", encoding="utf-8")
    provider = LocalKnowledgeProvider(active.root / "corpus", uploads)
    service.provider = provider
    monkeypatch.setattr(service, "edition", lambda: active)
    monkeypatch.setattr(provider, "edition_inventory", AsyncMock(side_effect=OSError("inventory fast path failed")))

    health, catalog = await asyncio.gather(service.health_check(), service.document_catalog())
    assert health["provider_available"] and health["workspace"]["document_count"] == 4
    assert provider._signature is not None
    assert any(row["filename"] == "from-user.md" and row["readable"] for row in catalog["documents"])


def test_literal_after_a_long_paragraph_remains_in_display_budget():
    original = "本页先记录第一阶段。" * 140 + _SENTENCE + "第二阶段后续观察。" * 30
    assert literal_excerpt(original, (compact_text(_SENTENCE),)) == _SENTENCE


@pytest.mark.asyncio
async def test_reviewed_note_and_caption_open_on_their_visible_page(service, tmp_path, monkeypatch):
    original_note = "记录达到规定条件后，再重新选择主节点。"
    original_caption = "可监视（Probe）备份通道状态"
    original_only = "文字层存有一句尚未进入经核验正文。"
    edition = _edition(tmp_path / "audited-note", reviewed_page=(
        "整理稿说明了如何判断状态可以继续。\r\n\r\n"
        f"教材附注原句：“{original_note}”\r\n\r\n"
        f"课件图注原句：“{original_caption}”。"
    ))
    (edition.root / "corpus" / "unreviewed-ocr.txt").write_text(original_only, encoding="utf8")
    monkeypatch.setattr(service, "edition", lambda: edition)

    for query, expected in ((original_note, original_note), (f'查找原句“{original_caption}”', original_caption)):
        raw = await service.search(query, top_k=1)
        [citation] = prepare_sources(raw, max_document_chars=1300, max_documents=1)
        reading = await service.read_document(citation["document_id"], None, citation["document_version"])
        assert citation["page"] == 4 and expected in citation["content"]
        anchor = next(section for section in reading["sections"] if section["id"] == citation["section_id"])
        assert anchor["title"] == "PDF 第 4 页"
        start = anchor["line"] - 1
        following = next((s["line"] - 1 for s in reading["sections"] if s["line"] > anchor["line"]), None)
        assert expected in "\n".join(reading["content"].splitlines()[start:following])

    assert await service.search(f'查找原句“{original_only}”') == []
    service.provider.search.assert_not_awaited()
