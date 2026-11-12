"""Versioned current-document reading, separate from immutable answer excerpts.

Only provider-authorized document IDs reach a provider's bounded local reader.
No user-supplied path or URL is opened and no filename is mapped across providers.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_SOURCE_BYTES = 10 * 1024 * 1024


class DocumentReadError(Exception):
    def __init__(self, code: str, message: str, status: int = 424):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def read_bounded(path: Path, root: Path) -> tuple[bytes, str]:
    path = path.resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise DocumentReadError('source_unavailable', '持久源文件不可读取，请管理员核对同步。')
    if path.suffix.lower() not in {'.md', '.txt'}:
        raise DocumentReadError('format_unavailable', '此源格式暂不支持全文阅读，可继续查看检索片段。')
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            raise DocumentReadError('source_too_large', '源文件超过10 MB阅读限制，未以片段冒充全文。')
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        raw.decode('utf-8-sig')
        return raw, modified
    except (OSError, UnicodeError) as exc:
        raise DocumentReadError('source_unavailable', '源文件不可读取或不是UTF-8文本，请管理员核对同步。') from exc


def sections(content: str) -> list[dict[str, Any]]:
    """One-based source-body lines. Code-fenced '#' is not a chapter heading."""
    result, fence = [], None
    for number, line in enumerate(content.splitlines(), 1):
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        heading = re.match(r'^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$', line)
        if heading:
            result.append({'id': f'section-{number}', 'line': number,
                           'level': len(heading[1]), 'title': heading[2]})
    return result


def document_payload(document: dict, raw: bytes, modified_at: str | None,
                     source_kind: str) -> dict:
    # Reuse the exact corpus frontmatter contract; never rewrite the source text.
    from .local_provider import _frontmatter
    metadata, body = _frontmatter(raw.decode('utf-8-sig'))
    metadata = {**(document.get('metadata') or {}), **metadata}
    if str(metadata.get('ingest', 'true')).lower() != 'true':
        raise DocumentReadError('document_revoked', '资料已撤回，不再展示正文。', 410)
    return {
        'id': str(document['id']), 'filename': document.get('filename') or document.get('title'),
        'title': metadata.get('title') or document.get('title') or document.get('filename'),
        'book': metadata.get('book') or '', 'book_title': metadata.get('book_title') or '',
        'doc_id': metadata.get('doc_id') or document.get('doc_id'),
        'seq': metadata.get('seq'), 'source_pdf': metadata.get('source_pdf'),
        'source_path': document.get('source_path'), 'source_kind': source_kind,
        'version': hashlib.sha256(raw).hexdigest(), 'size': len(raw), 'page': None,
        'modified_at': modified_at, 'created_at': None,
        'metadata': {k: metadata.get(k) for k in ('track', 'level', 'doc_type', 'quality', 'language', 'vendor')},
        'scope': 'current_document', 'content': body, 'sections': sections(body), 'truncated': False,
        'message': '当前持久源文件全文；与原回答保存的片段版本分别记录。页码未建立可靠映射。',
    }


async def read_current(provider, documents: list[dict], workspace: str | None,
                       document_id: str | None = None, filename: str | None = None,
                       version: str | None = None) -> dict:
    matches = [d for d in documents if str(d.get('id')) == document_id] if document_id else [
        d for d in documents if (d.get('filename') or d.get('title')) == filename]
    if not matches:
        raise DocumentReadError('document_revoked', '资料不存在或已撤回，请刷新目录。', 410)
    if len(matches) != 1:
        raise DocumentReadError('document_ambiguous', '同名资料不唯一，请从完整目录选择具体文档。', 409)
    method = getattr(provider, 'read_document', None)
    result = await method(workspace, matches[0]) if method else None
    if result is None:
        raise DocumentReadError('reader_unavailable', '当前知识服务未提供可核验的持久全文，请管理员配置源文件阅读；仍可查看检索片段。')
    if version and result['version'] != version:
        raise DocumentReadError('document_changed', '资料版本已更新，请刷新目录后重新打开。', 409)
    return result


async def catalog(provider, documents: list[dict], workspace: str | None) -> dict:
    rows = []
    for document in documents:
        item = {k: document.get(k) for k in ('id', 'filename', 'title', 'status')}
        try:
            read = await read_current(provider, documents, workspace, str(document['id']))
            item.update({k: v for k, v in read.items() if k not in {'content', 'sections', 'message', 'scope'}})
            item.update(readable=True, section_count=len(read['sections']), source_status='persistent')
        except DocumentReadError as exc:
            item.update(readable=False, size=None, page=None, created_at=None, modified_at=None,
                        version=None, book='', book_title='', source_status=exc.code, message=exc.message)
        rows.append(item)
    rows.sort(key=lambda d: (str(d.get('book') or ''), str(d.get('seq') or '').zfill(5), str(d.get('filename') or '')))
    digest = hashlib.sha256(repr([(d.get('id'), d.get('version'), d.get('source_status')) for d in rows]).encode()).hexdigest()
    return {'provider': provider.name, 'documents': rows, 'count': len(rows),
            'readable_count': sum(d['readable'] for d in rows), 'catalog_version': digest,
            'checked_at': datetime.now(timezone.utc).isoformat()}
