from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.ai_text import router
from modules.ai_text.llm_service import LLMService
from tests.test_ai_text.test_citation_verify import _auth, _token


@pytest.mark.asyncio
async def test_citation_reads_exact_owned_excerpt_and_checks_current_access(client, test_session_factory, monkeypatch):
    class Provider:
        model = "offline"
        async def stream_parts(self, *args, **kwargs):
            yield {"kind": "content", "text": "回答 [1]"}
    monkeypatch.setattr(router, "_retrieve", AsyncMock(return_value=[{
        "filename": "example.md", "document_id": "doc-1", "text": "回答实际使用的特定片段", "score": 1,
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
