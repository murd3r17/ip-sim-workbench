import hashlib
import json
from types import SimpleNamespace

import pytest

from modules.knowledge.edition import KnowledgeEdition


@pytest.fixture
def edition(tmp_path):
    body = "# 练习读本\n\n### PDF 第 1 页\n\n第一页。\n\n### PDF 第 2 页\n\n第二页。\n"
    reader_dir = tmp_path / "corpus"
    reader_dir.mkdir()
    source = reader_dir / "lesson.md"
    source.write_bytes(body.encode())
    version = hashlib.sha256(source.read_bytes()).hexdigest()
    page_map = tmp_path / "pages.json"
    page_map.write_bytes(json.dumps({"doc_id": "lesson", "version": version, "pages": [
        {"physical": 1, "role": "native-text", "heading": "PDF 第 1 页", "original_access": "editorial"},
        {"physical": 2, "role": "native-text", "heading": "PDF 第 2 页", "original_access": "editorial"},
        {"physical": 3, "role": "navigation", "original_access": "render"},
    ]}).encode())
    chapter = {"id": "new-id", "doc_id": "lesson", "title": "练习读本", "anchor": 1, "book": 1,
               "edition": "V1", "ingest": True, "sha256": version, "path": "lesson.md", "page_start": 1, "page_end": 3,
               "page_map": "pages.json", "page_map_sha256": hashlib.sha256(page_map.read_bytes()).hexdigest()}
    obj = KnowledgeEdition.__new__(KnowledgeEdition)
    obj.root, obj.version = tmp_path, "new-edition"
    obj.books = {1: {"title": "练习教材"}}
    obj.documents = {chapter["id"]: chapter}
    obj.by_doc_id = {chapter["doc_id"]: chapter}
    obj.nav = {chapter["id"]: []}
    obj.originals, obj.previews = None, {}
    obj.legacy = {"old-id": {"related": [{"doc_id": "lesson"}, {"doc_id": "revoked"}], "verified_anchors": [
        {"doc_id": "lesson", "historical_version": "old-version", "historical_section_id": "section-3",
         "physical": [2, 2]},
        {"doc_id": "lesson", "historical_version": "old-version", "historical_section_id": "section-99",
         "physical": [3, 3]},
    ]}}
    return obj


def test_legacy_uses_current_section_even_when_old_id_still_exists(edition):
    location = edition.legacy_locator("old-id", "old-version", "section-3")
    assert location["status"] == "exact-page-locator"
    assert location["target_page"] == 2
    assert location["section_id"] == "section-7"
    assert location["view"] == "body"
    assert location["edition_version"] == "new-edition"
    assert location["document"]["version"] == edition.documents["new-id"]["sha256"]


def test_legacy_figure_without_current_section_needs_an_available_source(edition):
    assert edition.legacy_locator("old-id", "old-version", "section-99")["status"] == "archive-only"
    edition.originals = SimpleNamespace(page_status=lambda book: "available")
    location = edition.legacy_locator("old-id", "old-version", "section-99")
    assert location["status"] == "exact-page-locator"
    assert location["target_page"] == 3
    assert location["section_id"] is None
    assert location["view"] == "original"
    page = edition.read(location["document"]["id"], location["document"]["version"])["original_pages"][-1]
    assert page["physical"] == 3 and page["evidence_eligible"] is False


@pytest.mark.parametrize("version, section", [("wrong-version", "section-3"), ("old-version", None)])
def test_legacy_archive_retains_existing_related_items(edition, version, section):
    location = edition.legacy_locator("old-id", version, section)
    assert location["status"] == "archive-only"
    assert [doc["id"] for doc in location["related"]] == ["new-id"]
    assert "target_page" not in location


def test_legacy_requires_the_entire_registered_page_interval(edition):
    anchor = edition.legacy["old-id"]["verified_anchors"][0]
    anchor["physical"] = [2, 4]
    location = edition.legacy_locator("old-id", "old-version", "section-3")
    assert location["status"] == "archive-only"


def test_legacy_falls_back_when_the_current_source_has_changed(edition):
    (edition.root / "corpus/lesson.md").write_bytes(b"changed")
    location = edition.legacy_locator("old-id", "old-version", "section-3")
    assert location["status"] == "archive-only"
