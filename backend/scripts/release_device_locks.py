"""释放残留的设备写锁（运维工具）。

背景：`confirm_task` 会给任务加 `DeviceWriteLock`，正常释放只发生在 execute/verify 路径上。
"确认了但没执行"或"执行了但没验证"的任务会把设备一直锁住 —— 终端（WebSSH）被拒接、
同设备的新任务 confirm 一直 409。UI 上每个任务都有「取消任务」按钮；本脚本用于批量清理
（例如服务异常重启后、e2e 跑完后）。

用法（在 backend 目录下）：
    .venv\\Scripts\\python.exe scripts\\release_device_locks.py            # 只报告
    .venv\\Scripts\\python.exe scripts\\release_device_locks.py --apply    # 释放
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

import modules.ai_text.models  # noqa: F401,E402
import modules.auth.models  # noqa: F401,E402
import modules.deploy.models  # noqa: F401,E402
import modules.device.models  # noqa: F401,E402
import modules.monitor.models  # noqa: F401,E402
import modules.system.models  # noqa: F401,E402
import modules.training.models  # noqa: F401,E402
from core.database import get_engine, init_db  # noqa: E402

TERMINAL = {"success", "failed", "rolled_back", "cancelled"}


async def main(apply: bool) -> int:
    await init_db()
    engine = get_engine()
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from modules.auth.models import User, UserRole
    from modules.deploy.models import DeployTask, DeviceWriteLock
    from modules.deploy.service import DeployService
    from modules.device.models import Device

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # 连接池的 dispose 必须放在会话块**之外**：在块内销毁池会把仍被会话占用的连接留成
    # 孤儿，解释器退出时 GC 到已关闭的事件循环，脚本虽然结果正确却会额外抛
    # RuntimeError: Event loop is closed 并以非 0 退出。
    try:
        async with factory() as db:
            locks = (await db.execute(select(DeviceWriteLock))).scalars().all()
            if not locks:
                print("没有残留写锁")
                return 0

            admin = (
                await db.execute(select(User).where(User.role == UserRole.ADMIN).order_by(User.id).limit(1))
            ).scalars().first()

            print(f"发现 {len(locks)} 个写锁：")
            planned: list[tuple[int, int, str]] = []
            for lock in locks:
                task = await db.get(DeployTask, lock.task_id)
                device = await db.get(Device, lock.device_id)
                host = device.hostname if device else "?"
                kind = getattr(lock, "lock_type", "deploy") or "deploy"
                expires = getattr(lock, "expire_at", None)
                # 过期时间只影响调度器自动清理；本脚本是人为介入，一律照常处理
                meta = f"[{kind}{'，已过期' if expires else ''}]"
                if task is None:
                    planned.append((lock.device_id, -1, f"{host} {meta}: 任务不存在 → 直接删锁"))
                    continue
                status = getattr(task.status, "value", str(task.status))
                if status in TERMINAL:
                    planned.append((lock.device_id, -1, f"{host} {meta}: 任务 {task.id} 已是 {status} → 直接删锁"))
                else:
                    planned.append((lock.device_id, task.id, f"{host} {meta}: 任务 {task.id} 处于 {status} → 取消任务并释放锁"))
            for _, _, desc in planned:
                print("  " + desc)

            if not apply:
                print("\n（未加 --apply，未做任何修改）")
                return 0

            if admin is None:
                print("库中没有管理员用户，无法写审计；中止")
                return 1

            user = {"user_id": admin.id, "role": "admin", "username": admin.username}
            released = 0
            for device_id, task_id, desc in planned:
                if task_id > 0:
                    await DeployService.cancel_task(db, task_id, user)
                else:
                    lock = await db.get(DeviceWriteLock, device_id)
                    if lock is not None:
                        await db.delete(lock)
                        await db.commit()
                released += 1
                print(f"  已处理：{desc}")

            remaining = (await db.execute(select(DeviceWriteLock))).scalars().all()
            print(f"\n完成，处理 {released} 个；剩余写锁 {len(remaining)}")
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="释放残留的设备写锁")
    parser.add_argument("--apply", action="store_true", help="执行释放（默认只报告）")
    raise SystemExit(asyncio.run(main(parser.parse_args().apply)))
