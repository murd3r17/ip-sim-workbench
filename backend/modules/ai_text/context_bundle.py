"""One bounded source representation for generation, UI and evaluation.

No additional retrieval or model call. Prompt text and hashes describe exactly
the excerpt retained after cleaning/trimming, not an arbitrary first 1200 chars.
"""
import hashlib
import re
from datetime import datetime, timezone

from .retrieval import clean_chunk
from core.markdown_blocks import blocks, complete_prefix, unclosed_fence_start
from modules.knowledge.reviewed_source_notes import notes_for_excerpt, notes_prompt

MAX_DOCUMENTS = 8
MAX_DOCUMENT_CHARS = 3000
MAX_DOCUMENTS_CHARS = 12000
INCOMPLETE_NOTE = "[来源不完整：仅保留完整段落，未提供全文，不得将缺失内容视为不存在。]\n"
_REFERENCE = re.compile(r"\[(?:n[=:]?[ \t]*|来源[ \t]*[:：]?[ \t]*)?(\d{1,6})(?:[ \t]{0,2}审校(?:说明|补充)?[ \t]{0,2})?\]", re.I)


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
        incomplete_fence = unclosed_fence_start(body)
        usable = body[:incomplete_fence].rstrip() if incomplete_fence is not None else body
        if not usable:
            continue
        title = str(hit.get("filename") or hit.get("title") or "参考文档")
        label = title
        if hit.get('edition_version') and hit.get('book_title'):
            book = str(hit['book_title'])
            chapter = str(hit.get('title') or '')
            label = f'{book} · {chapter}' if chapter and chapter != book else book
        prefix = f"[{' '.join(label.split())[:160]}]\n"
        page = hit.get('page')
        has_page = type(page) is int and page > 0
        if has_page and hit.get('edition_version'):
            prefix += f"该版原教材 PDF 物理页：{page}。\n"
        topic = hit.get("query_focus")
        if topic:
            prefix += f"本片段用于核对 {str(topic)[:100]}。\n"
        limit = min(document_limit, remaining)
        if limit <= len(prefix):
            break
        truncated = incomplete_fence is not None or len(usable) > limit - len(prefix)
        if truncated:
            prefix += INCOMPLETE_NOTE
        content = complete_prefix(usable, max(0, limit - len(prefix)))
        if not content:
            continue
        notes = notes_for_excerpt(title, content, hit.get("document_version"))
        supplement = notes_prompt(notes)
        if supplement and len(prefix + content + supplement) > limit:
            # Never send a known inaccurate claim after dropping its correction.
            # Reserve the note in the same source budget, then recheck which
            # complete paragraphs (and consequently notes) actually survived.
            if not truncated:
                prefix += INCOMPLETE_NOTE
                truncated = True
            content = complete_prefix(usable, max(0, limit - len(prefix) - len(supplement)))
            notes = notes_for_excerpt(title, content, hit.get("document_version"))
            supplement = notes_prompt(notes)
        if not content:
            continue
        prompt_text = prefix + content + supplement
        version = hashlib.sha256(content.encode("utf-8")).hexdigest()
        sources.append({
            "source_id": hashlib.sha256((title + "\n" + body).encode("utf-8")).hexdigest()[:16],
            "filename": title, "title": str(hit.get("title") or title), "score": hit.get("score"),
            **({"score_kind": "relative_within_query"} if hit.get("score_kind") == "relative_within_query" else {}),
            "content": content, "version": version, "captured_at": now,
            "prompt_text": prompt_text, "prompt_sha256": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
            "truncated": truncated or hit.get('source_range_reduced') is True,
            **({"reviewed_notes": notes} if notes else {}),
            **({"page": page} if has_page else {}),
            **{key: str(hit[key])[:256] for key in ("document_id", "doc_id", "source_path", "document_version", "section_id",
                 "query_focus", "book_title", "edition_version") if hit.get(key)},
        })
        remaining -= len(prompt_text)
        if len(sources) == document_count or not remaining:
            break
    return sources


def source_documents(sources):
    return SourceDocuments(sources)


def cited_indices(answer: str) -> tuple[int, ...]:
    prose = '\n'.join(answer[start:end] for kind, start, end in blocks(answer) if kind != 'fence')
    prose = re.sub(r'`[^`\n]*`', '', prose)
    return tuple(dict.fromkeys(int(value) for value in _REFERENCE.findall(prose)))


def answer_references(sources: list[dict], answer: str, status: str) -> tuple[str, list[dict]]:
    if not answer.strip() or status in {"blocked_environment", "unavailable"}:
        return "not_generated", []
    if status == "ok":
        return "generated", sources
    # A failed or cancelled stream may contain usable prose. Keep only
    # markers that actually occurred, retaining their original number.
    indices = set(cited_indices(answer))
    return "partial", [
        {**source, "reference_index": index}
        for index, source in enumerate(sources, 1) if index in indices
    ]


def sanitize_historical_references(result: dict | None) -> dict | None:
    if result is None or result.get("generation_status"):
        return result
    if result.get("status") not in {"failed", "unavailable", "cancelled", "interrupted", "degraded", "blocked_environment"}:
        return result
    # Old failure rows had no reliable boundary between retrieval metadata
    # and actual model content. Do not present those excerpts as citations.
    return {**result, "generation_status": "not_generated", "sources": []}
