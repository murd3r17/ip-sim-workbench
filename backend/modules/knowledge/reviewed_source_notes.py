"""Versioned editorial notes for exact, independently reviewed source claims.

No network lookup or caller-supplied annotations. Original excerpts/hashes stay
unchanged; the bounded generation snapshot separately carries these notes.
"""
import hashlib
import json
from pathlib import Path


_NOTES = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))


def notes_for_excerpt(filename: str, content: str) -> list[dict]:
    compact = ''.join(content.split())
    notes = []
    for record in _NOTES:
        matches = record['match'] if isinstance(record['match'], list) else [record['match']]
        if record['filename'] == filename and any(''.join(match.split()) in compact for match in matches):
            note = {k: record[k] for k in ('id', 'title', 'content', 'reference', 'url', 'reviewed_at')}
            note['version'] = hashlib.sha256(json.dumps(note, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            notes.append(note)
    return notes


def notes_prompt(notes: list[dict]) -> str:
    if not notes:
        return ''
    return ('\n\n【独立审校说明，非教材原文】\n'
            '以下说明针对上述原文的具体表述；有冲突时按所列标准限定回答，并明确这是审校补充。\n'
            + '\n'.join(f"{n['title']}：{n['content']}\n依据：{n['reference']} {n['url']}" for n in notes))
