"""Exercise the first-party teaching fallback without a service or private corpus."""

from hashlib import sha256
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from modules.ai_text import router
from modules.knowledge import local_provider
from modules.knowledge.local_provider import LocalKnowledgeProvider
from modules.knowledge.service import KnowledgeService, UploadPolicy
from tests.test_c3_request_api import api_case, events


QUESTION = "只依据教材说明 STP 的桥 ID 如何构成。"
SOURCE = "# STP 桥 ID\n\nSTP 的桥 ID 由桥优先级与交换机 MAC 地址组成。\n"
OTHER_SOURCE = "# STP 桥 ID\n\nSTP 的桥 ID 来源于自定义私人记录 UPLOAD_ONLY_CANARY。\n"
FILENAME = "stp-study.md"


@pytest.fixture
def bundled_knowledge(tmp_path, monkeypatch):
    root = tmp_path / "official" / "huawei-ip"
    storage = tmp_path / "uploads"
    root.mkdir(parents=True)
    storage.mkdir()
    published = root / FILENAME
    published.write_bytes(SOURCE.encode())
    (storage / FILENAME).write_bytes(OTHER_SOURCE.encode())
    monkeypatch.setattr(local_provider, "DEFAULT_CORPUS_DIR", root)
    # A legacy local deployment may write the official path with a redundant segment.
    provider = LocalKnowledgeProvider(corpus_dir=root.parent / ".." / "official" / "huawei-ip", storage_dir=storage)
    service = KnowledgeService(provider, UploadPolicy([], [], 10, 10))
    monkeypatch.setattr(service, "edition", lambda: None)
    monkeypatch.setattr(router, "_get_knowledge_service", lambda: service)
    return service, published


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
async def test_bundled_no_model_only_sends_reopenable_verified_text(api_case, bundled_knowledge, monkeypatch, path):
    client, headers, model, retrieval = api_case
    _, published = bundled_knowledge
    monkeypatch.setattr(router.SystemService, "build_llm_provider", AsyncMock(side_effect=RuntimeError("private-canary")))
    request_id = uuid4().hex
    response = await client.post("/api/v1/ai/copilot" + path, headers=headers, json={
        "request_id": request_id, "message": QUESTION, "context": {"route": "/knowledge"}})
    assert response.status_code == 200, response.text
    if path.endswith("/stream"):
        frames = events(response)
        assert frames[0]["provider"] == "local"
        reply = next(frame for frame in frames if frame["type"] == "references")
    else:
        reply = response.json()
        assert reply["status"] == "failed" and reply["provider"] == "local"
    assert reply["generation_status"] == "retrieval_only"
    [source] = reply["sources"]
    assert source["bundled"] is True and source["filename"] == FILENAME
    assert source["document_id"].startswith("corpus-")
    assert source["document_version"] == sha256(SOURCE.encode()).hexdigest()
    assert not any(source.get(field) for field in ("page", "section_id", "edition_version", "prompt_text"))
    assert "优先级" in source["content"] and "本地教材摘录" in response.text
    assert "UPLOAD_ONLY_CANARY" not in response.text and "private-canary" not in response.text
    assert model.calls == 0
    retrieval.assert_not_awaited()

    locator = {"filename": FILENAME, "request_id": request_id, "source_id": source["source_id"]}
    cited = await client.get("/api/v1/ai/copilot/citations/read", headers=headers, params=locator)
    assert cited.status_code == 200 and cited.json()["scope"] == "retrieval_excerpt"
    assert cited.json()["bundled"] and cited.json()["content"] == source["content"]
    read = await client.get("/api/v1/ai/knowledge/read", headers=headers, params={
        "document_id": source["document_id"], "version": source["document_version"]})
    assert read.status_code == 200 and read.json()["bundled"]
    assert read.json()["page"] is None and read.json()["version"] == source["document_version"]
    published.write_bytes(SOURCE.replace("桥优先级", "修订后的桥优先级").encode())
    revoked = await client.get("/api/v1/ai/copilot/citations/read", headers=headers, params=locator)
    assert revoked.status_code == 410


@pytest.mark.asyncio
async def test_no_original_quote_or_internal_paths_in_inventory(api_case, bundled_knowledge):
    client, headers, _, _ = api_case
    service, published = bundled_knowledge
    assert (await service.provider.list_documents())[0]["path"]
    for endpoint in ("/health", "/catalog"):
        response = await client.get("/api/v1/ai/knowledge" + endpoint, headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["original_quote_status"] == {"state": "unmounted", "scan_available": False}
        assert str(published.parent).replace("\\", "\\\\") not in response.text
        assert all("path" not in row and "stored_at" not in row for row in body["documents"])
        if endpoint == "/catalog":
            by_identity = {row["id"].split("-")[0]: row for row in body["documents"]}
            assert by_identity["corpus"]["bundled"] is True and by_identity["upload"]["bundled"] is False
            assert by_identity["corpus"]["readable"] and by_identity["corpus"]["source_status"] == "persistent"
    quote = await client.post("/api/v1/ai/knowledge/original-quote", headers=headers, json={"quote": "请核对未挂载的原教材文字"})
    assert quote.status_code == 404 and quote.json()["detail"]["code"] == "original_not_mounted"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
async def test_hosted_error_keeps_local_excerpt_and_does_not_save_unfinished_model_text(api_case, bundled_knowledge, monkeypatch, path):
    client, headers, model, retrieval = api_case

    async def disconnect(*args, **kwargs):
        model.calls += 1
        yield {"kind": "content", "text": "UNFINISHED_MODEL_ONLY"}
        raise httpx.ConnectError("PRIVATE_PROVIDER_ERROR")

    monkeypatch.setattr(model, "stream_parts", disconnect)
    retrieval.return_value = [{"filename": "external.md", "text": "来自外部服务的非随包材料。"}]
    request_id = uuid4().hex
    response = await client.post("/api/v1/ai/copilot" + path, headers=headers, json={
        "request_id": request_id, "message": QUESTION, "context": {"route": "/knowledge"}})
    assert response.status_code == 200, response.text
    if path.endswith("/stream"):
        frames = events(response)
        assert frames[-1]["status"] == "failed" and frames[-1]["trace"]["model_calls"] == 1
        assert any(frame.get("retrieval_only") and "本地教材摘录" in frame["replace_answer"] for frame in frames)
        cited = next(frame for frame in frames if frame["type"] == "references")
    else:
        cited = response.json()
        assert cited["status"] == "failed" and cited["trace"]["model_calls"] == 1
    [source] = cited["sources"]
    assert source["bundled"] and source["filename"] == FILENAME and "非随包材料" not in source["content"]
    assert cited["generation_status"] == "retrieval_only" and "PRIVATE_PROVIDER_ERROR" not in response.text
    stored = await client.get(f"/api/v1/ai/copilot/requests/{request_id}", headers=headers)
    assert stored.status_code == 200
    assert "本地教材摘录" in stored.json()["response"]["answer"]
    assert "UNFINISHED_MODEL_ONLY" not in stored.json()["response"]["answer"]


@pytest.mark.asyncio
async def test_unrelated_custom_data_and_unmounted_original_requests_cannot_substitute(bundled_knowledge, tmp_path):
    service, _ = bundled_knowledge
    custom = tmp_path / "custom"
    custom.mkdir()
    (custom / FILENAME).write_bytes(OTHER_SOURCE.encode())
    custom_service = KnowledgeService(LocalKnowledgeProvider(corpus_dir=custom, storage_dir=tmp_path / "custom-uploads"),
                                      UploadPolicy([], [], 10, 10))
    assert await custom_service.search_bundled_excerpt(QUESTION) == []
    assert await service.search_bundled_excerpt('查找教材原句“桥优先级和交换机地址”') == []
    assert await service.search_bundled_excerpt("请核对教材第 8 页的 STP 结构") == []
    assert await service.search_bundled_excerpt("只依据教材查完全虚构的熔融漂浮剂") == []

    within_corpus = KnowledgeService(LocalKnowledgeProvider(corpus_dir=local_provider.DEFAULT_CORPUS_DIR,
                                     storage_dir=local_provider.DEFAULT_CORPUS_DIR / "uploads"), UploadPolicy([], [], 10, 10))
    assert await within_corpus.search_bundled_excerpt(QUESTION) == []
