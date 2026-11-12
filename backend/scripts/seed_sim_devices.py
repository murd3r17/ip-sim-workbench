#!/usr/bin/env python3
"""播种离线模拟演示数据：演示拓扑 + 6 台设备（R-1..R-3, S-1..S-3）+ 演示实训 Lab。

用途：DEVICE_MODE=sim（无 eNSP、无设备凭据）时，让 健康检查/LLDP 拓扑/
监控采集/配置快照/下发预检→确认→执行(模拟)→验证/实训 hint·报告 全链路可跑通。

幂等：按名称检查，已存在则跳过。用法：
  cd backend
  .venv\\Scripts\\python.exe scripts\\seed_sim_devices.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_ROOT / ".env")
load_dotenv(WORKBENCH_ROOT / ".env", override=False)

from sqlalchemy import select  # noqa: E402

from core.database import close_db, get_session_factory, init_db  # noqa: E402
# 导入全部模型：Device 的 relationship 引用跨模块（ConfigVersion 等），
# 缺任一模型类都会在 mapper 配置时失败（与 tests/conftest.py 的做法一致）。
from modules.auth.models import User, AuditLog, UserRole  # noqa: E402
from modules.device.models import (  # noqa: E402
    Device, DeviceStatus, DeviceType, DeviceVendor, Topology,
    TopologyLink, TopologyType,
)
from modules.deploy.models import DeployTask, ConfigTemplate, ConfigVersion  # noqa: E402
from modules.monitor.models import MetricRecord, Alarm, MonitorJob  # noqa: E402
from modules.ai_text.models import AILog  # noqa: E402
from modules.system.models import SystemConfig, BackgroundTask  # noqa: E402
from modules.trust.models import EnvironmentProfile, ReadOnlyObservation  # noqa: E402
from modules.training.models import LabStatus, TrainingLab  # noqa: E402

TOPOLOGY_NAME = "模拟实训拓扑"
LAB_TITLE = "模拟网络巡检实训"

DEVICE_PLAN = [
    ("R-1", "192.168.100.11", DeviceType.ROUTER, "NE40E", "core"),
    ("R-2", "192.168.100.12", DeviceType.ROUTER, "NE40E", "core"),
    ("R-3", "192.168.100.13", DeviceType.ROUTER, "NE40E", "core"),
    ("S-1", "192.168.100.14", DeviceType.SWITCH_L3, "CE6800", "access"),
    ("S-2", "192.168.100.15", DeviceType.SWITCH_L3, "CE6800", "access"),
    ("S-3", "192.168.100.16", DeviceType.SWITCH_L3, "CE6800", "access"),
]

# (源设备, 源接口, 目标设备, 目标接口)
LINK_PLAN = [
    ("R-1", "GE3/0/0", "R-2", "GE3/0/1"),
    ("R-2", "GE3/0/2", "R-3", "GE3/0/3"),
    ("S-1", "GE0/0/1", "S-2", "GE0/0/2"),
    ("S-2", "GE0/0/3", "S-3", "GE0/0/1"),
    ("R-2", "GE0/0/4", "S-2", "GE0/0/4"),
]


async def main() -> int:
    await init_db()
    factory = get_session_factory()
    async with factory() as db:
        topology = (
            await db.execute(select(Topology).where(Topology.name == TOPOLOGY_NAME))
        ).scalar_one_or_none()
        if topology is None:
            # Fresh minimal installs need a main topology for the dashboard.
            # Existing topology choices and layouts are never changed by seeding.
            active_main_id = await db.scalar(
                select(Topology.id).where(
                    Topology.topology_type == TopologyType.MAIN,
                    Topology.status == "active",
                ).limit(1)
            )
            topology = Topology(
                name=TOPOLOGY_NAME,
                description="离线模拟演示拓扑（DEVICE_MODE=sim）",
                topology_type=TopologyType.MAIN if active_main_id is None else TopologyType.LAB,
                status="active",
                device_count=len(DEVICE_PLAN),
            )
            db.add(topology)
            await db.flush()
            print(f"[seed] 拓扑已创建 id={topology.id} name={TOPOLOGY_NAME}")
        else:
            print(f"[seed] 拓扑已存在 id={topology.id}，跳过")

        existing = {
            hostname
            for (hostname,) in (
                await db.execute(
                    select(Device.hostname).where(Device.topology_id == topology.id)
                )
            ).all()
        }
        created_devices: dict[str, Device] = {}
        for hostname, ip, dtype, model, role in DEVICE_PLAN:
            if hostname in existing:
                device = (
                    await db.execute(
                        select(Device).where(
                            Device.topology_id == topology.id, Device.hostname == hostname
                        )
                    )
                ).scalar_one()
            else:
                device = Device(
                    hostname=hostname, mgmt_ip=ip, ssh_port=22,
                    device_type=dtype, vendor=DeviceVendor.HUAWEI, model=model,
                    vrp_version="V200R005C20SPC607B607", network_role=role,
                    status=DeviceStatus.ONLINE, topology_id=topology.id,
                )
                db.add(device)
                await db.flush()
                print(f"[seed] 设备已创建 {hostname} {ip} ({dtype.value})")
            created_devices[hostname] = device
        await db.flush()

        # 基线链路
        link_rows = (
            await db.execute(select(TopologyLink).where(TopologyLink.topology_id == topology.id))
        ).scalars().all()
        if not link_rows:
            for src, src_if, dst, dst_if in LINK_PLAN:
                db.add(TopologyLink(
                    topology_id=topology.id,
                    source_device_id=created_devices[src].id, source_interface=src_if,
                    target_device_id=created_devices[dst].id, target_interface=dst_if,
                    link_type="business", status="up", discovery_source="baseline",
                    source_type="baseline",
                ))
            print(f"[seed] 已创建 {len(LINK_PLAN)} 条基线链路")
        else:
            print(f"[seed] 基线链路已存在 {len(link_rows)} 条，跳过")

        # 演示实训 Lab（instructor 取 id=1 或任意首个用户）
        lab = (
            await db.execute(select(TrainingLab).where(TrainingLab.title == LAB_TITLE))
        ).scalar_one_or_none()
        if lab is None:
            from modules.training.builtin_catalog import workflow_demo_lab
            demo = workflow_demo_lab()
            from modules.auth.models import User
            user = (await db.execute(select(User).order_by(User.id).limit(1))).scalar_one_or_none()
            instructor_id = user.id if user else 1
            lab = TrainingLab(
                title=LAB_TITLE,
                description=demo['description'],
                topology_id=topology.id,
                instructor_id=instructor_id,
                status=LabStatus.READY,
                objectives=demo['objectives'],
                content_version=demo['content_version'],
                environment_spec=demo['environment_spec'],
                time_limit_minutes=60,
                is_sandbox=False,
            )
            db.add(lab)
            print(f"[seed] 实训 Lab 已创建 title={LAB_TITLE} instructor_id={instructor_id}")
        else:
            print(f"[seed] 实训 Lab 已存在 id={lab.id}，跳过")

        await db.commit()

    await close_db()
    print("")
    print("[seed] 完成。离线模拟演示步骤：")
    print("  1) 默认使用 bootstrap-local.ps1 的 minimal 模式（DEVICE_MODE=sim）")
    print("  2) 打开 http://127.0.0.1:8000（账号见根 .env 的 ADMIN_USERNAME / ADMIN_PASSWORD）")
    print("  3) 设备页 → SSH 健康检查（模拟设备全部 ONLINE）；拓扑页 → LLDP 运行态校验")
    print("  4) 监控页 → 触发采集/巡检；配置管理 → 快照采集/差异比对/AI 分析")
    print("  5) 实训页 → 开始「模拟网络巡检实训」→ 记录操作/注入故障/提示/复盘/汇总（技能未验证）")
    print("  6) 接入 eNSP 时：DEVICE_MODE 改回 ssh 并配置设备凭据，业务代码无需改动")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
