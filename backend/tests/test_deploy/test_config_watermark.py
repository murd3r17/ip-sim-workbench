"""P2-06：DeployTask.config_watermark 此前没有任何写入点。"""

import pytest
from sqlalchemy import select

from modules.auth.models import User, UserRole
from modules.deploy.models import ConfigVersion, DeployTask
from modules.deploy.service import DeployService
from modules.device.models import (
    Device,
    DeviceStatus,
    DeviceType,
    DeviceVendor,
    Topology,
    TopologyType,
)


async def _seed_device(db, hostname: str = "wm-r1") -> Device:
    topology = Topology(name=f"topo-{hostname}", topology_type=TopologyType.LAB, status="active")
    db.add(topology)
    await db.flush()
    device = Device(
        hostname=hostname,
        mgmt_ip="198.51.100.31",
        device_type=DeviceType.ROUTER,
        vendor=DeviceVendor.HUAWEI,
        status=DeviceStatus.ONLINE,
        topology_id=topology.id,
    )
    db.add(device)
    await db.flush()
    return device


@pytest.mark.asyncio
async def test_watermark_points_at_latest_config_version(test_session_factory):
    async with test_session_factory() as db:
        operator = User(username="wm-operator", hashed_password="x", role=UserRole.ADMIN)
        db.add(operator)
        await db.flush()
        device = await _seed_device(db)
        db.add_all([
            ConfigVersion(
                device_id=device.id, version_number=1, config_snapshot="sysname R1",
                source="manual", created_by=operator.id,
            ),
            ConfigVersion(
                device_id=device.id, version_number=2, config_snapshot="sysname R2",
                source="manual", created_by=operator.id,
            ),
        ])
        await db.commit()
        latest = (
            await db.execute(
                select(ConfigVersion).where(ConfigVersion.version_number == 2)
            )
        ).scalars().one()

        await DeployService.create_pending_tasks(
            db, [device.id], "sysname R3", operator_id=operator.id
        )

        task = (await db.execute(select(DeployTask).where(DeployTask.device_id == device.id))).scalars().one()
        assert task.config_watermark == f"config_version:{latest.id}/v2"


@pytest.mark.asyncio
async def test_watermark_is_none_without_snapshot(test_session_factory):
    async with test_session_factory() as db:
        operator = User(username="wm-operator-2", hashed_password="x", role=UserRole.ADMIN)
        db.add(operator)
        await db.flush()
        device = await _seed_device(db, "wm-r2")
        await db.commit()

        await DeployService.create_pending_tasks(
            db, [device.id], "sysname R4", operator_id=operator.id
        )

        task = (await db.execute(select(DeployTask).where(DeployTask.device_id == device.id))).scalars().one()
        assert task.config_watermark is None
