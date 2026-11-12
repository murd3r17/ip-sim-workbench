"""P1 正确性回归测试（2026-09-09 审计批次 7）。"""
import asyncio
from types import SimpleNamespace

import pytest

from core.exceptions import AppException, parse_enum
from core.retry_engine import RetryEngine
from modules.deploy.config_template_engine import ConfigTemplateEngine, TemplateRenderError
from modules.deploy.service import DeployService
from modules.device.lldp_parser import classify_link_type
from modules.device.models import DeviceStatus, validate_status_transition


class TestTemplateFilters:
    """P1-15/16/17：过滤器非幂等、整数掩码产出非法配置、缺模板冒泡 500。"""

    def test_interface_name_is_idempotent(self):
        engine = ConfigTemplateEngine()
        full = "GigabitEthernet0/0/1"
        assert engine._filter_interface_name(full) == full
        assert engine._filter_interface_name("gi0/0/1") == full
        assert engine._filter_interface_name("GE0/0/1") == full

    def test_interface_name_does_not_mangle_xge_or_ethtrunk(self):
        engine = ConfigTemplateEngine()
        assert engine._filter_interface_name("XGE0/0/1") == "XGigabitEthernet0/0/1"
        assert engine._filter_interface_name("Eth-Trunk1") == "Eth-Trunk1"
        assert engine._filter_interface_name("LoopBack0") == "LoopBack0"

    def test_ip_mask_accepts_integer_prefix(self):
        engine = ConfigTemplateEngine()
        assert engine._filter_ip_mask("192.168.1.1", 24) == "192.168.1.1 255.255.255.0"
        assert engine._filter_ip_mask("192.168.1.1", "24") == "192.168.1.1 255.255.255.0"
        assert engine._filter_ip_mask("10.0.0.1", 30) == "10.0.0.1 255.255.255.252"

    def test_ip_mask_keeps_dotted_mask(self):
        engine = ConfigTemplateEngine()
        assert engine._filter_ip_mask("10.0.0.1", "255.255.0.0") == "10.0.0.1 255.255.0.0"

    def test_render_raises_readable_error_for_extends(self):
        engine = ConfigTemplateEngine()
        with pytest.raises(TemplateRenderError) as exc:
            engine.render('{% extends "base.vrp" %}')
        assert "模板不存在" in str(exc.value)


class TestDeviceStatusTransition:
    """P1-11：VALID_TRANSITIONS 缺 UNKNOWN→OFFLINE，新建设备首次探测离线必然报错。"""

    def test_unknown_can_go_offline(self):
        assert validate_status_transition(DeviceStatus.UNKNOWN, DeviceStatus.OFFLINE) is True

    def test_unknown_can_go_online(self):
        assert validate_status_transition(DeviceStatus.UNKNOWN, DeviceStatus.ONLINE) is True

    def test_maintenance_can_go_offline(self):
        assert validate_status_transition(DeviceStatus.MAINTENANCE, DeviceStatus.OFFLINE) is True


class TestLldpLinkClassification:
    """P1-18：子串匹配把 XGE0/0/0、GE0/0/01 误判为管理链路。"""

    def test_exact_management_port(self):
        assert classify_link_type("GE0/0/0", "GE0/0/1") == "management"
        assert classify_link_type("MEth0/0/0", "GE1/0/1") == "management"

    def test_similar_names_are_business(self):
        assert classify_link_type("XGE0/0/0", "GE0/0/1") == "business"
        assert classify_link_type("GE0/0/01", "GE0/0/1") == "business"
        assert classify_link_type("GE0/0/0.100", "GE0/0/1") == "business"
        assert classify_link_type("GE0/0/1", "GE0/0/2") == "business"


class TestEnumParsing:
    """P1-21：非法枚举查询参数此前冒泡成 500，且各处行为不一致。"""

    def test_valid_value(self):
        assert parse_enum(DeviceStatus, "online", "status") is DeviceStatus.ONLINE

    def test_invalid_value_is_422(self):
        with pytest.raises(AppException) as exc:
            parse_enum(DeviceStatus, "bogus", "status")
        assert exc.value.status_code == 422
        assert "online" in str(exc.value)


class TestRetryEngineBounds:
    """P1-25：max_retries<0 时此前抛 TypeError: exceptions must derive from BaseException。"""

    @pytest.mark.asyncio
    async def test_negative_max_retries_clamped_to_single_attempt(self):
        """max_retries<0 不再抛 TypeError，而是收敛为"只尝试一次"。"""
        engine = RetryEngine(max_retries=-1)
        assert await engine.execute(lambda: 1) == 1
        assert engine.attempt_count == 1

    @pytest.mark.asyncio
    async def test_negative_max_retries_propagates_original_error(self):
        engine = RetryEngine(max_retries=-1)

        async def boom():
            raise RuntimeError("original")

        with pytest.raises(RuntimeError, match="original"):
            await engine.execute(boom)

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self):
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("boom")
            return "ok"

        engine = RetryEngine(max_retries=2, backoff_base=0.01)
        assert await engine.execute(flaky) == "ok"
        assert calls["n"] == 2


class TestFallbackStream:
    """P1-31：流中途失败后追加降级文案，与已产出的真实 token 混排。"""

    @pytest.mark.asyncio
    async def test_no_fallback_message_after_real_tokens(self):
        from core.llm_provider import FallbackProvider

        class _Primary:
            name = "P"

            async def stream_parts(self, prompt, system=None, max_tokens=None, temperature=None):
                yield {"kind": "content", "text": "前半段"}
                raise RuntimeError("network died")

        provider = FallbackProvider(_Primary())
        parts = []
        with pytest.raises(RuntimeError, match="network died"):
            async for part in provider.stream_parts("hi"):
                parts.append(part)
        assert parts == [{"kind": "content", "text": "前半段"}]

    @pytest.mark.asyncio
    async def test_fallback_message_when_nothing_yielded(self):
        from core.llm_provider import FallbackProvider

        class _Primary:
            name = "P"

            async def stream_parts(self, prompt, system=None, max_tokens=None, temperature=None):
                raise RuntimeError("down")
                yield  # pragma: no cover

        provider = FallbackProvider(_Primary(), fallback_message="降级文案")
        parts = []
        with pytest.raises(RuntimeError, match="down"):
            async for part in provider.stream_parts("hi"):
                parts.append(part)
        assert parts == [{"kind": "content", "text": "降级文案"}]


class TestHighestRisk:
    """P1-24：风险等级此前取"第一个非 safe"，可能低估整体风险。"""

    def test_picks_highest_level(self):
        details = [
            {"risk_level": "warning"},
            {"risk_level": "safe"},
            {"risk_level": "dangerous"},
        ]
        assert DeployService._highest_risk(details) == "dangerous"

    def test_all_safe(self):
        assert DeployService._highest_risk([{"risk_level": "safe"}]) == "safe"

    def test_empty(self):
        assert DeployService._highest_risk([]) == "safe"


class TestCredentialNullGuard:
    """P1-13：password_encrypted 为 NULL 时 decrypt(None) → AttributeError → 500。"""

    @pytest.mark.asyncio
    async def test_null_password_returns_empty_string(self):
        from core.security import credential_encryptor
        from modules.device.service import DeviceService

        token = credential_encryptor.encrypt("user-token") if credential_encryptor.configured else "user-token"
        device = SimpleNamespace(
            username_encrypted=token,
            password_encrypted=None,
            enable_encrypted=None,
        )
        creds = await DeviceService.get_device_credentials(device)
        assert creds["username"] == "user-token"
        assert creds["password"] == ""
        assert creds["enable"] == ""


class TestModelLabel:
    """P1-33：AILog.model_used 此前记 provider 类名，无法按模型统计。"""

    def test_uses_real_model_name(self):
        from modules.ai_text.llm_service import LLMService
        from core.llm_provider import FallbackProvider

        primary = SimpleNamespace(name="OpenAICompatibleProvider", model="deepseek-v4-flash")
        service = LLMService.__new__(LLMService)
        service.provider = FallbackProvider(primary)
        assert service._model_label() == "deepseek-v4-flash"
