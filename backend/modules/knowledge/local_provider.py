"""本地知识库 Provider：直接检索仓库内的 Markdown 语料。

用途：**最小运行模式**——没有 AnythingLLM / Ollama 的机器也能用知识库检索。
实现：纯标准库。英文按单词切分，中文按连续词面二元组切分，BM25 打分，
索引在首次检索时惰性构建，语料目录变化（新增/删除文件）时自动重建。

契约与其它 provider 一致（见 modules/knowledge/provider.py）：
- search 返回 [{id, filename, title, text, score}]
- ask 返回 {question, answer(空), sources, status}
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.config import get_settings
from core.logger import get_logger
from core.markdown_blocks import retrieval_body, split_markdown
from modules.knowledge.provider import KnowledgeProvider

logger = get_logger("knowledge")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CORPUS_DIR = REPO_ROOT / "knowledge" / "corpus" / "huawei-ip"
DEFAULT_STORAGE_DIR = REPO_ROOT / ".runtime" / "local-kb"

_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_\-]{2,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_MAX_CHUNK_CHARS = 900

_K1 = 1.2
_B = 0.75
_INDEX_NAMES = {"00-index.md", "00-corpus-index.md"}


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Read this corpus's flat scalar metadata without introducing a YAML dependency."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end is None:
        return {"ingest": "false"}, ""  # malformed admission metadata is not content
    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*?)\s*$", line)
        if not match:
            continue
        key, value = match.groups()
        if value.startswith('"'):
            try:
                value, _ = json.JSONDecoder().raw_decode(value)
            except (ValueError, TypeError):
                continue
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1].replace("''", "'")
        else:
            value = re.sub(r"\s+#.*$", "", value).strip()
        metadata[key] = str(value)
    return metadata, "".join(lines[end + 1:])


def _tokenize(text: str) -> list[str]:
    """Keep real token boundaries; never join Chinese across English/punctuation.

    Chinese unigrams for every sentence drowned explicit protocol terms in common
    characters. Keep isolated single characters, otherwise use contiguous bigrams.
    ASCII identifiers/numbers stay intact for command and address lookup.
    """
    lowered = text.lower()
    tokens = _ASCII_WORD_RE.findall(lowered)
    for run in _CJK_RE.findall(lowered):
        if len(run) == 1:
            tokens.append(run)
        tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


_QUESTION_TOKENS = frozenset({
    "有什", "什么", "么区", "的区", "区别", "为什", "么是", "是什",
    "哪些", "有哪", "别是", "分别", "怎么", "如何", "应该", "该怎",
    "的", "是", "有", "和", "与", "及",
})


def _query_tokens(text: str) -> list[str]:
    """Remove query-format noise, preserving original documents and user prompts.

    Unrelated exercise questions used to outrank actual protocol explanations
    because short chunks shared '有什么区别'. A negative CLI-output preference
    must not become a positive search for configuration examples.
    """
    # A named protocol should match its name, not unrelated books containing
    # only the generic classifier. Keep the question itself unchanged upstream.
    text = re.sub(r"([A-Za-z][A-Za-z0-9_-]+)\s*协议", r"\1", text)
    text = re.sub(r"(?:不需要|无需|不用|不要)(?:给出|提供|写|附带|展示|包含|生成)?(?:配置|CLI|操作)?命令", "", text, flags=re.I)
    return [term for term in _tokenize(text) if term not in _QUESTION_TOKENS]


def _read_text(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text.lstrip("\ufeff")


def _split_chunks(text: str, max_chars: int = _MAX_CHUNK_CHARS) -> list[str]:
    _, body = _frontmatter(text.lstrip("\ufeff"))
    return split_markdown(body, max_chars)


class LocalKnowledgeProvider(KnowledgeProvider):
    """基于本地 Markdown 语料的关键词检索 provider。"""

    name = "local"

    def __init__(
        self,
        corpus_dir: str | Path | None = None,
        storage_dir: str | Path | None = None,
        top_k: int = 8,
        similarity_threshold: float = 0.2,
        workspace_slug: str = "ip-ops-kb",
    ) -> None:
        settings = get_settings()
        configured = corpus_dir or getattr(settings, "knowledge_corpus_dir", "") or ""
        self.corpus_dir = (Path(configured).expanduser() if configured else DEFAULT_CORPUS_DIR).resolve()
        self.storage_dir = (Path(storage_dir) if storage_dir else DEFAULT_STORAGE_DIR).resolve()
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        self.workspace_slug = workspace_slug
        self._lock = threading.RLock()
        self._signature: tuple | None = None
        self._generation: str = ""
        self._chunks: list[dict[str, Any]] = []
        self._df: Counter = Counter()
        self._avgdl: float = 0.0

    # ── 索引 ─────────────────────────────────────────────────────────
    def _document_identity(self, path: Path) -> tuple[str, str]:
        absolute = path.resolve()
        for namespace, root in (("upload", self.storage_dir), ("corpus", self.corpus_dir)):
            try:
                relative = absolute.relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
            digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24]
            return f"{namespace}-{digest}", f"{namespace}/{relative}"
        raise ValueError("文档不在本地知识库目录内")

    def _scan_files(self) -> list[Path]:
        files: list[Path] = []
        for root in (self.corpus_dir, self.storage_dir):
            if root and root.is_dir():
                files.extend(sorted(root.rglob("*.md")))
                files.extend(sorted(root.rglob("*.txt")))
        return sorted(set(files))

    def _compute_signature(self, files: list[Path]) -> tuple:
        return tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in files)

    def _ensure_index(self) -> None:
        files = self._scan_files()
        try:
            signature = self._compute_signature(files)
        except OSError:
            signature = None
        with self._lock:
            if signature is not None and signature == self._signature:
                return
            chunks: list[dict[str, Any]] = []
            df: Counter = Counter()
            for path in files:
                if path.name.lower() in _INDEX_NAMES:
                    continue
                text = _read_text(path)
                if not text.strip():
                    continue
                metadata, body = _frontmatter(text)
                if metadata.get("ingest", "true").lower() != "true":
                    continue
                try:
                    document_id, source_path = self._document_identity(path)
                except ValueError:
                    continue
                doc_id = metadata.get("doc_id") or document_id
                for seq, chunk in enumerate(_split_chunks(body)):
                    tokens = _tokenize(retrieval_body(chunk))
                    if not tokens:
                        continue
                    counts = Counter(tokens)
                    chunks.append({
                        "id": f"{document_id}#{seq}",
                        "document_id": document_id,
                        "doc_id": doc_id,
                        "path": str(path),
                        "source_path": source_path,
                        "filename": path.name,
                        "title": metadata.get("title") or path.stem,
                        "metadata": metadata,
                        "text": chunk,
                        "counts": counts,
                        "length": len(tokens),
                    })
                    df.update(counts.keys())
            self._chunks = chunks
            self._df = df
            self._avgdl = (sum(item["length"] for item in chunks) / len(chunks)) if chunks else 0.0
            self._signature = signature
            self._generation = hashlib.sha256(repr(signature).encode()).hexdigest() if signature is not None else ""
            logger.info(
                "local_kb_index_built",
                files=len(files),
                chunks=len(chunks),
                corpus_dir=str(self.corpus_dir),
            )

    def _score(self, query_tokens: list[str], chunk: dict[str, Any], total: int) -> float:
        if not query_tokens or not chunk["counts"] or self._avgdl <= 0:
            return 0.0
        score = 0.0
        for token in set(query_tokens):
            tf = chunk["counts"].get(token, 0)
            if not tf:
                continue
            df = self._df.get(token, 0)
            idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
            denominator = tf + _K1 * (1 - _B + _B * chunk["length"] / self._avgdl)
            score += idf * (tf * (_K1 + 1)) / denominator
        return score

    # ── KnowledgeProvider 接口 ───────────────────────────────────────
    async def health_check(self) -> dict[str, Any]:
        await asyncio.to_thread(self._ensure_index)
        return {
            "available": bool(self._chunks),
            "provider": self.name,
            "base_url": str(self.corpus_dir),
            "document_count": len({item["path"] for item in self._chunks}),
            "chunk_count": len(self._chunks),
            "mode": "keyword-bm25",
        }

    async def get_workspace(self, workspace_id: str | None = None) -> dict[str, Any]:
        await asyncio.to_thread(self._ensure_index)
        return {
            "id": workspace_id or self.workspace_slug,
            "name": self.workspace_slug,
            "document_count": len({item["path"] for item in self._chunks}),
            "chunk_count": len(self._chunks),
        }

    async def list_documents(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_documents)

    async def read_document(self, workspace_id: str | None, document: dict) -> dict:
        return await asyncio.to_thread(self._read_document, document)

    def _read_document(self, document: dict) -> dict:
        from .reader import DocumentReadError, document_payload, read_bounded
        # This record comes from the current provider list, never request data.
        # Validate its exact identity without rescanning all 135 files per row.
        path = Path(document.get('path') or '')
        try:
            identity, _ = self._document_identity(path)
        except ValueError as exc:
            raise DocumentReadError('source_unavailable', '持久源文件身份不可核验。') from exc
        if identity != str(document['id']):
            raise DocumentReadError('source_unavailable', '持久源文件身份已变化，请刷新目录。')
        root = self.storage_dir if str(document['id']).startswith('upload-') else self.corpus_dir
        raw, modified = read_bounded(path, root)
        return document_payload(document, raw, modified, 'local_source')

    def _list_documents(self) -> list[dict[str, Any]]:
        self._ensure_index()
        by_path: dict[str, dict[str, Any]] = {}
        for item in self._chunks:
            by_path.setdefault(item["path"], item)
        documents: list[dict[str, Any]] = []
        for path_str, item in sorted(by_path.items()):
            path = Path(path_str)
            try:
                stat = path.stat()
                size = stat.st_size
                created = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
            except OSError:
                size = 0
                created = None
            documents.append({
                "id": item["document_id"],
                "doc_id": item["doc_id"],
                "filename": path.name,
                "title": item["title"],
                "source_path": item["source_path"],
                "metadata": item["metadata"],
                "size": size,
                "status": "ready",
                "created_at": created,
                "path": path_str,
            })
        return documents

    async def upload_document(
        self,
        workspace_id: str | None,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        target = self.storage_dir / Path(filename).name
        target.write_bytes(content)
        self._signature = None  # 触发重建
        document_id, _ = self._document_identity(target)
        return {"id": document_id, "filename": target.name, "status": "ready", "stored_at": str(target)}

    async def delete_document(self, workspace_id: str | None, document_id: str) -> dict[str, Any]:
        if document_id.startswith("corpus-"):
            return {"deleted": [], "status": "forbidden", "error": "教材语料由源仓同步维护，不能通过上传文档接口删除"}
        if document_id.startswith("upload-"):
            target = next((path for path in self._scan_files()
                           if self._document_identity(path)[0] == document_id), None)
            if target is None:
                return {"deleted": [], "status": "not_found"}
            target = target.resolve()
        else:
            # Compatibility with previously returned upload filename IDs.
            if Path(document_id).name != document_id:
                return {"deleted": [], "status": "forbidden"}
            target = (self.storage_dir / document_id).resolve()
        # 只允许删除本地知识库目录内的文件，语料仓由 sync-corpus 管理
        try:
            target.relative_to(self.storage_dir.resolve())
        except ValueError:
            return {"deleted": [], "status": "forbidden", "error": "只能删除本地上传目录内的文档"}
        if target.is_file():
            target.unlink()
            self._signature = None
            return {"deleted": [document_id], "status": "ok"}
        return {"deleted": [], "status": "not_found"}

    async def search(
        self,
        query: str,
        workspace_id: str | None = None,
        top_k: int = 4,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._search, query, top_k)

    def _search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        # Keep the BM25 corpus, document frequencies and average length from one
        # index generation while concurrent requests may trigger a rebuild.
        with self._lock:
            return self._search_locked(query, top_k)

    def _search_locked(self, query: str, top_k: int) -> list[dict[str, Any]]:
        query_tokens = _query_tokens(query or "")
        if not query_tokens:
            return []
        self._ensure_index()
        total = len(self._chunks)
        if not total:
            return []
        scored = []
        for chunk in self._chunks:
            score = self._score(query_tokens, chunk, total)
            if score > 0:
                scored.append((score, chunk))
        if not scored:
            return []
        scored.sort(key=lambda pair: pair[0], reverse=True)
        best = scored[0][0]
        limit = top_k or self.top_k
        results: list[dict[str, Any]] = []
        for score, chunk in scored[:limit]:
            normalized = round(score / best, 4) if best else 0.0
            if normalized < self.similarity_threshold and results:
                continue
            results.append({
                "id": chunk["id"],
                "doc_id": chunk["doc_id"],
                "document_id": chunk["document_id"],
                "source_path": chunk["source_path"],
                "corpus_generation": self._generation,
                "metadata": dict(chunk["metadata"]),
                "filename": chunk["filename"],
                "title": chunk["title"],
                "text": chunk["text"],
                "score": normalized,
            })
        return results

    async def ask(
        self,
        question: str,
        workspace_id: str | None = None,
        top_k: int = 4,
    ) -> dict[str, Any]:
        sources = await self.search(question, workspace_id, top_k)
        return {
            "question": question,
            "answer": "",  # 本地 provider 不生成答案，由上层 LLM 基于 sources 生成
            "sources": sources,
            "workspace": workspace_id or self.workspace_slug,
            "provider": self.name,
            "status": "ok" if sources else "degraded",
        }


@lru_cache(maxsize=4)
def get_local_provider(corpus_dir: str | None, top_k: int, similarity_threshold: float,
                       workspace_slug: str) -> LocalKnowledgeProvider:
    """Bounded process cache; file signatures still refresh edited corpus files."""
    return LocalKnowledgeProvider(corpus_dir=corpus_dir, top_k=top_k,
                                  similarity_threshold=similarity_threshold, workspace_slug=workspace_slug)
