"""A5：模型配置补齐（设计 §8 的 8 项配置内容 + 备用模型回退）。

覆盖：
- LLM_CONFIG_KEYS 含 timeout 与 fallback 三键（此前只有 6 项）；
- `_parse_runtime_value` 按默认值类型解析（int/float/bool/str），非法值回退默认；
- `create_llm_provider` 在主模型之上按需套 FailoverProvider；
- FailoverProvider 的切换语义：主失败→切备用；已输出→不切（避免两段答案）；都失败→外抛给 FallbackProvider。
"""

from typing import AsyncIterator

import pytest

from core import llm_provider as lp
from modules.system.service import LLM_CONFIG_KEYS, SystemService


class _FakeProvider(lp.LLMProvider):
    """可控的假 provider：按脚本抛错或产出。"""

    def __init__(self, name: str, *, fail: bool = False, chunks: list[str] | None = None, answer: str = "ok"):
        self._name = name
        self.fail = fail
        self.chunks = chunks or []
        self.answer = answer
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def generate(self, prompt, system=None, max_tokens=None, temperature=None) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"{self._name} down")
        return f"{self.answer}:{self._name}"

    async def stream(self, prompt, system=None, max_tokens=None, temperature=None) -> AsyncIterator[str]:
        self.calls += 1
        for chunk in self.chunks:
            yield chunk
        if self.fail:
            raise RuntimeError(f"{self._name} stream down")

    async def health_check(self) -> bool:
        return not self.fail


class TestConfigKeys:
    def test_config_keys_cover_design_eight_items(self):
        """设计 §8：provider、base_url、api_key、model、timeout、temperature、max_tokens、fallback。"""
        keys = set(LLM_CONFIG_KEYS)
        assert {
            "llm.provider", "llm.base_url", "llm.api_key", "llm.model",
            "llm.timeout", "llm.temperature", "llm.max_tokens",
            "llm.fallback_model", "llm.fallback_base_url", "llm.fallback_api_key",
        } <= keys

    def test_parse_runtime_value_by_default_type(self):
        parse = SystemService._parse_runtime_value
        assert parse("llm.timeout", "300", 120) == 300
        assert parse("llm.timeout", "abc", 120) == 120  # 非法值回退
        assert parse("llm.max_tokens", "2048", 16384) == 2048
        assert parse("llm.temperature", "0.7", 0.3) == 0.7
        assert parse("llm.temperature", "", 0.3) == 0.3
        assert parse("llm.fallback_model", " qwen-max ", "") == "qwen-max"
        assert parse("llm.model", None, "def") == "def"

    def test_fallback_api_key_is_masked(self):
        assert SystemService._is_secret_key("llm.fallback_api_key") is True


class TestFailoverProvider:
    @pytest.mark.asyncio
    async def test_generate_switches_to_secondary(self):
        primary = _FakeProvider("primary", fail=True)
        secondary = _FakeProvider("secondary")
        provider = lp.FailoverProvider(primary, secondary)

        assert await provider.generate("hi") == "ok:secondary"
        assert primary.calls == 1 and secondary.calls == 1

    @pytest.mark.asyncio
    async def test_generate_uses_primary_when_healthy(self):
        primary = _FakeProvider("primary")
        secondary = _FakeProvider("secondary")
        provider = lp.FailoverProvider(primary, secondary)

        assert await provider.generate("hi") == "ok:primary"
        assert secondary.calls == 0

    @pytest.mark.asyncio
    async def test_stream_does_not_switch_after_partial_output(self):
        """已输出内容后失败不能再切备用，否则用户会看到两段不连贯答案。"""
        primary = _FakeProvider("primary", fail=True, chunks=["部分", "答案"])
        secondary = _FakeProvider("secondary", chunks=["备用"])
        provider = lp.FailoverProvider(primary, secondary)

        out = []
        with pytest.raises(RuntimeError, match="stream down"):
            async for chunk in provider.stream("hi"):
                out.append(chunk)

        assert out == ["部分", "答案"]
        assert secondary.calls == 0

    @pytest.mark.asyncio
    async def test_stream_switches_when_nothing_yielded(self):
        primary = _FakeProvider("primary", fail=True, chunks=[])
        secondary = _FakeProvider("secondary", chunks=["备用", "答案"])
        provider = lp.FailoverProvider(primary, secondary)

        out = [chunk async for chunk in provider.stream("hi")]

        assert out == ["备用", "答案"]

    @pytest.mark.asyncio
    async def test_both_down_raises_for_outer_fallback(self):
        provider = lp.FallbackProvider(lp.FailoverProvider(
            _FakeProvider("primary", fail=True), _FakeProvider("secondary", fail=True)
        ))
        with pytest.raises(lp.LLMUnavailableError, match="当前AI服务不可用"):
            await provider.generate("hi")

    @pytest.mark.asyncio
    async def test_health_check_falls_back(self):
        provider = lp.FailoverProvider(_FakeProvider("primary", fail=True), _FakeProvider("secondary"))
        assert await provider.health_check() is True


class TestCreateProvider:
    def test_without_fallback_keeps_single_wrapper(self):
        provider = lp.create_llm_provider({
            "llm_provider": "openai_compatible", "llm_base_url": "http://x/v1",
            "llm_model": "m", "llm_api_key": "k", "llm_fallback_model": "",
        })
        assert isinstance(provider, lp.FallbackProvider)
        assert not isinstance(provider.primary, lp.FailoverProvider)

    def test_with_fallback_wraps_failover(self):
        provider = lp.create_llm_provider({
            "llm_provider": "openai_compatible", "llm_base_url": "http://x/v1",
            "llm_model": "m", "llm_api_key": "k",
            "llm_fallback_model": "fb-model", "llm_fallback_base_url": "http://y/v1",
            "llm_fallback_api_key": "fk",
        })
        inner = provider.primary
        assert isinstance(inner, lp.FailoverProvider)
        assert inner.primary.model == "m"
        assert inner.secondary.model == "fb-model"
        assert inner.secondary.api_key == "fk"

    def test_fallback_base_url_defaults_to_primary(self):
        provider = lp.create_llm_provider({
            "llm_provider": "openai_compatible", "llm_base_url": "http://x/v1",
            "llm_model": "m", "llm_api_key": "k", "llm_fallback_model": "fb-model",
        })
        assert provider.primary.secondary.base_url.startswith("http://x/v1")
