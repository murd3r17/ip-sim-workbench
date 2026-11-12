#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L3：只读语料 manifest + 知识题原文依据候选（不接向量库、不写语料）。

  python scripts/final_delegation/corpus_tools.py manifest --out reference-data/corpus-manifest.json
  python scripts/final_delegation/corpus_tools.py basis --questions reference-data/knowledge-questions.json \
      --manifest reference-data/corpus-manifest.json --out reference-data/knowledge-basis.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = ROOT / "knowledge" / "corpus" / "huawei-ip"
DEFAULT_SOURCE = ROOT.parent / "ip-sim-source" / "md"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def parse_front(text: str) -> tuple[dict, str]:
    meta = {}
    body = text
    lines = text.splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
        if end is not None:
            for line in lines[1:end]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip('"')
            body = "".join(lines[end + 1:])
    return meta, body


def build_manifest(corpus: Path, source: Path | None) -> dict:
    corpus = corpus.resolve()
    source = source.resolve() if source else None
    files = sorted(corpus.rglob("*.md"))
    source_files = sorted(source.rglob("*")) if source and source.exists() else []
    entries = []
    names: dict[str, int] = {}
    hashes: dict[str, int] = {}
    for p in files:
        if not p.resolve().is_relative_to(corpus):
            raise ValueError("Corpus file resolves outside corpus root")
        raw = p.read_text(encoding="utf-8")
        meta, body = parse_front(raw)
        rel = p.relative_to(corpus).as_posix()
        names[p.name] = names.get(p.name, 0) + 1
        h = sha256(p)
        hashes[h] = hashes.get(h, 0) + 1
        src = (source / rel) if source else None
        if src and not src.resolve().is_relative_to(source):
            raise ValueError("Source file resolves outside source root")
        src = src if src and src.is_file() else None
        is_index = p.name.casefold() in {"00-index.md", "00-corpus-index.md"}
        entries.append({
            "path": rel, "filename": p.name, "bytes": p.stat().st_size,
            "encoding": "utf-8", "sha256": h,
            "book": meta.get("book") or meta.get("book_title") or "",
            "chapter": meta.get("title") or "",
            "doc_type": meta.get("doc_type") or "",
            "source": src.as_posix() if src else None,
            "source_rel": src.relative_to(source).as_posix() if src else None,
            "source_sha256": sha256(src) if src else None,
            "source_pdf": meta.get("source_pdf") or "",
            "ingest": not is_index and (meta.get("ingest") or "").lower() == "true",
            "kind": "index" if is_index else "body",
            "body_start_line": raw[:len(raw) - len(body)].count("\n") + 1,
            "body_chars": len(body),
        })
    same = sum(1 for e in entries if e["source_sha256"] and e["source_sha256"] == e["sha256"])
    diff = sum(1 for e in entries if e["source_sha256"] and e["source_sha256"] != e["sha256"])
    source_names = {p.relative_to(source).as_posix() for p in source_files if p.is_file() and p.suffix.lower() == ".md"}
    corpus_names = {p.relative_to(corpus).as_posix() for p in files}
    return {
        "schema": 2, "corpus_root": str(corpus), "count": len(entries),
        "body_count": sum(e["kind"] == "body" for e in entries),
        "index_count": sum(e["kind"] == "index" for e in entries),
        "ingest_count": sum(e["ingest"] for e in entries),
        "unique_filenames": len(names), "duplicate_filenames": {k: v for k, v in names.items() if v > 1},
        "duplicate_hashes": {k: v for k, v in hashes.items() if v > 1},
        "entries": entries,
        "source_root": str(source) if source else None,
        "source_present": bool(source and source.exists()),
        "target_only": sorted(corpus_names - source_names),
        "source_only_count": len(source_names - corpus_names),
        "source_missing_count": len([e for e in entries if not e["source"]]),
        "source_content_same": same, "source_content_diff": diff,
    }


def toks(text: str) -> set[str]:
    text = (text or "").lower()
    out = set(re.findall(r"[a-z0-9]{2,}", text))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        for i in range(len(run) - 1):
            out.add(run[i:i + 2])
    return out


def basis(questions: list[dict], manifest: dict, corpus: Path) -> dict:
    corpus = corpus.resolve()
    docs = []
    for e in manifest["entries"]:
        p = (corpus / e["path"]).resolve()
        if not p.is_relative_to(corpus):
            raise ValueError("Manifest path resolves outside corpus root")
        if not p.exists():
            raise ValueError(f"Manifest document is missing: {e['path']}")
        if sha256(p) != e.get("sha256"):
            raise ValueError(f"Manifest hash mismatch: {e['path']}")
        text = p.read_text(encoding="utf-8")
        _, body = parse_front(text)
        if not e.get("ingest", True):
            continue
        offset = text[:len(text) - len(body)].count("\n")
        lines = body.splitlines()
        docs.append((e, lines, offset))
    results = []
    for q in questions:
        for idx, fact in enumerate(q.get("facts") or []):
            ft = toks(fact)
            candidates = []
            for e, lines, offset in docs:
                best = (0.0, 0, 0, "")
                for i in range(0, len(lines), 12):
                    block = "\n".join(lines[i:i + 18])
                    bt = toks(block)
                    score = len(ft & bt) / max(1, len(ft))
                    if score > best[0]:
                        best = (score, offset + i + 1, offset + min(i + 18, len(lines)), block[:500])
                if best[0] > 0:
                    candidates.append((best[0], e, best[1], best[2], best[3]))
            candidates.sort(key=lambda x: x[0], reverse=True)
            top = candidates[:3]
            if not top:
                state = "not_found"
            elif len(top) > 1 and top[1][0] >= top[0][0] - 0.05 and top[1][1]["path"] != top[0][1]["path"]:
                state = "ambiguous"
            elif top[0][0] >= 0.6:
                state = "candidate"
            else:
                state = "partial"
            results.append({
                "question_id": q["id"], "question": q.get("question", ""),
                "fact_id": idx, "fact": fact, "status": state,
                "semantic_status": "not_reviewed",
                "candidates": [{"score": round(c[0], 3), "path": c[1]["path"], "chapter": c[1]["chapter"],
                                "line_start": c[2], "line_end": c[3], "coordinate_system": "raw_file_1_based_inclusive", "sha256": c[1]["sha256"],
                                "snippet": c[4]} for c in top],
            })
    return {"note": "agent 整理的候选依据，不是人类专家 gold；不改变原题/判据", "count": len(results), "facts": results}


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("manifest")
    m.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    m.add_argument("--source", default=str(DEFAULT_SOURCE))
    m.add_argument("--out", required=True)
    b = sub.add_parser("basis")
    b.add_argument("--questions", required=True)
    b.add_argument("--manifest", required=True)
    b.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    b.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.cmd == "manifest":
        data = build_manifest(Path(args.corpus), Path(args.source))
    else:
        q = json.loads(Path(args.questions).read_text(encoding="utf-8"))
        man = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        data = basis(q if isinstance(q, list) else q.get("questions", []), man, Path(args.corpus))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in data.items() if not isinstance(v, list)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
