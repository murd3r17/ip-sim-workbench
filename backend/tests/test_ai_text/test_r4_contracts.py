# -*- coding: utf-8 -*-
"""C-R4：guard 切块/长尾/正常解释、草稿占位、判据直接否定、选择对象解析。"""
import json
from datetime import datetime, timezone

import pytest

from modules.ai_text.draft_guard import StreamingDraftGuard, enforce, mask_target_values
from modules.ai_text.trusted_context import sanitize


@pytest.mark.parametrize("size", [1, 5, 17, 4096])
def test_protected_shutdown_with_long_tail_never_leaks(size):
    text = "interface GigabitEthernet0/0/7\nshutdown\n" + ("tail explanation. " * 15)
    g = StreamingDraftGuard(["GigabitEthernet0/0/7"])
    out = "".join(g.feed(text[i:i + size]) for i in range(0, len(text), size)) + g.flush()
    assert "shutdown" not in out.lower()


def test_normal_description_explanation_preserved():
    text = ("Management interface GigabitEthernet0/0/7 is read-only here; "
            "description means interface description, no modification requested. " + "Read-only explanation. " * 10)
    g = StreamingDraftGuard(["GigabitEthernet0/0/7"])
    assert g.feed(text) + g.flush() == text


def test_inline_protected_write_rejected():
    r = enforce("interface GigabitEthernet0/0/7 then shutdown", [], protected=["GigabitEthernet0/0/7"])
    assert r.refused_reason and "shutdown" not in r.answer.lower()


def test_draft_target_values_masked_when_environment_unknown():
    masked = mask_target_values(["ip address 192.168.1.1 255.255.255.0"])
    assert masked == ["ip address <IP地址> <掩码>"]


@pytest.mark.parametrize("fact,answer", [
    ("OSPF is a link-state protocol", "OSPF is not a link-state protocol"),
    ("OSPF 是链路状态路由协议", "OSPF 不是链路状态路由协议"),
])
def test_direct_negation_not_support(fact, answer):
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "fixtures" / "legacy" / "judge_car4.py"
    spec = importlib.util.spec_from_file_location("judge_car4", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.fact_hit(fact, answer) is False


def test_ui_selection_format_is_parsed_to_object():
    now = datetime.now(timezone.utc).isoformat()
    out = sanitize(json.dumps({"source": "sim", "device": "R-1", "collected_at": now}),
                   selection="device | R-1 | 192.0.2.1 NE40E | id=1", server_verified=True)
    assert out.trusted is True
