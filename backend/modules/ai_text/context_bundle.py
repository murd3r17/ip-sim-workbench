"""One bounded source representation for generation, UI and evaluation.

No additional retrieval or model call. Prompt text and hashes describe exactly
the excerpt retained after cleaning/trimming, not an arbitrary first 1200 chars.
"""
import hashlib
from datetime import datetime, timezone

from .retrieval import clean_chunk
from core.markdown_blocks import complete_prefix
from modules.knowledge.reviewed_source_notes import notes_for_excerpt, notes_prompt

MAX_DOCUMENTS = 8
MAX_DOCUMENT_CHARS = 3000
MAX_DOCUMENTS_CHARS = 12000
INCOMPLETE_NOTE = "[来源不完整：仅保留完整段落，未提供全文，不得将缺失内容视为不存在。]\n"


class SourceDocuments(list):
    """Server-created prompt sources; plain client text cannot supply metadata."""

    def __init__(self, sources):
        sources = tuple(sources)
        super().__init__(source['prompt_text'] for source in sources)
        self.reviewed_source_indices = tuple(
            index for index, source in enumerate(sources, 1) if source.get('reviewed_notes'))


def clip_documents(documents):
    remaining = MAX_DOCUMENTS_CHARS
    kept = []
    for document in (documents or [])[:MAX_DOCUMENTS]:
        text = str(document)
        limit = min(MAX_DOCUMENT_CHARS, remaining)
        if len(text) > limit:
            content = complete_prefix(text, max(0, limit - len(INCOMPLETE_NOTE)))
            text = INCOMPLETE_NOTE + content if content else ""
        if text:
            kept.append(text)
            remaining -= len(text)
        if not remaining:
            break
    return kept


def prepare_sources(hits, *, max_total_chars=MAX_DOCUMENTS_CHARS,
                    max_document_chars=MAX_DOCUMENT_CHARS, max_documents=MAX_DOCUMENTS):
    sources = []
    remaining = max(0, min(MAX_DOCUMENTS_CHARS, max_total_chars))
    document_limit = max(0, min(MAX_DOCUMENT_CHARS, max_document_chars))
    document_count = max(0, min(MAX_DOCUMENTS, max_documents))
    if not document_count:
        return sources
    now = datetime.now(timezone.utc).isoformat()
    for hit in (hits or []):
        if not isinstance(hit, dict):
            continue
        body = clean_chunk(str(hit.get("text") or hit.get("content") or ""))
        if not body:
            continue
        title = str(hit.get("filename") or hit.get("title") or "参考文档")
        prefix = f"[{title[:160]}]\n"
        limit = min(document_limit, remaining)
        if limit <= len(prefix):
            break
        truncated = len(body) > limit - len(prefix)
        if truncated:
            prefix += INCOMPLETE_NOTE
        content = complete_prefix(body, max(0, limit - len(prefix)))
        if not content:
            continue
        notes = notes_for_excerpt(title, content)
        supplement = notes_prompt(notes)
        if supplement and len(prefix + content + supplement) > limit:
            # Never send a known inaccurate claim after dropping its correction.
            # Reserve the note in the same source budget, then recheck which
            # complete paragraphs (and consequently notes) actually survived.
            if not truncated:
                prefix += INCOMPLETE_NOTE
                truncated = True
            content = complete_prefix(body, max(0, limit - len(prefix) - len(supplement)))
            notes = notes_for_excerpt(title, content)
            supplement = notes_prompt(notes)
        if not content:
            continue
        prompt_text = prefix + content + supplement
        version = hashlib.sha256(content.encode("utf-8")).hexdigest()
        sources.append({
            "source_id": hashlib.sha256((title + "\n" + body).encode("utf-8")).hexdigest()[:16],
            "filename": title, "title": str(hit.get("title") or title), "score": hit.get("score"),
            "content": content, "version": version, "captured_at": now,
            "prompt_text": prompt_text, "prompt_sha256": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
            "truncated": truncated,
            **({"reviewed_notes": notes} if notes else {}),
            **{key: str(hit[key])[:256] for key in ("document_id", "doc_id", "source_path") if hit.get(key)},
        })
        remaining -= len(prompt_text)
        if len(sources) == document_count or not remaining:
            break
    return sources


def source_documents(sources):
    return SourceDocuments(sources)
