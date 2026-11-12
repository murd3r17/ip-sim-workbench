# -*- coding: utf-8 -*-
"""T15：知识依赖失效时有界降级，不 500、不伪造来源。"""
import pytest

from core.security import create_access_token
from modules.ai_text import router as ai_router
from modules.auth.models import User, UserRole


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class _FakeService:
    async def copilot_chat_stream(self, **kwargs):
        yield {"type": "token", "text": "当前知识库不可用，我无法给出教材引用；可先按设备实时数据排查。"}
        yield {"type": "done", "status": "degraded", "trace": {"model_calls": 1, "tool_calls": 0}}


@pytest.mark.asyncio
async def test_knowledge_failure_degrades_without_500(client, test_session_factory, monkeypatch):
    async with test_session_factory() as db:
        user = User(username="t15-user", hashed_password="x", role=UserRole.ADMIN)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        token = create_access_token(user.id, user.username, "admin")

    def _broken():
        raise RuntimeError("anythingllm down")

    async def _fake_service(db, user):
        return _FakeService()

    monkeypatch.setattr(ai_router, "_get_knowledge_service", _broken)
    monkeypatch.setattr(ai_router.lexical_index, "search", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("lexical down")))
    monkeypatch.setattr(ai_router, "_get_service", _fake_service)

    resp = await client.post(
        "/api/v1/ai/copilot/chat",
        json={"message": "OSPF 邻居起不来怎么办？", "history": [], "context": {}, "top_k": 5},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["sources"] == []
