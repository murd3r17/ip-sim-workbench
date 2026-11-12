"""B2：受控"回滚到历史版本"。

旧入口 `/config-versions/{id}/rollback` 恒 409（会绕过写锁与授权）；新入口只生成一个
高风险回滚任务，随后走既有的确认→执行→验证链路。
"""

import pytest

from modules.auth.models import User, UserRole
from modules.deploy.models import ChangeLevel, ConfigVersion, DeployStatus, DeployTask
from modules.deploy.service import DeployService
from modules.device.models import Device, DeviceStatus, DeviceType, DeviceVendor, Topology, TopologyType

SNAPSHOT = "sysname R1\ninterface GigabitEthernet0/0/0\n ip address 10.0.0.1 255.255.255.0\n"


async def _seed(db, *, owner_id: int | None = None, snapshot: str = SNAPSHOT, version_number: int = 3):
    topology = Topology(name="rollback-topo", topology_type=TopologyType.LAB, status="active")
    db.add(topology)
    await db.flush()
    device = Device(
        hostname="rollback-dev", mgmt_ip="198.51.100.91",
        device_type=DeviceType.ROUTER, vendor=DeviceVendor.HUAWEI,
        status=DeviceStatus.ONLINE, topology_id=topology.id,
    )
    db.add(device)
    await db.flush()
    version = ConfigVersion(
        device_id=device.id, version_number=version_number,
        config_snapshot=snapshot, change_description="test snapshot",
        created_by=owner_id,
    )
    db.add(version)
    await db.commit()
    return device, version


async def _user(db, name: str, role: UserRole) -> User:
    user = User(username=name, hashed_password="x", role=role)
    db.add(user)
    await db.commit()
    return user


class TestCreateRollbackTask:
    @pytest.mark.asyncio
    async def test_creates_high_risk_awaiting_task_with_snapshot(self, test_session_factory):
        async with test_session_factory() as db:
            admin = await _user(db, "rollback-admin", UserRole.ADMIN)
            device, version = await _seed(db, owner_id=admin.id)

            result = await DeployService.create_rollback_task(
                db, version.id, {"user_id": admin.id, "role": "admin", "username": admin.username}
            )

            task = await db.get(DeployTask, result["task_id"])
            assert task.status == DeployStatus.AWAITING_CONFIRMATION
            assert task.change_level == ChangeLevel.HIGH_RISK
            assert task.config_content == SNAPSHOT
            assert task.device_id == device.id
            assert task.config_watermark == f"rollback_from_version:{version.id}/v{version.version_number}"
            # 关键：不直接执行、不持有写锁（必须人工确认后才加锁）
            assert result["status"] == "awaiting_confirmation"

    @pytest.mark.asyncio
    async def test_non_owner_without_admin_is_rejected(self, test_session_factory):
        async with test_session_factory() as db:
            owner = await _user(db, "rollback-owner", UserRole.USER)
            other = await _user(db, "rollback-other", UserRole.USER)
            _, version = await _seed(db, owner_id=owner.id)

            with pytest.raises(PermissionError):
                await DeployService.create_rollback_task(
                    db, version.id, {"user_id": other.id, "role": "user", "username": other.username}
                )

    @pytest.mark.asyncio
    async def test_missing_version_or_snapshot_is_rejected(self, test_session_factory):
        async with test_session_factory() as db:
            admin = await _user(db, "rollback-admin2", UserRole.ADMIN)
            _, version = await _seed(db, owner_id=admin.id, snapshot="   ")

            with pytest.raises(ValueError):
                await DeployService.create_rollback_task(
                    db, 999999, {"user_id": admin.id, "role": "admin", "username": admin.username}
                )
            with pytest.raises(ValueError):
                await DeployService.create_rollback_task(
                    db, version.id, {"user_id": admin.id, "role": "admin", "username": admin.username}
                )

    @pytest.mark.asyncio
    async def test_destructive_snapshot_is_blocked(self, test_session_factory):
        """含破坏性命令的快照不得生成回滚任务（与真实回滚同一套检查）。"""
        async with test_session_factory() as db:
            admin = await _user(db, "rollback-admin3", UserRole.ADMIN)
            _, version = await _seed(
                db, owner_id=admin.id, snapshot="reset saved-configuration\nreboot\n", version_number=4
            )

            with pytest.raises(ValueError) as exc_info:
                await DeployService.create_rollback_task(
                    db, version.id, {"user_id": admin.id, "role": "admin", "username": admin.username}
                )
            assert "禁止" in str(exc_info.value)
