"""Sync bootstrap for Windows local MySQL (avoids flaky aiomysql on some hosts)."""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from core.config import get_settings
from core.database import resolve_database_url
from core.migrations import prepare_database
from core.security import hash_password

from modules.auth.models import User, AuditLog, UserRole  # noqa: F401
from modules.device.models import Device, Topology, TopologyLink, TopologyVersion, TopologyRuntimeCheck  # noqa: F401
from modules.deploy.models import DeployTask, DeployBatch, ConfigTemplate, ConfigVersion, DeviceWriteLock  # noqa: F401
from modules.monitor.models import MetricRecord, MetricAggregated, Alarm, MonitorJob  # noqa: F401
from modules.training.models import TrainingLab, TrainingSession, FaultInjection, OperationLog  # noqa: F401
from modules.ai_text.models import AILog  # noqa: F401
from modules.system.models import SystemConfig, BackgroundTask  # noqa: F401

def _resolve_admin_password() -> tuple[str, bool]:
    """Only accept explicitly configured credentials; never generate or print a secret."""
    settings = get_settings()
    configured = (settings.admin_password or os.environ.get("ADMIN_PASSWORD") or "").strip()
    if configured:
        return configured, False
    raise ValueError("请先在本机环境变量或 .env 设置 ADMIN_PASSWORD，再初始化数据库；本脚本不会生成或回显口令。")


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移数据库并创建/重置初始管理员（同步驱动）")
    parser.add_argument("--backup-dir", help="SQLite 旧库升级前生成完整备份的目录")
    parser.add_argument("--backup-file", help="MySQL 旧库升级前由操作者导出并核验的备份文件")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="admin 已存在时也重置其口令（默认不重置，避免误改现网账号）",
    )
    args = parser.parse_args()

    settings = get_settings()
    admin_username = (settings.admin_username or "admin").strip() or "admin"
    try:
        admin_password, _generated = _resolve_admin_password()
    except ValueError as exc:
        print(str(exc))
        return 1

    url = resolve_database_url(settings)
    backup = prepare_database(url, args.backup_dir, args.backup_file)
    if backup:
        print(f"upgrade backup: {backup}")
    sync_url = make_url(url)
    sync_url = sync_url.set(drivername=sync_url.drivername.replace("+aiosqlite", "").replace("+aiomysql", "+pymysql"))
    engine = create_engine(sync_url, pool_pre_ping=True)
    if sync_url.get_backend_name() == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection, _record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")
    print("schema: ok")

    with Session(engine) as db:
        user = db.execute(select(User).where(User.username == admin_username)).scalar_one_or_none()
        if user is None:
            db.add(
                User(
                    username=admin_username,
                    hashed_password=hash_password(admin_password),
                    display_name="Administrator",
                    role=UserRole.ADMIN,
                    is_active=True,
                )
            )
            print(f"admin: created ({admin_username})")
            created = True
        elif args.reset_password:
            user.hashed_password = hash_password(admin_password)
            user.token_version += 1
            user.is_active = True
            print(f"admin: password reset ({admin_username})")
            created = True
        else:
            print(f"admin: 已存在，未改口令（需要重置请加 --reset-password）")
            created = False
        db.commit()

    engine.dispose()
    if created:
        print(f"login: {admin_username} / （口令来自本机配置的 ADMIN_PASSWORD，未回显）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
