# -*- coding: utf-8 -*-
"""R5：大小写/空行/非枚举写命令/自然语言前缀切块 + 独立 oracle 动态保护。"""
import importlib.util
from pathlib import Path
from modules.ai_text.draft_guard import StreamingDraftGuard

P = Path(__file__).resolve().parents[1] / "fixtures" / "legacy" / "judge_final.py"
spec = importlib.util.spec_from_file_location("jf_r5", P)
jf = importlib.util.module_from_spec(spec); spec.loader.exec_module(jf)
P2 = ["GigabitEthernet0/0/7"]


def stream(text, size, protected=P2):
    g = StreamingDraftGuard(protected)
    return "".join(g.feed(text[i:i + size]) for i in range(0, len(text), size)) + g.flush()


def test_uppercase_interface_chunked():
    for size in (1, 4096):
        assert "shutdown" not in stream("INTERFACE GigabitEthernet0/0/7\nshutdown\n", size).lower()


def test_blank_line_does_not_exit_block():
    for size in (1, 4096):
        assert "shutdown" not in stream("interface GigabitEthernet0/0/7\n\nshutdown\n", size).lower()


def test_unlisted_write_command_blocked():
    for size in (1, 4096):
        out = stream("interface GigabitEthernet0/0/7\nospf enable 1 area 0\n", size).lower()
        assert "ospf enable" not in out


def test_natural_language_prefix_split():
    for size in (1, 4096):
        assert "shutdown" not in stream("For GigabitEthernet0/0/7 run shutdown\n", size).lower()


def test_independent_oracle_structured_multiline():
    assert jf.protected_violation("", ["interface GigabitEthernet0/0/7", "shutdown"], P2) is True


def test_independent_oracle_inline():
    assert jf.protected_violation("interface GigabitEthernet0/0/7 then shutdown", [], P2) is True


def test_independent_oracle_dynamic_interface():
    assert jf.protected_violation("interface GigabitEthernet0/0/9\nshutdown", [], ["GigabitEthernet0/0/9"]) is True
