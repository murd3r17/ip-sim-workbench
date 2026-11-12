from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.knowledge.local_provider import LocalKnowledgeProvider
from modules.knowledge.reader import catalog, read_current, DocumentReadError, sections


@pytest.fixture
def provider(tmp_path):
    corpus, uploads = tmp_path / 'corpus', tmp_path / 'uploads'
    corpus.mkdir(); uploads.mkdir()
    (corpus / 'a.md').write_text('---\ntitle: "原始资料"\nbook: test\nseq: 1\ningest: true\n---\n# 开头\n'
                               + '完整内容。' * 1700 + '\n## 末尾\nEND-MARKER', encoding='utf-8')
    return LocalKnowledgeProvider(corpus_dir=corpus, storage_dir=uploads)


@pytest.mark.asyncio
async def test_full_content_version_and_unknown_metadata(provider):
    docs = await provider.list_documents()
    result = await catalog(provider, docs, None)
    row = result['documents'][0]
    assert row['size'] > 6000 and row['page'] is None and row['created_at'] is None
    assert row['book'] == 'test' and row['section_count'] == 2
    full = await read_current(provider, docs, None, row['id'], version=row['version'])
    assert full['content'].endswith('END-MARKER') and not full['truncated']
    assert full['scope'] == 'current_document' and len(full['version']) == 64
    assert '---' not in full['content']
    (provider.corpus_dir / 'a.md').write_text('# 新版本', encoding='utf-8')
    with pytest.raises(DocumentReadError) as error:
        await read_current(provider, docs, None, row['id'], version=row['version'])
    assert error.value.code == 'document_changed'


@pytest.mark.asyncio
async def test_same_filename_requires_identity_and_rechecks_admission(provider):
    (provider.storage_dir / 'a.md').write_text('# 上传的另一份\nOTHER', encoding='utf-8')
    docs = await provider.list_documents()
    with pytest.raises(DocumentReadError) as error:
        await read_current(provider, docs, None, filename='a.md')
    assert error.value.status == 409
    upload = next(d for d in docs if d['id'].startswith('upload-'))
    assert 'OTHER' in (await read_current(provider, docs, None, upload['id']))['content']
    (provider.storage_dir / 'a.md').write_text('---\ningest: false\n---\n撤回', encoding='utf-8')
    with pytest.raises(DocumentReadError) as error:
        await read_current(provider, docs, None, upload['id'])
    assert error.value.status == 410
    with pytest.raises(DocumentReadError):
        await read_current(provider, docs, None, document_id='../outside.md')


def test_toc_excludes_fenced_headings_and_keeps_source_lines():
    assert sections('# 第一节\n```text\n# 命令输出\n```\n~~~~\n## 示例\n~~~~\n###### 深层章节') == [
        {'id': 'section-1', 'line': 1, 'level': 1, 'title': '第一节'},
        {'id': 'section-8', 'line': 8, 'level': 6, 'title': '深层章节'}]


@pytest.mark.asyncio
async def test_external_unreadable_is_not_empty_or_local_filename_fallback():
    external = SimpleNamespace(name='external')
    result = await catalog(external, [{'id': 'remote', 'filename': 'a.md', 'size': 0}], None)
    assert result['count'] == 1 and result['readable_count'] == 0
    assert result['documents'][0]['size'] is None
    with pytest.raises(DocumentReadError) as error:
        await read_current(external, [{'id': 'remote', 'filename': 'a.md'}], None, 'remote')
    assert error.value.code == 'reader_unavailable'


@pytest.mark.asyncio
async def test_duplicate_ids_and_deleted_source_never_show_old_text(provider):
    docs = await provider.list_documents()
    result = await catalog(provider, [docs[0], docs[0]], None)
    assert result['readable_count'] == 0
    assert all(d['source_status'] == 'document_ambiguous' for d in result['documents'])
    (provider.corpus_dir / 'a.md').unlink()
    with pytest.raises(DocumentReadError):
        await read_current(provider, docs, None, docs[0]['id'])


@pytest.mark.asyncio
@pytest.mark.parametrize('bad_content', [b'oversized-test-source', b'\xff\xfe'])
async def test_oversized_and_non_utf8_source_fail_explicitly(provider, monkeypatch, bad_content):
    from modules.knowledge import reader
    docs = await provider.list_documents()
    monkeypatch.setattr(reader, 'MAX_SOURCE_BYTES', 4)
    (provider.corpus_dir / 'a.md').write_bytes(bad_content)
    with pytest.raises(DocumentReadError) as error:
        await read_current(provider, docs, None, docs[0]['id'])
    assert error.value.code in {'source_too_large', 'source_unavailable'}


@pytest.mark.asyncio
async def test_local_record_cannot_redirect_id_to_an_outside_file(provider, tmp_path):
    docs = await provider.list_documents()
    outside = tmp_path / 'outside.md'; outside.write_text('PRIVATE', encoding='utf-8')
    poisoned = {**docs[0], 'path': str(outside)}
    with pytest.raises(DocumentReadError):
        await provider.read_document(None, poisoned)


@pytest.mark.asyncio
async def test_anythingllm_reads_only_authorized_persistent_upload(tmp_path, monkeypatch):
    import json
    from modules.knowledge.anythingllm import AnythingLLMKnowledgeProvider
    uploads = tmp_path / 'documents' / 'uploads'; uploads.mkdir(parents=True)
    metadata = tmp_path / 'documents' / 'custom-documents'; metadata.mkdir()
    source = uploads / 'doc-001.md'; source.write_text('# 持久原文\n末尾', encoding='utf-8')
    mapping = metadata / 'exact.json'
    mapping.write_text(json.dumps({'url': 'file://' + str(source)}), encoding='utf-8')
    monkeypatch.setenv('KNOWLEDGE_ANYTHINGLLM_STORAGE', str(tmp_path))
    p = AnythingLLMKnowledgeProvider(base_url='http://127.0.0.1:1', api_key='', workspace_slug='test')
    docs = [{'id': 'custom-documents/exact.json', 'filename': 'a.md'}]
    assert (await read_current(p, docs, None, docs[0]['id']))['content'].endswith('末尾')
    # A hotdir / outside path or URL cannot be substituted, even by mapping content.
    for url in ['https://example.com/secret', 'file://' + str(tmp_path / 'outside.md'),
                'file://' + str(tmp_path / 'hotdir' / 'doc-001.md')]:
        mapping.write_text(json.dumps({'url': url}), encoding='utf-8')
        with pytest.raises(DocumentReadError):
            await read_current(p, docs, None, docs[0]['id'])
    with pytest.raises(DocumentReadError):
        await read_current(p, docs, None, 'custom-documents/../exact.json')
    # No workspace membership: do not even attempt local mapping IO.
    with pytest.raises(DocumentReadError) as error:
        await read_current(p, [], None, docs[0]['id'])
    assert error.value.status == 410


@pytest.mark.asyncio
async def test_api_auth_catalog_version_and_provider_failure(client, test_session_factory, monkeypatch, provider):
    from modules.ai_text import router
    from modules.knowledge.service import KnowledgeService, UploadPolicy
    from tests.test_ai_text.test_citation_verify import _auth, _token
    service = KnowledgeService(provider=provider, policy=UploadPolicy([], [], 10, 10))
    monkeypatch.setattr(router, '_get_knowledge_service', lambda: service)
    assert (await client.get('/api/v1/ai/knowledge/catalog')).status_code == 401
    token = await _token(test_session_factory)
    headers = _auth(token)
    cat = await client.get('/api/v1/ai/knowledge/catalog', headers=headers)
    assert cat.status_code == 200
    row = cat.json()['documents'][0]
    read = await client.get('/api/v1/ai/knowledge/read', headers=headers, params={'document_id': row['id'], 'version': row['version']})
    assert read.status_code == 200 and read.json()['content'].endswith('END-MARKER')
    assert (await client.get('/api/v1/ai/knowledge/read', headers=headers)).status_code == 422
    assert (await client.get('/api/v1/ai/knowledge/read', headers=headers, params={'document_id': row['id'], 'version': 'stale'})).status_code == 409
    monkeypatch.setattr(provider, 'list_documents', AsyncMock(side_effect=RuntimeError('unavailable')))
    assert (await client.get('/api/v1/ai/knowledge/catalog', headers=headers)).status_code == 503
