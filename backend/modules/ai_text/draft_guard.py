"""Shared protected-interface guard for synchronous, streaming and CLI output."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .protected_output import OutputScanner


@dataclass
class DraftGuardResult:
    answer: str
    commands: list[str]
    refused_reason: str = ""
    explanation: str = ""


def enforce(answer: str, commands: list[str] | None, explanation: str = "", protected: list[str] | None = None) -> DraftGuardResult:
    text_scanner = OutputScanner(protected)
    text = text_scanner.feed(answer or "") + text_scanner.flush()
    explanation_scanner = OutputScanner(protected)
    safe_explanation = explanation_scanner.feed(explanation or "") + explanation_scanner.flush()
    command_scanner = OutputScanner(protected, structured=True)
    reason = ""
    if commands is None:
        commands = []
    if not isinstance(commands, list) or any(not isinstance(c, str) for c in commands):
        commands = []
        reason = "配置草稿格式无效，未生成可执行命令。"
    else:
        # Scan across array items and lines using the same interface state.
        command_scanner.feed("\n".join(commands))
        command_scanner.flush()
    reason = reason or command_scanner.reason or text_scanner.reason or explanation_scanner.reason
    if reason:
        commands = []
        safe_explanation = ""
        note = "> 未生成配置草稿：" + reason
        if note not in text:
            text = (text.rstrip() + "\n\n" + note).strip()
    return DraftGuardResult(answer=text, commands=list(commands), refused_reason=reason, explanation=safe_explanation)


class StreamingDraftGuard:
    """Publish only inspected clauses/lines, independent of provider chunk size."""
    def __init__(self, protected: list[str] | None = None):
        self._scanner = OutputScanner(protected)

    @property
    def refused_reason(self):
        return self._scanner.reason

    def feed(self, text: str) -> str:
        return self._scanner.feed(text or "")

    def flush(self) -> str:
        return self._scanner.flush()


IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
MASK_RE = re.compile(r"\b255(?:\.\d{1,3}){3}\b")


def mask_target_values(commands: list[str] | None) -> list[str]:
    """R4-02：环境/保护项未核验时，不允许把具体地址当目标配置。"""
    out = []
    for line in commands or []:
        line = MASK_RE.sub("<掩码>", str(line))
        line = IP_RE.sub("<IP地址>", line)
        out.append(line)
    return out
