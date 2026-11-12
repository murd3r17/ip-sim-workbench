"""Source identity and citation coordinates must survive relocation and duplicate names."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("corpus_tools", ROOT / "scripts/final_delegation/corpus_tools.py")
corpus_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(corpus_tools)


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_same_basename_is_matched_by_book_relative_path(tmp_path):
    corpus, source = tmp_path / "corpus", tmp_path / "source"
    for book in ("BookA", "BookB"):
        for root in (corpus, source):
            write(root, f"{book}/00-index.md", f"# {book}")
    result = corpus_tools.build_manifest(corpus, source)
    assert result["source_content_same"] == 2
    assert result["source_content_diff"] == 0
    assert {e["source_rel"] for e in result["entries"]} == {"BookA/00-index.md", "BookB/00-index.md"}


def test_missing_source_never_borrows_another_books_document(tmp_path):
    corpus, source = tmp_path / "corpus", tmp_path / "source"
    write(corpus, "BookA/chapter.md", "# identical words")
    write(source, "BookB/chapter.md", "# identical words")
    entry = corpus_tools.build_manifest(corpus, source)["entries"][0]
    assert entry["source"] is None
    assert entry["source_rel"] is None


def test_candidate_coordinates_are_raw_file_lines(tmp_path):
    raw = '---\ntitle: "OSPF"\ningest: true\n---\n\nOSPF area identifiers must match.\n'
    path = write(tmp_path, "book/chapter.md", raw)
    manifest = corpus_tools.build_manifest(tmp_path, None)
    result = corpus_tools.basis([{"id": "q1", "facts": ["OSPF area identifiers must match"]}], manifest, tmp_path)
    candidate = result["facts"][0]["candidates"][0]
    lines = path.read_text(encoding="utf-8").splitlines()
    excerpt = "\n".join(lines[candidate["line_start"] - 1:candidate["line_end"]])
    assert candidate["snippet"] == excerpt[:500]
    assert "OSPF area identifiers must match." in excerpt
    assert "ingest:" not in excerpt
    assert result["facts"][0]["semantic_status"] == "not_reviewed"


def test_basis_rejects_manifest_content_drift(tmp_path):
    path = write(tmp_path, "chapter.md", "Original OSPF fact")
    manifest = corpus_tools.build_manifest(tmp_path, None)
    path.write_text("Different OSPF fact", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        corpus_tools.basis([], manifest, tmp_path)


def test_basis_rejects_outside_root_reference(tmp_path):
    outside = write(tmp_path, "outside.md", "OSPF fact")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    manifest = {"entries": [{"path": "../outside.md", "sha256": hashlib.sha256(outside.read_bytes()).hexdigest()}]}
    with pytest.raises(ValueError, match="outside"):
        corpus_tools.basis([], manifest, corpus)
