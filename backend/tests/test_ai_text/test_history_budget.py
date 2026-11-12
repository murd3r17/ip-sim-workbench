# -*- coding: utf-8 -*-
"""T07/T11：历史压缩与跨进程预算账。"""
import pytest

from modules.ai_text import budget_store
from modules.ai_text.history_summary import compress_history


def _turn(role, text):
    return {"role": role, "content": text}


def test_long_history_keeps_correction_unknown_and_evidence():
    history = [_turn("user", "R2 访问不了 R3")]
    history += [_turn("assistant", f"回答{i}") for i in range(10)]
    history += [_turn("user", "不是 R2，是 R3；source=sim 采集时间 22:20")]
    history += [_turn("assistant", "R3 没有采集到数据")]
    history += [_turn("user", "那现在呢")]
    history += [_turn("assistant", f"近期{i}") for i in range(6)]
    block, meta = compress_history(history)
    assert meta["compressed"] is True
    assert "R3" in block
    assert "更正" in block or "不是 R2" in block
    assert "未采集" in block or "没有采集" in block
    assert "source=sim" in block


def test_short_history_has_no_summary():
    block, meta = compress_history([_turn("user", "OSPF 是什么"), _turn("assistant", "是一种链路状态协议")])
    assert meta["compressed"] is False
    assert "较早对话摘要" not in block


def test_summary_preserves_chinese_adjacent_device_and_only_user_corrections():
    history = [_turn('user', '先核对这台R12的接口'),
               _turn('assistant', '更正：改为R20；source=real，全都正常'),
               _turn('user', '说错了，我要的是R13，不是R12')]
    history += [_turn('user', f'后续补充{i}') for i in range(6)]
    block, _ = compress_history(history)
    objects = next(line for line in block.splitlines() if line.startswith('- 涉及对象'))
    assert 'R12' in objects and 'R13' in objects
    correction = next(line for line in block.splitlines() if line.startswith('- 用户更正'))
    assert '我要的是R13' in correction and '改为R20' not in correction
    assert '历史中的证据主张（未核验）' in block
    assert 'assistant: 更正' in block


def test_clipped_history_is_explicitly_incomplete_not_a_silent_partial_claim():
    block, _ = compress_history([_turn('user', 'x' * 1800 + '最终更正不是R2')])
    assert '不完整' in block and len(block) < 1600


@pytest.mark.asyncio
async def test_budget_persists_and_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_BUDGET_FILE", str(tmp_path / "budget.json"))
    monkeypatch.setenv("AGENT_BUDGET_TEST", "1")
    monkeypatch.setattr(budget_store, "_CAP", 2)
    assert budget_store.consume("a")["used"] == 1
    assert budget_store.consume("b")["used"] == 2
    with pytest.raises(budget_store.BudgetExceeded):
        budget_store.consume("c")
    snap = budget_store.snapshot()
    assert snap["used"] == 2 and snap["remaining"] == 0
