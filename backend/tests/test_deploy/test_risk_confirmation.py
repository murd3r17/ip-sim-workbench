"""The stored risk label and generated batch risk must enforce human confirmation."""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from modules.deploy.models import ChangeLevel, DeployStatus, DeployTask, DeviceWriteLock
from modules.deploy.service import DeployService
from tests.test_deploy.test_execution_lifecycle import isolated_deploy  # noqa: F401


@pytest.mark.asyncio
async def test_high_risk_snapshot_cannot_be_confirmed_as_a_daily_change(isolated_deploy):
    factory, (task_id, device_id, user), _ = isolated_deploy
    async with factory() as db:
        task = await db.get(DeployTask, task_id)
        task.status = DeployStatus.AWAITING_CONFIRMATION
        task.change_level = ChangeLevel.HIGH_RISK
        await db.delete(await db.get(DeviceWriteLock, device_id))
        await db.commit()
        with pytest.raises(ValueError, match="高风险任务需要二次确认"):
            await DeployService.confirm_task(db, task_id, user, False)
        assert task.status == DeployStatus.AWAITING_CONFIRMATION
        assert await db.get(DeviceWriteLock, device_id) is None
        with pytest.raises(ValueError, match="高风险任务需要二次确认"):
            await DeployService.confirm_task(db, task_id, user, False)
        await DeployService.confirm_task(db, task_id, user, True)
        assert task.status == DeployStatus.CONFIRMED
        assert task.risk_confirmed_by == user["user_id"]
        assert task.risk_confirmed_at is not None


@pytest.mark.asyncio
async def test_batch_keeps_assessed_risk_in_task_metadata(isolated_deploy):
    factory, (_, device_id, user), _ = isolated_deploy
    async with factory() as db:
        batch = await DeployService.create_batch(
            db, name="risk regression", description=None, source="manual", planned_at=None,
            items=[SimpleNamespace(device_id=device_id, config_content="ospf 1", template_id=None)],
            engine="netmiko", operator_id=user["user_id"],
        )
        task = (await db.execute(select(DeployTask).where(DeployTask.batch_id == batch["id"]))).scalar_one()
        assert task.change_level == ChangeLevel.HIGH_RISK
