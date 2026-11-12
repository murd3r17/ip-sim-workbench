"""M1: real ORM state races, with an isolated SQLite file and a fake device only."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import Base
from modules.deploy.models import DeployStatus, DeployTask, DeviceWriteLock
from modules.deploy.service import DeployService
from tests.test_deploy.test_cancel_task import _seed


@pytest_asyncio.fixture
async def isolated_deploy(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'deploy.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        owner, _, _, device, task = await _seed(db)
        identity = (task.id, device.id, {"user_id": owner.id, "role": "user", "username": owner.username})
    monkeypatch.setattr("modules.deploy.service.get_settings", lambda: SimpleNamespace(deploy_simulate_only=False))
    monkeypatch.setattr(DeployService, "_is_authorized_stage4_target", AsyncMock(return_value=True))
    adapter = SimpleNamespace(
        run_command=AsyncMock(return_value="sysname X"), send_config=AsyncMock(return_value="ok"),
        save_config=AsyncMock(return_value="ok"), close=AsyncMock(),
    )
    monkeypatch.setattr("engines.device_adapter.get_device_adapter", AsyncMock(return_value=adapter))
    try:
        yield factory, identity, adapter
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_same_task_can_only_be_claimed_once_even_with_stale_identity_map(isolated_deploy):
    factory, (task_id, device_id, user), adapter = isolated_deploy
    entered, finish = asyncio.Event(), asyncio.Event()

    async def write(_commands):
        if not entered.is_set():
            entered.set()
            await finish.wait()
        return "ok"

    adapter.send_config.side_effect = write
    async with factory() as first, factory() as second:
        stale = await second.get(DeployTask, task_id)
        assert stale.status == DeployStatus.CONFIRMED
        running = asyncio.create_task(DeployService.execute_task(first, task_id, user))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            with pytest.raises(ValueError, match="状态|执行"):
                await DeployService.execute_task(second, task_id, user)
        finally:
            finish.set()
            await running
    assert adapter.send_config.await_count == 1
    async with factory() as db:
        assert (await db.get(DeployTask, task_id)).status == DeployStatus.DEPLOYING
        assert (await db.get(DeviceWriteLock, device_id)).task_id == task_id


@pytest.mark.asyncio
async def test_cancel_cannot_release_lock_while_device_write_is_running(isolated_deploy):
    factory, (task_id, device_id, user), adapter = isolated_deploy
    entered, finish = asyncio.Event(), asyncio.Event()

    async def write(_commands):
        entered.set()
        await finish.wait()

    adapter.send_config.side_effect = write
    async with factory() as first, factory() as second:
        await second.get(DeployTask, task_id)  # deliberately load pre-execution state
        running = asyncio.create_task(DeployService.execute_task(first, task_id, user))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            with pytest.raises(ValueError, match="执行|验证|状态"):
                await DeployService.cancel_task(second, task_id, user)
        finally:
            finish.set()
            await running
    async with factory() as db:
        assert (await db.get(DeployTask, task_id)).status == DeployStatus.DEPLOYING
        assert await db.get(DeviceWriteLock, device_id) is not None


@pytest.mark.asyncio
async def test_expired_lock_cannot_start_device_write(isolated_deploy):
    factory, (task_id, device_id, user), adapter = isolated_deploy
    async with factory() as db:
        lock = await db.get(DeviceWriteLock, device_id)
        lock.expire_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        await db.commit()
        with pytest.raises(ValueError, match="锁"):
            await DeployService.execute_task(db, task_id, user)
    adapter.send_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_adapter_creation_failure_finishes_task_and_releases_lock(isolated_deploy, monkeypatch):
    factory, (task_id, device_id, user), _ = isolated_deploy
    monkeypatch.setattr("engines.device_adapter.get_device_adapter", AsyncMock(side_effect=RuntimeError("synthetic failure")))
    async with factory() as db:
        result = await DeployService.execute_task(db, task_id, user)
        assert result["error_category"] == "RuntimeError"
        assert (await db.get(DeployTask, task_id)).status == DeployStatus.FAILED
        assert await db.get(DeviceWriteLock, device_id) is None


@pytest.mark.asyncio
async def test_blocked_rollback_releases_lock(isolated_deploy):
    factory, (task_id, device_id, user), adapter = isolated_deploy
    async with factory() as db:
        task = await db.get(DeployTask, task_id)
        task.status = DeployStatus.DEPLOYING
        task.result_output = "sysname WRONG"
        task.backup_config = "reboot"
        await db.commit()
        with pytest.raises(ValueError, match="破坏性"):
            await DeployService.verify_task(db, task_id, user)
        assert (await db.get(DeployTask, task_id)).status == DeployStatus.FAILED
        assert await db.get(DeviceWriteLock, device_id) is None
    adapter.send_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_does_not_resurrect_a_cancelled_task_from_stale_session(isolated_deploy):
    factory, (task_id, device_id, user), _ = isolated_deploy
    async with factory() as db:
        task = await db.get(DeployTask, task_id)
        task.status = DeployStatus.AWAITING_CONFIRMATION
        await db.delete(await db.get(DeviceWriteLock, device_id))
        await db.commit()
    async with factory() as confirming, factory() as cancelling:
        stale = await confirming.get(DeployTask, task_id)
        await DeployService.cancel_task(cancelling, task_id, user)
        assert stale.status == DeployStatus.AWAITING_CONFIRMATION
        with pytest.raises(ValueError, match="状态|确认"):
            await DeployService.confirm_task(confirming, task_id, user, False)
    async with factory() as db:
        assert (await db.get(DeployTask, task_id)).status == DeployStatus.CANCELLED
        assert await db.get(DeviceWriteLock, device_id) is None


@pytest.mark.asyncio
async def test_expiry_cleanup_rechecks_database_after_a_stale_read(isolated_deploy):
    factory, (task_id, device_id, _), _adapter = isolated_deploy
    async with factory() as db:
        lock = await db.get(DeviceWriteLock, device_id)
        lock.expire_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        await db.commit()
    async with factory() as cleanup, factory() as executing:
        stale = await cleanup.get(DeployTask, task_id)
        task = await executing.get(DeployTask, task_id)
        task.status = DeployStatus.DEPLOYING
        await executing.commit()
        assert stale.status == DeployStatus.CONFIRMED
        assert await DeployService.release_expired_locks(cleanup) == []
    async with factory() as db:
        assert await db.get(DeviceWriteLock, device_id) is not None


@pytest.mark.asyncio
async def test_verification_cannot_release_lock_before_write_finishes(isolated_deploy):
    factory, (task_id, device_id, user), adapter = isolated_deploy
    entered, finish = asyncio.Event(), asyncio.Event()

    async def write(_commands):
        entered.set()
        await finish.wait()

    adapter.send_config.side_effect = write
    async with factory() as executing, factory() as verifying:
        running = asyncio.create_task(DeployService.execute_task(executing, task_id, user))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            with pytest.raises(ValueError, match="执行|锁|状态"):
                await DeployService.verify_task(verifying, task_id, user)
            async with factory() as observing:
                assert await observing.get(DeviceWriteLock, device_id) is not None
        finally:
            finish.set()
            await running
    async with factory() as db:
        report = await DeployService.verify_task(db, task_id, user)
        assert report["verification"] == "passed"


@pytest.mark.asyncio
async def test_two_verifiers_cannot_both_start_rollback(isolated_deploy):
    factory, (task_id, device_id, user), adapter = isolated_deploy
    async with factory() as db:
        task = await db.get(DeployTask, task_id)
        task.status = DeployStatus.DEPLOYING
        task.result_output = "sysname WRONG"
        task.backup_config = "sysname BEFORE"
        await db.commit()
    entered, finish = asyncio.Event(), asyncio.Event()

    async def write(_commands):
        entered.set()
        await finish.wait()

    adapter.send_config.side_effect = write
    adapter.run_command.side_effect = lambda command: "sysname BEFORE" if adapter.send_config.await_count else "sysname WRONG"
    async with factory() as first, factory() as second:
        stale = await second.get(DeployTask, task_id)
        running = asyncio.create_task(DeployService.verify_task(first, task_id, user))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            assert stale.status == DeployStatus.DEPLOYING
            with pytest.raises(ValueError, match="状态|验证"):
                await DeployService.verify_task(second, task_id, user)
        finally:
            finish.set()
            await running
    assert adapter.send_config.await_count == 1


@pytest.mark.asyncio
async def test_setting_change_cannot_launder_missing_real_readback(isolated_deploy, monkeypatch):
    factory, (task_id, device_id, user), adapter = isolated_deploy
    adapter.run_command.side_effect = lambda command: "" if adapter.send_config.await_count else "sysname BEFORE"
    async with factory() as db:
        result = await DeployService.execute_task(db, task_id, user)
        assert result["error_category"] == "ValueError"
        monkeypatch.setattr("modules.deploy.service.get_settings", lambda: SimpleNamespace(deploy_simulate_only=True))
        with pytest.raises(ValueError, match="状态"):
            await DeployService.verify_task(db, task_id, user)
        assert (await db.get(DeployTask, task_id)).status == DeployStatus.FAILED
        assert await db.get(DeviceWriteLock, device_id) is None


@pytest.mark.asyncio
async def test_simulated_execution_keeps_its_mode_after_setting_change(isolated_deploy, monkeypatch):
    factory, (task_id, _device_id, user), adapter = isolated_deploy
    async with factory() as db:
        monkeypatch.setattr("modules.deploy.service.get_settings", lambda: SimpleNamespace(deploy_simulate_only=True))
        await DeployService.execute_task(db, task_id, user)
        # A-07：执行模式落库，历史任务不再依赖当前开关
        assert (await db.get(DeployTask, task_id)).execution_mode == "simulated"
        monkeypatch.setattr("modules.deploy.service.get_settings", lambda: SimpleNamespace(deploy_simulate_only=False))
        report = await DeployService.verify_task(db, task_id, user)
        assert report["mode"] == "simulated"
        assert report["verification"] == "not_performed"
    adapter.send_config.assert_not_awaited()
