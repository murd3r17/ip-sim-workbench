"""Validated local material for a frozen textbook edition."""
from __future__ import annotations

import hashlib
import json
from bisect import bisect_right
from functools import cached_property, lru_cache
from collections import Counter
import math
from pathlib import Path
import re
import sqlite3

from .original_pdf import OriginalPdfLibrary
from .reader import DocumentReadError, document_payload, read_bounded
from .query_focus import compact_text, lookup_parts, scoped_terms, title_key


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


_BODY_HEADING = re.compile(r"^(?:### )?PDF 第 (\d+) 页", re.M)
_RAW_PAGE_BOUNDARY = re.compile(r"^### PDF 第 \d+ 页\b")
_NON_EVIDENCE_ROLES = frozenset({"navigation", "non-instruction"})
_VECTOR_ALIAS = re.compile(r"ipsim-[0-9a-f]{16}-\d{3,}\.md")
_COLLECTOR_HEADER = re.compile(r"\A<document_metadata>\r?\n[^\0]{0,900}?\r?\n</document_metadata>\s*")


def import_alias(value: str) -> str:
    return value.partition(".md")[0] + ".md"


class KnowledgeEdition:
    def __init__(self, root: Path, original_root: Path | None = None):
        self.root = root
        self.originals = OriginalPdfLibrary(original_root) if original_root is not None else None
        manifest_raw = self._asset("manifest.json").read_bytes()
        freeze = self._json("freeze.json")
        manifest = json.loads(manifest_raw)
        if (freeze["status"] != "FROZEN" or freeze["reading_manifest_sha256"] != sha256(manifest_raw)
                or freeze["edition"] != manifest["version"]):
            raise ValueError("Edition and import are not pinned together.")
        self.version = manifest["version"]
        self.documents = {row["id"]: row for row in manifest["documents"]}
        self.books = {row["book"]: row for row in manifest["books"]}
        self.vector = freeze["anythingllm"]
        self.aliases = {}
        by_path = {row["path"]: row for row in self.documents.values()}
        for path, source in self.vector["documents"].items():
            doc = by_path[path]
            if source["logical_id"] != doc["doc_id"] or source["source_sha256"] != doc["sha256"]:
                raise ValueError("Imported source does not match its reading edition.")
            alias = import_alias(source["alias"])
            if alias in self.aliases or not _VECTOR_ALIAS.fullmatch(alias):
                raise ValueError("Imported source alias is ambiguous.")
            self.aliases[alias] = source, doc
        self.previews = {}
        if freeze.get("figures"):
            raw = self._asset("figures.json").read_bytes()
            value = json.loads(raw)
            if sha256(raw) != freeze["figures"]["manifest_sha256"] or value["edition"] != self.version:
                raise ValueError("Edition figure manifest does not match.")
            self.previews = {(r["book"], r["physical"]): r for r in value["figures"]}
        choices = {row["doc_id"]: row for row in self.documents.values()}
        self.nav = {identifier: [choices[child] for child in row["subsections"]] for identifier, row in self.documents.items()}
        self.observations = self._learning_index()
        self.legacy = {}
        raw = self._asset("legacy-identity.json").read_bytes()
        if sha256(raw) != manifest["legacy_sha256"]:
            raise ValueError("Edition legacy locator manifest does not match.")
        for record in json.loads(raw):
            for field in ("old_local_id", "old_doc_id"):
                value = record.get(field)
                if value:
                    self.legacy[value] = record
        self.by_doc_id = choices

    @cached_property
    def keyword_index(self):
        from .local_provider import LocalKnowledgeProvider

        return LocalKnowledgeProvider(
            self.root / "corpus", corpus_only=True,
            frozen_documents={doc["path"]: doc for doc in self.documents.values() if doc["ingest"]},
            frozen_page_loader=self._evidence_pages,
        )

    @staticmethod
    def _is_evidence_page(doc, page):
        return bool(doc["ingest"] and page.get("role") and page["role"] not in _NON_EVIDENCE_ROLES
                    and doc["page_start"] <= page["physical"] <= doc["page_end"])

    def _evidence_pages(self, doc):
        try:
            return {page["physical"] for page in self._document_pages(doc) if self._is_evidence_page(doc, page)}
        except (DocumentReadError, OSError, ValueError, KeyError, TypeError):
            return set()

    def search_scope(self, query):
        titles, phrases, pages, terms = lookup_parts(query)
        docs = list(self.documents.values())
        expression = compact_text(query)
        names = {number: (book["title"], book.get("filename") or "") for number, book in self.books.items()}
        books = {number for number, labels in names.items()
                 if any(label and compact_text(label) in expression for label in labels)}
        if books:
            docs = [doc for doc in docs if doc["book"] in books]
            for number in books:
                for label in names[number]:
                    if label:
                        terms = re.sub(re.escape(label), "", terms, flags=re.I)
        book_labels = {compact_text(label) for number in books for label in names[number] if label}
        remaining = scoped_terms(terms)
        chapter_labels = [label for label in titles if compact_text(label) not in book_labels]

        def matching_chapters(label):
            compact = compact_text(label)
            exact = [doc for doc in docs if compact_text(doc["title"]) == compact or compact_text(doc["doc_id"]) == compact]
            if exact or title_key(label) != compact:
                return exact
            return [doc for doc in docs if title_key(doc["title"]) == compact]

        explicit_groups = [matching_chapters(label) for label in chapter_labels]
        if any(not group for group in explicit_groups):
            return remaining, [], set(), pages, phrases
        bare_matches = matching_chapters(remaining) if remaining else []
        chapters = list({doc["id"]: doc for group in explicit_groups or [bare_matches] for doc in group}.values())
        if chapters and not phrases and not pages and (not remaining or bare_matches):
            return "", chapters, None, None, ()
        document_ids = {doc["id"] for doc in chapters or docs} if chapters or books else None
        if chapters:
            # Admission controls what can provide evidence, independently of
            # which descendants belong to the requested chapter.
            pending = list(document_ids)
            while pending:
                for child in self.nav[pending.pop()]:
                    identifier = child["id"]
                    if identifier not in document_ids:
                        document_ids.add(identifier)
                        pending.append(identifier)
        if bare_matches and pages:
            remaining = ""
        return remaining if document_ids is not None or pages else query, [], document_ids, pages, phrases

    def has_search_scope(self, query: str) -> bool:
        _, chapters, document_ids, pages, phrases = self.search_scope(query)
        return bool(chapters or document_ids is not None or pages or phrases)

    def navigation_hits(self, records, limit):
        hits = []
        for record in records:
            try:
                body = self.read(record["id"], record["sha256"], include_original_status=False)
            except (DocumentReadError, OSError, ValueError, KeyError):
                continue
            heading = next((s for s in body["sections"] if s["level"] == 1 and
                            title_key(s["title"]) == title_key(record["title"])), None)
            if heading:
                text = body["content"].splitlines()[heading["line"] - 1]
                hits.append(self._bound_hit({"retriever": "edition_title"}, record, text, heading["id"]))
                if len(hits) == limit:
                    break
        return hits

    def reviewed_page_hits(self, note):
        row = next((item for item in self.documents.values() if item["path"].endswith("/" + note["filename"])), None)
        if not row or row["sha256"] != note["document_version"]:
            return []
        try:
            reading = self.read(row["id"], row["sha256"], include_original_status=False)
        except (DocumentReadError, OSError, ValueError, KeyError):
            return []
        page = note["source_page"]
        location = _page_texts(reading).get(page)
        if not location:
            return []
        anchor, excerpt = location
        return [self._bound_hit({"retriever": "reviewed_excerpt"}, row, excerpt.strip(), anchor, page)]

    def _learning_index(self):
        from .local_provider import _tokenize

        evidence = []
        for doc in self.documents.values():
            for note in doc.get("observations", []):
                context = self.books[doc["book"]]["title"]
                title = Counter(_tokenize(note["title"] + " " + doc["title"]))
                body = Counter(_tokenize(note["text"]))
                evidence.append((doc, note, title, body, frozenset(_tokenize(context))))
        return evidence

    def learning_hits(self, query, limit):
        from .local_provider import _query_tokens

        terms = set(_query_tokens(query))
        if not terms or not self.observations:
            return []
        frequency = Counter(term for _, _, title, body, _ in self.observations for term in title.keys() | body.keys() if term in terms)
        idf = {t: math.log1p(len(self.observations) / (1 + c)) for t, c in frequency.items()}
        ranks = []
        for doc, note, title, body, context in self.observations:
            matches = terms.intersection(title.keys() | body.keys())
            if len(matches) < 2:
                continue
            score = sum(idf[t] * (1 + (.65 if t in title else 0)) for t in matches)
            score += sum(.8 for t in terms.intersection(context) if t.isascii())
            ranks.append((score, len(matches), doc, note))
        ranks.sort(key=lambda item: (item[0], item[1]), reverse=True)
        hits = []
        for score, _, doc, note in ranks[:limit]:
            if score < 4 or score < ranks[0][0] * .42:
                continue
            try:
                body = self.read(doc["id"], doc["sha256"], include_original_status=False)
            except (DocumentReadError, OSError, ValueError, KeyError):
                continue
            allowed = {row["physical"] for row in body["original_pages"] if row["evidence_eligible"]}
            if not note["pages"] or not set(note["pages"]).issubset(allowed):
                continue
            anchor = next((row["id"] for row in body["sections"] if row["title"] == note["title"]), None)
            loc = "、".join(str(page) for page in note["pages"])
            excerpt = f"## {note['title']}\n\n原件核验 · PDF 第 {loc} 页。\n\n{note['text']}"
            if not anchor or excerpt not in body["content"]:
                continue
            hit = self._bound_hit({"score": round(score / ranks[0][0], 4), "retriever": "edition_review"},
                                  doc, excerpt, anchor, note["pages"][0])
            hits.append({**hit, "title": note["title"]})
        return hits

    def _asset(self, relative):
        target = self.root / relative
        if target.is_symlink() or not target.resolve().is_relative_to(self.root):
            raise ValueError("Edition asset outside configured edition.")
        return target

    def _json(self, relative):
        return json.loads(self._asset(relative).read_bytes())

    def catalog(self) -> list[dict]:
        return [self._entry(doc) for doc in self.documents.values()]

    def _entry(self, doc):
        return {"id": doc["id"], "title": doc["title"], "filename": Path(doc["path"]).name,
                "book": f"huawei-b{doc['book']:02d}", "book_title": self.books[doc["book"]]["title"],
                "doc_id": doc["doc_id"], "seq": doc["anchor"], "edition": doc["edition"],
                "page_start": doc["page_start"], "page_end": doc["page_end"], "version": doc["sha256"],
                "readable": True, "bundled": True, "section_count": len(self.nav[doc["id"]]),
                "catalog_kind": "subsection" if doc.get("level", 1) > 1 else "chapter",
                "reading_kind": doc.get("reading_kind"),
                "source_status": "edition", "status": "ready"}

    def read(self, identifier: str, version: str | None = None, *, include_original_status: bool = True) -> dict:
        doc = self.documents.get(identifier)
        if doc is None:
            raise DocumentReadError("document_revoked", "该版资料已更新。请在资料目录中查阅。", 410)
        if version and version != doc["sha256"]:
            raise DocumentReadError("document_changed", "资料版本已更新。请从资料目录重新打开。", 409)
        raw, modified = read_bounded(self._asset(f"corpus/{doc['path']}"), self.root / "corpus")
        if sha256(raw) != doc["sha256"]:
            raise DocumentReadError("source_version_changed", "教材正文已变化，请管理员恢复对应版本。", 409)
        result = document_payload(self._entry(doc), raw, modified, "reviewed_edition", allow_navigation=True)
        found = {int(match[1]): entry["id"] for entry in result["sections"]
                 if (match := _BODY_HEADING.match(entry["title"]))}
        pages = self._document_pages(doc)
        book = self.books[doc["book"]]
        original_status = "original_not_mounted"
        if include_original_status and self.originals and any(self._allows_original(doc, item) for item in pages):
            original_status = self.originals.page_status(book)
        original_pages = []
        for item in pages:
            physical = item["physical"]
            saved_preview = self._saved_preview(doc, item) is not None
            status = original_status if self._allows_original(doc, item) else "editorial_only"
            if item["role"] in _NON_EVIDENCE_ROLES and not saved_preview and not self._allows_original(doc, item):
                continue
            original_pages.append({"physical": physical, "section_id": found.get(physical),
                                   "printed_hint": item.get("printed_hint") or "",
                                   "preview": saved_preview or status == "available",
                                   "original_status": "saved_preview" if saved_preview else status,
                                   "evidence_eligible": self._is_evidence_page(doc, item)})
        result.update(edition=doc["edition"], page_start=doc["page_start"], page_end=doc["page_end"],
                      edition_version=self.version, bundled=True, reading_kind=doc.get("reading_kind"),
                      subsections=[self._entry(row) for row in self.nav[identifier]],
                      original_pages=original_pages,
                      message="正文与目录使用同版原件页位。")
        return result

    def _document_pages(self, doc: dict) -> list[dict]:
        raw = self._asset(doc["page_map"]).read_bytes()
        page_map = json.loads(raw)
        if (page_map["version"] != doc["sha256"] or page_map["doc_id"] != doc["doc_id"]
                or doc.get("page_map_sha256") and sha256(raw) != doc["page_map_sha256"]):
            raise DocumentReadError("source_unavailable", "教材页位映射与该版本不符。")
        return page_map["pages"]

    @staticmethod
    def _allows_original(doc: dict, page: dict) -> bool:
        return bool(doc.get("page_map_sha256") and page.get("original_access") == "render"
                    and doc["page_start"] <= page["physical"] <= doc["page_end"])

    def _saved_preview(self, doc: dict, page: dict) -> dict | None:
        number = page["physical"]
        if (not doc["page_start"] <= number <= doc["page_end"] or not page.get("preview")
                or page.get("original_access") == "editorial"):
            return None
        return self.previews.get((doc["book"], number))

    def legacy_locator(self, identifier: str, version: str, section_id: str | None = None) -> dict:
        saved = self.legacy.get(identifier)
        if not saved:
            return {}
        matches = [row for row in saved["verified_anchors"] if version and section_id
                   and version == row["historical_version"] and section_id == row["historical_section_id"]]
        if len(matches) == 1:
            location = self._current_legacy_page(matches[0])
            if location:
                return location
        return {"status": "archive-only", "related": [self._entry(doc) for row in saved["related"]
                                                       if (doc := self.by_doc_id.get(row["doc_id"]))],
                "message": "历史片段仍保留，可在资料目录打开新版内容。"}

    def _current_legacy_page(self, anchor: dict) -> dict | None:
        doc = self.by_doc_id.get(anchor["doc_id"])
        physical = anchor.get("physical")
        if (not doc or not doc.get("page_map_sha256") or not isinstance(physical, list)
                or len(physical) != 2 or any(type(number) is not int for number in physical)):
            return None
        start, end = physical
        if not doc["page_start"] <= start <= end <= doc["page_end"]:
            return None
        try:
            mapped = {row["physical"] for row in self._document_pages(doc)}
            if any(number not in mapped for number in range(start, end + 1)):
                return None
            reading = self.read(doc["id"], doc["sha256"])
        except (DocumentReadError, OSError, ValueError, KeyError):
            return None
        page = next((row for row in reading["original_pages"] if row["physical"] == start), None)
        if not page or not (page["section_id"] or page["preview"]):
            return None
        return {"status": "exact-page-locator", "document": self._entry(doc), "physical": physical,
                "edition_version": self.version, "target_page": start, "section_id": page["section_id"],
                "view": "body" if page["section_id"] else "original",
                "message": "可查看新版中核对过的原件页位，历史引文仍保留在原回答。"}

    def figure(self, identifier: str, version: str, number: int) -> bytes:
        doc = self.documents.get(identifier)
        if not doc:
            raise DocumentReadError("document_revoked", "该版资料已更新。请在资料目录中查阅。", 410)
        if version != doc["sha256"]:
            raise DocumentReadError("document_changed", "资料版本已更新。请从资料目录重新打开。", 409)
        page = next((row for row in self._document_pages(doc) if row["physical"] == number), None)
        artifact = self._saved_preview(doc, page) if page else None
        if artifact:
            raw = self._asset(artifact["file"]).read_bytes()
            if len(raw) > 8 * 1024 * 1024 or sha256(raw) != artifact["sha256"]:
                raise DocumentReadError("source_unavailable", "原页图校验失败，请联系管理员。")
            return raw
        if page and self._allows_original(doc, page):
            if self.originals is None:
                raise DocumentReadError("original_not_mounted", "尚未挂载这本书的原版 PDF。", 404)
            return self.originals.render(self.books[doc["book"]], number)
        raise DocumentReadError("preview_unavailable", "工作台未提供这一页的原图，请使用资料中的原书页号。", 404)

    def resolve_hits(self, hits, provider, workspace, *, query=""):
        local = provider is self.keyword_index
        if local:
            vector_ids = {}
        elif provider.name == "anythingllm" and workspace == self.vector["workspace"]:
            vector_ids = self._vector_members(hits, provider, workspace)
        else:
            return []
        verified_pages = {}
        route_excerpts = {}
        results = []
        for item in hits:
            doc = item if local else vector_ids.get((item.get("raw") or {}).get("id"), {})
            record = self.documents.get(doc.get("document_id"))
            if not record or not record["ingest"]:
                continue
            identifier = record["id"]
            if identifier not in verified_pages:
                try:
                    reading = self.read(identifier, record["sha256"], include_original_status=False)
                    verified_pages[identifier] = _page_texts(reading), _page_texts(reading, facts_only=False) if not local else {}
                except (DocumentReadError, OSError, ValueError, KeyError):
                    verified_pages[identifier] = {}, {}
            source_text = item.get("text") or item.get("content") or ""
            if not local:
                source_text = _COLLECTOR_HEADER.sub("", source_text, count=1)
                if source_text.strip() not in doc["stored_text"] and not same_source_lines(source_text, doc["stored_text"]):
                    continue
            page_hint = item.get("page") if local else None
            pages, all_pages = verified_pages[identifier]
            if local:
                if page_hint not in pages:
                    continue
                candidates = ((page_hint, pages[page_hint]),)
            else:
                locators = {int(page) for page in _BODY_HEADING.findall(source_text)}
                if locators:
                    if len(locators) != 1 or not locators.issubset(pages):
                        continue
                    locator = next(iter(locators))
                    candidates = ((locator, pages[locator]),)
                else:
                    # Do not reassign indistinguishable text from an excluded
                    # page to an eligible one just because it repeats there.
                    candidates = all_pages.items()
            matches = []
            for page, (section, content) in candidates:
                excerpt = _source_excerpt(source_text, content)
                if excerpt is None and local:
                    excerpt = _source_table_rows(source_text, content)
                if excerpt:
                    matches.append((page, section, excerpt))
            if len(matches) == 1 and matches[0][0] in pages:
                page, section, excerpt = matches[0]
                hit = {k: v for k, v in item.items() if k not in {"raw", "content", "partial_readonly_table"}}
                hit["retriever"] = "edition_local" if local else "edition_vector"
                if local and query:
                    from core.readonly_cli_tables import select_readonly_cli_excerpt
                    from core.readonly_route_tables import select_readonly_route_excerpt
                    from .reviewed_source_notes import notes_for_excerpt

                    selection = select_readonly_cli_excerpt(excerpt, query)
                    if selection is None:
                        page_key = identifier, page
                        if page_key not in route_excerpts:
                            route_excerpts[page_key] = select_readonly_route_excerpt(pages[page][1], query)
                        selection = route_excerpts[page_key]
                    if selection:
                        filename = Path(record["path"]).name
                        version = record["sha256"]
                        if notes_for_excerpt(filename, excerpt, version) == notes_for_excerpt(filename, selection, version):
                            excerpt = selection
                            hit["partial_readonly_table"] = True
                results.append(self._bound_hit(hit, record, excerpt, section, page))
        return results

    def _bound_hit(self, hit, record, text, section, page=None):
        return {**hit, "title": record["title"], "filename": Path(record["path"]).name,
                "doc_id": record["doc_id"], "document_id": record["id"], "document_version": record["sha256"],
                "source_path": record["path"], "book": record["book"], "edition": record["edition"],
                "book_title": self.books[record["book"]]["title"],
                "edition_version": self.version, "section_id": section, "page": page, "text": text}

    def improve_page_excerpts(self, hits, query):
        """When useful, show additional authentic blocks from the selected page."""
        from .reviewed_source_notes import notes_for_excerpt

        results = []
        for hit in hits:
            if hit.get("partial_readonly_table") or hit.get("retriever") not in {"edition_local", "edition_fused"}:
                results.append(hit)
                continue
            try:
                reading = self.read(hit["document_id"], hit["document_version"], include_original_status=False)
            except (DocumentReadError, OSError, ValueError, KeyError):
                continue
            mapped = _page_texts(reading).get(hit["page"])
            if mapped and mapped[0] == hit["section_id"]:
                focused = _rr_role_excerpt(mapped[1], hit["text"], query)
                if focused and notes_for_excerpt(hit["filename"], focused, hit["document_version"]) == notes_for_excerpt(
                    hit["filename"], hit["text"], hit["document_version"]
                ):
                    text = focused
                else:
                    text = self.keyword_index.improve_page_excerpt(mapped[1], hit["text"], query)
                results.append({**hit, "text": text})
        return results

    def cover_page_excerpts(self, hits, request):
        """Keep an observation and its conditions at the verified physical anchor."""
        from .page_evidence import paired_excerpt
        from .reviewed_source_notes import notes_for_excerpt, notes_prompt

        results = hits.copy()
        identities = {(hit.get("document_id"), hit.get("section_id"), compact_text(hit["text"])) for hit in hits}
        verified = {}
        for index, hit in enumerate(hits):
            if (hit.get("edition_version") != self.version or hit.get("partial_readonly_table")
                    or hit.get("source_range_reduced") or not hit.get("page") or not hit.get("section_id")
                    or hit.get("retriever") not in {"edition_local", "edition_fused", "focused_original"}):
                continue
            document, version = hit["document_id"], hit["document_version"]
            key = document, version
            if key not in verified:
                try:
                    reading = self.read(document, version, include_original_status=False)
                    verified[key] = _page_texts(reading)
                except (DocumentReadError, OSError, ValueError, KeyError):
                    verified[key] = {}
            page = verified[key].get(hit["page"])
            if not page or page[0] != hit["section_id"]:
                continue
            notes = notes_for_excerpt(hit["filename"], hit["text"], version)
            focus = str(hit.get("query_focus") or "")[:100]
            # Reserve space for the title, physical page, focus, and existing review notes.
            budget = 1100 - len(notes_prompt(notes)) - (len(focus) + 12 if focus else 0)
            excerpt = paired_excerpt(page[1], hit["text"], request, max_chars=budget)
            if not excerpt or notes_for_excerpt(hit["filename"], excerpt, version) != notes:
                continue
            identity = document, hit["section_id"], compact_text(excerpt)
            if identity not in identities:
                identities.add(identity)
                results[index] = {**hit, "text": excerpt}
        return results

    def _vector_members(self, hits, provider, workspace):
        pointers = {(hit.get("raw") or {}).get("id"): self.aliases.get(hit.get("title"))
                    for hit in hits if hit.get("title") in self.aliases}
        pointers.pop(None, None)
        root_value = provider._default_storage_dir()
        if not pointers or not root_value:
            return {}
        root = Path(root_value).resolve()
        db = (root / "anythingllm.db").resolve()
        if not db.is_relative_to(root) or not db.is_file():
            return {}
        keys = ",".join("?" for _ in pointers)
        try:
            with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=1) as conn:
                rows = conn.execute(
                    "SELECT v.vectorId, w.docId, w.docpath FROM document_vectors v "
                    "JOIN workspace_documents w ON w.docId = v.docId "
                    "JOIN workspaces s ON s.id = w.workspaceId "
                    f"WHERE s.slug = ? and v.vectorId IN ({keys})", (workspace, *pointers),
                ).fetchall()
        except sqlite3.Error:
            return {}
        result = {}
        uploads = (root / "documents" / "uploads").resolve()
        for vector_id, provider_id, provider_path in rows:
            saved, target = pointers[vector_id]
            if saved["provider_id"] != provider_id or saved["document_id"] != provider_path:
                continue
            reference = (root / "documents" / provider_path).resolve()
            if not reference.is_relative_to(root / "documents" / "custom-documents"):
                continue
            persistent = uploads / import_alias(saved["alias"])
            try:
                raw, _ = read_bounded(persistent, uploads)
                if sha256(raw) != target["sha256"]:
                    continue
                value = json.loads(reference.read_bytes())
            except (OSError, ValueError, DocumentReadError):
                continue
            if isinstance(value.get("pageContent"), str):
                result[vector_id] = {"document_id": target["id"], "stored_text": value["pageContent"]}
        return result


def _page_texts(body, *, facts_only=True):
    lines = body["content"].splitlines(keepends=True)
    recognized = [s for s in body["sections"] if s["level"] < 3 or _BODY_HEADING.match(s["title"])]
    # Raw page markers can interrupt a malformed Markdown fence. They limit a
    # quotation's source span without granting a reader link to that marker.
    raw_pages = {line_number for line_number, line in enumerate(lines, 1) if _RAW_PAGE_BOUNDARY.match(line)}
    boundaries = sorted(raw_pages | {section["line"] for section in recognized})
    evidence_sections = {p["section_id"] for p in body["original_pages"] if p["evidence_eligible"]}
    pages = {}
    for section in recognized:
        identifier = section["id"]
        match = _BODY_HEADING.match(section["title"])
        if match and (not facts_only or identifier in evidence_sections):
            following = bisect_right(boundaries, section["line"])
            end = boundaries[following] - 1 if following < len(boundaries) else len(lines)
            pages[int(match[1])] = identifier, "".join(lines[section["line"] - 1:end])
    return pages


_RR = r"(?:RR(?![a-z0-9])|(?:路由)?反射器)"
_RR_TIER = r"(?P<tier>[一二三四五六七八九十0-9]{1,2})\s*[级层]\s*"
_RR_DEVICE = r"(?<![a-z0-9])(?:AR|PE|P|R|CE|NE)[0-9]+(?![a-z0-9])"
_RR_PEERS = rf"{_RR_DEVICE}(?:\s*(?:、|与|和|及|[,，])\s*{_RR_DEVICE})*"
_RR_QUERY = re.compile(rf"(?:第\s*)?{_RR_TIER}{_RR}\s*(?:是|为)?\s*(?:谁|哪(?:一)?[台个])", re.I)
_RR_LEADER = re.compile(rf"(?P<leader>{_RR_DEVICE})\s*(?:作为|是|为)\s*(?:第\s*)?{_RR_TIER}{_RR}", re.I)
_RR_CLIENT = re.compile(
    rf"(?P<clients>{_RR_PEERS})\s*(?:配置为|设为|作为|是|为)\s*(?P<owner>{_RR_DEVICE})\s*的?\s*(?:{_RR}\s*)?客户端", re.I,
)
_RR_DEVICE_NAME = re.compile(_RR_DEVICE, re.I)
_RR_CLIENT_COUNT = re.compile(r"(?P<count>[两一二三四五六七八九0-9]{1,2})\s*(?:台|个)\s*(?:反射器)?客户端")
_LIST_NUMBER = re.compile(r"^\s*[0-9]{1,3}(?:\.(?:\s+|$)|、)")
_TIER_DIGITS = str.maketrans("一二两三四五六七八九", "1223456789")


def _rr_participants(relation):
    owner = relation["owner"].casefold()
    clients = frozenset(name.casefold() for name in _RR_DEVICE_NAME.findall(relation["clients"]))
    return owner, clients


def _rr_role_excerpt(body, current, query):
    """Keep a whole paragraph or ordered item proving a reflector/client relation."""
    from core.markdown_blocks import blocks

    levels = {match["tier"].translate(_TIER_DIGITS) for match in _RR_QUERY.finditer(query)}
    if len(levels) != 1 or "客户端" not in query:
        return None
    if len(_BODY_HEADING.findall(body)) != 1 or not _RAW_PAGE_BOUNDARY.match(body):
        return None
    spans = list(blocks(body))
    candidates = {}
    requested_devices = {name.casefold() for name in _RR_DEVICE_NAME.findall(query)}
    client_count_match = _RR_CLIENT_COUNT.search(query)
    client_count = int(client_count_match["count"].translate(_TIER_DIGITS)) if client_count_match else None
    for index, (kind, start, stop) in enumerate(spans):
        if kind != "paragraph":
            continue
        if _LIST_NUMBER.match(body[start:stop]):
            for following, left, right in spans[index + 1:]:
                if following != "paragraph" or _LIST_NUMBER.match(body[left:right]):
                    break
                stop = right
        text = body[start:stop].strip()
        for declaration in _RR_LEADER.finditer(text):
            if declaration["tier"].translate(_TIER_DIGITS) not in levels:
                continue
            leader = declaration["leader"].casefold()
            for relation in _RR_CLIENT.finditer(text):
                owner, peers = _rr_participants(relation)
                if (leader == owner and leader not in peers
                        and requested_devices <= (peers | {leader}) and (client_count is None or len(peers) == client_count)):
                    candidates.setdefault((leader, peers), text)
    if len(candidates) != 1:
        return None
    participants, text = next(iter(candidates.items()))
    if text in current and all(_rr_participants(relation) == participants for relation in _RR_CLIENT.finditer(current)):
        return current
    excerpt = "\n\n".join((body.splitlines()[0], "**同页角色关系摘录。**", text))
    return excerpt if len(excerpt) <= 1040 else None


def _source_excerpt(fragment, source):
    """Locate contiguous text on one actual page, ignoring added ancestor headings."""
    from core.markdown_blocks import blocks

    starts = list(blocks(fragment))
    if not starts or all(kind == "heading" for kind, _, _ in starts):
        return None
    for kind, start, _ in starts:
        candidate = fragment[start:].strip()
        if len(compact_text(candidate)) >= 8:
            if candidate in source:
                return candidate
            # Markdown packing changes inter-block whitespace. Match the same
            # characters and return the original excerpt at the matched span.
            if compact_text(candidate) in compact_text(source):
                pattern = r"\s*".join(map(re.escape, re.sub(r"\s+", "", candidate)))
                match = re.search(pattern, source)
                if match:
                    return match.group()
        if kind != "heading":
            break
    return None


def _source_table_rows(fragment, source):
    """Verify the splitter's repeated header and consecutive original rows on one page."""
    from core.markdown_blocks import blocks

    candidates = [(kind, fragment[start:end].strip()) for kind, start, end in blocks(fragment) if kind != "heading"]
    if len(candidates) != 1 or candidates[0][0] != "table":
        return None
    wanted = [line.strip() for line in candidates[0][1].splitlines()]
    if len(wanted) < 3:
        return None
    matches = []
    for kind, start, end in blocks(source):
        if kind != "table":
            continue
        raw = source[start:end].splitlines(keepends=True)
        lines = [line.strip() for line in raw]
        if lines[:2] != wanted[:2]:
            continue
        length = len(wanted) - 2
        for offset in range(2, len(lines) - length + 1):
            if lines[offset:offset + length] == wanted[2:]:
                matches.append("".join(raw[:2] + raw[offset:offset + length]).strip())
    return matches[0] if len(matches) == 1 else None


def literal_excerpt(text, phrases, max_chars=900):
    """Keep the matching source paragraph or complete sentence for a quotation."""
    from core.markdown_blocks import blocks

    if len(text) <= max_chars:
        return text
    for kind, start, end in blocks(text):
        paragraph = text[start:end].strip()
        if kind != "paragraph" or not any(phrase in compact_text(paragraph) for phrase in phrases):
            continue
        if len(paragraph) <= max_chars:
            return paragraph
        bounds = [0, *(m.end() for m in re.finditer(r"[。？！]|[?!](?=\s|$)", paragraph)), len(paragraph)]
        for left, right in zip(bounds, bounds[1:]):
            sentence = paragraph[left:right].strip()
            if len(sentence) <= max_chars and any(phrase in compact_text(sentence) for phrase in phrases):
                return sentence
    return text


def same_source_lines(fragment, body):
    from unicodedata import normalize

    def flat(value):
        return "".join(c for c in normalize("NFKC", value).casefold() if c.isalnum() or c in (".", "/", ":", "%"))

    candidate = flat(fragment)
    source = flat(body)
    if len(candidate) < 24 or candidate not in source:
        return None
    locators = {int(n) for n in _BODY_HEADING.findall(fragment)}
    return (next(iter(locators)) if len(locators) == 1 else None, None)


@lru_cache(maxsize=2)
def open_edition(directory: str, original_directory: str = ""):
    original_root = Path(original_directory).expanduser() if original_directory else None
    return KnowledgeEdition(Path(directory).expanduser().resolve(), original_root)
