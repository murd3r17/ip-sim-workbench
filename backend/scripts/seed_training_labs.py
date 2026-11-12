# -*- coding: utf-8 -*-
"""Create missing versioned training labs without overwriting existing rows.

Step verification consumes trusted server observations, not keyword matching
or an assistant's self-evaluation. Historical content upgrades are explicit.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 注册模型
import modules.auth.models  # noqa: F401
import modules.deploy.models  # noqa: F401
import modules.device.models  # noqa: F401
import modules.monitor.models  # noqa: F401
import modules.training.models  # noqa: F401
import modules.ai_text.models  # noqa: F401
import modules.trust.models  # noqa: F401

from sqlalchemy import select
from core.database import init_db, close_db, get_session_factory
from modules.training.models import TrainingLab, LabStatus
from modules.device.models import Device

# Current definitions are versioned independently of the historical V7-A migrator.
from modules.training.builtin_catalog import builtin_labs  # noqa: E402

LABS = builtin_labs()


async def main() -> None:
    engine, _ = await init_db()
    factory = get_session_factory()
    async with factory() as db:
        # 拓扑取"第一台设备所属的拓扑"，没有设备时退回第一个拓扑（不再硬编码 id=7 / 3）
        topology_id = None
        first_device = (await db.execute(select(Device).order_by(Device.id).limit(1))).scalar_one_or_none()
        if first_device:
            topology_id = first_device.topology_id
        else:
            from modules.device.models import Topology
            first_topo = (await db.execute(select(Topology).order_by(Topology.id).limit(1))).scalar_one_or_none()
            topology_id = first_topo.id if first_topo else None
        if topology_id is None:
            print("没有可用拓扑：请先建拓扑或运行 seed_sim_devices.py")
            await close_db()
            return
        # 找 admin 用户
        from modules.auth.models import User
        admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one_or_none()
        if not admin:
            print("无 admin 用户，请先 bootstrap")
            await close_db()
            return

        existing = (await db.execute(select(TrainingLab))).scalars().all()
        count = 0
        for lab in LABS:
            dup = any(e.title == lab["title"] for e in existing)
            if dup:
                print(f"跳过（已存在）: {lab['title']}")
                continue
            # 目标 id 被占用时**不再跳过**，让数据库分配新 id
            # （此前会静默丢掉这个实验，例如 seed_sim_devices 先建了 id=1 的演示 Lab）
            wanted_id = lab.get("id")
            if wanted_id and any(e.id == wanted_id for e in existing):
                print(f"提示：id={wanted_id} 已被占用，{lab['title']} 将使用自增 id")
                wanted_id = None
            new_lab = TrainingLab(
                title=lab["title"],
                description=lab["description"],
                topology_id=topology_id,
                instructor_id=admin.id,
                objectives=lab["objectives"],
                scoring_rules={},
                time_limit_minutes=lab.get("time_limit_minutes", 45),
                is_sandbox=lab.get("is_sandbox", False),
                content_version=lab.get("content_version"),
                environment_spec=lab.get("environment_spec"),
                status=LabStatus.READY,
            )
            if wanted_id:
                new_lab.id = wanted_id
            db.add(new_lab)
            count += 1
            print(f"新增: {lab['title']}" + (f" id={wanted_id}" if wanted_id else ""))
        await db.commit()
        print(f"seed 完成: 新增 {count} 个实验")

        # 确认
        labs = (await db.execute(select(TrainingLab))).scalars().all()
        print("当前实验:", [(l.id, l.title, l.status.value) for l in labs])
    await close_db()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
