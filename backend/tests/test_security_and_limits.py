"""安全边界与限流回归测试（2026-09-09 审计 P0-22/23、P1-01/03/04）。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.rate_limiter import _rate_key_path
from core.security import BCRYPT_MAX_BYTES, CredentialEncryptor, hash_password, verify_password
from tests.test_api_full import _setup_admin_user, auth_header


class TestPasswordLength:
    """P0-23：bcrypt 只取前 72 字节，超长口令此前"哈希成功但永远验不过"。"""

    def test_normal_password_roundtrip(self):
        hashed = hash_password("Str0ngPass")
        assert verify_password("Str0ngPass", hashed) is True
        assert verify_password("wrong", hashed) is False

    def test_over_72_bytes_rejected_at_hash_time(self):
        with pytest.raises(ValueError) as exc:
            hash_password("a" * (BCRYPT_MAX_BYTES + 1))
        assert "72" in str(exc.value)

    def test_over_72_bytes_never_verifies(self):
        # 不该抛异常到调用方，只应判为不匹配
        assert verify_password("a" * 100, hash_password("a" * 10)) is False

    def test_multibyte_password_counts_bytes(self):
        # 25 个汉字 = 75 字节 > 72
        with pytest.raises(ValueError):
            hash_password("密" * 25)


class TestCredentialEncryptor:
    """P0-22：FERNET_KEY 缺失时此前直接返回明文（设备口令明文入库）。"""

    def _fresh(self, fernet_key: str):
        encryptor = CredentialEncryptor.__new__(CredentialEncryptor)
        encryptor._initialized = False
        encryptor._fernet = None
        from cryptography.fernet import Fernet
        encryptor._fernet = Fernet(fernet_key.encode()) if fernet_key else None
        encryptor._initialized = True
        return encryptor

    def test_encrypt_refuses_without_key(self):
        encryptor = self._fresh("")
        assert encryptor.configured is False
        with pytest.raises(RuntimeError) as exc:
            encryptor.encrypt("device-password")
        assert "FERNET_KEY" in str(exc.value)

    def test_decrypt_keeps_legacy_plaintext(self):
        encryptor = self._fresh("")
        assert encryptor.decrypt("legacy-plain") == "legacy-plain"

    def test_roundtrip_with_key(self):
        from cryptography.fernet import Fernet
        encryptor = self._fresh(Fernet.generate_key().decode())
        token = encryptor.encrypt("device-password")
        assert token != "device-password"
        assert encryptor.decrypt(token) == "device-password"

    def test_decrypt_with_wrong_key_raises_readable_error(self):
        from cryptography.fernet import Fernet
        encryptor = self._fresh(Fernet.generate_key().decode())
        token = encryptor.encrypt("device-password")
        other = self._fresh(Fernet.generate_key().decode())
        with pytest.raises(RuntimeError) as exc:
            other.decrypt(token)
        assert "FERNET_KEY" in str(exc.value)


class TestRateLimitKey:
    """P1-01：限流键含具体路径 → 遍历 task_id 即可绕过 30/分。"""

    def test_uses_route_template_not_raw_path(self):
        request = SimpleNamespace(
            scope={"route": SimpleNamespace(path="/api/v1/deploy/tasks/{task_id}/execute")},
            url=SimpleNamespace(path="/api/v1/deploy/tasks/42/execute"),
        )
        assert _rate_key_path(request) == "/api/v1/deploy/tasks/{task_id}/execute"

    def test_falls_back_to_raw_path_without_route(self):
        request = SimpleNamespace(scope={}, url=SimpleNamespace(path="/api/v1/x"))
        assert _rate_key_path(request) == "/api/v1/x"


class TestMissingTokenStatus:
    """P1-03：HTTPBearer 默认缺凭证返回 403，语义应为 401。"""

    @pytest.mark.asyncio
    async def test_missing_token_is_401(self, client, test_session_factory):
        await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/devices")
        assert resp.status_code == 401, resp.text

    @pytest.mark.asyncio
    async def test_invalid_token_is_401(self, client, test_session_factory):
        resp = await client.get("/api/v1/devices", headers=auth_header("not-a-jwt"))
        assert resp.status_code == 401, resp.text


class _FakeProvider:
    """最小可用的 LLM provider：无工具调用 + 流式输出一段文本。"""

    name = "FakeProvider"

    async def chat_completion(self, messages, tools=None, tool_choice="auto", max_tokens=None, temperature=None):
        return {"role": "assistant", "content": "", "tool_calls": None}

    async def stream_parts(self, prompt, system=None, max_tokens=None, temperature=None):
        yield {"kind": "content", "text": "你好"}

    async def stream(self, prompt, system=None, max_tokens=None, temperature=None):
        yield "你好"

    async def health_check(self):
        return True


class TestCopilotStreamShortSessions:
    """P1-04：SSE 端点此前注入请求级 session，整条流独占一个连接池连接。"""

    @pytest.mark.asyncio
    async def test_stream_works_without_request_scoped_session(self, client, test_session_factory, monkeypatch):
        from modules.ai_text import router as ai_router
        from modules.system.service import SystemService

        token = await _setup_admin_user(test_session_factory)
        monkeypatch.setattr(
            SystemService, "build_llm_provider",
            AsyncMock(return_value=_FakeProvider()),
        )
        monkeypatch.setattr(
            ai_router, "_get_knowledge_service",
            lambda: SimpleNamespace(ask=AsyncMock(return_value={"sources": [], "status": "ok", "provider": "local"})),
        )

        resp = await client.post(
            "/api/v1/ai/copilot/chat/stream",
            json={"message": "你好", "top_k": 1},
            headers=auth_header(token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.text
        assert '"type": "meta"' in body or "'type': 'meta'" in body
        assert "你好" in body
        assert "done" in body
