# -*- coding: utf-8 -*-
"""R6 生命周期：重复提交、取消登记身份、历史读取零生成。"""
import asyncio
import pytest

from core.security import create_access_token
from modules.ai_text import router as ai_router
from modules.ai_text.cancel import CancellationRegistry, RequestIdConflict


def test_duplicate_request_conflicts_and_releases():
    reg = CancellationRegistry()
    first = reg.register(1, "req-a")
    with pytest.raises(RequestIdConflict):
        reg.register(1, "req-a")
    assert reg.unregister(1, "req-a", first) is True
    second = reg.register(1, "req-a")  # 完成后可复用
    assert second is not first


def test_old_request_cannot_unregister_new_registration():
    reg = CancellationRegistry()
    old = reg.register(1, "req-b")
    reg.unregister(1, "req-b", old)
    new = reg.register(1, "req-b")
    assert reg.unregister(1, "req-b", old) is False
    assert reg.is_cancelled(1, "req-b") is False
    reg.request_cancel(1, "req-b")
    assert reg.is_cancelled(1, "req-b") is True
    assert new.is_set()


def test_capacity_rejects_without_silent_drop():
    reg = CancellationRegistry(max_entries=1)
    reg.register(1, "one")
    with pytest.raises(Exception):
        reg.register(1, "two")


@pytest.mark.asyncio
async def test_reopen_session_never_builds_llm(client, test_session_factory, monkeypatch):
    from modules.auth.models import User, UserRole
    async with test_session_factory() as db:
        user = User(username="r6-life", hashed_password="x", role=UserRole.ADMIN)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        token = create_access_token(user.id, user.username, "admin")

    def _boom(**kwargs):
        raise AssertionError("重开历史不应构造 LLMService")

    monkeypatch.setattr(ai_router, "LLMService", _boom)
    resp = await client.get("/api/v1/ai/copilot/sessions/not-exist", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json().get("exists") is False
