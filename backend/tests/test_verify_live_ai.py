"""Live probe gates exercised with in-memory HTTP responses only."""
import json
from types import SimpleNamespace

import httpx
import pytest

from scripts import verify_live_ai as probe


@pytest.fixture
def rig(monkeypatch):
    from core.config import Settings
    import core.config

    settings = Settings(_env_file=None, llm_provider="openai_compatible", llm_base_url="https://api.deepseek.com/v1",
                        llm_model="deepseek-chat", llm_api_key="test-placeholder", knowledge_provider="anythingllm",
                        knowledge_base_url="http://kb.example.invalid", knowledge_workspace_slug="ip-ops-kb", knowledge_api_key="test-placeholder")
    monkeypatch.setattr(core.config, "get_settings", lambda: settings)
    from core.llm_provider import OpenAICompatibleProvider
    from modules.knowledge.anythingllm import AnythingLLMKnowledgeProvider
    from modules.knowledge.service import KnowledgeService, UploadPolicy

    state = SimpleNamespace(generate="ok", stream="ok", count=135, search="ok", requests=[])

    def handler(request):
        state.requests.append(request.url.path)
        payload = json.loads(request.content) if request.content else {}
        if request.url.path.endswith("/chat/completions"):
            marker = payload["messages"][-1]["content"].split()[-1]
            if payload["stream"]:
                delta = {"reasoning_content" if state.stream == "reasoning" else "content": marker}
                chunk = {"choices": [{"delta": delta}]}
                body = "data: " + json.dumps(chunk) + "\n\n"
                if state.stream != "truncated":
                    body += "data: [DONE]\n\n"
                return httpx.Response(200, text=body)
            if state.generate == "exception":
                raise RuntimeError("sensitive response must never enter evidence")
            content = marker if state.generate == "ok" else state.generate
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        if request.url.path.endswith("/workspaces"):
            return httpx.Response(200, json={"workspaces": [{"slug": "ip-ops-kb"}]})
        if request.url.path.endswith("/vector-search"):
            if state.search == "synthetic":
                return httpx.Response(200, json={"answer": "This is not a retrieved chunk"})
            if state.search == "failure":
                return httpx.Response(503, json={"error": "private upstream body"})
            return httpx.Response(200, json={"sources": [{
                "id": "chunk-1", "text": "OSPF uses areas and link-state advertisements.",
                "title": "doc-001.md", "score": 0.82,
                "metadata": {"docId": "corpus-document-1"},
            }]})
        return httpx.Response(200, json={"workspace": [{"documents": [
            {"id": n, "filename": f"doc-{n:03}.md"} for n in range(state.count)
        ]}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    primary = OpenAICompatibleProvider()
    primary._client = client
    kb = AnythingLLMKnowledgeProvider(settings.knowledge_base_url)
    kb._client = client
    service = KnowledgeService(kb, UploadPolicy([], [], 10, 200))
    monkeypatch.setattr(probe, "build_primary", lambda runtime: primary)
    monkeypatch.setattr(probe, "build_knowledge", lambda: service)
    runtime = {key: getattr(settings, key) for key in (
        "llm_provider", "llm_base_url", "llm_model", "llm_api_key", "llm_fallback_model",
    )}
    state.settings, state.runtime = settings, runtime
    state.client = client
    return state


async def run(rig):
    try:
        return await probe.run_probe(rig.runtime, rig.settings, {"identity_sha256": "test-database"})
    finally:
        await rig.client.aclose()


@pytest.mark.asyncio
async def test_live_probe_accepts_real_provider_protocol_and_retrieval(rig):
    result = await run(rig)
    assert result["ok"] is True
    assert result["scope"] == "deepseek_and_anythingllm_readonly"
    assert len(result["checks"]) == 4
    assert result["identity"]["database"]["identity_sha256"] == "test-database"
    assert result["identity"]["llm"]["fallback_used"] is False
    assert "test-placeholder" not in json.dumps(result)
    assert "OSPF uses" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("generate", ""), ("generate", "当前AI服务不可用，请稍后重试。"),
    ("generate", "exception"), ("stream", "truncated"), ("stream", "reasoning"),
    ("count", 134), ("search", "synthetic"), ("search", "failure"),
])
async def test_live_probe_rejects_false_green_without_leaking_raw_response(rig, field, value):
    setattr(rig, field, value)
    result = await run(rig)
    assert result["ok"] is False
    encoded = json.dumps(result, ensure_ascii=False)
    assert "sensitive response" not in encoded
    assert "private upstream body" not in encoded


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("llm_base_url", "https://api.deepseek.com.evil.invalid/v1"),
    ("llm_model", "different-model"), ("llm_api_key", ""),
])
async def test_identity_failure_blocks_outbound_calls(rig, field, value):
    rig.runtime[field] = value
    result = await run(rig)
    assert not result["ok"]
    assert rig.requests == []


@pytest.mark.asyncio
async def test_local_knowledge_cannot_count_as_anythingllm_success(rig):
    rig.settings.knowledge_provider = "local"
    assert not (await run(rig))["ok"]
    assert rig.requests == []


def test_database_identity_never_contains_credentials_or_local_path():
    identity = probe.database_identity("mysql+aiomysql://account:placeholder@localhost:13317/clone?token=private")
    encoded = json.dumps(identity)
    assert identity["database"] == "clone"
    assert all(value not in encoded for value in ("account", "placeholder", "private"))
    sqlite = probe.database_identity("sqlite+aiosqlite:///D:/private/workspace/a.db")
    assert "D:/private" not in json.dumps(sqlite)


@pytest.mark.asyncio
async def test_runner_returns_nonzero_for_configuration_failure(monkeypatch, tmp_path):
    async def fail():
        raise RuntimeError("credentials must not leak")

    monkeypatch.setattr(probe, "load_runtime", fail)
    output = tmp_path / "probe.json"
    assert await probe.main(["--output", str(output)]) == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert "credentials must not leak" not in json.dumps(report)
