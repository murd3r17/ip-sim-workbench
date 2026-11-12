import pytest

from modules.deploy.config_verifier import ConfigVerifier, UnsupportedRestoreError
from modules.deploy.models import DeployTask, DeviceWriteLock
from modules.deploy.service import DeployService
from tests.test_deploy.test_execution_lifecycle import isolated_deploy  # noqa: F401


@pytest.mark.parametrize(("current", "target", "expected"), [
    ("sysname R1\nlldp enable", "sysname R1", ["undo lldp enable"]),
    ("sysname R1", "sysname R1\nlldp enable", ["lldp enable"]),
    ("sysname R1\nlldp enable", "sysname R1\nundo lldp enable", ["undo lldp enable"]),
])
def test_only_global_lldp_enable_has_a_bounded_inverse(current, target, expected):
    assert ConfigVerifier.build_restore_commands(current, target) == expected


def test_only_global_lldp_default_disable_is_snapshot_equivalent():
    assert ConfigVerifier.verify_snapshot("sysname R1", "sysname R1\nundo lldp enable") is None
    current = "interface GigabitEthernet0/0/1\n undo lldp enable"
    target = "interface GigabitEthernet0/0/1"
    assert ConfigVerifier.verify_snapshot(current, target) is not None
    with pytest.raises(UnsupportedRestoreError):
        ConfigVerifier.build_restore_commands(current, target)


@pytest.mark.asyncio
async def test_backup_is_committed_before_first_device_write(isolated_deploy):
    factory, (task_id, device_id, user), adapter = isolated_deploy

    async def observe(_commands):
        async with factory() as observer:
            assert (await observer.get(DeployTask, task_id)).backup_config == "sysname X"
            assert (await observer.get(DeviceWriteLock, device_id)).lock_type == "deploy_executing"
        return "ok"

    adapter.send_config.side_effect = observe
    async with factory() as db:
        result = await DeployService.execute_task(db, task_id, user)
    assert "error_category" not in result


@pytest.mark.asyncio
async def test_unsupported_incremental_write_has_no_device_side_effect(isolated_deploy):
    factory, (task_id, _, user), adapter = isolated_deploy
    async with factory() as db:
        task = await db.get(DeployTask, task_id)
        task.config_content = "ssh server cipher aes128_ctr"
        await db.commit()
        result = await DeployService.execute_task(db, task_id, user)
    assert result["error_category"] == "UnsupportedRestoreError"
    adapter.send_config.assert_not_awaited()
    adapter.save_config.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("rollback", [False, True])
async def test_preexisting_unsaved_changes_are_never_saved_by_deploy_or_rollback(isolated_deploy, rollback):
    from modules.deploy.models import DeployStatus

    factory, (task_id, _, user), adapter = isolated_deploy

    async def read(command):
        return "sysname RUNNING" if command == "display current-configuration" else "sysname SAVED"

    adapter.run_command.side_effect = read
    async with factory() as db:
        task = await db.get(DeployTask, task_id)
        if rollback:
            task.status = DeployStatus.DEPLOYING
            task.config_content = "sysname EXPECTED"
            task.backup_config = "sysname ORIGINAL"
            task.result_output = "sysname RUNNING"
            await db.commit()
            report = await DeployService.verify_task(db, task_id, user)
            assert report["rollback"] == "rollback_failed"
        else:
            report = await DeployService.execute_task(db, task_id, user)
            assert "error_category" in report
    adapter.send_config.assert_not_awaited()
    adapter.save_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_rollback_requires_saved_configuration_to_match_restored_running(isolated_deploy):
    from modules.deploy.models import DeployStatus

    factory, (task_id, _, user), adapter = isolated_deploy

    async def read(command):
        if not adapter.send_config.await_count:
            return "sysname WRONG"
        return "sysname BEFORE" if command == "display current-configuration" else "sysname WRONG"

    adapter.run_command.side_effect = read
    async with factory() as db:
        task = await db.get(DeployTask, task_id)
        task.status = DeployStatus.DEPLOYING
        task.config_content = "sysname EXPECTED"
        task.backup_config = "sysname BEFORE"
        task.result_output = "sysname WRONG"
        await db.commit()
        report = await DeployService.verify_task(db, task_id, user)
        assert report["rollback"] == "rollback_failed"
        assert task.status == DeployStatus.FAILED
