# -*- coding: utf-8 -*-
"""BF4-01：终端写锁完整生命周期矩阵（正式测试节点）。

覆盖 R6/R7/R8 要求的组合与剩余项：unknown→alive 同 token 续租、token 换代停止、
短 DB 故障恢复、shutdown 清理、release outbox 并发、活动/未知拒绝、审计失败不释放、
PID 复用/实例缺失、检查后状态换代的 CAS。全部使用隔离 SQLite 与受控进程状态，
不连接真实设备。
"""
from __future__ import annotations

import asyncio
import importlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from modules.auth.models import AuditLog, User, UserRole
from modules.deploy.models import DeviceWriteLock, ServiceInstance
from modules.trust import service
from tests.test_training.test_v7a_state_and_reports import _admin_token, auth_header
from tests.test_trust.test_v7b_trust import _device

router_module = importlib.import_module("modules.webssh.router")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _add_lock(factory, device_id: int, token: str, *, state: str = "active",
                    age_seconds: int = 0, **extra) -> None:
    async with factory() as db:
        db.add(DeviceWriteLock(
            device_id=device_id, task_id=None, lock_type="terminal", owner_type="terminal",
            owner_id=extra.pop("owner_id", 1), owner_token=token, state=state,
            last_seen_at=_now().replace(tzinfo=None) - timedelta(seconds=age_seconds),
            expire_at=_now().replace(tzinfo=None) + timedelta(hours=1), **extra,
        ))
        await db.commit()


async def _lock(factory, device_id: int) -> dict | None:
    async with factory() as db:
        row = await db.get(DeviceWriteLock, device_id)
        if row is None:
            return None
        return {"state": row.state, "token": row.owner_token,
                "last_seen_at": row.last_seen_at, "release_state": row.release_state}


@pytest.mark.asyncio
async def test_unknown_then_alive_same_token_heartbeat_continues(client, test_session_factory):
    """R8 组合：身份暂不可确认→unknown；恢复 alive 后状态回 active 且心跳继续续租。"""
    token = await _admin_token(test_session_factory)
    did = await _device(test_session_factory, hostname="BF8-COMBO")
    await _add_lock(test_session_factory, did, "combo-token", age_seconds=120)
    before = (await _lock(test_session_factory, did))["last_seen_at"]
    stop = asyncio.Event()
    task = asyncio.create_task(router_module._terminal_heartbeat(
        test_session_factory, did, "combo-token", stop))
    router_module._track_heartbeat(task)
    try:
        await asyncio.sleep(0.6)
        first = await _lock(test_session_factory, did)
        assert first["last_seen_at"] > before, "首次续租没有立即执行"
        # 模拟 reconcile 在进程身份暂不可确认时把同一把锁标 unknown
        async with test_session_factory() as db:
            await db.execute(update(DeviceWriteLock).where(DeviceWriteLock.device_id == did)
                             .values(state="unknown"))
            await db.commit()
        unknown_seen = (await _lock(test_session_factory, did))["last_seen_at"]
        await asyncio.sleep(10.8)  # 生产 10s 间隔
        after = await _lock(test_session_factory, did)
        assert after is not None, "同 token 锁被误删"
        assert after["state"] == "active", f"unknown 后未恢复 active: {after}"
        assert after["last_seen_at"] > unknown_seen, "unknown→active 后心跳永久停止"
        assert not task.done(), "心跳任务在锁仍属自己时提前结束"
    finally:
        stop.set()
        await asyncio.gather(task, return_exceptions=True)
    row = await _lock(test_session_factory, did)
    assert row is not None and row["token"] == "combo-token"


@pytest.mark.asyncio
async def test_heartbeat_stops_after_token_replacement(client, test_session_factory, monkeypatch):
    """锁换代（token 被别的会话替换）必须停止续租，不能继续写他人锁。"""
    did = await _device(test_session_factory, hostname="BF8-TOKEN")
    await _add_lock(test_session_factory, did, "old-token")
    monkeypatch.setattr(router_module, "TERMINAL_HEARTBEAT_INTERVAL", 0.3)
    stop = asyncio.Event()
    task = asyncio.create_task(router_module._terminal_heartbeat(
        test_session_factory, did, "old-token", stop))
    try:
        await asyncio.sleep(0.6)
        async with test_session_factory() as db:
            await db.execute(update(DeviceWriteLock).where(DeviceWriteLock.device_id == did)
                             .values(owner_token="new-token", state="active"))
            await db.commit()
        await asyncio.wait_for(task, timeout=3)
        assert task.done() and not task.cancelled()
        row = await _lock(test_session_factory, did)
        assert row["token"] == "new-token"
    finally:
        stop.set()
        await asyncio.gather(task, return_exceptions=True)


class _RaisingCtx:
    def __init__(self, exc: Exception):
        self.exc = exc

    async def __aenter__(self):
        raise self.exc

    async def __aexit__(self, *args):
        return False


@pytest.mark.asyncio
async def test_heartbeat_recovers_after_short_db_fault(client, test_session_factory, monkeypatch):
    """短 DB 故障后有界退避并恢复续租，而不是永久结束心跳。"""
    did = await _device(test_session_factory, hostname="BF8-DBFAULT")
    await _add_lock(test_session_factory, did, "db-token", age_seconds=120)
    monkeypatch.setattr(router_module, "TERMINAL_HEARTBEAT_INTERVAL", 0.3)
    calls = {"n": 0}

    def flaky_factory():
        calls["n"] += 1
        if calls["n"] <= 2:
            return _RaisingCtx(RuntimeError("transient db unavailable"))
        return test_session_factory()

    before = (await _lock(test_session_factory, did))["last_seen_at"]
    stop = asyncio.Event()
    task = asyncio.create_task(router_module._terminal_heartbeat(flaky_factory, did, "db-token", stop))
    try:
        await asyncio.sleep(4.0)  # 1s + 2s 退避后应恢复
        after = await _lock(test_session_factory, did)
        assert calls["n"] >= 3, calls
        assert after is not None and after["last_seen_at"] > before, "短故障后 last_seen 未恢复"
        assert not task.done(), "短故障后心跳任务提前结束"
        assert after["state"] == "active"
    finally:
        stop.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_shutdown_terminal_tasks_cancels_heartbeat_and_release(test_session_factory, monkeypatch, tmp_path):
    """真实心跳/释放任务在 shutdown 后收尾：任务取消、锁保留、outbox 无脏记录。"""
    did = await _device(test_session_factory, hostname="BF8-SHUTDOWN")
    await _add_lock(test_session_factory, did, "shutdown-token", state="active")
    outbox = tmp_path / "shutdown-outbox.jsonl"
    monkeypatch.setenv("TERMINAL_RELEASE_OUTBOX", str(outbox))
    stop = asyncio.Event()
    heartbeat = asyncio.create_task(router_module._terminal_heartbeat(
        test_session_factory, did, "shutdown-token", stop))
    router_module._track_heartbeat(heartbeat)

    class _FailingCtx:
        async def __aenter__(self):
            raise RuntimeError("db unavailable during shutdown")

        async def __aexit__(self, *args):
            return False

    release = asyncio.create_task(router_module._release_terminal_lock(
        lambda: _FailingCtx(), did, 1, "shutdown-token"))
    router_module._track_release(release)
    await asyncio.sleep(0.15)  # 释放任务进入重试等待，心跳在 10s 租约等待中
    await router_module.shutdown_terminal_tasks(timeout=0.5)
    assert heartbeat.done() and release.done()
    assert heartbeat.cancelled() and release.cancelled()
    assert (await _lock(test_session_factory, did)) is not None, "释放未完成时锁必须保留待下次恢复"
    assert did not in service.TERMINAL_RELEASE_FAILURES
    if outbox.exists():
        assert not outbox.read_text(encoding="utf-8").strip(), "被取消的释放不应留下脏 outbox 记录"


@pytest.mark.asyncio
async def test_recover_same_token_state_change_after_check_rejected(client, test_session_factory, monkeypatch):
    """R9：token 不变但状态/租期在检查后被改回 active，必须 409、保留锁、不提交成功审计。"""
    admin = await _admin_token(test_session_factory)
    did = await _device(test_session_factory, hostname="BF8-STATE-CAS")
    await _add_lock(test_session_factory, did, "state-token", state="orphaned", age_seconds=60)
    original = service._audit_lock

    async def refresh_state(db, user, action, device_id, detail, result="success", commit=True):
        if result == "success":
            now = _now().replace(tzinfo=None)
            await db.execute(update(DeviceWriteLock).where(DeviceWriteLock.device_id == device_id).values(
                state="active", last_seen_at=now, expire_at=now + timedelta(hours=1)))
        return await original(db, user, action, device_id, detail, result, commit)

    monkeypatch.setattr(service, "_audit_lock", refresh_state)
    resp = await client.post(f"/api/v1/trust/locks/{did}/recover", headers=auth_header(admin))
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "lock_changed"
    row = await _lock(test_session_factory, did)
    assert row is not None and row["token"] == "state-token"
    async with test_session_factory() as db:
        count = int((await db.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "terminal_lock_recovered")))
            .scalar_one())
    assert count == 0, "删除失败时不能留下成功审计"


def test_release_outbox_concurrent_appends_do_not_lose_records(tmp_path, monkeypatch):
    """释放失败 outbox 并发追加不丢记录（跨任务恢复依赖它）。"""
    from concurrent.futures import ThreadPoolExecutor

    outbox = tmp_path / "release.jsonl"
    monkeypatch.setenv("TERMINAL_RELEASE_OUTBOX", str(outbox))
    total = 40
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: service._append_release_outbox(i % 4, f"token-{i}"), range(total)))
    tokens = service._pending_release_tokens(2)
    expected = {service._token_fingerprint(f"token-{i}") for i in range(total) if i % 4 == 2}
    assert len(tokens) == total // 4, (len(tokens), len(expected))
    assert tokens == expected
    lines = [line for line in outbox.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == total


@pytest.mark.asyncio
async def test_recover_requires_admin_and_audit_failure_keeps_lock(client, test_session_factory, monkeypatch):
    """恢复只允许管理员；成功审计写失败时必须 409 且锁保留。"""
    admin = await _admin_token(test_session_factory)
    async with test_session_factory() as db:
        user = User(username="bf8-recover-user", hashed_password="x", role=UserRole.USER)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    from core.security import create_access_token

    normal = create_access_token(user.id, user.username, "user")
    did = await _device(test_session_factory, hostname="BF8-AUDIT")
    await _add_lock(test_session_factory, did, "audit-token", state="orphaned", age_seconds=60)

    denied = await client.post(f"/api/v1/trust/locks/{did}/recover", headers=auth_header(normal))
    assert denied.status_code == 403
    assert (await _lock(test_session_factory, did)) is not None

    async def failing_log(*args, **kwargs):
        raise RuntimeError("audit storage down")

    monkeypatch.setattr("modules.auth.service.AuditService.log", failing_log)
    failed = await client.post(f"/api/v1/trust/locks/{did}/recover", headers=auth_header(admin))
    assert failed.status_code == 409, failed.text
    assert failed.json()["detail"] == "audit_failed"
    assert (await _lock(test_session_factory, did)) is not None, "审计失败却删了锁"


@pytest.mark.asyncio
async def test_recover_rejects_live_and_unknown_states(client, test_session_factory):
    """活动锁与未知活动状态都拒绝恢复，不能把 unknown 一律放行。"""
    admin = await _admin_token(test_session_factory)
    live_device = await _device(test_session_factory, hostname="BF8-LIVE")
    unknown_device = await _device(test_session_factory, hostname="BF8-UNKNOWN")
    await _add_lock(test_session_factory, live_device, "live-token")
    await _add_lock(test_session_factory, unknown_device, "unknown-token", state="unknown")
    live = await client.post(f"/api/v1/trust/locks/{live_device}/recover", headers=auth_header(admin))
    unknown = await client.post(f"/api/v1/trust/locks/{unknown_device}/recover", headers=auth_header(admin))
    assert live.status_code == 409 and live.json()["detail"] == "active_terminal_requires_disconnect"
    assert unknown.status_code == 409 and unknown.json()["detail"] == "active_state_unknown_requires_disconnect"
    assert await _lock(test_session_factory, live_device) is not None
    assert await _lock(test_session_factory, unknown_device) is not None


@pytest.mark.asyncio
async def test_reconcile_detects_pid_reuse_and_missing_instance(client, test_session_factory):
    """PID 复用（创建时间不符）判 orphaned；实例身份缺失判 unknown，均不可误放行。"""
    reuse_device = await _device(test_session_factory, hostname="BF8-PIDREUSE")
    missing_device = await _device(test_session_factory, hostname="BF8-NOINST")
    async with test_session_factory() as db:
        db.add(ServiceInstance(instance_id="bf8-reused-instance", pid=os.getpid(),
                               process_started_at=datetime(2000, 1, 1),
                               started_at=_now().replace(tzinfo=None),
                               last_heartbeat_at=_now().replace(tzinfo=None)))
        db.add(DeviceWriteLock(device_id=reuse_device, lock_type="terminal", owner_type="terminal",
                               owner_id=1, owner_token="reuse-token", state="active",
                               owner_instance_id="bf8-reused-instance",
                               last_seen_at=_now().replace(tzinfo=None),
                               expire_at=_now().replace(tzinfo=None) + timedelta(hours=1)))
        db.add(DeviceWriteLock(device_id=missing_device, lock_type="terminal", owner_type="terminal",
                               owner_id=1, owner_token="missing-token", state="active",
                               owner_instance_id="bf8-does-not-exist",
                               last_seen_at=_now().replace(tzinfo=None),
                               expire_at=_now().replace(tzinfo=None) + timedelta(hours=1)))
        await db.commit()
    async with test_session_factory() as db:
        await service.reconcile_terminal_locks(db)
    reuse = await _lock(test_session_factory, reuse_device)
    missing = await _lock(test_session_factory, missing_device)
    assert reuse["state"] == "orphaned", reuse
    assert missing["state"] == "unknown", missing


@pytest.mark.asyncio
async def test_recover_cas_rejects_state_change_after_check(client, test_session_factory, monkeypatch):
    """检查通过后 token 换代：DELETE 条件不匹配，返回 lock_changed 且不误删新锁。"""
    admin = await _admin_token(test_session_factory)
    did = await _device(test_session_factory, hostname="BF8-CAS")
    await _add_lock(test_session_factory, did, "cas-token", state="orphaned", age_seconds=60)
    original = service._audit_lock

    async def swap_before_delete(db, user, action, device_id, detail, result="success", commit=True):
        if result == "success":
            await db.execute(update(DeviceWriteLock).where(DeviceWriteLock.device_id == device_id)
                             .values(owner_token="raced-token"))
        return await original(db, user, action, device_id, detail, result, commit)

    monkeypatch.setattr(service, "_audit_lock", swap_before_delete)
    resp = await client.post(f"/api/v1/trust/locks/{did}/recover", headers=auth_header(admin))
    assert resp.status_code == 409
    assert resp.json()["detail"] == "lock_changed"
    # DELETE 条件不匹配后整体回滚（含同事务内的模拟换代），关键结论是锁没有被删除。
    row = await _lock(test_session_factory, did)
    assert row is not None, "检查后状态换代仍然删除了锁"
