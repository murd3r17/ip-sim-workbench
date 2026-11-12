# -*- coding: utf-8 -*-
"""CA-03/T07：长历史压缩（不调用模型）。

保留：目标、显式对象、用户更正、未知/未采集、证据来源与时间；
最近 6 轮原文保留，较早轮次压成结构化摘要，避免直接截断丢关键事实。
"""
from __future__ import annotations

import re
from .trusted_context import DEVICE_LABEL_PATTERN
from .context_limits import bounded_text

DEVICE = re.compile(DEVICE_LABEL_PATTERN + r"|(?<![A-Za-z0-9_-])(?:REAL-R\d+|CE\d+|NE\d+)(?![A-Za-z0-9_-])", re.I)
CORRECTION = re.compile(r"更正|改为|不是|说错|重新|纠正")
UNKNOWN = re.compile(r"未采集|无法|未知|没有数据|过期")
EVIDENCE = re.compile(r"source\s*=\s*\w+|source=|采集时间|collected_at|sim|snapshot", re.I)
KEEP_LAST = 6


def compress_history(history: list | None) -> tuple[str, dict]:
    items = [h for h in (history or []) if isinstance(h, dict)]
    if len(items) <= KEEP_LAST:
        lines = [_line(h) for h in items]
        return ("\n".join(x for x in lines if x), {"compressed": False, "older": 0})

    older, recent = items[:-KEEP_LAST], items[-KEEP_LAST:]
    goal = next((h.get("content", "") for h in older if h.get("role") == "user" and h.get("content")), "")
    devices: list[str] = []
    corrections: list[str] = []
    unknowns: list[str] = []
    evidence: list[str] = []
    for h in older:
        text = (h.get("content") or "").strip()
        if not text:
            continue
        for d in DEVICE.findall(text):
            key = d.upper()
            if key not in devices:
                devices.append(key)
        if h.get("role") == "user" and CORRECTION.search(text):
            corrections.append(bounded_text(text, 160))
        if UNKNOWN.search(text):
            unknowns.append(bounded_text(text, 160))
        if EVIDENCE.search(text):
            evidence.append(f"{h.get('role') or 'user'}: {bounded_text(text, 160)}")

    summary = [
        "【较早对话摘要】",
        f"- 初始目标：{bounded_text(goal, 200) or '未记录'}",
        f"- 涉及对象：{', '.join(devices) or '未记录'}",
        f"- 用户更正（最近）：{' | '.join(corrections[-3:]) or '无'}",
        f"- 未知/未采集：{' | '.join(unknowns[:3]) or '无'}",
        f"- 历史中的证据主张（未核验）：{' | '.join(evidence[:3]) or '无'}",
    ]
    recent_lines = [_line(h) for h in recent]
    block = "\n".join(summary + ["【最近对话】"] + [x for x in recent_lines if x])
    return block, {"compressed": True, "older": len(older), "recent": len(recent)}


def _line(h: dict) -> str:
    role = h.get("role") or "user"
    content = (h.get("content") or "").strip()
    return f"{role}: {bounded_text(content, 1500)}" if content else ""
