"""终端会话日志记录器 - JSON Lines格式保存（含敏感信息脱敏与保留期清理）"""
import json
import os
import re
import time
from datetime import datetime, timezone
from core.config import get_settings
from core.redaction import redact_sensitive


def _utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── 敏感信息脱敏 ─────────────────────────────────────────────────────
_PASSWORD_PROMPT = re.compile(r"(?:password|passphrase)\s*[:：]\s*$", re.IGNORECASE)
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_MAX_LINE = 65536


def _mask_sensitive(text: str) -> str:
    return redact_sensitive(text)


def _cleanup_old_logs(settings) -> None:
    """删除超过保留期的会话日志（默认 30 天）。"""
    try:
        log_dir = os.path.join(settings.log_dir, "webssh_sessions")
        cutoff = time.time() - settings.webssh_log_retention_days * 86400
        for name in os.listdir(log_dir):
            path = os.path.join(log_dir, name)
            if name.endswith(".jsonl") and os.path.getmtime(path) < cutoff:
                os.remove(path)
    except Exception:
        pass


class TerminalSessionLogger:
    """终端会话日志记录器 - JSON Lines格式保存（输入输出脱敏后落盘）"""

    def __init__(self, user_id: int, device_ip: str, session_id: str = None):
        self.user_id = user_id
        self.device_ip = device_ip
        self.session_id = session_id or _utcnow_naive().strftime("%Y%m%d_%H%M%S")
        self._awaiting_password = False
        self._password_echo_pending = False
        self._buffers = {"input": "", "output": ""}
        self._private = {"input": False, "output": False}
        settings = get_settings()
        log_dir = os.path.join(settings.log_dir, "webssh_sessions")
        os.makedirs(log_dir, exist_ok=True)
        _cleanup_old_logs(settings)
        self._file_path = os.path.join(log_dir, f"user{user_id}_{device_ip}_{self.session_id}.jsonl")
        self._file = open(self._file_path, "a", encoding="utf-8")
        self._write_entry({"type": "session_start", "user_id": user_id, "device_ip": device_ip, "timestamp": _utcnow_naive().isoformat()})

    def log_input(self, data: str):
        self._append("input", data)

    def log_output(self, data: str):
        self._append("output", data)

    def _append(self, direction: str, data: str):
        """Log complete logical lines, never independently redact transport fragments.

        This only buffers the audit copy; forwarding to the terminal is unchanged.
        Edited input and overlong lines are withheld rather than risking a partial secret.
        """
        if self._file.closed:
            return
        for char in data:
            if direction == "output" and (self._awaiting_password or self._password_echo_pending):
                self._private[direction] = True
            if direction == "input" and self._awaiting_password:
                self._private[direction] = True
                self._buffers[direction] = ""
            if char in "\r\n":
                if direction == "input" and self._awaiting_password:
                    self._password_echo_pending = True
                self._flush_line(direction, char)
                if direction == "input":
                    self._awaiting_password = False
                continue
            if direction == "input" and (ord(char) < 32 and char != "\t" or char == "\x7f"):
                self._private[direction] = True
                self._buffers[direction] = ""
            # After submission buffer one output line only to distinguish actual
            # echo from CR/LF or ANSI-only frames; its audit text stays private.
            if not self._private[direction] or (direction == "output" and self._password_echo_pending):
                self._buffers[direction] += char
                if len(self._buffers[direction]) > _MAX_LINE:
                    self._buffers[direction] = ""
                    self._private[direction] = True
                elif direction == "output" and char in ":：" and _PASSWORD_PROMPT.search(
                    _ANSI_ESCAPE.sub("", self._buffers[direction])
                ):
                    self._awaiting_password = True
                    # Also protect any echoed value after the input has been submitted.
                    self._private[direction] = True
                    self._buffers[direction] = ""

    def _flush_line(self, direction: str, ending: str = ""):
        text = self._buffers[direction]
        if direction == "output" and self._password_echo_pending and _ANSI_ESCAPE.sub("", text).strip():
            # If the device does not echo, the first response line is withheld
            # conservatively. Subsequent normal output remains auditable.
            self._password_echo_pending = False
        if self._private[direction]:
            text = "******"
        elif text:
            text = _ANSI_ESCAPE.sub("", text)
            # Cursor edits / unknown escape sequences can split sensitive keywords.
            if any(ord(char) < 32 and char != "\t" or char == "\x7f" for char in text):
                text = "******"
            else:
                text = _mask_sensitive(text)
        if text or ending:
            self._write_entry({"type": direction, "data": text + ending,
                               "timestamp": _utcnow_naive().isoformat()})
        self._buffers[direction] = ""
        self._private[direction] = False

    def _write_entry(self, entry: dict):
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self):
        if self._file.closed:
            return
        for direction in ("input", "output"):
            self._flush_line(direction)
        self._write_entry({"type": "session_end", "timestamp": _utcnow_naive().isoformat()})
        self._file.close()
