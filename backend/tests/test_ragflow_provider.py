"""RagflowKnowledgeProvider unit tests (no live server)."""
from __future__ import annotations

import pytest

from modules.knowledge.ragflow import RagflowKnowledgeProvider


@pytest.mark.asyncio
async def test_ask_returns_sources_without_answer(monkeypatch):
    provider = RagflowKnowledgeProvider(
        base_url="http://127.0.0.1:9380",
        api_key="k",
        dataset_id="ds1",
    )

    async def fake_search(query, workspace_id=None, top_k=4):
        return [
            {
                "id": "c1",
                "content": "ospf silent-interface",
                "filename": "lab.md",
                "score": 0.9,
            }
        ]

    monkeypatch.setattr(provider, "search", fake_search)
    result = await provider.ask("如何配置 silent-interface", top_k=4)
    assert result["answer"] == ""
    assert result["provider"] == "ragflow"
    assert result["sources"][0]["content"]


@pytest.mark.asyncio
async def test_normalize_dataset_resolution():
    provider = RagflowKnowledgeProvider(
        base_url="http://127.0.0.1:9380",
        dataset_id="abc",
        dataset_name="huawei-ip-ops",
    )
    assert provider._dataset(None) == "abc"
    assert provider._dataset("huawei-ip-ops") == "abc"
    assert provider._dataset("other-id") == "other-id"
