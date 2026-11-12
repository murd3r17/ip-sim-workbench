"""A2：设备写锁的字段与过期自动释放（设计 §15.3）。

- 加锁写入 lock_type 与 expire_at；
- 过期且**未进入执行**的锁由调度器清理并留审计；
- 正在执行/验证中的锁即使过期也**不**自动释放（避免同一设备被并发写）；
- 释放原因记在审计（`device_write_lock_released` 的 result 字段）。
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from modules.auth.models import AuditLog, User, UserRole
from modules.deploy.models import DeployStatus, DeployTask, DeviceWriteLock
from modules.deploy.service import DeployService
from modules.device.models import Device, DeviceStatus, DeviceType, DeviceVendor, Topology, TopologyType


async def _seed(db, *, status: DeployStatus, expire_delta: int, hostname: str = "lock-dev"):
    operator = User(username=f"op-{status.value}-{hostname}", hashed_password="x", role=UserRole.ADMIN)
    db.add(operator)
    await db.flush()
    topology = Topology(name=f"topo-{hostname}-{status.value}", topology_type=TopologyType.LAB, status="active")
    db.add(topology)
    await db.flush()
    device = Device(
        hostname=hostname,
        mgmt_ip="198.51.100.71",
        device_type=DeviceType.ROUTER,
        vendor=DeviceVendor.HUAWEI,
        status=DeviceStatus.ONLINE,
        topology_id=topology.id,
    )
    db.add(device)
    await db.flush()
    task = DeployTask(
        device_id=device.id, config_content="sysname X", status=status, operator_id=operator.id,
    )
    db.add(task)
    await db.flush()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(
        DeviceWriteLock(
            device_id=device.id,
            task_id=task.id,
            lock_type="deploy",
            expire_at=now + timedelta(seconds=expire_delta),
        )
    )
    await db.commit()
    return operator, device, task


class TestLockFields:
    @pytest.mark.asyncio
    async def test_confirm_task_writes_lock_type_and_expire_at(self, test_session_factory):
        async with test_session_factory() as db:
            operator = User(username="lock-confirm-op", hashed_password="x", role=UserRole.ADMIN)
            db.add(operator)
            await db.flush()
            topology = Topology(name="lock-confirm-topo", topology_type=TopologyType.LAB, status="active")
            db.add(topology)
            await db.flush()
            device = Device(
                hostname="lock-confirm-dev", mgmt_ip="198.51.100.72",
                device_type=DeviceType.ROUTER, vendor=DeviceVendor.HUAWEI,
                status=DeviceStatus.ONLINE, topology_id=topology.id,
            )
            db.add(device)
            await db.flush()
            task = DeployTask(
                device_id=device.id, config_content="sysname X",
                status=DeployStatus.AWAITING_CONFIRMATION, operator_id=operator.id,
            )
            db.add(task)
            await db.commit()

            await DeployService.confirm_task(
                db, task.id, {"user_id": operator.id, "role": "admin", "username": "lock-confirm-op"}, False
            )

            lock = await db.get(DeviceWriteLock, device.id)
            assert lock is not None
            assert lock.lock_type == "deploy"
            assert lock.expire_at is not None
            assert lock.expire_at > datetime.now(timezone.utc).replace(tzinfo=None)


class TestExpiredLockRelease:
    @pytest.mark.asyncio
    async def test_expired_lock_on_confirmed_task_is_released_with_audit(self, test_session_factory):
        async with test_session_factory() as db:
            _, device, task = await _seed(db, status=DeployStatus.CONFIRMED, expire_delta=-60)

            released = await DeployService.release_expired_locks(db)

            assert [item["device_id"] for item in released] == [device.id]
            assert await db.get(DeviceWriteLock, device.id) is None
            audits = (
                await db.execute(
                    select(AuditLog).where(
                        AuditLog.action == "device_write_lock_released",
                        AuditLog.resource_id == str(task.id),
                    )
                )
            ).scalars().all()
            assert audits and "expired" in (audits[0].detail or "")

    @pytest.mark.asyncio
    async def test_expired_lock_on_deploying_task_is_kept(self, test_session_factory):
        """正在执行的任务即使锁过期也不能自动释放（否则同设备会被并发写）。"""
        async with test_session_factory() as db:
            _, device, _ = await _seed(db, status=DeployStatus.DEPLOYING, expire_delta=-60, hostname="lock-busy")

            released = await DeployService.release_expired_locks(db)

            assert released == []
            assert await db.get(DeviceWriteLock, device.id) is not None

    @pytest.mark.asyncio
    async def test_unexpired_lock_is_kept(self, test_session_factory):
        async with test_session_factory() as db:
            _, device, _ = await _seed(db, status=DeployStatus.CONFIRMED, expire_delta=3600, hostname="lock-fresh")

            released = await DeployService.release_expired_locks(db)

            assert released == []
            assert await db.get(DeviceWriteLock, device.id) is not None


class TestSchedulerRegistration:
    def test_lock_expiry_job_registered_even_when_monitor_disabled(self):
        """写锁过期清理必须与监控采集开关解耦，否则默认配置下永不执行。"""
        from scheduler.monitor_scheduler import register_jobs

        class _StubScheduler:
            def __init__(self):
                self.added: list[str] = []

            def add_job(self, func, trigger, **kwargs):  # noqa: ANN001
                self.added.append(kwargs["id"])

        settings = SimpleNamespace(
            deploy_lock_expire_check_seconds=300,
            monitor_scheduler_enabled=False,
            monitor_collect_interval=120,
        )
        scheduler = _StubScheduler()
        ids = register_jobs(scheduler, settings)

        assert ids == ["deploy_lock_expiry_cycle"]
        assert scheduler.added == ["deploy_lock_expiry_cycle"]

    def test_monitor_jobs_registered_when_enabled(self):
        from scheduler.monitor_scheduler import register_jobs

        class _StubScheduler:
            def __init__(self):
                self.added: list[str] = []

            def add_job(self, func, trigger, **kwargs):  # noqa: ANN001
                self.added.append(kwargs["id"])

        settings = SimpleNamespace(
            deploy_lock_expire_check_seconds=300,
            monitor_scheduler_enabled=True,
            monitor_collect_interval=120,
        )
        scheduler = _StubScheduler()
        ids = register_jobs(scheduler, settings)

        assert ids == ["deploy_lock_expiry_cycle", "monitor_collect_cycle", "monitor_aggregation_cycle"]
