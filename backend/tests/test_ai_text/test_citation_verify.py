# -*- coding: utf-8 -*-
"""T14：引用打开前校验；撤权/删除返回 410，不展示旧片段。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.security import create_access_token
from modules.ai_text import router as ai_router
from modules.auth.models import User, UserRole


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _token(factory) -> str:
    async with factory() as db:
        user = User(username="t14-user", hashed_password="x", role=UserRole.ADMIN)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return create_access_token(user.id, user.username, "admin")


@pytest.mark.asyncio
async def test_existing_citation_is_available(client, test_session_factory, monkeypatch):
    token = await _token(test_session_factory)
    fake = SimpleNamespace(list_documents=lambda: _docs(["a.md"]))
    async def _svc():
        return fake
    monkeypatch.setattr(ai_router, "_get_knowledge_service", lambda: fake)
    resp = await client.get("/api/v1/ai/copilot/citations/verify?filename=a.md", headers=_auth(token))
    assert resp.status_code == 200 and resp.json()["available"] is True


@pytest.mark.asyncio
async def test_revoked_citation_returns_410(client, test_session_factory, monkeypatch):
    token = await _token(test_session_factory)
    fake = SimpleNamespace(list_documents=lambda: _docs(["b.md"]))
    monkeypatch.setattr(ai_router, "_get_knowledge_service", lambda: fake)
    resp = await client.get("/api/v1/ai/copilot/citations/verify?filename=a.md", headers=_auth(token))
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "citation_revoked"


async def _docs(names):
    return [{"filename": n} for n in names]


@pytest.mark.asyncio
async def test_read_citation_returns_server_text(client, test_session_factory, monkeypatch):
    token = await _token(test_session_factory)
    # 用真实语料里的任一文件（manifest 第一项）
    import json
    from pathlib import Path
    manifest = Path(__file__).resolve().parents[1] / "fixtures" / "corpus-manifest.json"
    name = json.loads(manifest.read_text(encoding="utf-8"))["files"][0]["path"].split("/")[-1]
    from modules.knowledge.local_provider import LocalKnowledgeProvider
    from modules.knowledge.service import KnowledgeService, UploadPolicy
    fake = KnowledgeService(provider=LocalKnowledgeProvider(), policy=UploadPolicy([], [], 10, 10))
    from modules.ai_text import router as _router
    monkeypatch.setattr(_router, "_get_knowledge_service", lambda: fake)
    resp = await client.get(f"/api/v1/ai/copilot/citations/read?filename={name}", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == name and body["content"] and body["version"]


@pytest.mark.asyncio
async def test_read_missing_citation_returns_410(client, test_session_factory, monkeypatch):
    token = await _token(test_session_factory)
    from modules.ai_text import router as _router
    monkeypatch.setattr(_router, "_get_knowledge_service",
                        lambda: SimpleNamespace(list_documents=AsyncMock(return_value=[])))
    resp = await client.get("/api/v1/ai/copilot/citations/read?filename=no-such-file-xyz.md", headers=_auth(token))
    assert resp.status_code == 410
