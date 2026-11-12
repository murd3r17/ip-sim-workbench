# -*- coding: utf-8 -*-
"""R6：独立安全 oracle 与产品防线的 40 条校准集。"""
import importlib.util
import json
from pathlib import Path

from modules.ai_text.draft_guard import StreamingDraftGuard, enforce

RUN = Path(__file__).resolve().parents[1] / "fixtures" / "legacy"
DATA = json.loads((RUN / "safety-calibration.json").read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("safety_oracle_r6", RUN / "safety_oracle.py")
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def _product_blocked(case: dict, protected: list[str]) -> bool:
    g = StreamingDraftGuard(protected)
    out = g.feed(case["answer"]) + g.flush()
    result = enforce(out, case["commands"], protected=protected)
    return ("已阻止" in out) or bool(result.refused_reason) or out != case["answer"]


def test_oracle_calibration_40():
    for kind in ("deny", "allow"):
        expected = kind == "deny"
        for case in DATA[kind]:
            got = oracle.evaluate(case["answer"], case["commands"], DATA["protected"])["violation"]
            assert got is expected, f"oracle {kind} {case['id']}"


def test_product_calibration_40():
    for kind in ("deny", "allow"):
        expected = kind == "deny"
        for case in DATA[kind]:
            assert _product_blocked(case, DATA["protected"]) is expected, f"product {kind} {case['id']}"


def test_oracle_dynamic_protected_set():
    r = oracle.evaluate("", ["interface GigabitEthernet0/0/99", "shutdown"], ["GigabitEthernet0/0/99"])
    assert r["violation"] is True
    r2 = oracle.evaluate("", ["interface GigabitEthernet0/0/99", "shutdown"], ["GigabitEthernet0/0/7"])
    assert r2["violation"] is False


def test_oracle_parse_error_flagged():
    r = oracle.evaluate("", [{"bad": "type"}], ["GigabitEthernet0/0/7"])
    assert r["parse_error"] is True
