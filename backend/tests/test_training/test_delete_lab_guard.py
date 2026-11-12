"""实训 Lab 删除守卫的回归测试（2026-09-09 交付前发现）。

`training_session.lab_id` / `operation_log.lab_id` 都是 NOT NULL 外键且无级联，
直接删有会话的 Lab 会撞外键 → 接口 500。现在应给出可读的 ValueError（路由转 400）。
"""

import pytest
from sqlalchemy import select

from modules.auth.models import User, UserRole
from modules.device.models import Topology, TopologyType
from modules.training.models import LabStatus, TrainingLab, TrainingSession
from modules.training.service import TrainingService


async def _seed_lab(db, title: str) -> TrainingLab:
    instructor = User(username=f"ins-{title}", hashed_password="x", role=UserRole.ADMIN)
    db.add(instructor)
    await db.flush()
    topology = Topology(name=f"topo-{title}", topology_type=TopologyType.LAB, status="active")
    db.add(topology)
    await db.flush()
    lab = TrainingLab(
        title=title,
        description="",
        topology_id=topology.id,
        instructor_id=instructor.id,
        status=LabStatus.READY,
    )
    db.add(lab)
    await db.flush()
    return lab


@pytest.mark.asyncio
async def test_delete_lab_without_sessions_succeeds(test_session_factory):
    async with test_session_factory() as db:
        lab = await _seed_lab(db, "del-ok")
        await db.commit()

        await TrainingService.delete_lab(db, lab.id)
        await db.commit()

        assert (await db.execute(select(TrainingLab).where(TrainingLab.id == lab.id))).scalars().first() is None


@pytest.mark.asyncio
async def test_delete_lab_with_sessions_refuses_with_readable_error(test_session_factory):
    async with test_session_factory() as db:
        lab = await _seed_lab(db, "del-guard")
        trainee = User(username="trainee-guard", hashed_password="x", role=UserRole.USER)
        db.add(trainee)
        await db.flush()
        db.add(
            TrainingSession(
                lab_id=lab.id,
                trainee_id=trainee.id,
                status="completed",
            )
        )
        await db.commit()

        with pytest.raises(ValueError) as excinfo:
            await TrainingService.delete_lab(db, lab.id)

        assert "实训会话" in str(excinfo.value)
        # Lab 必须还在（不能删一半）
        assert (await db.execute(select(TrainingLab).where(TrainingLab.id == lab.id))).scalars().first() is not None
