import pytest
from modules.ai_text import kb_cache

class _Svc:
    def __init__(self): self.calls = 0
    async def search(self, q, ws, k):
        self.calls += 1
        return [{"filename": "a.md", "score": 1.0}]

@pytest.mark.asyncio
async def test_actual_provider_scope_and_credentials_isolate_cached_results():
    from types import SimpleNamespace
    kb_cache.invalidate()
    a, b = _Svc(), _Svc()
    a.provider = SimpleNamespace(base_url="http://a", workspace_slug="shared", api_key="key-a")
    b.provider = SimpleNamespace(base_url="http://b", workspace_slug="shared", api_key="key-a")
    await kb_cache.cached_search(a, "OSPF", 5)
    await kb_cache.cached_search(b, "OSPF", 5)
    assert a.calls == b.calls == 1
    a.provider.api_key = "key-b"
    await kb_cache.cached_search(a, "OSPF", 5)
    assert a.calls == 2

@pytest.mark.asyncio
async def test_returned_sources_cannot_mutate_cached_evidence():
    kb_cache.invalidate(); svc = _Svc()
    sources = await kb_cache.cached_search(svc, "OSPF", 5)
    sources[0]["filename"] = "injected"
    second = await kb_cache.cached_search(svc, "OSPF", 5)
    assert second[0]["filename"] == "a.md" and svc.calls == 1

@pytest.mark.asyncio
async def test_failed_load_is_not_cached_and_candidate_count_is_not_doubled():
    kb_cache.invalidate()
    class Service(_Svc):
        async def search(self, q, ws, k):
            self.calls += 1
            assert k == 12
            if self.calls == 1:
                raise TimeoutError()
            return [{"filename": "recovered.md"}]
    svc = Service()
    with pytest.raises(TimeoutError):
        await kb_cache.cached_search(svc, "OSPF", 12)
    result = await kb_cache.cached_search(svc, "OSPF", 12)
    assert result[0]["filename"] == "recovered.md" and svc.calls == 2

@pytest.mark.asyncio
async def test_same_query_uses_cache():
    kb_cache.invalidate(); svc = _Svc()
    a = await kb_cache.cached_search(svc, "OSPF LSA", 5)
    b = await kb_cache.cached_search(svc, "ospf lsa", 5)
    assert svc.calls == 1 and a == b

@pytest.mark.asyncio
async def test_different_query_or_topk_misses():
    kb_cache.invalidate(); svc = _Svc()
    await kb_cache.cached_search(svc, "VRRP", 5)
    await kb_cache.cached_search(svc, "VRRP", 6)
    await kb_cache.cached_search(svc, "BGP", 5)
    assert svc.calls == 3

@pytest.mark.asyncio
async def test_invalidate_forces_reload():
    kb_cache.invalidate(); svc = _Svc()
    await kb_cache.cached_search(svc, "QinQ", 5)
    kb_cache.invalidate()
    await kb_cache.cached_search(svc, "QinQ", 5)
    assert svc.calls == 2

@pytest.mark.asyncio
async def test_ttl_expiry(monkeypatch):
    kb_cache.invalidate(); svc = _Svc()
    monkeypatch.setattr(kb_cache, "_TTL", -1)  # 写入即过期
    await kb_cache.cached_search(svc, "ACL", 5)
    await kb_cache.cached_search(svc, "ACL", 5)
    assert svc.calls == 2
