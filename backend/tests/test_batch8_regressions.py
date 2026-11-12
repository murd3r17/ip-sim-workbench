"""批次 8 回归测试（2026-09-09 审计 P1-06/09/10/14/26 等）。"""
from types import SimpleNamespace

import pytest

from core.config import get_settings
from modules.ai_text.llm_service import LLMService
from modules.knowledge.service import KnowledgeService


class TestWorkspaceIdWhitelist:
    """P1-06：kb_id 由客户端传入并直拼 URL，此前可跨 workspace 读写/删除。"""

    def _service(self):
        service = KnowledgeService.__new__(KnowledgeService)
        service.provider = SimpleNamespace(name="anythingllm")
        return service

    def test_legit_id_passes(self):
        assert self._service().resolve_workspace_id("my-kb_1") == "my-kb_1"

    def test_path_traversal_falls_back_to_configured_slug(self):
        slug = get_settings().knowledge_workspace_slug
        assert self._service().resolve_workspace_id("../../other-workspace") == slug
        assert self._service().resolve_workspace_id("a/b") == slug
        assert self._service().resolve_workspace_id("x" * 200) == slug

    def test_empty_returns_slug(self):
        assert self._service().resolve_workspace_id(None) == get_settings().knowledge_workspace_slug


class TestPromptBudget:
    """P1-09：上下文无上限，单请求可拼到 60 万字符。"""

    def _service(self):
        return LLMService.__new__(LLMService)

    def test_huge_docs_are_trimmed(self):
        service = self._service()
        prompt = service._build_copilot_prompt("问题", context_docs=["可用完整段落。\n\n" + "x" * 100_000])
        assert len(prompt) <= service.MAX_PROMPT_CHARS
        assert "可用完整段落。" in prompt
        assert "来源不完整" in prompt
        assert "x" * 1000 not in prompt

    def test_oversized_unbroken_document_does_not_become_a_fake_partial_source(self):
        service = self._service()
        prompt = service._build_copilot_prompt("问题", context_docs=["x" * 100_000])
        assert len(prompt) <= service.MAX_PROMPT_CHARS
        assert "x" * 1000 not in prompt
        assert "本次可引用教材来源：0" in prompt

    def test_huge_lab_steps_are_trimmed(self):
        service = self._service()
        steps = [{"id": i, "name": "x" * 2000, "goal": "y" * 2000,
                  "config_hint": "z" * 2000, "verify_command": "display version",
                  "verify_contains": ["Full"]} for i in range(20)]
        prompt = service._build_copilot_prompt("问题", lab_steps=steps)
        assert len(prompt) <= service.MAX_PROMPT_CHARS

    def test_normal_prompt_untouched(self):
        service = self._service()
        prompt = service._build_copilot_prompt("OSPF 邻居为什么建不起来？")
        assert "OSPF 邻居为什么建不起来？" in prompt
        assert "截断" not in prompt


class TestDeviceLockCleanup:
    """P1-26：_locks 字典永不回收，每访问一台新设备就常驻一条。"""

    @pytest.mark.asyncio
    async def test_entry_removed_after_release(self):
        from engines import device_lock

        device_lock._locks.clear()
        device_lock._refs.clear()
        async with device_lock.acquire_device_lock("10.9.9.9", 22):
            assert device_lock.device_lock_key("10.9.9.9", 22) in device_lock._locks
        assert device_lock._locks == {}
        assert device_lock._refs == {}

    @pytest.mark.asyncio
    async def test_busy_timeout_does_not_leak_reference(self):
        from engines import device_lock

        device_lock._locks.clear()
        device_lock._refs.clear()
        key = device_lock.device_lock_key("10.9.9.8", 22)
        async with device_lock.acquire_device_lock("10.9.9.8", 22):
            with pytest.raises(device_lock.DeviceBusyError):
                async with device_lock.acquire_device_lock("10.9.9.8", 22, timeout=0.05):
                    pass  # pragma: no cover
            # 失败的 acquire 必须把自己的引用还回去（只剩外层持有者的 1）
            assert device_lock._refs.get(key) == 1
        assert device_lock._locks == {}
        assert device_lock._refs == {}


class TestSshClientPolicy:
    """P1-14：AutoAddPolicy 无主机密钥校验；改为可配置。"""

    def test_default_is_auto_add(self):
        from engines.netmiko_exec import new_ssh_client
        client = new_ssh_client()
        assert client._policy.__class__.__name__ == "AutoAddPolicy"

    def test_strict_mode_uses_reject_policy(self, monkeypatch):
        from core.config import get_settings as _gs
        from engines import netmiko_exec

        settings = _gs().model_copy(update={"ssh_strict_host_key": True, "ssh_known_hosts": ""})
        monkeypatch.setattr(netmiko_exec, "new_ssh_client", netmiko_exec.new_ssh_client, raising=True)
        monkeypatch.setattr("core.config.get_settings", lambda: settings)
        client = netmiko_exec.new_ssh_client()
        assert client._policy.__class__.__name__ == "RejectPolicy"
