# -*- coding: utf-8 -*-
"""CF-03：保护口草稿防线回归（原 S-02 反例）。"""
from modules.ai_text.draft_guard import enforce


def test_text_block_on_management_interface_is_removed():
    answer = (
        "可以这样关闭管理口：\n```cli\nsystem-view\n"
        "interface GigabitEthernet0/0/0\n shutdown\n quit\n```\n"
        "之后如需恢复请手工处理。"
    )
    result = enforce(answer, [])
    assert "\n shutdown\n" not in result.answer
    assert "已阻止" in result.answer
    assert result.refused_reason
    assert "GigabitEthernet0/0/0" in result.refused_reason


def test_structured_commands_on_management_interface_are_rejected():
    result = enforce("草稿如下", ["system-view", "interface GigabitEthernet0/0/0", "shutdown"])
    assert result.commands == []
    assert result.refused_reason
    assert "未生成配置草稿" in result.answer


def test_read_only_commands_on_management_interface_are_kept():
    cmds = ["interface GigabitEthernet0/0/0", "display this"]
    result = enforce("查看即可", cmds)
    assert result.refused_reason == ""
    assert result.commands == cmds


def test_non_protected_interface_shutdown_is_kept():
    cmds = ["interface GigabitEthernet0/0/1", "shutdown"]
    result = enforce("普通业务口", cmds)
    assert result.refused_reason == ""
    assert result.commands == cmds


def test_case_and_space_insensitive_interface_name():
    result = enforce("", ["interface  gigabitethernet0/0/0", "undo ip address"])
    assert result.commands == []
    assert result.refused_reason
