# -*- coding: utf-8 -*-
"""CA-T05：工具参数校验（错类型/缺字段/额外字段不得执行）。"""
import pytest

from modules.ai_text import agent_tools

FAKE = {
    "type": "function",
    "function": {
        "name": "fake_probe",
        "description": "test",
        "parameters": {
            "type": "object",
            "properties": {"device_id": {"type": "integer"}, "note": {"type": "string"}},
            "required": ["device_id"],
        },
    },
}


@pytest.fixture(autouse=True)
def _with_fake(monkeypatch):
    monkeypatch.setattr(agent_tools, "TOOL_DEFS", [*agent_tools.TOOL_DEFS, FAKE])


def test_missing_required_field_rejected():
    assert "缺少必填字段" in agent_tools.validate_tool_args("fake_probe", {})


def test_unknown_field_rejected():
    assert "不支持字段" in agent_tools.validate_tool_args("fake_probe", {"device_id": 1, "evil": 2})


def test_wrong_type_rejected():
    assert "应为" in agent_tools.validate_tool_args("fake_probe", {"device_id": "one"})


def test_valid_args_pass():
    assert agent_tools.validate_tool_args("fake_probe", {"device_id": 1, "note": "x"}) == ""


def test_bad_json_shape_rejected():
    assert "JSON 对象" in agent_tools.validate_tool_args("fake_probe", ["not", "dict"])
