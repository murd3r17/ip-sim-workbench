"""End-to-end fixture for settings, first recorded values and later checks."""

from hashlib import sha256
from types import SimpleNamespace

import pytest

from modules.ai_text import router
from modules.ai_text.schemas import CopilotChatRequest
from modules.knowledge.edition import KnowledgeEdition, _page_texts, _source_excerpt
from tests.test_knowledge_edition_retrieval import _write_json, service


QUESTION = "纸带分类练习里，光点阈值在哪一步登记？当时第一份抄表写了哪一栏？后来用什么记录复查？"
SETTING = "分拣开始前，记录员把光点阈值登记在门限卡。"
RECORDED = "首份抄表已经完成，抄表上写了斑点密度这一栏。"
CHECKED = "复查时，记录员用当批的光敏校验日志核对首次抄表。"
EXPECTED = "预计第一次会把照度写进抄表。"
NOT_CHECKED = "准备后来拿滤光纸交接单复查，目前尚未做复查。"
DECOY = "另一轮用设备领用表复查。"


def record_edition(root, check=CHECKED, *, name="纸带分类练习", setup=SETTING, record=RECORDED, expected=EXPECTED):
    corpus = root / "corpus"
    corpus.mkdir(parents=True)
    identity, version = "paper-records", "record-sequence-fiction"
    title = "纸样工序实验册"
    sections = (
        f"#### 案例 1：{name}\n\n##### 步骤 1 采集准备\n\n{setup}",
        f"##### 步骤 2 读取第一份记录\n\n{expected}\n\n{record}",
        "##### 步骤 3 复查纸带\n\n" + check + "\n\n#### 案例 2：纸带校验练习\n\n##### 步骤 1 复查纸样\n\n" + DECOY,
    )
    pages = list(range(3, 3 + len(sections)))
    raw = (f'---\ndoc_id: "{identity}"\ntitle: "{title}"\ningest: "true"\n---\n# {title}\n\n'
           + "\n\n".join(f"### PDF 第 {page} 页\n\n{body}" for page, body in zip(pages, sections, strict=True))).encode()
    (corpus / f"{identity}.md").write_bytes(raw)
    checksum = sha256(raw).hexdigest()
    page_hash = _write_json(root / "pages.json", {"version": checksum, "doc_id": identity,
                                                 "pages": [{"physical": page, "role": "instruction"} for page in pages]})
    legacy_hash = _write_json(root / "legacy-identity.json", [])
    manifest_hash = _write_json(root / "manifest.json", {"version": version, "books": [{"book": 1, "title": title}],
        "legacy_sha256": legacy_hash,
        "documents": [{"id": identity, "doc_id": identity, "path": f"{identity}.md", "book": 1, "title": title,
                       "sha256": checksum, "page_map": "pages.json", "page_map_sha256": page_hash,
                       "edition": "V1", "ingest": True, "anchor": 1, "page_start": pages[0], "page_end": pages[-1],
                       "subsections": []}]})
    _write_json(root / "freeze.json", {"status": "FROZEN", "edition": version, "reading_manifest_sha256": manifest_hash,
                                       "anythingllm": {"workspace": "textbook-audit", "documents": {}}})
    return KnowledgeEdition(root)


@pytest.fixture
def frozen(tmp_path):
    return record_edition(tmp_path / "frozen")


async def retrieval(service, monkeypatch, edition, question):
    monkeypatch.setattr(service, "edition", lambda: edition)
    monkeypatch.setattr(router, "_get_knowledge_service", lambda: service)
    outcome = await service.search_ranked_evidence(question, top_k=6)
    assert outcome.hits == await service.search(question, top_k=6)
    request = CopilotChatRequest(message=question, top_k=6, context={"route": "/knowledge"})
    hits = router._FacetHits(outcome.hits, outcome.facet_evidence, outcome.ranked, outcome.pool)
    sources, notice = router._prepare_copilot_sources(request, hits, SimpleNamespace(id="knowledge_answer"), "")
    return outcome, sources, notice


@pytest.mark.asyncio
async def test_record_sequence_proves_setting_first_read_and_real_later_check(service, monkeypatch, tmp_path):
    edition = record_edition(tmp_path / "records")
    outcome, sources, notice = await retrieval(service, monkeypatch, edition, QUESTION)
    assert outcome.ranked and outcome.ranked.verified_bundle, (outcome.ranked.facets if outcome.ranked else (), sources, notice)
    assert [source["page"] for source in sources] == [3, 4, 5]
    assert "步骤 1 采集准备" in sources[0]["content"]
    assert not notice
    for source, fact in zip(sources, (SETTING, RECORDED, CHECKED), strict=True):
        original = edition.read(source["document_id"], source["document_version"], include_original_status=False)
        section, page = _page_texts(original)[source["page"]]
        assert source["edition_version"] == edition.version and source["section_id"] == section
        assert fact in source["content"] and _source_excerpt(source["content"], page)
    assert not any(part in source["content"] for source in sources for part in (EXPECTED, DECOY))


@pytest.mark.asyncio
async def test_record_sequence_missing_check_preserves_first_two_real_evidence_pages(service, monkeypatch, tmp_path):
    edition = record_edition(tmp_path / "partial", check=NOT_CHECKED)
    outcome, sources, notice = await retrieval(service, monkeypatch, edition, QUESTION)
    assert outcome.ranked and outcome.ranked.missing == (3,)
    assert [source["page"] for source in sources] == [3, 4]
    assert "第 3 项" in notice and "复查" in notice
    assert all(part not in source["content"] for source in sources for part in (NOT_CHECKED, DECOY, EXPECTED))


@pytest.mark.asyncio
async def test_record_sequence_uses_independent_exercise_wording_and_original_actions(service, monkeypatch, tmp_path):
    question = "滤片比对实验中，偏差上限在哪个环节写入？最早那份回显读出了哪一项？之后拿哪种台账复核？"
    setup = "抽检前，把偏差上限记入检验卡。"
    reading = "第一份回显显示本轮滤片的透光偏差。"
    checked = "随后用正样校准台账复核第一次回显。"
    edition = record_edition(tmp_path / "independent", check=checked, name="滤片比对实验", setup=setup,
                             record=reading, expected="预计第一份回显要登记滤片的条码。")
    outcome, sources, notice = await retrieval(service, monkeypatch, edition, question)
    assert outcome.ranked and outcome.ranked.verified_bundle and not notice
    assert [entry["page"] for entry in sources] == [3, 4, 5]
    assert all(fact in source["content"] for source, fact in zip(sources, (setup, reading, checked), strict=True))


@pytest.mark.asyncio
async def test_record_sequence_rejects_unobserved_first_record_and_wrong_record_of_review(service, monkeypatch, tmp_path):
    edition = record_edition(tmp_path / "instructions", record="首份抄表应填写斑点密度这一栏。")
    outcome, _, _ = await retrieval(service, monkeypatch, edition, QUESTION)
    assert outcome.ranked is None or outcome.ranked.verified_bundle is None

    review = "复查时，记录员用光敏校验日志核对第二份抄表。"
    other = record_edition(tmp_path / "other-record", check=review)
    outcome, sources, notice = await retrieval(service, monkeypatch, other, QUESTION)
    assert outcome.ranked and outcome.ranked.missing == (3,)
    assert [source["page"] for source in sources] == [3, 4] and "第 3 项" in notice


@pytest.mark.asyncio
async def test_record_sequence_leaves_plain_principle_question_untouched(service, monkeypatch, tmp_path):
    edition = record_edition(tmp_path / "principle")
    outcome, sources, notice = await retrieval(service, monkeypatch, edition, "纸带分类练习里，光点阈值是什么意思？")
    assert outcome.ranked is None or outcome.ranked.verified_bundle is None
    assert sources and not notice
