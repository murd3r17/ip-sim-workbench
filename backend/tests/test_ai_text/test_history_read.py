# -*- coding: utf-8 -*-
"""T16：重开历史/列表只读，不构造模型服务、不产生生成。"""
import pytest

from core.security import create_access_token
from modules.ai_text import router as ai_router
from modules.auth.models import User, UserRole


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_session_list_never_builds_llm(client, test_session_factory, monkeypatch):
    async with test_session_factory() as db:
        user = User(username="t16-user", hashed_password="x", role=UserRole.ADMIN)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        token = create_access_token(user.id, user.username, "admin")

    def _boom(**kwargs):
        raise AssertionError("历史列表不应构造 LLMService")

    monkeypatch.setattr(ai_router, "LLMService", _boom)
    resp = await client.get("/api/v1/ai/copilot/sessions", headers=_auth(token))
    assert resp.status_code == 200
