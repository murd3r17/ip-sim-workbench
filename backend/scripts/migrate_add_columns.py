"""为存量数据库补齐新增列（幂等，可重复执行）。

背景：本项目的 Alembic `0001_initial` 是 `Base.metadata.create_all`，只对**空库**有效；
`create_all` 不会给已存在的表加列。因此新增列（A2 写锁字段、A4 V6.1 预留字段）必须对
存量库显式 ALTER，否则代码一旦插入这些列就会报
`no such column` / `Unknown column`（例如确认下发任务时写 device_write_lock）。

用法（在 backend 目录下）：
    .venv\\Scripts\\python.exe scripts\\migrate_add_columns.py            # 只检查并报告
    .venv\\Scripts\\python.exe scripts\\migrate_add_columns.py --apply    # 执行加列

只做"新增可空列 / 带默认值的列"，不做删除、改类型、改数据。回滚方式见文末 ROLLBACK_SQL。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from core.config import get_settings  # noqa: E402
from core.database import is_sqlite_url, resolve_database_url  # noqa: E402

# (表名, 列名, 列定义) —— 列定义在 SQLite 与 MySQL 下都合法
NEW_COLUMNS: list[tuple[str, str, str]] = [
    # A2：设备写锁记录对齐设计 §15.3（释放原因记在审计，不落表 —— 释放即删行）
    ("device_write_lock", "lock_type", "VARCHAR(32) NOT NULL DEFAULT 'deploy'"),
    ("device_write_lock", "expire_at", "DATETIME NULL"),
    # A4：V6.1 预留字段（只落表，不参与逻辑）
    ("topology", "city_id", "INTEGER NULL"),
    ("topology", "node_id", "INTEGER NULL"),
    ("topology", "topology_source", "VARCHAR(32) NULL"),
    ("device", "city_id", "INTEGER NULL"),
    ("device", "node_id", "INTEGER NULL"),
    ("deploy_task", "city_id", "INTEGER NULL"),
    ("deploy_task", "node_id", "INTEGER NULL"),
    ("audit_log", "city_id", "INTEGER NULL"),
    ("audit_log", "node_id", "INTEGER NULL"),
    ("user", "data_scope", "VARCHAR(255) NULL"),
]

ROLLBACK_SQL = """\
-- 如需回滚本次新增列（先确认没有依赖）：
ALTER TABLE device_write_lock DROP COLUMN lock_type, DROP COLUMN expire_at, DROP COLUMN release_reason;
ALTER TABLE topology DROP COLUMN city_id, DROP COLUMN node_id, DROP COLUMN topology_source;
ALTER TABLE device DROP COLUMN city_id, DROP COLUMN node_id;
ALTER TABLE deploy_task DROP COLUMN city_id, DROP COLUMN node_id;
ALTER TABLE audit_log DROP COLUMN city_id, DROP COLUMN node_id;
ALTER TABLE user DROP COLUMN data_scope;
"""


async def _sqlite_columns(conn, table: str) -> set[str]:
    rows = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
    return {row[1] for row in rows}


async def _mysql_columns(conn, table: str) -> set[str]:
    rows = await conn.exec_driver_sql(f"SHOW COLUMNS FROM `{table}`")
    return {row[0] for row in rows}


async def main(apply: bool) -> int:
    settings = get_settings()
    url = resolve_database_url(settings)
    sqlite = is_sqlite_url(url)
    backend = "sqlite" if sqlite else "mysql"
    print(f"目标库: {backend}（{url.split('@')[-1] if '@' in url else url}）")

    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url, future=True)
    added, present, missing_tables = 0, 0, []

    async with engine.begin() as conn:
        for table, column, ddl in NEW_COLUMNS:
            try:
                existing = await (_sqlite_columns(conn, table) if sqlite else _mysql_columns(conn, table))
            except Exception:
                missing_tables.append(table)
                continue
            if column in existing:
                present += 1
                continue
            if not apply:
                print(f"  [待加] {table}.{column}  {ddl}")
                continue
            await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            print(f"  [已加] {table}.{column}  {ddl}")
            added += 1

    await engine.dispose()

    if missing_tables:
        print(f"  跳过（表不存在，可能是尚未建库）: {sorted(set(missing_tables))}")
    print(f"\n已存在 {present} 列 / 本次新增 {added} 列")
    if not apply and added == 0 and present:
        print("（当前库已是最新；加 --apply 可执行新增）")
    elif not apply:
        print("（未加 --apply，未做任何修改）")
    if not apply:
        print("\n回滚 SQL：\n" + ROLLBACK_SQL)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="为存量库补齐新增列（幂等）")
    parser.add_argument("--apply", action="store_true", help="执行加列（默认只检查）")
    raise SystemExit(asyncio.run(main(parser.parse_args().apply)))
