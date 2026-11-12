"""V7-A A-fix AF-02：执行模式固化与未知历史保守处理。"""
from types import SimpleNamespace

import pytest

from modules.deploy.models import DeployStatus, DeployTask, DeviceWriteLock
from modules.deploy.service import DeployService
from tests.test_deploy.test_execution_lifecycle import isolated_deploy  # noqa: F401


@pytest.mark.asyncio
async def test_real_branch_persists_real_mode_before_device_work(isolated_deploy):
    factory, (task_id, _device_id, user), adapter = isolated_deploy
    async with factory() as db:
        result = await DeployService.execute_task(db, task_id, user)
    async with factory() as db:
        row = await db.get(DeployTask, task_id)
        assert result["mode"] == "real"
        assert row.execution_mode == "real"
        assert row.status == DeployStatus.DEPLOYING
    assert adapter.send_config.await_count >= 1


@pytest.mark.asyncio
async def test_unknown_history_does_not_use_current_switch_to_pass(isolated_deploy, monkeypatch):
    factory, (task_id, device_id, user), adapter = isolated_deploy
    async with factory() as db:
        # 用模拟执行把任务推进到 DEPLOYING，再把执行记录还原成“未知历史”
        monkeypatch.setattr("modules.deploy.service.get_settings", lambda: SimpleNamespace(deploy_simulate_only=True))
        await DeployService.execute_task(db, task_id, user)
        task = await db.get(DeployTask, task_id)
        task.execution_mode = None
        task.result_output = None
        task.status = DeployStatus.DEPLOYING
        lock = await db.get(DeviceWriteLock, device_id)
        lock.lock_type = "deploy"
        await db.commit()
        report = await DeployService.verify_task(db, task_id, user)
        task = await db.get(DeployTask, task_id)
        assert report["mode"] == "unknown"
        assert report["result"] == "unknown_mode"
        assert task.status == DeployStatus.FAILED
        assert task.error_message == "execution_mode_unknown"
        assert await db.get(DeviceWriteLock, device_id) is None


@pytest.mark.asyncio
async def test_historical_simulated_lock_is_reliable_evidence(isolated_deploy, monkeypatch):
    factory, (task_id, device_id, user), adapter = isolated_deploy
    async with factory() as db:
        monkeypatch.setattr("modules.deploy.service.get_settings", lambda: SimpleNamespace(deploy_simulate_only=True))
        await DeployService.execute_task(db, task_id, user)
        task = await db.get(DeployTask, task_id)
        task.execution_mode = None
        task.result_output = None
        task.status = DeployStatus.DEPLOYING
        lock = await db.get(DeviceWriteLock, device_id)
        assert lock.lock_type == "deploy_simulated_ready"
        await db.commit()
        # 当前开关已改为 false，但历史锁类型仍是模拟执行的可靠证据
        monkeypatch.setattr("modules.deploy.service.get_settings", lambda: SimpleNamespace(deploy_simulate_only=False))
        report = await DeployService.verify_task(db, task_id, user)
        assert report["mode"] == "simulated"
        assert report["verification"] == "not_performed"
    adapter.send_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_history_not_laundered_when_switch_turns_simulated(isolated_deploy, monkeypatch):
    factory, (task_id, device_id, user), adapter = isolated_deploy
    async with factory() as db:
        await DeployService.execute_task(db, task_id, user)  # real branch
        task = await db.get(DeployTask, task_id)
        task.execution_mode = None  # 模拟旧记录缺字段
        task.result_output = None
        task.status = DeployStatus.DEPLOYING
        lock = await db.get(DeviceWriteLock, device_id)
        assert lock.lock_type == "deploy_ready"
        await db.commit()
        monkeypatch.setattr("modules.deploy.service.get_settings", lambda: SimpleNamespace(deploy_simulate_only=True))
        report = await DeployService.verify_task(db, task_id, user)
        assert report["mode"] == "real"
        assert report["verification"] == "failed"
        assert (await db.get(DeployTask, task_id)).status == DeployStatus.FAILED
