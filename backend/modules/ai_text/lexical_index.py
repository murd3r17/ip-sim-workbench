# -*- coding: utf-8 -*-
"""C-R2 5.4.2：独立词法召回（中文 bigram + 英文/缩写/命令词）。

与向量召回并行，归一化后融合；不依赖 AnythingLLM 的返回顺序。
只读本地语料文件，不调用外部服务。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

CORPUS_ROOT = Path(r"D:\work\ip-sim-workbench\knowledge\corpus")
CHUNK_CHARS = 900
_INDEX: list[dict] | None = None
_DIGEST: str | None = None
_DF: Counter = Counter()
_N_DOCS = 0
_SIG: tuple | None = None


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for run in re.findall(r"[\u4e00-\u9fff]+", text or ""):
        out.extend(run[i:i + 2] for i in range(len(run) - 1))
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-/\.]*", text or ""):
        out.append(w.lower())
    return out


def _chunks(text: str) -> list[str]:
    parts = re.split(r"(?m)^#{1,3}\s+", text or "")
    chunks: list[str] = []
    for part in parts:
        part = part.strip()
        while len(part) > CHUNK_CHARS:
            cut = part.rfind("\n", 0, CHUNK_CHARS)
            cut = cut if cut > 200 else CHUNK_CHARS
            chunks.append(part[:cut])
            part = part[cut:]
        if part:
            chunks.append(part)
    return chunks


def build_index(root: Path | None = None) -> int:
    global _INDEX, _DF, _N_DOCS
    root = root or CORPUS_ROOT
    docs: list[dict] = []
    df: Counter = Counter()
    for path in sorted((root).rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        title = path.stem
        for i, chunk in enumerate(_chunks(text)):
            toks = _tokens(chunk)
            if not toks:
                continue
            tf = Counter(toks)
            docs.append({
                "filename": path.name,
                "title": title,
                "chunk": i,
                "content": chunk,
                "tf": tf,
                "len": len(toks),
            })
            df.update(set(toks))
    _INDEX = docs
    _DF = df
    _N_DOCS = max(1, len(docs))
    return len(docs)


def _ensure(root: Path | None = None) -> list[dict]:
    global _INDEX, _SIG
    root = root or CORPUS_ROOT
    sig = _signature(root)
    if _INDEX is None or _SIG != sig:
        build_index(root)
        _SIG = sig
    return _INDEX or []


def search(query: str, top_k: int = 10, root: Path | None = None) -> list[dict]:
    docs = _ensure(root)
    q = _tokens(query)
    if not docs or not q:
        return []
    avg = sum(d["len"] for d in docs) / len(docs)
    k1, b = 1.4, 0.75
    scored = []
    for doc in docs:
        score = 0.0
        for term in set(q):
            tf = doc["tf"].get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (_N_DOCS - _DF[term] + 0.5) / (_DF[term] + 0.5))
            denom = tf + k1 * (1 - b + b * doc["len"] / avg)
            score += idf * tf * (k1 + 1) / denom
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, doc in scored[:top_k]:
        out.append({
            "filename": doc["filename"],
            "title": doc["title"],
            "chunk": doc["chunk"],
            "score": round(score, 6),
            "content": doc["content"],
            "retriever": "lexical",
        })
    return out


def fuse(vector_hits: list[dict] | None, lexical_hits: list[dict] | None, top_k: int, vector_weight: float = 0.8) -> list[dict]:
    """按来源归一化后融合去重；同文件名+同片段只保留一条。"""
    v = list(vector_hits or [])
    l = list(lexical_hits or [])
    vmax = max((float(h.get("score") or 0) for h in v), default=1.0) or 1.0
    lmax = max((float(h.get("score") or 0) for h in l), default=1.0) or 1.0
    merged: dict[tuple, dict] = {}
    for h in v:
        key = (h.get("filename"), (h.get("content") or "")[:80])
        item = dict(h)
        item["fused"] = vector_weight * float(h.get("score") or 0) / vmax
        item["retriever"] = "vector"
        merged[key] = item
    for h in l:
        key = (h.get("filename"), (h.get("content") or "")[:80])
        add = (1 - vector_weight) * float(h.get("score") or 0) / lmax
        if add <= 0:
            continue
        if key in merged:
            merged[key]["fused"] += add
            merged[key]["retriever"] = "hybrid"
        else:
            item = dict(h)
            item["fused"] = add
            item["retriever"] = "lexical"
            merged[key] = item
    ordered = sorted(merged.values(), key=lambda x: x.get("fused", 0), reverse=True)
    return ordered[:top_k]


def _signature(root: Path) -> tuple:
    files = sorted(root.rglob("*.md"))
    total = sum(p.stat().st_size for p in files)
    latest = max((p.stat().st_mtime_ns for p in files), default=0)
    return (len(files), total, latest)


def corpus_version(root: Path | None = None) -> str:
    """语料版本：每次按文件状态计算，变更/删除立即反映。"""
    global _DIGEST
    root = root or CORPUS_ROOT
    import hashlib
    h = hashlib.sha256()
    for p in sorted(root.rglob("*.md")):
        st = p.stat()
        h.update(f"{p.relative_to(root).as_posix()}|{st.st_size}|{st.st_mtime_ns}".encode("utf-8"))
    _DIGEST = h.hexdigest()[:12]
    return _DIGEST


def find_document(filename: str, root: Path | None = None) -> dict | None:
    """按文件名在语料中定位；同名多份时返回第一条并标明歧义。"""
    root = root or CORPUS_ROOT
    matches = [p for p in sorted(root.rglob("*.md")) if p.name == filename]
    if not matches:
        return None
    p = matches[0]
    text = p.read_text(encoding="utf-8", errors="replace")
    title = p.stem
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            front = text[3:end]
            m = re.search(r"(?m)^title:\s*\"?([^\"\n]+)", front)
            if m:
                title = m.group(1).strip()
            text = text[end + 4:]
    return {
        "filename": p.name,
        "title": title,
        "path": p.relative_to(root).as_posix(),
        "sha256": __import__("hashlib").sha256(p.read_bytes()).hexdigest()[:12],
        "content": text.lstrip()[:6000],
        "ambiguous": len(matches) > 1,
        "corpus_version": corpus_version(root),
    }


def enrich_with_neighbors(hits: list[dict] | None, max_chars: int = 2600) -> list[dict]:
    """按需拼接同文档相邻片段，提升 Top5 论断支撑；不改文档数/K。"""
    docs = _ensure()
    by_key: dict[tuple, dict] = {}
    for d in docs:
        by_key[(d["filename"], d["chunk"])] = d
    out = []
    for h in hits or []:
        item = dict(h)
        filename = item.get("filename") or (str(item.get("title") or "") + ("" if str(item.get("title") or "").endswith(".md") else ".md"))
        chunk = item.get("chunk")
        if chunk is None and filename:
            prefix = re.sub(r"\s+", "", (item.get("content") or ""))[:80]
            best: tuple[float, int] | None = None
            for (fn, idx), d in by_key.items():
                if fn != filename:
                    continue
                body = re.sub(r"\s+", "", d["content"])
                if body[:80] == prefix:
                    chunk = idx
                    break
                # 模糊匹配：取前 200 字二元组重合，适配清洗后的向量片段
                a, b = set(re.findall(r"[\u4e00-\u9fff]{2}|[a-z0-9]{2,}", (item.get("content") or "")[:300].lower())), \
                       set(re.findall(r"[\u4e00-\u9fff]{2}|[a-z0-9]{2,}", d["content"][:300].lower()))
                score = len(a & b) / max(1, len(a | b))
                if best is None or score > best[0]:
                    best = (score, idx)
            if chunk is None and best and best[0] >= 0.55:
                chunk = best[1]
        if filename and chunk is not None:
            parts = []
            for idx in (chunk - 1, chunk, chunk + 1):
                d = by_key.get((filename, idx))
                if d:
                    parts.append(d["content"])
            if parts:
                item["content"] = "\n...\n".join(parts)[:max_chars]
        out.append(item)
    return out
