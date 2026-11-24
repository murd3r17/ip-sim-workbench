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
             local_ids=False, keep_crlf=False):
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
        path = corpus / f"{identity}.md"
        raw = (f'---\r\ndoc_id: "{identity}"\r\ntitle: "{title}"\r\ningest: "true"\r\n---\r\n'
               f"# {title}\r\n\r\n### PDF 第 3 页\r\n\r\n{first}\r\n\r\n"
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
