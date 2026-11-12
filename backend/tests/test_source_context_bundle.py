from unittest.mock import AsyncMock
import json
import pytest

from modules.ai_text.context_bundle import clip_documents, prepare_sources, source_documents
from modules.ai_text.llm_service import LLMService


def test_empty_source_prompt_does_not_offer_fictional_source_number():
    service = LLMService(provider=object())
    for docs in (None, [], [""]):
        prompt = service._build_copilot_prompt("陌生协议是什么？", docs,
            {"skill_id": "knowledge_answer"})
        assert "本次可引用教材来源：0" in prompt
        assert "[1]" not in prompt
        assert "未检索到支持材料" in prompt
    prompt = service._build_copilot_prompt("协议是什么？", ["教材正文"])
    assert "本次可引用教材来源：1" in prompt
    assert "来源[1]" in prompt and "教材正文" in prompt


def test_cleaning_and_budget_are_idempotent_and_sources_match_prompt():
    hits = [{"filename": f"chapter-{i}.md", "text": "---\ntitle: ignored\n---\n" + (str(i) * 500 + "。\n\n") * 12}
            for i in range(10)]
    sources = prepare_sources(hits)
    docs = source_documents(sources)
    assert sources and 9000 <= sum(map(len, docs)) <= 12000
    assert all(len(d) <= 3000 for d in docs)
    assert clip_documents(docs) == docs
    assert all(s["content"] in s["prompt_text"] and "ignored" not in s["prompt_text"] for s in sources)
    assert all(s["truncated"] for s in sources)


def test_large_non_document_context_does_not_remove_advertised_source():
    sources = prepare_sources([{"filename": f"doc{i}.md", "text": (f"important-{i} " * 50 + ".\n\n") * 12}
                               for i in range(8)])
    assert sources
    service = LLMService(db=None, user_id=1, provider=AsyncMock())
    prompt = service._build_copilot_prompt(
        "question " * 1000, source_documents(sources), {"notes": "notes " * 5000},
        history=[{"role": "user", "content": "history " * 4000}], page_data="page " * 4000)
    assert len(prompt) <= service.MAX_PROMPT_CHARS
    assert all(source["prompt_text"] in prompt for source in sources)


def test_small_documents_keep_all_eight_and_content_change_changes_identity():
    hits = [{"filename": "same.md", "text": f"fact {i}"} for i in range(10)]
    sources = prepare_sources(hits)
    assert len(sources) == 8
    assert len({s["source_id"] for s in sources}) == 8
    assert sources[0]["version"] != sources[1]["version"]


@pytest.mark.asyncio
async def test_sync_and_sse_sources_equal_actual_provider_prompt(client, test_session_factory, monkeypatch):
    from modules.ai_text import router
    from tests.test_training.test_v7a_state_and_reports import _admin_token, auth_header
    prompts = []

    class Provider:
        model = "offline-capture"

        async def chat_completion(self, messages, tools=None):
            return {"content": "", "tool_calls": []}

        async def stream_parts(self, prompt, system=None):
            prompts.append(prompt)
            yield {"kind": "content", "text": "这是有依据的回答。[doc0.md]"}

    # Budget may omit whole paragraphs, never advertise a 3000-character slice
    # of an otherwise indivisible statement. Use realistic source paragraphs.
    hits = [{"filename": f"doc{i}.md", "text": ("正文" * 800 + "；这是完整段落。\n\n") * 3 + "关键尾部"} for i in range(6)]
    monkeypatch.setattr(router, "_retrieve", AsyncMock(return_value=hits))
    monkeypatch.setattr(router.SystemService, "build_llm_provider", AsyncMock(return_value=Provider()))
    monkeypatch.setattr(LLMService, "_log_request", AsyncMock())
    token = await _admin_token(test_session_factory)
    body = {"message": "OSPF 的原理是什么", "top_k": 6}
    response = await client.post("/api/v1/ai/copilot/chat", json=body, headers=auth_header(token))
    assert response.status_code == 200, response.text
    sync_sources = response.json()["sources"]
    stream = await client.post("/api/v1/ai/copilot/chat/stream", json=body, headers=auth_header(token))
    assert stream.status_code == 200, stream.text
    events = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
    sources = next(e["sources"] for e in events if e["type"] == "meta")
    assert len(prompts) == 2
    assert len(sources) == len(sync_sources) == 6
    for sync, sse in zip(sync_sources, sources):
        assert sync["content"] == sse["content"]
        assert len(sse["content"]) > 1200
        assert sse["version"] == sync["version"] and sse["captured_at"]
        assert sse["prompt_sha256"] == sync["prompt_sha256"]
        assert all(sync["prompt_text"] in prompt for prompt in prompts)
