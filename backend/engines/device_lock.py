"""Per-device SSH session lock (NE40E ~2 VTY). WebSSH, display, and collect share one lock per host:port."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

DEFAULT_TIMEOUT = 8.0

_locks: dict[str, asyncio.Lock] = {}
# 引用计数：锁释放且无人等待时把条目从字典里删掉，否则每访问一台新设备就常驻一条
_refs: dict[str, int] = {}
_lock_guard = asyncio.Lock()


class DeviceBusyError(Exception):
    """Raised when the device lock cannot be acquired before timeout."""


def device_lock_key(host: str, port: int) -> str:
    return f"{host}:{int(port)}"


async def _acquire_entry(key: str) -> asyncio.Lock:
    async with _lock_guard:
        _refs[key] = _refs.get(key, 0) + 1
        lock = _locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks[key] = lock
        return lock


async def _release_entry(key: str) -> None:
    async with _lock_guard:
        remaining = _refs.get(key, 1) - 1
        if remaining <= 0:
            _refs.pop(key, None)
            _locks.pop(key, None)
        else:
            _refs[key] = remaining


@asynccontextmanager
async def acquire_device_lock(host: str, port: int, timeout: float = DEFAULT_TIMEOUT) -> AsyncIterator[None]:
    key = device_lock_key(host, port)
    lock = await _acquire_entry(key)
    try:
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
        except TimeoutError as exc:
            raise DeviceBusyError("设备终端占用中，请稍后重试") from exc
        try:
            yield
        finally:
            lock.release()
    finally:
        await _release_entry(key)
