# -*- coding: utf-8 -*-
"""CF-02：技能工具白名单回归。"""
import pytest

from modules.ai_text.agent_tools import available_tool_defs, execute_tool


def test_available_tools_filtered_by_skill():
    names = [t["function"]["name"] for t in available_tool_defs({"role": "user"}, allowed=["search_knowledge"])]
    assert names == ["search_knowledge"]


def test_available_tools_none_means_all_visible():
    names = [t["function"]["name"] for t in available_tool_defs({"role": "user"})]
    assert "query_devices" in names and "query_audit_logs" not in names


def test_admin_sees_audit_but_skill_can_exclude():
    names = [t["function"]["name"] for t in available_tool_defs({"role": "admin"}, allowed=["query_audit_logs"])]
    assert names == ["query_audit_logs"]
