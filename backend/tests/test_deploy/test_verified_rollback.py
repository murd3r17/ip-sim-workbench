"""Rollback is a verified state transition, not successful completion of a send call."""
import pytest

from modules.deploy.models import DeployStatus, DeployTask, DeviceWriteLock
from modules.deploy.service import DeployService
from tests.test_deploy.test_execution_lifecycle import isolated_deploy  # noqa: F401


async def _prepare(db, task_id, *, backup="sysname BEFORE", actual="sysname WRONG"):
    task = await db.get(DeployTask, task_id)
    task.status = DeployStatus.DEPLOYING
    task.config_content = "sysname INTENDED"
    task.result_output = actual
    task.backup_config = backup
    await db.commit()
    return task


@pytest.mark.asyncio
async def test_rollback_command_error_cannot_be_reported_as_restored(isolated_deploy):
    factory, (task_id, device_id, user), adapter = isolated_deploy
    adapter.run_command.return_value = "sysname WRONG"
    adapter.send_config.return_value = "Error: synthetic rejection"
    async with factory() as db:
        task = await _prepare(db, task_id)
        report = await DeployService.verify_task(db, task_id, user)
        assert report["rollback"] == "rollback_failed"
        assert task.status == DeployStatus.FAILED
        assert await db.get(DeviceWriteLock, device_id) is None


@pytest.mark.asyncio
async def test_rollback_requires_new_readback_without_residual_configuration(isolated_deploy):
    factory, (task_id, device_id, user), adapter = isolated_deploy
    residue = "sysname BEFORE\n#\ninterface LoopBack99\n description residual"
    adapter.run_command.side_effect = lambda command: residue if adapter.send_config.await_count else "sysname WRONG"
    async with factory() as db:
        task = await _prepare(db, task_id)
        report = await DeployService.verify_task(db, task_id, user)
        assert report["rollback"] == "rollback_failed"
        assert task.status == DeployStatus.FAILED
        assert task.rollback_output == residue
        assert "残留" in task.verify_diff
        assert await db.get(DeviceWriteLock, device_id) is None
    assert [call.args[0] for call in adapter.run_command.await_args_list] == [
        "display current-configuration", "display saved-configuration", "display current-configuration"]


@pytest.mark.asyncio
async def test_unsupported_restore_is_rejected_before_any_write(isolated_deploy):
    factory, (task_id, device_id, user), adapter = isolated_deploy
    adapter.run_command.return_value = "ssh server cipher aes256_ctr"
    async with factory() as db:
        task = await _prepare(db, task_id, backup="ssh server cipher aes128_ctr")
        report = await DeployService.verify_task(db, task_id, user)
        assert report["rollback"] == "rollback_unsupported"
        assert task.status == DeployStatus.FAILED
        assert await db.get(DeviceWriteLock, device_id) is None
    adapter.send_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_undo_residue_cannot_be_reported_as_rolled_back(isolated_deploy):
    factory, (task_id, device_id, user), adapter = isolated_deploy
    target = "interface GigabitEthernet0/0/1"
    residue = target + "\n undo portswitch"
    adapter.run_command.return_value = residue
    async with factory() as db:
        task = await _prepare(db, task_id, backup=target, actual=residue)
        report = await DeployService.verify_task(db, task_id, user)
        assert report["rollback"] == "rollback_unsupported"
        assert task.status == DeployStatus.FAILED
        assert "undo portswitch" in task.verify_diff
        assert await db.get(DeviceWriteLock, device_id) is None
    adapter.send_config.assert_not_awaited()
    adapter.save_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_supported_restore_reaches_rolled_back_only_after_matching_readback(isolated_deploy):
    factory, (task_id, device_id, user), adapter = isolated_deploy
    adapter.run_command.side_effect = lambda command: "sysname BEFORE" if adapter.send_config.await_count else "sysname WRONG"
    async with factory() as db:
        task = await _prepare(db, task_id)
        report = await DeployService.verify_task(db, task_id, user)
        assert report["rollback"] == "rolled_back"
        assert task.status == DeployStatus.ROLLED_BACK
        assert task.completed_at is not None
        assert task.rollback_output == "sysname BEFORE"
        assert await db.get(DeviceWriteLock, device_id) is None
    adapter.send_config.assert_awaited_once_with(["sysname BEFORE"])
    assert [call.args[0] for call in adapter.run_command.await_args_list] == [
        "display current-configuration", "display saved-configuration",
        "display current-configuration", "display saved-configuration"]


@pytest.mark.asyncio
async def test_manual_snapshot_restore_removes_added_loopback_before_verification(isolated_deploy):
    factory, (task_id, device_id, user), adapter = isolated_deploy
    current = "sysname BEFORE\n#\ninterface LoopBack99\n description temporary"
    adapter.run_command.side_effect = lambda command: "sysname BEFORE" if adapter.send_config.await_count else current
    async with factory() as db:
        task = await db.get(DeployTask, task_id)
        task.config_content = "sysname BEFORE"
        task.config_watermark = "rollback_from_version:1/v1"
        await db.commit()
        await DeployService.execute_task(db, task_id, user)
        report = await DeployService.verify_task(db, task_id, user)
        assert report["verification"] == "passed"
        assert task.status == DeployStatus.SUCCESS
        assert await db.get(DeviceWriteLock, device_id) is None
    assert "undo interface loopback99" in adapter.send_config.await_args.args[0]
