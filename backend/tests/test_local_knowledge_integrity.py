"""Local retrieval admission, document identity and cache regressions; temporary files only."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from modules.knowledge.local_provider import LocalKnowledgeProvider, _tokenize
from modules.knowledge.service import KnowledgeService


def test_tokenization_does_not_invent_phrases_across_protocols_or_punctuation():
    tokens = _tokenize("接口 OSPF 状态；故障排查，AS_PATH 65535 192.0.2.1")
    assert {"接口", "ospf", "状态", "故障", "排查", "as_path", "65535", "192"} <= set(tokens)
    assert not {"口状", "态故", "查接"} & set(tokens)
    assert "状" not in tokens  # sentence-wide common-character matches caused noise


@pytest.mark.asyncio
async def test_ignores_indexes_and_explicit_non_ingest_documents(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "00-index.md").write_text("# OSPF index only", encoding="utf-8")
    (corpus / "00-CORPUS-INDEX.md").write_text("# OSPF corpus index", encoding="utf-8")
    (corpus / "excluded.md").write_text("---\ningest: false\n---\n# OSPF excluded", encoding="utf-8")
    (corpus / "included.md").write_text(
        '---\ningest: true\ndoc_id: "ospf-1"\ntitle: "OSPF title"\nquality: "ocr-mixed"\nbook: "Book-A"\nsource_pdf: "book.pdf"\n---\n# OSPF content', encoding="utf-8",
    )
    provider = LocalKnowledgeProvider(corpus, tmp_path / "uploads")
    documents = await provider.list_documents()
    assert [item["filename"] for item in documents] == ["included.md"]
    hits = await provider.search("OSPF")
    assert hits[0]["doc_id"] == "ospf-1"
    assert hits[0]["title"] == "OSPF title"
    assert hits[0]["metadata"]["quality"] == "ocr-mixed"
    assert hits[0]["metadata"]["source_pdf"] == "book.pdf"


@pytest.mark.asyncio
async def test_same_filenames_have_distinct_ids_and_corpus_cannot_delete_upload(tmp_path):
    corpus, uploads = tmp_path / "corpus", tmp_path / "uploads"
    for directory in (corpus / "A", corpus / "B", uploads):
        directory.mkdir(parents=True)
        (directory / "same.md").write_text("# OSPF neighbor", encoding="utf-8")
    provider = LocalKnowledgeProvider(corpus, uploads)
    documents = await provider.list_documents()
    assert len({item["id"] for item in documents}) == 3
    first_ids = {item["path"]: item["id"] for item in documents}
    corpus_doc = next(item for item in documents if str(corpus) in item["path"])
    response = await provider.delete_document(None, corpus_doc["id"])
    assert response["status"] == "forbidden"
    assert (uploads / "same.md").exists()
    fresh = LocalKnowledgeProvider(corpus, uploads)
    assert {item["path"]: item["id"] for item in await fresh.list_documents()} == first_ids
    uploaded = next(item for item in documents if str(uploads) in item["path"])
    assert (await provider.delete_document(None, uploaded["id"]))["status"] == "ok"
    assert (await provider.health_check())["document_count"] == 2


@pytest.mark.asyncio
async def test_provider_reused_by_settings_and_rebuilds_only_after_change(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    target = corpus / "content.md"
    target.write_text("# OSPF neighbor", encoding="utf-8")
    settings = SimpleNamespace(knowledge_provider="local", knowledge_corpus_dir=str(corpus))
    with patch("modules.knowledge.service.get_settings", return_value=settings):
        first = KnowledgeService.from_settings().provider
        second = KnowledgeService.from_settings().provider
    assert first is second
    # Exclude any real upload directory; the only indexed data is the fixture.
    first.storage_dir = tmp_path / "uploads"
    with patch("modules.knowledge.local_provider._read_text", wraps=__import__("modules.knowledge.local_provider", fromlist=["_read_text"])._read_text) as read:
        await first.search("OSPF")
        count = read.call_count
        await second.search("OSPF")
        assert read.call_count == count
        target.write_text("# BGP changed document", encoding="utf-8")
        assert await second.search("BGP")
        assert read.call_count > count


@pytest.mark.asyncio
async def test_empty_corpus_is_unavailable(tmp_path):
    provider = LocalKnowledgeProvider(tmp_path / "missing", tmp_path / "uploads")
    assert (await provider.health_check())["available"] is False
