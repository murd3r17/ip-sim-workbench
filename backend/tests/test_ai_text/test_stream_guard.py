# -*- coding: utf-8 -*-
"""CF-03：流式文本防线回归（含分片切断围栏）。"""
from modules.ai_text.draft_guard import StreamingDraftGuard


def test_streaming_guard_buffers_fence_until_closed():
    g = StreamingDraftGuard()
    out = ""
    for chunk in ["先说明：\n```cli\ninter", "face GigabitEthernet0/0/0\n shu", "tdown\n quit\n```\n完成"]:
        out += g.feed(chunk)
    out += g.flush()
    assert "\n shutdown\n" not in out
    assert "已阻止" in out
    assert "完成" in out


def test_streaming_guard_releases_plain_text_immediately():
    g = StreamingDraftGuard()
    # R4 后普通文本立即放行（不再整段阻塞），且内容不变
    assert g.feed("普通文本，") == "普通文本，"
    assert g.flush() == ""


def test_streaming_guard_removes_unclosed_block_command():
    g = StreamingDraftGuard()
    out = g.feed("```cli\ninterface GigabitEthernet0/0/0\nshutdown") + g.flush()
    assert "interface GigabitEthernet0/0/0" in out
    assert "\nshutdown" not in out
    assert "已阻止" in out
