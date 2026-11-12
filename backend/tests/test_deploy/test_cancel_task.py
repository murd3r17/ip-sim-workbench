"""取消下发任务 / 释放设备写锁的回归测试。

背景（2026-09-09 交付前实测）：`confirm_task` 会加 `DeviceWriteLock`，而释放只发生在
execute/verify 路径上；"确认了但没执行"的任务会把设备永久锁死（终端拒接、新任务 409），
且前后端都没有取消入口。新增 `POST /deploy/tasks/{id}/cancel` 提供人工恢复路径。
"""

import uuid

import pytest
from sqlalchemy import select

from modules.auth.models import AuditLog, User, UserRole
from modules.deploy.models import DeployStatus, DeployTask, DeviceWriteLock
from modules.deploy.service import DeployService
from modules.device.models import Device, DeviceStatus, DeviceType, DeviceVendor, Topology, TopologyType


async def _seed(db, *, status: DeployStatus = DeployStatus.CONFIRMED, with_lock: bool = True):
    # 内存库是 session 级共享且本模块不做逐例清表，用唯一后缀避免与其它用例撞唯一约束
    suffix = uuid.uuid4().hex[:8]
    owner = User(username=f"op-{status.value}-{suffix}", hashed_password="x", role=UserRole.USER)
    other = User(username=f"other-{status.value}-{suffix}", hashed_password="x", role=UserRole.USER)
    admin = User(username=f"admin-{status.value}-{suffix}", hashed_password="x", role=UserRole.ADMIN)
    db.add_all([owner, other, admin])
    await db.flush()
    topology = Topology(name=f"topo-{status.value}-{suffix}", topology_type=TopologyType.LAB, status="active")
    db.add(topology)
    await db.flush()
    device = Device(
        hostname=f"dev-{status.value}-{suffix}",
        mgmt_ip="198.51.100.91",
        device_type=DeviceType.ROUTER,
        vendor=DeviceVendor.HUAWEI,
        status=DeviceStatus.ONLINE,
        topology_id=topology.id,
    )
    db.add(device)
    await db.flush()
    task = DeployTask(
        device_id=device.id,
        config_content="sysname X",
        status=status,
        operator_id=owner.id,
    )
    db.add(task)
    await db.flush()
    if with_lock:
        db.add(DeviceWriteLock(device_id=device.id, task_id=task.id))
    await db.commit()
    return owner, other, admin, device, task


@pytest.mark.asyncio
async def test_cancel_confirmed_task_releases_lock(test_session_factory):
    async with test_session_factory() as db:
        owner, _, _, device, task = await _seed(db)
        result = await DeployService.cancel_task(db, task.id, {"user_id": owner.id, "role": "user", "username": "op"})
        assert result["status"] == DeployStatus.CANCELLED.value
        assert result["released_lock"] is True

        refreshed = await db.get(DeployTask, task.id)
        assert refreshed.status == DeployStatus.CANCELLED
        assert refreshed.completed_at is not None
        assert await db.get(DeviceWriteLock, device.id) is None

        audits = (
            await db.execute(select(AuditLog).where(AuditLog.action == "deploy_task_cancelled"))
        ).scalars().all()
        assert len(audits) == 1


@pytest.mark.asyncio
async def test_cancel_terminal_task_is_rejected(test_session_factory):
    async with test_session_factory() as db:
        owner, _, _, _, task = await _seed(db, status=DeployStatus.SUCCESS, with_lock=False)
        with pytest.raises(ValueError) as excinfo:
            await DeployService.cancel_task(db, task.id, {"user_id": owner.id, "role": "user"})
        assert "终态" in str(excinfo.value)


@pytest.mark.asyncio
async def test_cancel_requires_owner_or_admin(test_session_factory):
    async with test_session_factory() as db:
        _, other, admin, _, task = await _seed(db)
        with pytest.raises(PermissionError):
            await DeployService.cancel_task(db, task.id, {"user_id": other.id, "role": "user"})
        # 管理员可以取消他人任务
        result = await DeployService.cancel_task(db, task.id, {"user_id": admin.id, "role": "admin"})
        assert result["status"] == DeployStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_cancel_awaiting_confirmation_has_no_lock(test_session_factory):
    async with test_session_factory() as db:
        owner, _, _, device, task = await _seed(db, status=DeployStatus.AWAITING_CONFIRMATION, with_lock=False)
        result = await DeployService.cancel_task(db, task.id, {"user_id": owner.id, "role": "user"})
        assert result["released_lock"] is False
        assert (await db.get(DeployTask, task.id)).status == DeployStatus.CANCELLED
