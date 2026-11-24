from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.ai_text import router
from modules.ai_text.context_bundle import answer_references
from modules.ai_text.knowledge_continuation import cited_locators
from modules.ai_text.llm_service import LLMService
from tests.test_ai_text.test_citation_verify import _auth, _token


def test_partial_source_indices_exclude_code_and_preserve_review_marker_numbers():
    sources = [{'page': 101}, {'page': 102}, {'page': 103}]
    status, cited = answer_references(sources, '依据 [2 审校补充]，[99]。`字段[1]`\n\n```cli\n接口[3]\n```', 'failed')
    assert status == 'partial'
    assert cited == [{'page': 102, 'reference_index': 2}]


def test_pdf_page_markers_require_the_saved_physical_page():
    edition = {'edition_version': 'edition-1', 'document_id': 'doc-1', 'document_version': 'v1'}
    first = {**edition, 'page': 12, 'source_id': 'first'}
    second = {**edition, 'page': 24, 'source_id': 'second'}
    sources = [first, second]
    answer = '材料给出 [2，PDF 第 24 页]。页码不匹配 [1, PDF第24页]。编号未提供 [3，PDF第12页]。'
    status, cited = answer_references(sources, answer, 'failed')
    assert status == 'partial'
    assert cited == [{**second, 'reference_index': 2}]
    assert cited_locators({'answer': answer, 'sources': cited}) == [second]
    assert cited_locators({'answer': answer, 'sources': sources}) == [second]


@pytest.mark.asyncio
async def test_citation_reads_exact_owned_excerpt_and_checks_current_access(client, test_session_factory, monkeypatch):
    class Provider:
        model = "offline"
        async def stream_parts(self, *args, **kwargs):
            yield {"kind": "content", "text": "回答 [1]"}
    monkeypatch.setattr(router, "_retrieve", AsyncMock(return_value=[{
        "filename": "example.md", "document_id": "doc-1", "text": "回答实际使用的特定片段", "score": 1,
        "book_title": "测试教材", "edition_version": "edition-v1", "page": 12,
    }]))
    monkeypatch.setattr(router.SystemService, "build_llm_provider", AsyncMock(return_value=Provider()))
    monkeypatch.setattr(LLMService, "_log_request", AsyncMock())
    docs = [{"filename": "example.md", "id": "doc-1"}]
    monkeypatch.setattr(router, "_get_knowledge_service", lambda: SimpleNamespace(list_documents=AsyncMock(return_value=docs)))
    token = await _token(test_session_factory)
    response = await client.post('/api/v1/ai/copilot/chat', headers=_auth(token), json={
        "message": "OSPF 是什么", "request_id": "c5-owned-excerpt",
    })
    assert response.status_code == 200, response.text
    source = response.json()["sources"][0]
    params = {"filename": "example.md", "request_id": "c5-owned-excerpt", "source_id": source["source_id"]}
    read = await client.get('/api/v1/ai/copilot/citations/read', params=params, headers=_auth(token))
    assert read.status_code == 200, read.text
    assert read.json()["content"] == source["content"]
    assert read.json()["version"] == source["version"]
    assert read.json()["scope"] == "answer_excerpt"
    assert (read.json()["book_title"], read.json()["page"], read.json()["edition_version"]) == ("测试教材", 12, "edition-v1")
    # Same filename, replaced document identity: do not authorize old excerpts.
    docs[0]["id"] = "replacement-document"
    assert (await client.get('/api/v1/ai/copilot/citations/read', params=params, headers=_auth(token))).status_code == 410
    docs[0]["id"] = "doc-1"
    # Another authenticated owner cannot use a guessed request ID.
    from modules.auth.models import User, UserRole
    from core.security import create_access_token
    async with test_session_factory() as db:
        user = User(username="other-c5", hashed_password="x", role=UserRole.ADMIN)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        other = create_access_token(user.id, user.username, "admin")
    assert (await client.get('/api/v1/ai/copilot/citations/read', params=params, headers=_auth(other))).status_code == 404
    params["source_id"] = "invented"
    assert (await client.get('/api/v1/ai/copilot/citations/read', params=params, headers=_auth(token))).status_code == 404


@pytest.mark.asyncio
async def test_registered_archive_keeps_the_owned_answer_excerpt_without_current_page_claim(client, test_session_factory, monkeypatch):
    class Provider:
        async def stream_parts(self, *args, **kwargs):
            yield {'kind': 'content', 'text': '旧版出处[1]'}

    monkeypatch.setattr(router, '_retrieve', AsyncMock(return_value=[{
        'filename': 'old.md', 'document_id': 'archived-doc', 'document_version': 'archived-version',
        'title': '历史章节', 'text': '生成原回答时采用的已归档片段。',
    }]))
    monkeypatch.setattr(router.SystemService, 'build_llm_provider', AsyncMock(return_value=Provider()))
    monkeypatch.setattr(LLMService, '_log_request', AsyncMock())
    locator = AsyncMock(return_value={'status': 'archive-only', 'related': [], 'message': '历史来源已归档。'})
    list_documents = AsyncMock(side_effect=AssertionError('legacy material has no current document identity'))
    monkeypatch.setattr(router, '_get_knowledge_service', lambda: SimpleNamespace(
        legacy_locator=locator, list_documents=list_documents))
    token = await _token(test_session_factory)
    request_id = 'c5-archived-excerpt'
    response = await client.post('/api/v1/ai/copilot/chat', headers=_auth(token), json={
        'message': 'OSPF 是什么', 'request_id': request_id,
    })
    source = response.json()['sources'][0]
    params = {'filename': 'old.md', 'request_id': request_id, 'source_id': source['source_id']}
    read = await client.get('/api/v1/ai/copilot/citations/read', params=params, headers=_auth(token))
    assert read.status_code == 200, read.text
    assert read.json()['content'] == source['content']
    assert read.json()['legacy_locator']['status'] == 'archive-only'
    assert read.json()['page'] is None and 'document_version' not in read.json()
    locator.assert_awaited_once_with('archived-doc', 'archived-version', None)
    list_documents.assert_not_called()


@pytest.mark.asyncio
async def test_reviewed_note_read_is_generation_snapshot_not_current_annotation(client, test_session_factory, monkeypatch):
    from modules.knowledge import reviewed_source_notes
    from tests.test_reviewed_source_notes import hit, TITLE
    class Provider:
        model = "offline"
        async def stream_parts(self, *args, **kwargs):
            yield {"kind": "content", "text": "RA 目的地址需结合审校说明 [1]"}
    monkeypatch.setattr(router, "_retrieve", AsyncMock(return_value=[hit()]))
    monkeypatch.setattr(router.SystemService, "build_llm_provider", AsyncMock(return_value=Provider()))
    monkeypatch.setattr(LLMService, "_log_request", AsyncMock())
    docs = [{"filename": TITLE, "id": "corpus-example"}]
    monkeypatch.setattr(router, "_get_knowledge_service", lambda: SimpleNamespace(list_documents=AsyncMock(return_value=docs)))
    token = await _token(test_session_factory)
    response = await client.post('/api/v1/ai/copilot/chat', headers=_auth(token), json={
        "message": "RS 和 RA 有何区别？", "request_id": "reviewed-source-snapshot",
    })
    assert response.status_code == 200, response.text
    source = response.json()["sources"][0]
    assert source["reviewed_notes"]
    monkeypatch.setattr(reviewed_source_notes, "_NOTES", [])
    params = {"filename": TITLE, "request_id": "reviewed-source-snapshot", "source_id": source["source_id"]}
    read = await client.get('/api/v1/ai/copilot/citations/read', params=params, headers=_auth(token))
    assert read.status_code == 200, read.text
    assert read.json()["reviewed_notes"] == source["reviewed_notes"]
    assert read.json()["content"] == source["content"]
    docs.clear()
    assert (await client.get('/api/v1/ai/copilot/citations/read', params=params, headers=_auth(token))).status_code == 410
