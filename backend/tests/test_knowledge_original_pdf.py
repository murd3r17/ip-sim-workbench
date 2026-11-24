import hashlib
import sqlite3
from types import SimpleNamespace

import pymupdf
import pytest

from modules.knowledge.edition import KnowledgeEdition
from modules.knowledge.original_index import (
    INDEX_NAME, SCANS_INDEX_NAME, build_original_index, original_quote_status, search_original_quote,
)
from modules.knowledge.original_pdf import OriginalPdfLibrary
from modules.knowledge.reader import DocumentReadError


@pytest.fixture
def mounted_book(tmp_path):
    path = tmp_path / "教材原件.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((50, 50), "First page")
        pdf.new_page().insert_text((50, 50), "Second page")
        pdf.save(path)
    return path, {"filename": path.name, "pages": 2, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def test_mount_renders_only_registered_bytes_and_number(mounted_book):
    path, book = mounted_book
    library = OriginalPdfLibrary(path.parent)
    assert library.page_status(book) == "available"
    assert library.render(book, 2).startswith(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(DocumentReadError, match="页数"):
        library.render(book, 3)

    path.write_bytes(b"wrong textbook")
    assert library.page_status(book) == "original_version_mismatch"
    with pytest.raises(DocumentReadError) as wrong_version:
        library.render(book, 1)
    assert wrong_version.value.code == "original_version_mismatch"


def test_page_permission_stays_bound_to_document_and_review(mounted_book, monkeypatch):
    _, book = mounted_book
    edition = KnowledgeEdition.__new__(KnowledgeEdition)
    edition.books = {1: book}
    edition.documents = {"chapter": {"book": 1, "sha256": "version", "page_start": 1, "page_end": 2}}
    edition.previews = {}
    edition.originals = SimpleNamespace(render=lambda source, page: f"{source['filename']}:{page}".encode())
    monkeypatch.setattr(edition, "_document_pages", lambda doc: [
        {"physical": 1, "original_access": "render"}, {"physical": 2, "original_access": "editorial"},
        {"physical": 3, "original_access": "render"},
    ])
    with pytest.raises(DocumentReadError) as unbound:
        edition.figure("chapter", "version", 1)
    assert unbound.value.code == "preview_unavailable"

    edition.documents["chapter"]["page_map_sha256"] = "pinned-map"
    assert edition.figure("chapter", "version", 1) == f"{book['filename']}:1".encode()
    for page in (2, 3):
        with pytest.raises(DocumentReadError) as excluded:
            edition.figure("chapter", "version", page)
        assert excluded.value.code == "preview_unavailable"

    with pytest.raises(DocumentReadError) as outdated:
        edition.figure("chapter", "old-version", 1)
    assert outdated.value.code == "document_changed"


def test_original_quote_revalidates_permissions_and_mounted_source(mounted_book, monkeypatch):
    path, book = mounted_book
    edition = KnowledgeEdition.__new__(KnowledgeEdition)
    edition.root = path.parent
    edition.version = "edition-one"
    edition.books = {1: {**book, "title": "Textbook"}}
    edition.originals = OriginalPdfLibrary(path.parent)
    edition.documents = {"chapter": {"id": "chapter", "book": 1, "title": "Chapter", "edition": "V1",
                                       "sha256": "document-one", "page_start": 1, "page_end": 2,
                                       "page_map_sha256": "pinned-map"}}
    pages = [
        {"physical": 1, "original_access": "render", "role": "native"},
        {"physical": 2, "original_access": "editorial", "role": "native"},
    ]
    monkeypatch.setattr(edition, "_document_pages", lambda _: pages)
    target = edition.root / INDEX_NAME
    assert original_quote_status(edition) == {'state': 'index_needed', 'scan_available': False}
    report = build_original_index(edition, target)
    assert original_quote_status(edition) == {'state': 'ready', 'scan_available': False}
    assert report["by_book"] == {1: {"authorized_body_pages": 1, "native_text_pages": 1}}
    hits = search_original_quote(edition, "ｆｉｒｓｔ - PAGE", book=1)
    assert hits == [{"document_id": "chapter", "document_version": "document-one", "page": 1,
                    "title": "Chapter", "book_title": "Textbook", "edition": "V1"}]
    assert search_original_quote(edition, "Second page") == []

    scan_index = edition.root / SCANS_INDEX_NAME
    build_original_index(edition, scan_index, read_scan=lambda _: "scanwordsonly")
    assert original_quote_status(edition) == {'state': 'ready', 'scan_available': True}
    scanned = search_original_quote(edition, "scan words only")
    assert len(scanned) == 1 and scanned[0]["match_type"] == "scan_locator"
    assert scanned[0]["page"] == 1 and "text" not in scanned[0]
    with sqlite3.connect(scan_index) as index:
        index.execute("UPDATE metadata SET edition = 'old-edition'")
    assert original_quote_status(edition) == {'state': 'ready', 'scan_available': False}
    assert search_original_quote(edition, "scan words only") == []
    assert search_original_quote(edition, "First page") == hits

    with sqlite3.connect(target) as index:
        # A stale or edited locator cannot reinstate a restricted page.
        index.execute("UPDATE page_locator SET physical = 2")
    assert search_original_quote(edition, "First page") == []
    with sqlite3.connect(target) as index:
        index.execute("UPDATE page_locator SET physical = 1")
    pages[0]["role"] = "navigation"
    assert search_original_quote(edition, "First page") == []
    pages[0]["role"] = "native"
    path.write_bytes(b"wrong textbook")
    with pytest.raises(DocumentReadError) as error:
        search_original_quote(edition, "First page")
    assert error.value.code == "original_version_mismatch"


def test_scan_index_resumes_committed_pages_and_skips_restricted_pages(tmp_path, monkeypatch):
    path = tmp_path / 'scan.pdf'
    with pymupdf.open() as pdf:
        for _ in range(26):
            pdf.new_page()
        pdf.save(path)
    edition = KnowledgeEdition.__new__(KnowledgeEdition)
    edition.root = path.parent
    edition.version = 'frozen-ocr-test'
    edition.books = {1: {'filename': path.name, 'pages': 26, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}
    edition.originals = OriginalPdfLibrary(path.parent)
    edition.documents = {'chapter': {'id': 'chapter', 'book': 1, 'page_start': 1, 'page_end': 26,
                                      'page_map_sha256': 'test-pages'}}
    monkeypatch.setattr(edition, '_document_pages', lambda _: [
        {'physical': page, 'original_access': 'render' if page < 26 else 'editorial', 'role': 'native'}
        for page in range(1, 27)
    ])
    staging = tmp_path / 'unpublished.sqlite3'

    def interrupted(page):
        if page.number == 24:
            raise KeyboardInterrupt
        return 'checkpoint test phrase'

    with pytest.raises(KeyboardInterrupt):
        build_original_index(edition, staging, read_scan=interrupted, scan_checkpoint=True)

    resumed = []

    def scan(page):
        resumed.append(page.number + 1)
        return 'checkpoint test phrase'

    result = build_original_index(edition, staging, read_scan=scan, scan_checkpoint=True)
    assert resumed == [25]
    assert result['by_book'][1] == {'authorized_body_pages': 25, 'indexed_scan_pages': 25}
    with sqlite3.connect(staging) as db:
        assert db.execute('SELECT count(*), count(DISTINCT physical), max(physical) FROM page_locator').fetchone() == (25, 25, 25)
    edition.version = 'different-edition'
    with pytest.raises(ValueError, match='different edition'):
        build_original_index(edition, staging, read_scan=scan, scan_checkpoint=True)
