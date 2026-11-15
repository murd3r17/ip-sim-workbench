"""Versioned editorial notes for exact, independently reviewed source claims.

No network lookup or caller-supplied annotations. Original excerpts/hashes stay
unchanged; the bounded generation snapshot separately carries these notes.
"""
import hashlib
import json
import re
from pathlib import Path


_NOTES = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))


def matching_learning_notes(question: str) -> list[dict]:
    compact = "".join(question.lower().split())
    intent = re.sub(r"[。？！?!，,]", "", compact)

    def includes(terms: list[str]) -> bool:
        return any("".join(term.lower().split()) in compact for term in terms)

    return [note for note in _NOTES
            if includes(note.get("query_terms", []))
            and not includes(note.get("unless_query_terms", []))
            and (not note.get("query_pattern") or re.fullmatch(note["query_pattern"], intent))]


def applies_to_edition_excerpt(note: dict, filename: str, content: str, document_version: str | None) -> bool:
    """Keep the same note bound to the reviewed chapter and physical page."""
    return bool(note.get("source_page") and note["document_version"] == document_version
                and note["filename"] == filename and any(
        str(note["source_page"]) in marker.split("、")
        for marker in re.findall(r"PDF 第 ([0-9、]+) 页", content)
    ))


def notes_for_excerpt(filename: str, content: str, document_version: str | None = None) -> list[dict]:
    compact = ''.join(content.split())
    notes = []
    for record in _NOTES:
        matches = record['match'] if isinstance(record['match'], list) else [record['match']]
        applies = (applies_to_edition_excerpt(record, filename, content, document_version)
                   if record.get('source_page') else record['filename'] == filename
                   and any(''.join(match.split()) in compact for match in matches))
        if applies:
            note = {k: record[k] for k in ('id', 'title', 'content', 'reference', 'url', 'reviewed_at')}
            note['version'] = hashlib.sha256(json.dumps(note, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            notes.append(note)
    return notes


def notes_prompt(notes: list[dict]) -> str:
    if not notes:
        return ''
    return ('\n\n【独立审校说明，非教材原文】\n'
            '以下说明针对上述原文的具体表述；有冲突时按所列标准限定回答，并明确这是审校补充。\n'
            + '\n'.join(
                f"{n['title']}：{n['content']}\n依据：{n['reference']}" + (f" {n['url']}" if n['url'] else "")
                for n in notes
            ))
