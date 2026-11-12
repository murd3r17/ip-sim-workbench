"""AI 链路静默失效回归测试（2026-09-09 审计批次 4）。

这些缺陷的共同特征：接口 200、界面正常，但能力实际已经失效（工具拿不到正文、
视觉返回 None、工具循环整体不触发、日志落成不可解析的 dict、sim 数据每次重启都变）。
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


async def _capture_post(captured):
    async def _post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return _Resp({"choices": [{"message": {"role": "assistant", "content": "ok"}}]})
    return _post


class TestKnowledgeToolContent:
    """P0-35：search_knowledge 只读 content，而 AnythingLLM 返回的是 text → 永远没有正文。"""

    @pytest.mark.asyncio
    async def test_tool_reads_text_and_title(self, monkeypatch):
        from modules.knowledge.service import KnowledgeService
        from modules.ai_text import agent_tools

        fake = SimpleNamespace(
            search=AsyncMock(return_value=[
                {"text": "OSPF 邻居建立过程", "title": "01-ospf.md", "score": 0.91},
            ])
        )
        monkeypatch.setattr(KnowledgeService, "from_settings", classmethod(lambda cls: fake))

        out = await agent_tools._search_knowledge(None, {"query": "ospf", "top_k": 3})
        assert "OSPF 邻居建立过程" in out
        assert "01-ospf.md" in out

    @pytest.mark.asyncio
    async def test_tool_still_supports_content_key(self, monkeypatch):
        from modules.knowledge.service import KnowledgeService
        from modules.ai_text import agent_tools

        fake = SimpleNamespace(search=AsyncMock(return_value=[{"content": "旧键兼容", "filename": "x.md"}]))
        monkeypatch.setattr(KnowledgeService, "from_settings", classmethod(lambda cls: fake))
        out = await agent_tools._search_knowledge(None, {"query": "x"})
        assert "旧键兼容" in out


class TestThinkingPayloadGuard:
    """P0-37：chat_completion 无条件下发 thinking → 非 DeepSeek 端点 400 → 工具循环静默失效。"""

    @pytest.mark.asyncio
    async def test_non_deepseek_omits_thinking(self):
        from core.llm_provider import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(base_url="http://127.0.0.1:9999", model="qwen2.5:7b", api_key="k")
        captured: dict = {}
        provider._client = SimpleNamespace(post=await _capture_post(captured))

        await provider.chat_completion([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])

        assert "thinking" not in captured["payload"]
        assert captured["payload"]["tools"]

    @pytest.mark.asyncio
    async def test_deepseek_sends_thinking_disabled(self):
        from core.llm_provider import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(
            base_url="https://api.deepseek.com", model="deepseek-v4-flash", api_key="k"
        )
        captured: dict = {}
        provider._client = SimpleNamespace(post=await _capture_post(captured))

        await provider.chat_completion([{"role": "user", "content": "hi"}])

        assert captured["payload"]["thinking"] == {"type": "disabled"}


class TestVisionFallback:
    """P0-36：主 provider 不支持视觉时 generate_with_images 返回 None。"""

    @pytest.mark.asyncio
    async def test_falls_back_to_text_when_unsupported(self):
        from core.llm_provider import FallbackProvider

        class _Primary:
            name = "P"

            async def generate(self, prompt, system=None, max_tokens=None, temperature=None):
                return "text-only"

        provider = FallbackProvider(_Primary())
        out = await provider.generate_with_images("看图", [{"url": "data:image/png;base64,AAA"}])
        assert out == "text-only"


class TestSafetyFilter:
    """P0-38：子串匹配让 `undo shutdown` 被误杀，reb/shut 缩写反而绕过。"""

    def _filter(self, commands):
        from modules.ai_text.llm_service import LLMService
        service = LLMService.__new__(LLMService)
        return service._filter_dangerous_commands(commands)

    def test_undo_shutdown_is_allowed(self):
        safe, warnings = self._filter(["undo shutdown"])
        assert safe == ["undo shutdown"]
        assert warnings == []

    @pytest.mark.parametrize("cmd", ["shutdown", "reboot", "reb", "shut", "restart", "reset saved-configuration"])
    def test_destructive_commands_blocked(self, cmd):
        safe, warnings = self._filter([cmd])
        assert safe == []
        assert warnings


class TestStringCommands:
    """P0-39：commands 为字符串时逐字符当命令。"""

    @pytest.mark.asyncio
    async def test_string_commands_split_by_line(self):
        from modules.ai_text.llm_service import LLMService

        class _Provider:
            name = "Mock"

            async def generate(self, prompt, system=None, max_tokens=None, temperature=None):
                return '{"commands": "sysname R1\\ninterface GE0/0/1", "explanation": "x"}'

        service = LLMService(provider=_Provider())
        result = await service.generate_cli_commands("改主机名")
        assert result["commands"] == ["sysname R1", "interface GE0/0/1"]


class TestLogRequestRollback:
    """P0-40：commit 失败后不回滚，会话进入 PendingRollbackError。"""

    @pytest.mark.asyncio
    async def test_commit_failure_triggers_rollback(self):
        from modules.ai_text.llm_service import LLMService

        db = SimpleNamespace(
            add=lambda entry: None,
            commit=AsyncMock(side_effect=RuntimeError("db down")),
            refresh=AsyncMock(),
            rollback=AsyncMock(),
        )
        service = LLMService(db=db, user_id=1, provider=SimpleNamespace(name="Mock"))
        assert await service._log_request("t", "p", "r", 0.0) is None
        db.rollback.assert_awaited()


class TestLoggerFormat:
    """P0-41：handler 未使用 ProcessorFormatter → 落盘是 dict repr；模块名单缺项 → 日志被丢弃。"""

    def test_module_logger_list_covers_previously_dropped_modules(self):
        from core.logger import MODULE_LOGGERS

        for name in ("device", "system"):
            assert name in MODULE_LOGGERS

    def test_output_is_parseable_json(self, tmp_path):
        import json
        import logging

        import structlog

        from core import logger as logger_module

        logger_module.setup_logging()
        handler = logging.FileHandler(tmp_path / "probe.log", encoding="utf-8")
        handler.setFormatter(logger_module._build_formatter(logger_module._shared_processors()))
        probe = logging.getLogger("json-probe")
        probe.addHandler(handler)
        probe.setLevel(logging.INFO)
        try:
            structlog.get_logger("json-probe").info("probe_event", value=1, text="中文")
        finally:
            probe.removeHandler(handler)
            handler.close()

        line = (tmp_path / "probe.log").read_text(encoding="utf-8").strip().splitlines()[-1]
        payload = json.loads(line)
        assert payload["event"] == "probe_event"
        assert payload["value"] == 1


class TestSimDeterminism:
    """P0-42：sim 适配器用内置 hash()，跨进程不稳定，与"同一设备每次稳定"矛盾。"""

    def test_current_config_is_stable_across_instances(self):
        from engines.device_adapter import SimDeviceAdapter

        first = SimDeviceAdapter(hostname="R1")._current_config()
        second = SimDeviceAdapter(hostname="R1")._current_config()
        assert first == second

    def test_different_devices_differ(self):
        from engines.device_adapter import SimDeviceAdapter

        assert SimDeviceAdapter(hostname="R1")._current_config() != SimDeviceAdapter(
            hostname="R2"
        )._current_config()
