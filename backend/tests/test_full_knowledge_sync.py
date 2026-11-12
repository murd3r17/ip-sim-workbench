"""E05 must reconcile persisted uploads before retrying an interrupted import."""
import json
from pathlib import Path

import pytest

from modules.knowledge.anythingllm import AnythingLLMKnowledgeProvider
from scripts.sync_full_knowledge import digest, sync


@pytest.fixture
def setup(tmp_path, monkeypatch):
    stage, corpus, storage = (tmp_path / name for name in ("stage", "corpus", "storage"))
    metadata_dir = storage / "documents/custom-documents"
    metadata_dir.mkdir(parents=True)
    stage.mkdir()
    corpus.mkdir()
    rows = []
    for index in (1, 2):
        data = f"---\ntitle: 正文 {index}\n---\n\nOSPF、BGP 和 MPLS 练习 {index}。".encode()
        source = f"lesson-{index}.md"
        staged = f"doc-{index:03}.md"
        (corpus / source).write_bytes(data)
        (stage / staged).write_bytes(data)
        rows.append({"file": staged, "source": source, "sha256": digest(data)})
    (stage / "corpus-manifest.json").write_text(json.dumps({"documents": rows}), encoding="utf-8")
    monkeypatch.setenv("KNOWLEDGE_ANYTHINGLLM_STORAGE", str(storage))
    return stage, storage, corpus, metadata_dir


@pytest.mark.asyncio
async def test_uncertain_upload_and_embedding_reconcile_without_duplicates(setup, monkeypatch):
    stage, storage, corpus, directory = setup
    provider = AnythingLLMKnowledgeProvider("http://127.0.0.1:12345", workspace_slug="receiver-only")
    workspace = {"id": 42, "slug": "receiver-only", "documents": []}
    calls = {"upload": 0, "embed": 0}
    failing = ["upload", "embed"]

    async def request(method, path, **kwargs):
        if method == "GET":
            return {"workspace": [workspace]}
        if path.endswith("/upload"):
            name, _, _ = kwargs["files"]["file"]
            calls["upload"] += 1
            filename = name + "-fixture.json"
            (directory / filename).write_text(json.dumps({"title": name, "url": "file://hotdir/unused"}))
            response = {"success": True, "documents": [{"location": "custom-documents/" + filename}]}
            if failing and failing[0] == "upload":
                failing.pop(0)
                raise TimeoutError
            return response
        if path.endswith("/update-embeddings"):
            calls["embed"] += 1
            ref, = kwargs["json"]["adds"]
            meta = json.loads((directory / Path(ref).name).read_bytes())
            workspace["documents"].append({"docpath": ref, "metadata": json.dumps(meta)})
            if failing and failing[0] == "embed":
                failing.pop(0)
                raise TimeoutError
            return {"workspace": workspace}
        return {"results": [{"text": "测试检索片段", "metadata": {"title": json.loads(workspace["documents"][0]["metadata"])["title"]}}]}

    monkeypatch.setattr(provider, "_request", request)
    for _ in range(2):
        with pytest.raises(TimeoutError):
            await sync(provider, stage, storage, corpus, apply=True, expected=2)
        assert json.loads((stage / "knowledge-sync.json").read_bytes())["status"] == "INCOMPLETE"
    state = await sync(provider, stage, storage, corpus, apply=True, expected=2)
    assert state["document_count"] == 2 and len(state["search"]) == 3
    assert calls == {"upload": 2, "embed": 2}
    # A new client has no in-memory upload state. The disk and workspace are authoritative.
    restarted = AnythingLLMKnowledgeProvider(provider.base_url, workspace_slug=provider.workspace_slug)
    monkeypatch.setattr(restarted, "_request", request)
    assert (await sync(restarted, stage, storage, corpus, apply=False, expected=2))["verified"] == state["verified"]
    assert calls == {"upload": 2, "embed": 2}


@pytest.mark.asyncio
async def test_unmanaged_workspace_fails_before_mutation(setup, monkeypatch):
    stage, storage, corpus, _ = setup
    provider = AnythingLLMKnowledgeProvider("http://127.0.0.1:12345", workspace_slug="receiver-only")

    async def request(method, path, **kwargs):
        assert method == "GET"
        return {"workspace": [{"id": 42, "slug": "receiver-only",
                               "documents": [{"docpath": "custom-documents/existing.json"}]}]}

    monkeypatch.setattr(provider, "_request", request)
    with pytest.raises(ValueError, match="workspace_not_empty_or_already_used"):
        await sync(provider, stage, storage, corpus, apply=True, expected=2)
    assert not (stage / "knowledge-sync.json").exists()
