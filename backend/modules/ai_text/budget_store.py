# -*- coding: utf-8 -*-
"""CA-07/T11：跨进程生成预算账。

- 每调用一次模型生成记 1 笔，落盘到运行目录（不是仓库）；
- 并发用文件锁（Windows 下 msvcrt），原子读改写；
- 默认不限累计次数；可用 `AGENT_BUDGET_CAP` 显式设置上限；
- 测试环境（PYTEST_CURRENT_TEST）自动跳过，避免污染真实账本；
- 只记次数与时间，不记录消息或密钥。
"""
from __future__ import annotations

import json
import os
import time
import tempfile
from contextlib import contextmanager
from pathlib import Path

DEFAULT_FILE = Path(os.environ.get("AGENT_BUDGET_FILE") or (Path.cwd() / ".runtime" / "agent-budget.json"))
# C-R3：默认不限次（None），但持续记账；显式配置 AGENT_BUDGET_CAP=N 才强制上限。
# 工程账与产品配置分离，接收方正常配置凭据即可运行。
_CAP = int(os.environ["AGENT_BUDGET_CAP"]) if os.environ.get("AGENT_BUDGET_CAP") not in (None, "") else None


class BudgetExceeded(RuntimeError):
    pass


def _path() -> Path:
    return Path(os.environ.get("AGENT_BUDGET_FILE", str(DEFAULT_FILE)))


def _disabled() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ and os.environ.get("AGENT_BUDGET_TEST") != "1"


def _lock(fh):
    deadline = time.monotonic() + 5
    while True:
        fh.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if time.monotonic() >= deadline:
                raise BudgetExceeded("预算账加锁失败，拒绝继续派发") from exc
            time.sleep(0.02)


def _unlock(fh):
    fh.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


@contextmanager
def _ledger_lock(path):
    # Separate stable inode: replacing the JSON must not release its process lock.
    with path.with_suffix(path.suffix + ".lock").open("a+b") as fh:
        if fh.seek(0, 2) == 0:
            fh.write(b"\0")
            fh.flush()
        _lock(fh)
        try:
            yield
        finally:
            _unlock(fh)


def _used(data):
    value = data.get("used", 0) if isinstance(data, dict) else None
    if type(value) is not int or value < 0:
        raise ValueError("used must be a nonnegative integer")
    if not isinstance(data.get("entries", []), list):
        raise ValueError("entries must be a list")
    return value


def snapshot() -> dict:
    path = _path()
    if not path.exists():
        return {"used": 0, "cap": _CAP, "remaining": _CAP}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        used = _used(data)
    except (ValueError, OSError):
        return {"used": None, "cap": _CAP, "remaining": None, "corrupt": True}
    cap = _CAP
    return {"used": used, "cap": cap, "remaining": (None if cap is None else max(0, cap - used))}


def consume(kind: str = "model") -> dict:
    """记一笔生成调用；超上限抛 BudgetExceeded。返回当前账。"""
    if _disabled():
        return {"used": 0, "cap": _CAP, "remaining": _CAP, "skipped": "pytest"}
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _ledger_lock(path):
            try:
                data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                used = _used(data)
            except (ValueError, TypeError) as exc:
                raise BudgetExceeded("预算账损坏，拒绝继续派发") from exc
            if _CAP is not None and used + 1 > _CAP:
                raise BudgetExceeded(f"生成预算已用尽：{used}/{_CAP}")
            data["used"] = used + 1
            data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            entry = data.setdefault("entries", [])
            entry.append({"kind": kind, "at": data["updated_at"]})
            data["entries"] = entry[-200:]
            fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps(data, ensure_ascii=False))
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return {"used": data["used"], "cap": _CAP,
                    "remaining": (None if _CAP is None else _CAP - data["used"])}
    except OSError as exc:
        raise BudgetExceeded("预算账无法保存，拒绝继续派发") from exc
