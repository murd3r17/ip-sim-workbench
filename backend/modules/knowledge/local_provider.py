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
from typing import Any, Callable
from unicodedata import normalize

from core.config import get_settings
from core.logger import get_logger
from core.markdown_blocks import blocks, retrieval_body, split_markdown
from modules.knowledge.provider import KnowledgeProvider
from modules.knowledge.query_focus import (
    OSPF_PEER_COMMAND, compact_text, context_only_query, introductory_query, ospf_peer_lookup, protocol_names,
    passage_concepts, passage_intent, passage_query, technical_aliases, title_key, vlan_mapping_query,
)

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
_PAGE_HEADING = re.compile(r"^### PDF 第 (\d+) 页\b", re.M)
_CHINESE_LAYOUT_SPACE = re.compile(r"(?<=[\u4e00-\u9fff])(?:[^\S\n]|\n(?!\s*\n))+(?=[\u4e00-\u9fff])")
_ENTITY_LETTER = re.compile(r"(?<![A-Za-z0-9])[A-Z](?![A-Za-z0-9])")
_NETWORK_LABEL = re.compile(
    r"(?<![A-Za-z0-9])(?:\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?|"
    r"[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{0,4}){2,}(?:/\d{1,3})?|"
    r"(?:GigabitEthernet|Ethernet|GE|Eth)\s*\d+(?:/\d+){1,3}(?:\.\d+)?|"
    r"(?:VLANIF|Loopback|Area|VNI|VLAN|BD|AS)\s*\d+)(?![A-Za-z0-9])", re.I,
)
_OUTLINE = re.compile(r"(?:本章|本节|这章|本课)(?:从|介绍|主要|将|内容|包括)|"
                      r"(?:课程|课件|课文|实验|章节)目录|学习目标|章节概览|本章小节|复习题|课后练习")
_OBSERVED = re.compile(r"\bdisplay\s|\bshow\s|回显|读回|结果截图|\bEstablished\b|"
                       r"\b(?:Up|Down)\b|^\s*\|.+\|\s*$", re.I | re.M)
_VISUAL = re.compile(r"图\s*\d|表\s*\d|原图|图中|图内|图注|截图|连线|^\s*\|.+\|\s*$", re.M)
_OBSERVED_VALUES = re.compile(r"^\s*(?:[A-Za-z][\w ]{0,30}\s*:\s*\S|\|[^\r\n]*\d[^\r\n]*\|\s*$)|"
                              r"\b(?:Established|Full|Up|Down)\b|`[^`\r\n]*(?:\d|Up|Down)[^`\r\n]*`", re.I | re.M)
_INTERPRETATION = re.compile(r"表示|表示的是|概念|含义|示意|指向|分别指|另指|用于区分|"
                             r"是(?:本版|文本|路由|状态|属性|起源|标识)")
_SLASH_FIELD = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9_]{1,18}/[A-Za-z][A-Za-z0-9_]{1,18}(?![A-Za-z0-9])")
_MSTP_MAPPING_HEADER = re.compile(r"^[ \t]*Instance[ \t]+VLANs?[ \t]+Mapped[ \t]*\r?$", re.I | re.M)
_MSTP_MAPPING_ROW = re.compile(r"^[ \t]*[1-9]\d{0,3}[ \t]{2,}(\d{1,4}(?:[ \t]*,[ \t]*\d{1,4})*)[ \t]*,?[ \t]*$")


def vlan_mapping_excerpt(text: str, wanted: frozenset[int]) -> str:
    """Return one complete source table containing the requested mapped VLAN IDs."""
    if not wanted or "mapped" not in text.casefold():
        return ""
    for kind, start, stop in blocks(text):
        if kind != "fence":
            continue
        table = text[start:stop].strip()
        header = _MSTP_MAPPING_HEADER.search(table)
        if not header or not table.endswith("```") or _MSTP_MAPPING_HEADER.search(table, header.end()):
            continue
        values = Counter(int(value) for line in table[header.end():].splitlines()
                         if (row := _MSTP_MAPPING_ROW.fullmatch(line)) for value in row[1].split(","))
        if all(values[value] == 1 for value in wanted):
            return table
    return ""
_NUMBERED_ENTITY = re.compile(r"[a-z]{1,9}\d+[a-z0-9-]*")


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
    tokens = [token if token != "is-is" else "isis" for token in _ASCII_WORD_RE.findall(lowered)]
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
    if context_only_query(text):
        return []
    text = re.sub(r"([A-Za-z][A-Za-z0-9_-]+)\s*协议", r"\1", text)
    text = re.sub(r"(?:不需要|无需|不用|不要)(?:给出|提供|写|附带|展示|包含|生成)?(?:配置|CLI|操作)?命令", "", text, flags=re.I)
    return [term for term in _tokenize(text) if term not in _QUESTION_TOKENS]


def _edition_tokens(text: str, *, query=False) -> list[str]:
    text = normalize("NFKC", text)
    text = _CHINESE_LAYOUT_SPACE.sub("", text)
    tokens = _query_tokens(text) if query else _tokenize(text)
    tokens.extend("letter=" + match.group().lower() for match in _ENTITY_LETTER.finditer(text))
    tokens.extend("concept=" + concept for concept in sorted(passage_concepts(text)))
    tokens.extend("label=" + match.group().lower() for match in _SLASH_FIELD.finditer(text))
    for match in _NETWORK_LABEL.finditer(text):
        label = compact_text(match.group())
        label = label.replace("gigabitethernet", "ge", 1) if label.startswith("gigabitethernet") else label
        label = label.replace("ethernet", "eth", 1) if label.startswith("ethernet") else label
        tokens.append("label=" + label)
    return tokens


def _passage_role(body: str):
    from core.markdown_blocks import HEADING

    lines = [line.strip() for line in body.splitlines() if line.strip()]
    prose = next((line for line in lines if not HEADING.match(line)), "")
    leading = " ".join(lines[:3])
    outline = bool(_OUTLINE.search(leading) and (_OUTLINE.search(prose) or len(prose) < 170))
    observed = bool(_OBSERVED.search(body))
    return outline, observed, observed and bool(_OBSERVED_VALUES.search(body)), bool(_VISUAL.search(body)), bool(_INTERPRETATION.search(body))


def _best_window(text: str, weights: dict[str, float], limit: int) -> tuple[float, str]:
    spans = [(kind, start, end, weights.keys() & set(_edition_tokens(text[start:end])))
             for kind, start, end in blocks(text)]
    best = (0.0, "")
    for i, (_, start, _, _) in enumerate(spans):
        seen = set()
        for kind, _, stop, terms in spans[i:]:
            if stop - start > limit:
                break
            seen.update(terms)
            if kind != "heading":
                score = sum(weights[term] for term in seen)
                if score > best[0]:
                    best = score, text[start:stop].strip()
    return best


def _ranked_window(text: str, weights: dict[str, float], limit: int = 1050) -> str:
    if len(text) <= limit or not weights:
        return text
    return _best_window(text, weights, limit)[1] or text


def _distinct_pages(ranked):
    first, continuations = [], []
    seen = set()
    for item in ranked:
        key = item[1]["page_key"]
        if key in seen:
            continuations.append(item)
        else:
            first.append(item)
            seen.add(key)
    return first + continuations


def _priority_queries(query, weights):
    runs = list(dict.fromkeys(run for run in _CJK_RE.findall(passage_query(normalize("NFKC", query))) if len(run) >= 3))
    phrases = []
    for run in runs[:12]:
        width = 4 if len(run) >= 4 else 3
        phrases.append(tuple(run[i:i + width] for i in range(min(10, len(run) - width + 1))))
    labels = tuple((term, weight) for term, weight in weights.items() if _explicit_identifier(term)
                   or (len(term) >= 3 and re.fullmatch(r"[a-z0-9_/-]+", term) and not term.isdecimal()))
    return phrases, labels


def _explicit_identifier(term: str) -> bool:
    return term.startswith(("label=", "letter=")) or bool(_NUMBERED_ENTITY.fullmatch(term))


def _priority_rank(ranked, query, weights, page_terms):
    """Retrieve focused passages by explicit labels and contiguous Chinese phrases."""
    phrases, labels = _priority_queries(query, weights)
    if not phrases and not labels:
        return ranked
    context_ranks = []
    label_weight = sum(weight for _, weight in labels) or 1.0
    phrase_count = len(phrases) or 1
    for score, chunk, passage in ranked:
        text = chunk["compact_body"]
        heading = chunk["compact_headings"]
        same_passage = sum(weight for term, weight in labels if term in chunk["counts"]) / label_weight
        same_page = sum(weight for term, weight in labels if term in page_terms.get(chunk["page_key"], ())) / label_weight
        matched_phrases = sum(any(value in text for value in group) for group in phrases) / phrase_count
        matched_headings = sum(any(value in heading for value in group) for group in phrases) / phrase_count
        focal = .55 * same_passage + .21 * same_page + .55 * matched_phrases + .25 * matched_headings
        if chunk["role"][0]:
            focal *= .65
        context_ranks.append((score, focal, chunk, passage))
    ceiling = max(item[1] for item in context_ranks)
    if not ceiling:
        return ranked
    best = ranked[0][0]
    combined = [(score + .36 * best * focal / ceiling, chunk, passage)
                for score, focal, chunk, passage in context_ranks]
    combined.sort(key=lambda item: item[0], reverse=True)
    return combined


def _read_text(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text.lstrip("\ufeff")


def _split_chunks(text: str, max_chars: int = _MAX_CHUNK_CHARS) -> list[str]:
    _, body = _frontmatter(text.lstrip("\ufeff"))
    return split_markdown(body, max_chars)


_INSTRUCTION_LEAD = re.compile(r"^(?:[图表]\s*\d|步骤|任务|实验|操作|配置(?:要求|如下|步骤)|查看|执行|验证)")
_DEFINITION_LANGUAGE = re.compile(r"是一种|是指|简称|用于|作用是|基于|采用|主要承担")
_MECHANISM_LANGUAGE = re.compile(r"通过|建立|交换|转发|运行在|选举|决定|描述|计算|生成|维护")
_LEADING_TERM = re.compile(r"[A-Za-z][A-Za-z0-9-]*")
_DEVICE_COMMAND = re.compile(r"^\s*(?:\[[^\]\n]+\]|<[^>\n]+>)\s*(\S.*)$", re.M)
_PEER_COMMAND_LINE = re.compile(
    rf"^\s*(?:\[[^\]\n]+\]|<[^>\n]+>)?\s*{re.escape(OSPF_PEER_COMMAND)}(?:\s|$)", re.I | re.M,
)


def _learning_passages(text: str) -> tuple[list[tuple[set[str], set[str], int, str]], str]:
    explanations = []
    peer_excerpt = ""
    for kind, start, end in blocks(text):
        passage = text[start:end].strip()
        if kind == "fence" and not peer_excerpt and _PEER_COMMAND_LINE.search(passage):
            commands = _DEVICE_COMMAND.findall(passage)
            if all(command.casefold().startswith("display ") for command in commands):
                peer_excerpt = passage
        if kind != "paragraph" or len(passage) > _MAX_CHUNK_CHARS:
            continue
        lead = passage.lstrip("-*>` ")
        if _INSTRUCTION_LEAD.match(lead):
            continue
        subjects = protocol_names(passage)
        if subjects:
            definition = _DEFINITION_LANGUAGE.search(passage)
            if definition or _MECHANISM_LANGUAGE.search(passage):
                term = _LEADING_TERM.match(lead)
                opening = protocol_names(term.group()) if term else set()
                explanations.append((subjects, opening, 2 if definition else 1, passage))
    return explanations, peer_excerpt


def _choose_explanation(chunk: dict, subject: str, query: str) -> tuple[int, str]:
    asks_about_neighbors = subject == "ospf" and ("邻居" in query or "邻接" in query)
    best = (0, chunk["text"])
    for subjects, opening, quality, passage in chunk["explanations"]:
        if subject not in subjects or (asks_about_neighbors and "邻居" not in passage and "邻接" not in passage):
            continue
        score = quality + (2 if subject in opening else 0)
        if score > best[0]:
            best = (score, passage)
    return best


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
        *,
        corpus_only: bool = False,
        frozen_documents: dict[str, dict] | None = None,
        frozen_page_loader: Callable[[dict], set[int]] | None = None,
    ) -> None:
        settings = get_settings() if not corpus_dir or (not storage_dir and not corpus_only) else None
        configured = corpus_dir or getattr(settings, "knowledge_corpus_dir", "") or ""
        self.corpus_dir = (Path(configured).expanduser() if configured else DEFAULT_CORPUS_DIR).resolve()
        storage = storage_dir or getattr(settings, "knowledge_local_storage", "") or DEFAULT_STORAGE_DIR
        self.storage_dir = Path(storage).expanduser().resolve()
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        self.workspace_slug = workspace_slug
        self.corpus_only = corpus_only
        self.frozen_documents = frozen_documents
        self._frozen_page_loader = frozen_page_loader
        self._lock = threading.RLock()
        self._signature: tuple | None = None
        self._generation: str = ""
        self._chunks: list[dict[str, Any]] = []
        self._df: Counter = Counter()
        self._page_terms: dict[tuple[int, int], set[str]] = {}
        self._ranked_count = 0
        self._avgdl: float = 0.0
        self._ordinary_count_compatible = False
        self._edition_inventory_cache: tuple[tuple, list[dict[str, Any]], int] | None = None

    # ── 索引 ─────────────────────────────────────────────────────────
    @staticmethod
    def _relative_document_id(namespace: str, relative: str) -> str:
        digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24]
        return f"{namespace}-{digest}"

    def _document_identity(self, path: Path) -> tuple[str, str]:
        absolute = path.resolve()
        for namespace, root in self._document_roots():
            try:
                relative = absolute.relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
            return self._relative_document_id(namespace, relative), f"{namespace}/{relative}"
        raise ValueError("文档不在本地知识库目录内")

    def _document_roots(self) -> tuple[tuple[str, Path], ...]:
        roots = (("corpus", self.corpus_dir),)
        return roots if self.corpus_only else (("upload", self.storage_dir), *roots)

    def _scan_files(self) -> list[Path]:
        if self.frozen_documents is not None:
            return [path for relative in self.frozen_documents
                    if (path := self.corpus_dir / relative).is_file()
                    and not path.is_symlink() and path.resolve().is_relative_to(self.corpus_dir)]
        files: list[Path] = []
        for _, root in self._document_roots():
            if root and root.is_dir():
                files.extend(sorted(root.rglob("*.md")))
                files.extend(sorted(root.rglob("*.txt")))
        return sorted(set(files))

    def _compute_signature(self, files: list[Path]) -> tuple:
        def stamp(path):
            try:
                stat = path.stat()
                return str(path), stat.st_mtime_ns, stat.st_size
            except OSError:
                return str(path), None, None

        base = tuple(stamp(path) for path in files)
        if self._frozen_page_loader is None or self.frozen_documents is None:
            return base
        return base + tuple(stamp(self.corpus_dir.parent / self.frozen_documents[path.relative_to(self.corpus_dir).as_posix()]["page_map"])
                            for path in files)

    def _ensure_index(self) -> None:
        files = self._scan_files()
        signature = self._compute_signature(files)
        with self._lock:
            if signature is not None and signature == self._signature:
                return
            chunks: list[dict[str, Any]] = []
            df: Counter = Counter()
            page_terms: dict[tuple[int, int], set[str]] = {}
            ranked_count = ranked_length = 0
            ordinary_count_compatible = True
            for path in files:
                if path.name.lower() in _INDEX_NAMES:
                    continue
                frozen = None
                if self.frozen_documents is not None:
                    from .reader import DocumentReadError, read_bounded

                    frozen = self.frozen_documents[path.relative_to(self.corpus_dir).as_posix()]
                    try:
                        raw, _ = read_bounded(path, self.corpus_dir)
                    except DocumentReadError:
                        continue
                    if hashlib.sha256(raw).hexdigest() != frozen["sha256"]:
                        continue
                    text = raw.decode("utf-8-sig")
                    if "\r" in text or text.startswith(("\n", "\ufeff")):
                        ordinary_count_compatible = False
                else:
                    text = _read_text(path)
                if not text.strip():
                    continue
                metadata, body = _frontmatter(text.lstrip("\r\n") if frozen else text)
                if metadata.get("ingest", "true").lower() != "true":
                    continue
                try:
                    document_id, source_path = self._document_identity(path)
                except ValueError:
                    continue
                if frozen:
                    if document_id != frozen["id"]:
                        ordinary_count_compatible = False
                    document_id, source_path = frozen["id"], frozen["path"]
                allowed = self._frozen_page_loader(frozen) if frozen and self._frozen_page_loader else None
                doc_id = metadata.get("doc_id") or document_id
                title = frozen["title"] if frozen else metadata.get("title") or path.stem
                for seq, chunk in enumerate(_split_chunks(body)):
                    passage = retrieval_body(chunk)
                    tokens = _tokenize(passage)
                    if not tokens:
                        continue
                    evidence_page = not frozen
                    if frozen:
                        tokens = _edition_tokens(passage)
                    counts = Counter(tokens)
                    explanations, peer_excerpt = _learning_passages(chunk)
                    chunks.append({
                        "id": f"{document_id}#{seq}",
                        "document_id": document_id,
                        "doc_id": doc_id,
                        "path": str(path),
                        "source_path": source_path,
                        "filename": path.name,
                        "title": title,
                        "metadata": metadata,
                        "text": chunk,
                        "counts": counts,
                        "length": len(tokens),
                        "explanations": explanations,
                        "peer_excerpt": peer_excerpt,
                    })
                    if frozen:
                        page = _PAGE_HEADING.search(chunk)
                        physical_page = int(page[1]) if page else None
                        page_key = (frozen["book"], physical_page) if physical_page else None
                        evidence_page = bool(physical_page and (allowed is None or physical_page in allowed))
                        heading_text = "\n".join(passage[start:end] for kind, start, end in blocks(passage)
                                                 if kind == "heading" and not _PAGE_HEADING.match(passage[start:end]))
                        chunks[-1].update(page=physical_page, evidence_page=evidence_page, page_key=page_key, role=_passage_role(passage),
                                          compact_body=compact_text(passage), compact_title=title_key(title),
                                          compact_headings=compact_text(heading_text))
                        if evidence_page:
                            page_terms.setdefault(page_key, set()).update(counts)
                    if evidence_page:
                        df.update(counts.keys())
                        ranked_count += 1
                        ranked_length += len(tokens)
            self._chunks = chunks
            self._df = df
            self._page_terms = page_terms
            self._ranked_count = ranked_count
            self._avgdl = ranked_length / ranked_count if ranked_count else 0.0
            self._ordinary_count_compatible = ordinary_count_compatible
            self._signature = signature
            self._generation = hashlib.sha256(repr(signature).encode()).hexdigest() if signature is not None else ""
            logger.info(
                "local_kb_index_built",
                files=len(files),
                chunks=len(chunks),
                corpus_dir=str(self.corpus_dir),
            )

    def _weights(self, query_tokens: list[str], total: int) -> dict[str, float]:
        return {token: (.75 if token.startswith("concept=") else 1.0)
                * math.log1p((total - self._df[token] + 0.5) / (self._df[token] + 0.5))
                for token in sorted(set(query_tokens)) if token in self._df}

    def _score(self, weights: dict[str, float], chunk: dict[str, Any]) -> float:
        if not weights or not chunk["counts"] or self._avgdl <= 0:
            return 0.0
        score = 0.0
        norm = _K1 * (1 - _B + _B * chunk["length"] / self._avgdl)
        for token, idf in weights.items():
            tf = chunk["counts"].get(token, 0)
            if tf:
                score += idf * (tf * (_K1 + 1)) / (tf + norm)
        return score

    def _passage_score(self, score, weights, total_weight, chunk, intent):
        if score <= 0 or not weights:
            return score
        wants_overview, wants_observation, wants_visual, wants_interpretation = intent
        overview, observation, observed_values, visual, interpretation = chunk["role"]
        tokens = chunk["counts"]
        page_tokens = self._page_terms.get(chunk["page_key"], ())
        same_passage = nearby = 0.0
        for term, weight in weights.items():
            if term in tokens:
                same_passage += weight
            elif term in page_tokens:
                nearby += weight
        score = score * (1 + .25 * same_passage / total_weight) + .12 * nearby
        if overview and not wants_overview:
            score *= .68
        if wants_interpretation and interpretation:
            score *= 1.23
        elif wants_observation and observation and not wants_interpretation:
            score *= 1.3 if observed_values else 1.12
        if wants_visual and visual:
            score *= 1.12
        return score

    def improve_page_excerpt(self, body: str, current: str, query: str) -> str:
        if vlan_mapping_excerpt(current, vlan_mapping_query(query)):
            return current
        query_tokens = _edition_tokens(passage_query(query), query=True)
        with self._lock:
            weights = self._weights(query_tokens, self._ranked_count)
        if len(weights) < 4:
            return current
        current_terms = set(weights).intersection(_edition_tokens(current))
        current_score = sum(weights[term] for term in current_terms)
        score, candidate = _best_window(body, weights, 1050)
        if score > current_score:
            current_ids = {term for term in current_terms if _explicit_identifier(term)}
            expanded_ids = {term for term in set(weights).intersection(_edition_tokens(candidate)) if _explicit_identifier(term)}
            if not current_ids.issubset(expanded_ids):
                return current
            if current_ids < expanded_ids:
                return candidate
        if score <= max(current_score + 1.0, current_score * 1.15):
            return current
        return candidate

    def topical_hits(self, query: str, hits: list[dict]) -> list[dict]:
        """Keep same-edition semantic candidates with visible topical support."""
        query_tokens = _edition_tokens(passage_query(query), query=True)
        with self._lock:
            weights = self._weights(query_tokens, self._ranked_count)
        if not weights:
            return []
        subjects = protocol_names(query)
        identifiers = {term for term in weights if term.startswith("label=")}
        applicable = []
        minimum_weight = .26 * sum(weights.values())
        for hit in hits:
            body = hit["text"]
            if subjects and not subjects.intersection(protocol_names(body + " " + hit.get("title", ""))):
                continue
            shared = set(weights).intersection(_edition_tokens(retrieval_body(body)))
            if identifiers and not identifiers.intersection(shared):
                continue
            if len(shared) >= min(2, len(weights)) and sum(weights[term] for term in shared) >= minimum_weight:
                applicable.append(hit)
        return applicable

    # ── KnowledgeProvider 接口 ───────────────────────────────────────
    async def health_check(self) -> dict[str, Any]:
        await asyncio.to_thread(self._ensure_index)
        available = bool(self._ranked_count)
        return {
            "available": available,
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

    def shares_frozen_corpus(self, frozen: LocalKnowledgeProvider) -> bool:
        return (self.frozen_documents is None and not self.corpus_only and frozen.frozen_documents is not None
                and self.corpus_dir == frozen.corpus_dir and not self.storage_dir.is_relative_to(self.corpus_dir)
                and not self.corpus_dir.is_relative_to(self.storage_dir)
                and all(Path(path).suffix in {".md", ".txt"} and self._relative_document_id("corpus", path) == record["id"]
                        for path, record in frozen.frozen_documents.items()))

    def can_supply_workspace_counts(self, document_count: int) -> bool:
        # The regular reader normalizes line endings before splitting chunks.
        return (self.frozen_documents is not None and self._ordinary_count_compatible
                and document_count == len(self.frozen_documents))

    async def edition_inventory(self, frozen: LocalKnowledgeProvider) -> tuple[list[dict[str, Any]], int]:
        """Read regular provider rows outside a separately indexed frozen edition."""
        verified = {self.corpus_dir / relative: row["id"] for relative, row in frozen.frozen_documents.items()}
        return await asyncio.to_thread(self._edition_inventory, verified)

    def _edition_inventory(self, verified: dict[Path, str]) -> tuple[list[dict[str, Any]], int]:
        files = [path for path in self._scan_files() if path not in verified and path.name.lower() not in _INDEX_NAMES]
        indexed_ids = frozenset(verified.values())
        signature = (indexed_ids, self._compute_signature(files))
        with self._lock:
            cached = self._edition_inventory_cache
            if cached is not None and cached[0] == signature:
                return cached[1], cached[2]
            documents, chunk_count = self._read_inventory(files, indexed_ids)
            self._edition_inventory_cache = (signature, documents, chunk_count)
            return documents, chunk_count

    def _read_inventory(self, files: list[Path], indexed_ids: frozenset[str]) -> tuple[list[dict[str, Any]], int]:
        documents = []
        chunk_count = 0
        for path in files:
            try:
                identifier, source_path = self._document_identity(path)
            except ValueError:
                continue
            if identifier in indexed_ids:
                # A second path to an indexed source can contribute another ordinary row.
                raise ValueError("The frozen source is also visible through an alternate local path.")
            text = _read_text(path)
            if not text.strip():
                continue
            metadata, body = _frontmatter(text)
            if metadata.get("ingest", "true").lower() != "true":
                continue
            chunks = sum(bool(_tokenize(retrieval_body(chunk))) for chunk in _split_chunks(body))
            if chunks:
                chunk_count += chunks
                documents.append(self._document_row(path, identifier, metadata.get("doc_id") or identifier,
                                                     metadata.get("title") or path.stem, source_path, metadata))
        return documents, chunk_count

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
        payload = document_payload(document, raw, modified, 'local_source')
        payload["bundled"] = identity.startswith("corpus-") and self.corpus_dir == DEFAULT_CORPUS_DIR
        return payload

    def _list_documents(self) -> list[dict[str, Any]]:
        self._ensure_index()
        by_path: dict[str, dict[str, Any]] = {}
        for item in self._chunks:
            by_path.setdefault(item["path"], item)
        return [self._document_row(Path(path), item["document_id"], item["doc_id"], item["title"],
                                   item["source_path"], item["metadata"])
                for path, item in sorted(by_path.items())]

    @staticmethod
    def _document_row(path, identifier, doc_id, title, source_path, metadata):
        try:
            stat = path.stat()
            size = stat.st_size
            created = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            size = 0
            created = None
        return {"id": identifier, "doc_id": doc_id, "filename": path.name, "title": title,
                "source_path": source_path, "metadata": metadata, "size": size,
                "status": "ready", "created_at": created, "path": str(path)}

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
        self._edition_inventory_cache = None
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
            self._edition_inventory_cache = None
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

    async def search_pages(self, query, top_k, *, document_ids=None, pages=None, phrases=()):
        """Report whether this frozen source has verified text, even for a miss."""
        def search():
            with self._lock:
                self._ensure_index()
                return bool(self._ranked_count), self._search_locked(
                    query, top_k, document_ids=document_ids, pages=pages, phrases=phrases, ready=True,
                )

        return await asyncio.to_thread(search)

    def _search_locked(self, query: str, top_k: int, *, document_ids=None, pages=None, phrases=(), ready=False) -> list[dict[str, Any]]:
        peer_lookup = ospf_peer_lookup(query or "") or (query or "").strip().casefold() == OSPF_PEER_COMMAND
        alias = OSPF_PEER_COMMAND if peer_lookup else technical_aliases(query or "")
        query_text = f"{query} {alias}" if alias else query or ""
        query_tokens = _edition_tokens(passage_query(query_text), query=True) if ready and not phrases else _query_tokens(query_text)
        if not query_tokens and not (ready and (pages or document_ids or phrases)):
            return []
        if not ready:
            self._ensure_index()
        total = self._ranked_count
        if not total:
            return []
        weights = self._weights(query_tokens, total)
        total_weight = sum(weights.values())
        intent = passage_intent(query) if ready else None
        protocols = protocol_names(query)
        short_subject = next(iter(protocols)) if not alias and len(protocols) == 1 and len(set(query_tokens)) <= 6 and len(query) <= 22 else None
        prefer_explanation = short_subject is not None and introductory_query(query)
        scored = []
        literals = tuple(compact_text(phrase) for phrase in phrases)
        vlan_ids = vlan_mapping_query(query) if ready and not literals else frozenset()
        natural = compact_text(query) if ready and not literals and not prefer_explanation else ""
        if len(natural) < 4:
            natural = ""
        for chunk in self._chunks:
            if self.frozen_documents is not None and not chunk.get("evidence_page"):
                continue
            if document_ids is not None and chunk["document_id"] not in document_ids:
                continue
            if pages and not pages[0] <= chunk["page"] <= pages[1]:
                continue
            body = chunk.get("compact_body", "")
            exact = sum(phrase in body for phrase in literals)
            if literals and not exact:
                continue
            score = self._score(weights, chunk) if query_tokens else 1.0
            if ready and not literals:
                score = self._passage_score(score, weights, total_weight, chunk, intent)
            mapping = vlan_mapping_excerpt(chunk["text"], vlan_ids)
            if score > 0 or exact or mapping:
                matches_subject = short_subject and short_subject in chunk["counts"]
                title_match = bool(matches_subject and short_subject in protocol_names(chunk["title"]))
                title_match = title_match or bool(natural and natural in chunk.get("compact_title", ""))
                scored.append((score, title_match, exact or int(bool(natural and natural in body)), chunk, mapping))
        if not scored:
            return []
        weight = max(score for score, *_ in scored) or 1.0
        ranked = []
        for score, preferred, exact, chunk, mapping in scored:
            passage = chunk["text"]
            if exact:
                score += exact * weight * 8
            else:
                if preferred:
                    score += weight
                if prefer_explanation and short_subject in chunk["counts"]:
                    explanation, passage = _choose_explanation(chunk, short_subject, query)
                    score += explanation * weight
            if not exact and peer_lookup and chunk["peer_excerpt"]:
                score += weight * 2
                passage = chunk["peer_excerpt"]
            if mapping:
                score += weight * 3
                passage = mapping
            ranked.append((score, chunk, passage))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if ready and len(weights) > 4 and not (literals or peer_lookup or prefer_explanation):
            ranked = _priority_rank(ranked, query, weights, self._page_terms)
        best = ranked[0][0]
        if ready and not literals:
            ranked = _distinct_pages(ranked)
        limit = top_k or self.top_k
        results: list[dict[str, Any]] = []
        for score, chunk, passage in ranked[:limit]:
            normalized = round(score / best, 4) if best else 0.0
            if normalized < self.similarity_threshold and results:
                continue
            if ready and not literals and passage == chunk["text"]:
                passage = _ranked_window(passage, weights)
            result = {
                "id": chunk["id"],
                "doc_id": chunk["doc_id"],
                "document_id": chunk["document_id"],
                "source_path": chunk["source_path"],
                "corpus_generation": self._generation,
                "metadata": dict(chunk["metadata"]),
                "filename": chunk["filename"],
                "title": chunk["title"],
                "text": passage,
                "score": normalized,
                "score_kind": "relative_within_query",
            }
            if self.frozen_documents is not None:
                result["page"] = chunk["page"]
            results.append(result)
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
