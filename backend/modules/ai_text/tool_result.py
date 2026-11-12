# -*- coding: utf-8 -*-
"""C-R2 5.2.5：工具结果结构化。

不把 busy/forbidden/timeout/cancelled/partial 冒充 done-success；
保留 target/source/时间/证据ID/摘要，供模型和 UI 判断下一步。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


class EvidenceText(str):
    """Text compatibility for existing callers plus server-owned provenance.

    Never construct this metadata by parsing model/device-supplied JSON.
    """
    def __new__(cls, text, **metadata):
        value = super().__new__(cls, text)
        value.metadata = metadata
        return value


def text_limit(tool: str) -> int:
    # Device/LLDP summaries already cap rows independently. Preserve their
    # scope/count header and bounded rows together instead of dropping a whole
    # JSON line at the old generic 1500-character boundary.
    return 4500 if tool in {'query_device_detail', 'query_topology'} else 1500


@dataclass
class ToolOutcome:
    tool: str
    status: str  # ok|busy|forbidden|timeout|cancelled|partial|error|rejected
    target: str = ""
    source: str = "server_tool"
    collected_at: str = ""
    evidence_id: int | None = None
    summary: str = ""
    text: str = ""
    error: str = ""
    mode: str = "unknown"
    completeness: str = "unknown"
    truncated: bool = False
    retryable: bool = False
    parser_version: str = ""
    reused: bool = False
    retry_exhausted: bool = False

    def as_json(self) -> str:
        data = asdict(self)
        from .context_limits import bounded_text
        limit = text_limit(self.tool)
        data["text"] = bounded_text(self.text, limit)
        if len(self.text or "") > limit:
            data["truncated"] = True
            data["completeness"] = "partial"
        return json.dumps(data, ensure_ascii=False)


def _target(args: dict) -> str:
    for key in ("device_id", "hostname", "device", "target"):
        if isinstance(args, dict) and args.get(key) not in (None, ""):
            return str(args.get(key))
    return ""


def classify(name: str, args: dict, raw: str) -> ToolOutcome:
    text = str(raw or "")
    status = "ok"
    error = ""
    if "占用" in text and "稍后" in text:
        status = "busy"
    elif text.startswith("拒绝执行") or "无权" in text or "不在当前技能允许范围" in text:
        status = "forbidden"
    elif "参数错误" in text:
        status = "rejected"
    elif text.startswith("工具执行失败") and ("超时" in text or "timeout" in text.lower()):
        status = "timeout"
    elif "工具执行失败" in text or text.startswith("未知工具"):
        status = "error"
        error = text[:200]
    elif "部分" in text or "空回显" in text:
        status = "partial"
    elif not text.strip() or text.strip() in {"当前无设备记录", "当前无告警", "当前无配置下发任务", "无配置快照版本", "无拓扑", "知识库未命中相关文档"}:
        status = "empty"
    elif "截断" in text or "---- More ----" in text:
        status = "partial"
    summary = text.splitlines()[0][:160] if text else ""
    outcome = ToolOutcome(
        tool=name, status=status, target=_target(args or {}), source="server_tool",
        collected_at="", summary=summary, text=text, error=error,
    )
    if isinstance(raw, EvidenceText):
        for key in ("status", "target", "source", "collected_at", "evidence_id", "mode",
                    "completeness", "truncated", "retryable", "parser_version", "error",
                    "reused", "retry_exhausted"):
            if key in raw.metadata:
                setattr(outcome, key, raw.metadata[key])
    outcome.retryable = outcome.retryable or outcome.status in {"busy", "timeout"}
    if outcome.retry_exhausted:
        outcome.retryable = False
    outcome.truncated = outcome.truncated or len(text) > text_limit(name)
    if outcome.truncated:
        outcome.completeness = "partial"
    return outcome


def event(name: str, outcome: ToolOutcome) -> dict:
    return {
        "type": "tool", "name": name, "status": outcome.status,
        "target": outcome.target, "source": outcome.source,
        "collected_at": outcome.collected_at, "evidence_id": outcome.evidence_id,
        "summary": outcome.summary,
        "mode": outcome.mode, "completeness": outcome.completeness,
        "truncated": outcome.truncated, "retryable": outcome.retryable,
        "reused": outcome.reused, "retry_exhausted": outcome.retry_exhausted,
    }
