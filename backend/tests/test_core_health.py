"""健康接口 LLM 检查 TTL 缓存测试。"""
import pytest

import core.health as health
import core.llm_provider as lp


class _CountingProvider:
    """每次 health_check 递增计数，模拟慢/挂的外部 LLM API。"""

    def __init__(self, base_url="http://llm.test", model="m", api_key="k", healthy=True):
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self.healthy = healthy
        self.calls = 0

    async def health_check(self) -> bool:
        self.calls += 1
        return self.healthy


@pytest.fixture(autouse=True)
def _clear_cache():
    old_ttl = lp._LLM_HEALTH_TTL_SECONDS
    lp._LLM_HEALTH_CACHE.clear()
    health._SIDE_HEALTH_CACHE.clear()
    yield
    lp._LLM_HEALTH_CACHE.clear()
    health._SIDE_HEALTH_CACHE.clear()
    lp._LLM_HEALTH_TTL_SECONDS = old_ttl


@pytest.mark.asyncio
async def test_cache_hits_within_ttl():
    provider = _CountingProvider()
    assert await lp.cached_llm_health_check(provider) is True
    assert await lp.cached_llm_health_check(provider) is True
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_cache_expires_after_ttl():
    provider = _CountingProvider()
    lp._LLM_HEALTH_TTL_SECONDS = 0.0
    assert await lp.cached_llm_health_check(provider) is True
    assert await lp.cached_llm_health_check(provider) is True
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_cache_key_separates_provider_configs():
    p1 = _CountingProvider(base_url="http://a", model="m1")
    p2 = _CountingProvider(base_url="http://b", model="m2")
    await lp.cached_llm_health_check(p1)
    await lp.cached_llm_health_check(p2)
    assert p1.calls == 1
    assert p2.calls == 1


@pytest.mark.asyncio
async def test_unhealthy_result_is_cached_too():
    provider = _CountingProvider(healthy=False)
    assert await lp.cached_llm_health_check(provider) is False
    assert await lp.cached_llm_health_check(provider) is False
    assert provider.calls == 1


def test_knowledge_down_does_not_make_unhealthy():
    assert health._mark_degraded("healthy") == "degraded"
    assert health._mark_degraded("degraded") == "degraded"
    assert health._mark_degraded("unhealthy") == "unhealthy"


def test_side_probe_cache_roundtrip():
    health._cache_set("minio", {"status": "unavailable"})
    first = health._cache_get("minio")
    second = health._cache_get("minio")
    assert first == second == {"status": "unavailable"}


class TestLlmConfigSource:
    """health 的 config_source 必须反映"DB 里是否真有 llm.* 覆盖行"。

    此前只要 `get_llm_runtime_config` 查询成功就标 system_config，于是 DB 一行都没有、
    实际全用 .env 时也被标成 system_config，全链路校验因此报"来源不一致"。
    """

    @pytest.mark.asyncio
    async def test_no_db_rows_reports_env(self, test_session_factory):
        from modules.system.service import SystemService

        async with test_session_factory() as db:
            assert await SystemService.get_llm_config_source(db) == "env"

    @pytest.mark.asyncio
    async def test_db_row_reports_system_config(self, test_session_factory):
        from modules.system.models import SystemConfig
        from modules.system.service import SystemService

        async with test_session_factory() as db:
            db.add(
                SystemConfig(
                    config_key="llm.model",
                    config_value="deepseek-chat",
                    description="test",
                )
            )
            await db.commit()
            assert await SystemService.get_llm_config_source(db) == "system_config"
