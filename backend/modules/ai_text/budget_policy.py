# -*- coding: utf-8 -*-
"""Bounded Agent workflows, independent of monetary/HTTP dispatch ceilings.

- direct：页面/简单问题，不规划工具，1 次生成；
- standard：最多 2 轮取证、6 次工具尝试、4 次逻辑生成；
- diagnostic：最多 3 轮取证、9 次工具尝试、6 次逻辑生成；
重复结果提前停止；逻辑生成包括规划、私有初稿及定稿，不把 HTTP 故障转移当新规划。
2026-11-06 用户取消费用和调用上限；这些边界用于防循环，超时/取消仍有效。
档位升级不重置已用计数，由调用方累计。
"""
from __future__ import annotations

from dataclasses import dataclass
from .skills import select_skill


@dataclass(frozen=True)
class TierLimits:
    name: str
    max_rounds: int      # 工具取证轮数
    max_reads: int       # 实际工具读取次数
    max_generations: int  # 最终回答 + 规划/草稿等生成上界


LIMITS = {
    "direct": TierLimits("direct", 0, 0, 1),
    "standard": TierLimits("standard", 2, 6, 4),
    "diagnostic": TierLimits("diagnostic", 3, 9, 6),
}


def select_tier(message: str, *, page_data: str | None = None, want_draft: bool = False,
                skill_id: str | None = None) -> str:
    # Incidental snapshot presence, text length and a bare "why" do not
    # establish a diagnostic evidence gap or authorize a higher budget.
    skill_id = skill_id or select_skill(message, want_draft=want_draft).id
    if want_draft or skill_id == "troubleshooting":
        return "diagnostic"
    if skill_id == "page_help":
        return "direct"
    return "standard"


def limits_for(tier: str) -> TierLimits:
    return LIMITS.get(tier, LIMITS["standard"])
