# -*- coding: utf-8 -*-
"""C-R2 5.2：三条无云 Agent 轨迹 + 工具结构化/动态保护项回归。"""
import asyncio
from types import SimpleNamespace

import pytest

from modules.ai_text import agent_tools
from modules.ai_text.llm_service import LLMService
from modules.ai_text.protect_ports import parse_protections
from modules.ai_text.tool_result import classify


class _Provider:
    """按对话轮次决定工具调用，验证观察结果确实改变下一步。"""

    def __init__(self):
        self.rounds = 0
        self.seen_results = []

    async def chat_completion(self, messages, tools=None):
        self.rounds += 1
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        self.seen_results = [m.get("content", "") for m in tool_msgs]
        if self.rounds == 1:
            return {"content": "", "tool_calls": [
                {"id": "c1", "function": {"name": "query_devices", "arguments": "{}"}}]}
        if self.rounds == 2:
            # 只有看到第一轮结果（含 device_id=7）才继续精确读取
            assert any("7" in r for r in self.seen_results), self.seen_results
            return {"content": "", "tool_calls": [
                {"id": "c2", "function": {"name": "query_device_detail", "arguments": "{\"device_id\": 7}"}}]}
        return {"content": "", "tool_calls": []}

    async def stream_parts(self, prompt, system=None):
        yield {"kind": "content", "text": "R1 接口 up，依据两次只读查询。"}


@pytest.mark.asyncio
async def test_agent_two_reads_change_next_step(monkeypatch):
    calls = []

    async def fake_tool(db, name, args, user_id=None, actor=None, allowed=None):
        calls.append((name, dict(args)))
        if name == "query_devices":
            return "R1 device_id=7 hostname=R1"
        return "R1 GigabitEthernet0/0/1 up 10.0.0.1/24"

    monkeypatch.setattr(agent_tools, "execute_tool", fake_tool)
    svc = LLMService(db=None, user_id=1, provider=_Provider(), actor={"user_id": 1, "role": "user"})
    monkeypatch.setattr(svc, "_build_copilot_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(svc, "_log_request", AsyncMock())
    events = [e async for e in svc.copilot_chat_stream("R1 接口正常吗？请排查根因", allowed_tools=None, tier="diagnostic")]
    tools = [e for e in events if e["type"] == "tool" and e["status"] != "running"]
    assert [t["status"] for t in tools] == ["ok", "ok"], events
    assert [c[0] for c in calls] == ["query_devices", "query_device_detail"]
    assert events[-1]["trace"]["tool_calls"] == 2 and events[-1]["trace"]["tier"] == "diagnostic"
    assert "两次只读" in "".join(e.get("text", "") for e in events if e["type"] == "token")


def test_tool_result_statuses_are_not_done_success():
    assert classify("query_devices", {}, "设备终端占用中，请稍后重试").status == "busy"
    assert classify("run_display_command", {}, "拒绝执行：命令不在只读白名单内").status == "forbidden"
    assert classify("query_devices", {}, "工具执行失败: timeout").status in ("error", "timeout")
    assert classify("query_devices", {}, "R1 up").status == "ok"


def test_dynamic_protected_interfaces_from_environment_mapping():
    protections = [
        {"kind": "管理口", "target": "R1:GigabitEthernet0/0/1", "note": "带外"},
        {"kind": "上联", "target": "R1:GigabitEthernet0/0/2"},
    ]
    assert parse_protections(protections) == ["GigabitEthernet0/0/1", "GigabitEthernet0/0/2"]


def test_dynamic_protected_interface_blocks_draft():
    from modules.ai_text.draft_guard import enforce
    r = enforce("", ["interface GigabitEthernet0/0/1", "shutdown"],
                protected=["GigabitEthernet0/0/1"])
    assert r.commands == [] and r.refused_reason


from unittest.mock import AsyncMock  # noqa: E402


class _CounterfactualProvider:
    """首轮工具失败时不再二次读取，直接给结论。"""
    def __init__(self):
        self.rounds = 0
    async def chat_completion(self, messages, tools=None):
        self.rounds += 1
        if self.rounds == 1:
            return {"content": "", "tool_calls": [{"id": "c1", "function": {"name": "query_devices", "arguments": "{}"}}]}
        tool_text = "".join(m.get("content", "") for m in messages if m.get("role") == "tool")
        assert "busy" in tool_text
        return {"content": "", "tool_calls": []}
    async def stream_parts(self, prompt, system=None):
        yield {"kind": "content", "text": "设备忙，先不继续读取。"}


@pytest.mark.asyncio
async def test_failure_feedback_changes_next_step(monkeypatch):
    calls = []
    async def busy_tool(db, name, args, user_id=None, actor=None, allowed=None):
        calls.append(name)
        return "设备终端占用中，请稍后重试"
    monkeypatch.setattr(agent_tools, "execute_tool", busy_tool)
    svc = LLMService(db=None, user_id=1, provider=_CounterfactualProvider(), actor={"user_id": 1, "role": "user"})
    monkeypatch.setattr(svc, "_build_copilot_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(svc, "_log_request", AsyncMock())
    events = [e async for e in svc.copilot_chat_stream("排查 R1", allowed_tools=None, tier="diagnostic")]
    assert calls == ["query_devices"]
    assert any(e["type"] == "tool" and e.get("status") == "busy" for e in events)


class _BadJsonProvider:
    async def chat_completion(self, messages, tools=None):
        return {"content": "", "tool_calls": [{"id": "c1", "function": {"name": "query_devices", "arguments": "{bad"}}]}
    async def stream_parts(self, prompt, system=None):
        yield {"kind": "content", "text": "参数错误。"}


@pytest.mark.asyncio
async def test_bad_json_is_rejected_without_dispatch(monkeypatch):
    called = []
    async def fake_tool(*a, **k):
        called.append(1)
        return "should not run"
    monkeypatch.setattr(agent_tools, "execute_tool", fake_tool)
    svc = LLMService(db=None, user_id=1, provider=_BadJsonProvider(), actor={"user_id": 1, "role": "user"})
    monkeypatch.setattr(svc, "_build_copilot_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(svc, "_log_request", AsyncMock())
    events = [e async for e in svc.copilot_chat_stream("坏 JSON", allowed_tools=None, tier="diagnostic")]
    assert called == []
    assert any(e["type"] == "tool" and e.get("status") == "rejected" for e in events)
