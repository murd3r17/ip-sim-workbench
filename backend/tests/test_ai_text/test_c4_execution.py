import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from modules.ai_text.llm_service import LLMService
from modules.ai_text.context_bundle import prepare_sources, source_documents
from modules.ai_text.context_limits import bounded_text


class Provider:
    model = "fixture-c4"

    def __init__(self):
        self.plans, self.prompts, self.drafts = [], [], []

    async def chat_completion(self, messages, tools=None):
        self.plans.append(list(messages))
        number = len(self.plans)
        if number > 2:
            return {'tool_calls': []}  # Enough actual feedback; no new read needed.
        if number == 1:
            name, args = "query_devices", {}
        else:
            assert any(m["role"] == "tool" and 'R2' in m["content"] for m in messages)
            name, args = "run_display_command", {"device_id": 2, "command": "display ospf peer"}
        return {"tool_calls": [{"id": str(number), "function": {"name": name, "arguments": json.dumps(args)}}]}

    async def stream_parts(self, prompt, system=None):
        self.prompts.append(prompt)
        yield {"kind": "content", "text": "需要核对 R2 邻居证据，不能仅凭在线下结论。"}

    async def generate(self, prompt, system=None):
        self.drafts.append(prompt)
        if len(self.drafts) == 1:
            return "not JSON"
        return json.dumps({"commands": ["interface LoopBack0", "description training"],
                           "explanation": "未执行的描述草稿", "warnings": []})


def service(monkeypatch, provider):
    svc = LLMService(db=None, user_id=1, provider=provider, actor={"role": "admin"})
    monkeypatch.setattr(svc, "_log_request", AsyncMock())
    return svc


@pytest.mark.asyncio
async def test_second_diagnostic_round_uses_first_read_feedback(monkeypatch):
    from modules.ai_text import agent_tools
    async def execute(db, name, args, *rest, **kwargs):
        if name == "query_devices":
            return '[{"id":2,"hostname":"R2"}]'
        assert args["device_id"] == 2
        return "Router ID: 2.2.2.2\nState: Down\n采集时间: 2026-11-05T10:00:00+08:00"
    monkeypatch.setattr(agent_tools, "execute_tool", execute)
    provider = Provider()
    svc = service(monkeypatch, provider)
    events = [e async for e in svc.copilot_chat_stream("排查 R2 邻居", tier="diagnostic",
                                                     allowed_tools=["query_devices", "run_display_command"])]
    assert events[-1]["status"] == "ok"
    assert events[-1]["trace"]["model_calls"] == 4
    assert events[-1]["trace"]["tool_calls"] == 2
    assert len(provider.plans) == 3 and "State: Down" in provider.prompts[0]


@pytest.mark.asyncio
async def test_draft_retry_accounting_and_draft_has_same_sources_and_environment(monkeypatch):
    provider = Provider()
    svc = service(monkeypatch, provider)
    events = [e async for e in svc.copilot_chat_stream("生成 LoopBack0 描述草稿", want_draft=True,
            tier="diagnostic", allowed_tools=[], context_docs=["[manual] 描述不修改接口IP"],
            page_data="环境版本: test-v4\n当前对象: R2")]
    assert events[-1]["status"] == "ok"
    assert events[-1]["trace"]["model_calls"] == 3  # answer + malformed JSON + retry
    assert len(provider.drafts) == 2
    assert all("[manual]" in text and "test-v4" in text for text in provider.drafts)
    assert any(e["type"] == "draft" for e in events)


@pytest.mark.asyncio
async def test_standard_workflow_allows_one_malformed_draft_retry_without_new_request(monkeypatch):
    provider = Provider()
    svc = service(monkeypatch, provider)
    events = [e async for e in svc.copilot_chat_stream("生成草稿", want_draft=True,
                                                     tier="standard", allowed_tools=[])]
    assert len(provider.prompts) == 1 and len(provider.drafts) == 2
    assert events[-1]["status"] == "ok"
    assert events[-1]["trace"]["model_calls"] == 3
    assert events[-1]["trace"]["tier"] == 'standard'
    assert any(e["type"] == "draft" for e in events)


@pytest.mark.asyncio
async def test_cancel_before_dispatch_has_zero_actual_model_calls(monkeypatch):
    svc = service(monkeypatch, Provider())
    cancel = asyncio.Event()
    cancel.set()
    events = [e async for e in svc.copilot_chat_stream("解释 OSPF", cancel_event=cancel)]
    assert events[-1]["status"] == "cancelled"
    assert events[-1]["trace"]["model_calls"] == 0


def test_whole_prompt_bound_includes_files_tools_and_exact_advertised_sources(monkeypatch):
    svc = service(monkeypatch, Provider())
    sources = prepare_sources([{"filename": f"doc{i}", "text": "事实及限制条件。\n\n" * 400} for i in range(8)])
    assert sources
    prompt = svc._build_copilot_prompt("请核对\n" * 2000, source_documents(sources),
            {"notes": "备注\n" * 4000}, [{"role": "user", "content": "历史\n" * 4000}],
            page_data="页面记录\n" * 4000,
            text_attachments=[{"name": "long.log", "content": "记录\n" * 100000}],
            tool_results=["工具状态: failed\n" + "整行结果\n" * 1000] * 6)
    assert len(prompt) <= svc.MAX_PROMPT_CHARS
    assert all(source["prompt_text"] in prompt for source in sources)
    assert "上下文不完整" in prompt


def test_bounded_text_keeps_tail_conditions_and_does_not_slice_single_json_record():
    text = "设备状态说明\n" + "常规记录\n" * 1000 + "限制条件: 本记录已过期，不能作为实时依据。\n"
    result = bounded_text(text, 500)
    assert len(result) <= 500 and "本记录已过期" in result and "设备状态说明" in result
    result = bounded_text(json.dumps({"status": "up", "padding": "x" * 5000, "stale": True}), 500)
    assert '"status": "up"' not in result and "不完整" in result
