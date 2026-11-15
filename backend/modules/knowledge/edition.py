"""Validated local material for a frozen textbook edition."""
from __future__ import annotations

import hashlib
import json
from functools import cached_property, lru_cache
from collections import Counter
import math
from pathlib import Path
import re
import sqlite3

from .reader import DocumentReadError, document_payload, read_bounded


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


_BODY_HEADING = re.compile(r"^(?:### )?PDF 第 (\d+) 页", re.M)
_VECTOR_ALIAS = re.compile(r"ipsim-[0-9a-f]{16}-\d{3,}\.md")
_COLLECTOR_HEADER = re.compile(r"\A<document_metadata>\r?\n[^\0]{0,900}?\r?\n</document_metadata>\s*")


def import_alias(value: str) -> str:
    return value.partition(".md")[0] + ".md"


class KnowledgeEdition:
    def __init__(self, root: Path):
        self.root = root
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

        return LocalKnowledgeProvider(self.root / "corpus", corpus_only=True)

    def reviewed_page_hits(self, note, workspace, provider_name):
        if provider_name != "local" and (provider_name != "anythingllm" or workspace != self.vector["workspace"]):
            return []
        row = next((item for item in self.documents.values() if item["path"].endswith("/" + note["filename"])), None)
        if not row or row["sha256"] != note["document_version"]:
            return []
        try:
            reading = self.read(row["id"], row["sha256"])
        except (DocumentReadError, OSError, ValueError):
            return []
        page = note["source_page"]
        match = re.search(rf"^### PDF 第 {page} 页\b.*\n", reading["content"], re.M)
        if not match:
            return []
        following = _BODY_HEADING.search(reading["content"], match.end())
        excerpt = reading["content"][match.start():following.start() if following else len(reading["content"])].strip()
        excerpt = excerpt.split("## 后续小节", 1)[0].strip()
        anchor = next((part["section_id"] for part in reading["original_pages"] if part["physical"] == page), None)
        if not anchor:
            return []
        return [{"document_id": row["id"], "document_version": row["sha256"], "doc_id": row["doc_id"],
                 "section_id": anchor, "page": page, "title": row["title"], "filename": note["filename"],
                 "source_path": row["path"], "text": excerpt, "retriever": "reviewed_excerpt"}]

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
            body = self.read(doc["id"], doc["sha256"])
            anchor = next((row["id"] for row in body["sections"] if row["title"] == note["title"]), None)
            loc = "、".join(str(page) for page in note["pages"])
            excerpt = f"## {note['title']}\n\n原件核验 · PDF 第 {loc} 页。\n\n{note['text']}"
            if not anchor or excerpt not in body["content"]:
                continue
            hits.append({"document_id": doc["id"], "document_version": doc["sha256"], "doc_id": doc["doc_id"],
                         "source_path": doc["path"], "section_id": anchor, "title": note["title"],
                         "filename": Path(doc["path"]).name, "text": excerpt, "page": note["pages"][0],
                         "score": round(score / ranks[0][0], 4)})
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
                "source_status": "edition", "status": "ready"}

    def read(self, identifier: str, version: str | None = None) -> dict:
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
        page_map = self._json(doc["page_map"])
        if page_map["version"] != doc["sha256"] or page_map["doc_id"] != doc["doc_id"]:
            raise DocumentReadError("source_unavailable", "教材页位映射与该版本不符。")
        result.update(edition=doc["edition"], page_start=doc["page_start"], page_end=doc["page_end"],
                      edition_version=self.version, bundled=True,
                      subsections=[self._entry(row) for row in self.nav[identifier]],
                      original_pages=[{"physical": item["physical"], "section_id": found.get(item["physical"]),
                                       "preview": bool(item.get("preview") and (doc["book"], item["physical"]) in self.previews)}
                                      for item in page_map["pages"] if item["role"] not in ("navigation", "non-instruction")],
                      message="正文与目录使用同版原件页位。")
        return result

    def legacy_locator(self, identifier: str, version: str, section_id: str | None = None) -> dict:
        saved = self.legacy.get(identifier)
        if not saved:
            return {}
        match = next((row for row in saved["verified_anchors"] if version == row["historical_version"]
                      and section_id and section_id == row["historical_section_id"]), None)
        if match:
            doc = self.by_doc_id[match["doc_id"]]
            return {"status": "exact-page-locator", "document": self._entry(doc), "physical": match["physical"],
                    "message": "可查看新版中核对过的原件页位，历史引文仍保留在原回答。"}
        return {"status": "archive-only", "related": [self._entry(self.by_doc_id[row["doc_id"]])
                                                       for row in saved["related"]],
                "message": "历史片段仍保留，可在资料目录打开新版内容。"}

    def figure(self, identifier: str, version: str, number: int) -> bytes:
        doc = self.documents.get(identifier)
        if not doc:
            raise DocumentReadError("document_revoked", "该版资料已更新。请在资料目录中查阅。", 410)
        if version != doc["sha256"]:
            raise DocumentReadError("document_changed", "资料版本已更新。请从资料目录重新打开。", 409)
        artifact = self.previews.get((doc["book"], number))
        if not artifact or not any(x["physical"] == number and x.get("preview") for x in self._json(doc["page_map"])["pages"]):
            raise DocumentReadError("preview_unavailable", "本页请从指定教材原件查阅。", 404)
        raw = self._asset(artifact["file"]).read_bytes()
        if len(raw) > 8 * 1024 * 1024 or sha256(raw) != artifact["sha256"]:
            raise DocumentReadError("source_unavailable", "原页图校验失败，请联系管理员。")
        return raw

    def resolve_hits(self, hits, provider, workspace):
        if provider.name == "anythingllm" and workspace != self.vector["workspace"]:
            return hits
        vector_ids = self._vector_members(hits, provider, workspace) if provider.name == "anythingllm" else {}
        results = []
        for item in hits:
            doc = item if provider.name == "local" else vector_ids.get((item.get("raw") or {}).get("id"), {})
            record = self.documents.get(doc.get("document_id"))
            if not record:
                results.append(item)
                continue
            try:
                body = self.read(record["id"], record["sha256"])
            except (DocumentReadError, OSError, ValueError):
                # A changed or missing source invalidates the link. The
                # provider's returned fragment can still serve as an excerpt.
                results.append({key: value for key, value in item.items()
                                if key not in ("document_id", "document_version", "section_id")})
                continue
            source_text = item.get("text") or item.get("content") or ""
            if provider.name == "anythingllm" and doc.get("stored_text"):
                source_text = _COLLECTOR_HEADER.sub("", source_text, count=1)
                # AnythingLLM embeds text decoded by its collector, which can
                # include front matter or formatting changed during import.
                if not same_source_lines(source_text, doc["stored_text"]):
                    results.append(item)
                    continue
            # Match complete content against the immutable source. Ancestor headings
            # added by the local searcher are navigational and can be absent here.
            verified = same_version_fragment(source_text, body["content"])
            if verified is None and provider.name == "anythingllm":
                # The collector may flatten Markdown blocks. Confirm that the
                # actual returned body also maps back to the same original text.
                verified = same_source_lines(source_text, body["content"])
            if verified is None:
                results.append({**item, "title": record["title"], "filename": Path(record["path"]).name})
                continue
            location, index = verified
            page_sections = body["original_pages"]
            match = None
            if location is not None:
                match = next((p for p in page_sections if p["physical"] == location), None)
            if match is None and index is not None:
                line = body["content"].count("\n", 0, index) + 1
                previous = [entry for entry in body["sections"] if entry["line"] <= line and _BODY_HEADING.match(entry["title"])]
                if previous:
                    match = next((p for p in page_sections if p["section_id"] == previous[-1]["id"]), None)
            item = {**item, "title": record["title"], "filename": Path(record["path"]).name, "doc_id": record["doc_id"],
                    "document_id": record["id"], "document_version": record["sha256"], "source_path": record["path"],
                    "book": record["book"], "edition": record["edition"], "text": source_text}
            if match:
                item.update(page=match["physical"], section_id=match["section_id"])
            results.append(item)
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


def same_version_fragment(fragment, body):
    """Resolve actual source text after harmless whitespace and Markdown processing."""
    from core.markdown_blocks import blocks
    plain = re.sub(r"\s+", "", fragment)
    if len(plain) < 18:
        return None
    anchors = {int(p) for p in _BODY_HEADING.findall(fragment)}
    norm = re.sub(r"\s+", "", body)
    if plain in norm:
        start = body.find(fragment.strip())
        return (next(iter(anchors)) if len(anchors) == 1 else None, start if start >= 0 else None)
    parts = [(kind, fragment[start:end].strip()) for kind, start, end in blocks(fragment)]
    content = [re.sub(r"\s+", "", raw) for kind, raw in parts if kind != "heading" and len(raw) >= 18]
    if not content or not all(text in norm for text in content):
        return None
    anchor = next(iter(anchors)) if len(anchors) == 1 and _BODY_HEADING.search(body) else None
    return anchor, None


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
def open_edition(directory: str):
    return KnowledgeEdition(Path(directory).expanduser().resolve())
