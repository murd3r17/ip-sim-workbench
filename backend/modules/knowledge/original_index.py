"""Locate quoted text on allowed mounted PDF pages without returning extracted text."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import unicodedata

import pymupdf

from .original_pdf import OriginalPdfLibrary, _fingerprint, _matches, _render_lock
from .reader import DocumentReadError


INDEX_NAME = "original-quotes.sqlite3"
SCANS_INDEX_NAME = "original-scans.sqlite3"
_SCHEMA = 1
_MIN_QUOTE = 8
_MAX_QUOTE = 180
_NON_TEXT_ROLES = {"navigation", "non-instruction", "editorial-only", "restricted"}


def _normalized(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", text).casefold() if ch.isalnum())


def _original_text(page: pymupdf.Page) -> str:
    # Use the selectable PDF text inside the trimmed page. No OCR guesses or
    # off-page text is added, and separate columns are read in visual order.
    return _normalized(page.get_text("text", sort=True, clip=page.rect))


def _permission(edition, doc, page):
    return edition._allows_original(doc, page) and page.get("role") not in _NON_TEXT_ROLES


def _pinned_pdf(library: OriginalPdfLibrary, book: dict):
    path = library._path(book)
    fingerprint = _fingerprint(path)
    if not _matches(path, fingerprint, book["sha256"]):
        raise DocumentReadError("original_version_mismatch", "挂载的 PDF 与登记版本不同。", 409)
    return path, fingerprint


def build_original_index(edition, destination: Path, *, read_scan=None, skipped=None,
                         scan_checkpoint=False, progress=None) -> dict:
    """Populate private staging. Optionally keep completed scan pages across interrupts."""
    if edition.originals is None:
        raise ValueError("Original PDF root is required.")
    if scan_checkpoint and read_scan is None:
        raise ValueError("Only the scan index supports scan checkpoints.")
    # Several reader entries share a physical page. Point to the most specific
    # allowed reader entry and keep a single hit for the page.
    by_book: dict[int, dict[int, str]] = {}
    docs = sorted(edition.documents.values(), key=lambda doc: (doc["page_end"] - doc["page_start"], doc["id"]))
    for doc in docs:
        pages = by_book.setdefault(doc["book"], {})
        for entry in edition._document_pages(doc):
            if _permission(edition, doc, entry):
                pages.setdefault(entry["physical"], doc["id"])

    stats: dict[int, dict[str, int]] = {}
    with closing(sqlite3.connect(destination)) as db, db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name = 'metadata'").fetchone():
            checkpoint = db.execute("SELECT 1 FROM sqlite_master WHERE name = 'scan_progress'").fetchone()
            if not scan_checkpoint or not checkpoint or db.execute("SELECT * FROM metadata").fetchall() != [(_SCHEMA, edition.version)]:
                raise ValueError("Scan checkpoint is for a different edition or index format.")
        else:
            db.executescript("""
                BEGIN;
                CREATE TABLE metadata (schema_version INTEGER, edition TEXT);
                CREATE TABLE page_locator (book INTEGER, physical INTEGER, document_id TEXT);
                CREATE VIRTUAL TABLE phrase USING fts5(text, content='', tokenize='trigram');
            """)
            db.execute("INSERT INTO metadata VALUES (?, ?)", (_SCHEMA, edition.version))
            if scan_checkpoint:
                db.execute("""CREATE TABLE scan_progress (
                    book INTEGER, physical INTEGER, outcome INTEGER, PRIMARY KEY (book, physical)
                ) WITHOUT ROWID""")
            db.commit()
        for number, pages in sorted(by_book.items()):
            book = edition.books[number]
            path, fingerprint = _pinned_pdf(edition.originals, book)
            processed = dict(db.execute("SELECT physical, outcome FROM scan_progress WHERE book = ?", (number,))) if scan_checkpoint else {}
            if processed.keys() - pages.keys():
                raise ValueError("Scan checkpoint contains pages outside the current approved mapping.")
            inserted = sum(outcome == 1 for outcome in processed.values())
            if skipped is not None:
                skipped.extend((number, page) for page, outcome in processed.items() if outcome == -1)
            pending = 0
            with pymupdf.open(path) as pdf:
                if pdf.page_count != book["pages"]:
                    raise ValueError("Original PDF page count differs from the edition.")
                for checked, (physical, doc_id) in enumerate(sorted(pages.items()), 1):
                    if physical in processed:
                        continue
                    page = pdf[physical - 1]
                    text = _original_text(page)
                    outcome = 0
                    if read_scan is not None:
                        # Pages with enough native text already have a native locator.
                        if len(text) < 80:
                            try:
                                text = read_scan(page)
                            except (RuntimeError, ValueError, OSError, TypeError):
                                outcome = -1
                                text = ""
                                if skipped is not None:
                                    skipped.append((number, physical))
                        else:
                            text = ""
                    if len(text) >= _MIN_QUOTE:
                        row = db.execute("INSERT INTO page_locator VALUES (?, ?, ?)", (number, physical, doc_id))
                        db.execute("INSERT INTO phrase(rowid, text) VALUES (?, ?)", (row.lastrowid, text))
                        inserted += 1
                        outcome = 1
                    if scan_checkpoint:
                        db.execute("INSERT INTO scan_progress VALUES (?, ?, ?)", (number, physical, outcome))
                        pending += 1
                        if pending == 24:
                            if _fingerprint(path) != fingerprint:
                                raise ValueError("An original PDF changed while building the lookup index.")
                            db.commit()
                            pending = 0
                            if progress:
                                progress(number, checked, len(pages), inserted)
            if _fingerprint(path) != fingerprint:
                raise ValueError("An original PDF changed while building the lookup index.")
            if scan_checkpoint:
                db.commit()
            if progress:
                progress(number, len(pages), len(pages), inserted)
            stats[number] = {"authorized_body_pages": len(pages),
                             ("native_text_pages" if read_scan is None else "indexed_scan_pages"): inserted}
        db.execute("INSERT INTO phrase(phrase) VALUES ('optimize')")
    return {"edition": edition.version, "by_book": stats}


def _read_candidates(edition, normalized: str, book: int | None, limit: int, filename=INDEX_NAME):
    try:
        path = edition._asset(filename)
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            if db.execute("SELECT * FROM metadata").fetchone() != (_SCHEMA, edition.version):
                raise DocumentReadError("original_index_mismatch", "原句索引与当前教材版次不一致。", 409)
            return db.execute("""
                SELECT book, physical, document_id FROM phrase AS f
                JOIN page_locator AS p ON p.rowid = f.rowid
                WHERE phrase MATCH ? AND (? IS NULL OR book = ?)
                ORDER BY rank, book, physical LIMIT ?
            """, (f'"{normalized}"', book, book, limit * 4)).fetchall()
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise DocumentReadError("original_index_unavailable", "原书原句索引尚未生成或需要重建。", 503) from exc


def original_quote_status(edition) -> dict:
    """Report local lookup availability without opening any actual textbook."""
    originals = getattr(edition, 'originals', None)
    if originals is None or not originals.directory.is_dir():
        return {'state': 'unmounted', 'scan_available': False}
    for book in edition.books.values():
        try:
            originals._path(book)
        except DocumentReadError:
            continue
        break
    else:
        return {'state': 'unmounted', 'scan_available': False}

    def index_exists(name):
        try:
            path = edition._asset(name)
            if not path.is_file():
                return False
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
                return db.execute('SELECT * FROM metadata').fetchone() == (_SCHEMA, edition.version)
        except (OSError, ValueError, sqlite3.Error):
            return False

    available = index_exists(INDEX_NAME)
    return {'state': 'ready' if available else 'index_needed',
            'scan_available': available and index_exists(SCANS_INDEX_NAME)}


def search_original_quote(edition, quote: str, book: int | None = None, limit: int = 8) -> list[dict]:
    normalized = _normalized(quote)
    if not _MIN_QUOTE <= len(normalized) <= _MAX_QUOTE:
        raise DocumentReadError("original_query_length", "请粘贴 8 至 180 个有效文字或数字的原句。", 422)
    if edition is None or edition.originals is None:
        raise DocumentReadError("original_not_mounted", "工作台尚未挂载本地原书 PDF。", 404)
    if book is not None and book not in edition.books:
        raise DocumentReadError("original_book_unknown", "请选择当前知识库中的教材。", 422)
    rows = [(row, False) for row in _read_candidates(edition, normalized, book, limit)]
    if (edition.root / SCANS_INDEX_NAME).is_file():
        try:
            scan_rows = _read_candidates(edition, normalized, book, limit, SCANS_INDEX_NAME)
        except DocumentReadError:
            # The optional scan index can be rebuilt separately from the PDF text index.
            scan_rows = []
        rows += [(row, True) for row in scan_rows]
    results = []
    pinned = {}
    used_pages = set()
    with _render_lock:
        for (book_number, physical, doc_id), scan in rows:
            if (book_number, physical) in used_pages:
                continue
            doc = edition.documents.get(doc_id)
            if not doc or doc["book"] != book_number:
                continue
            entry = next((page for page in edition._document_pages(doc) if page["physical"] == physical), None)
            if not entry or not _permission(edition, doc, entry):
                continue
            original = edition.books[book_number]
            if book_number not in pinned:
                pinned[book_number] = _pinned_pdf(edition.originals, original)
            path, fingerprint = pinned[book_number]
            with pymupdf.open(path) as pdf:
                if pdf.page_count != original["pages"] or not 1 <= physical <= pdf.page_count:
                    continue
                if not scan and normalized not in _original_text(pdf[physical - 1]):
                    continue
            if _fingerprint(path) != fingerprint:
                raise DocumentReadError("original_version_mismatch", "PDF 在检索期间发生变化，请重试。", 409)
            results.append({"document_id": doc_id, "document_version": doc["sha256"], "title": doc["title"],
                            "book_title": original["title"], "edition": doc["edition"], "page": physical})
            used_pages.add((book_number, physical))
            if scan:
                results[-1]["match_type"] = "scan_locator"
            if len(results) == limit:
                break
    return results
