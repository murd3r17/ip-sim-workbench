"""Copilot 会话 PUT 必须按 user_id 隔离，禁止劫持他人会话。"""
import pytest
from core.security import create_access_token, hash_password


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_user(session_factory, username: str, role_name: str):
    from modules.auth.models import User, UserRole
    from sqlalchemy import select

    role = UserRole.ADMIN if role_name == "admin" else UserRole.USER
    async with session_factory() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                username=username,
                hashed_password=hash_password("test-pass"),
                display_name=username,
                role=role,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        return create_access_token(user.id, user.username, user.role.value)


class TestCopilotSessionIdor:
    @pytest.mark.asyncio
    async def test_put_other_users_session_returns_403(self, client, test_session_factory):
        admin_token = await _make_user(test_session_factory, "admin", "admin")
        user_token = await _make_user(test_session_factory, "idor-user", "user")
        conv_id = "idor-conv-owner-a"

        created = await client.put(
            f"/api/v1/ai/copilot/sessions/{conv_id}",
            json={"title": "A的会话", "messages": [{"role": "user", "content": "secret-from-a"}]},
            headers=auth_header(admin_token),
        )
        assert created.status_code == 200
        assert created.json().get("success") is True

        hijack = await client.put(
            f"/api/v1/ai/copilot/sessions/{conv_id}",
            json={"title": "被劫持", "messages": [{"role": "user", "content": "stolen-by-b"}]},
            headers=auth_header(user_token),
        )
        assert hijack.status_code == 403

        original = await client.get(
            f"/api/v1/ai/copilot/sessions/{conv_id}",
            headers=auth_header(admin_token),
        )
        assert original.status_code == 200
        body = original.json()
        assert body.get("exists") is True
        assert body.get("title") == "A的会话"
        assert (body.get("messages") or [{}])[0].get("content") == "secret-from-a"
