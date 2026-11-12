"""Create empty MySQL schema, alembic upgrade head, drop schema. Never prints secrets."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymysql
from alembic.config import Config
from alembic import command

from core.config import get_settings

TEST_DB = "sim_workspace_migrate_test"


def _connect(settings, database: str | None = None):
    return pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=database,
        charset="utf8mb4",
        autocommit=True,
    )


def _env_value(key: str) -> str:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return ""
    prefix = f"{key}="
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip().strip("'").strip('"')
    return ""


def _connect_root(settings):
    root_pwd = _env_value("MYSQL_ROOT_PASSWORD")
    if not root_pwd:
        raise RuntimeError("MYSQL_ROOT_PASSWORD missing in root .env")
    return pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user="root",
        password=root_pwd,
        charset="utf8mb4",
        autocommit=True,
    )


def _prepare_test_db(settings) -> None:
    conn = _connect_root(settings)
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
            cur.execute(
                f"CREATE DATABASE `{TEST_DB}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cur.execute(
                f"GRANT ALL PRIVILEGES ON `{TEST_DB}`.* TO '{settings.db_user}'@'%'"
            )
            cur.execute(
                f"GRANT ALL PRIVILEGES ON `{TEST_DB}`.* TO '{settings.db_user}'@'localhost'"
            )
            cur.execute(
                f"GRANT ALL PRIVILEGES ON `{TEST_DB}`.* TO '{settings.db_user}'@'127.0.0.1'"
            )
            cur.execute("FLUSH PRIVILEGES")
    finally:
        conn.close()


def _drop_test_db(settings) -> None:
    conn = _connect_root(settings)
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
    finally:
        conn.close()


def _sqlite_replay() -> int:
    from sqlalchemy import create_engine, inspect

    db_path = Path(__file__).resolve().parents[2] / ".runtime" / "tmp" / "alembic_empty.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    os.environ["ALEMBIC_URL"] = f"sqlite:///{db_path.as_posix()}"
    try:
        cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(cfg, "head")
        engine = create_engine(os.environ["ALEMBIC_URL"])
        tables = set(inspect(engine).get_table_names())
        engine.dispose()
    finally:
        os.environ.pop("ALEMBIC_URL", None)
        if db_path.exists():
            db_path.unlink()
    required = {
        "user", "audit_log", "device", "topology", "deploy_task",
        "copilot_conversation", "ai_log", "training_lab",
    }
    missing = required - tables
    if missing:
        print(f"sqlite upgrade head missing tables: {sorted(missing)}")
        return 1
    print(f"alembic empty-db replay ok via sqlite: {len(tables)} tables")
    return 0


def main() -> int:
    settings = get_settings()
    try:
        _prepare_test_db(settings)
    except Exception as exc:
        code = exc.args[0] if getattr(exc, "args", None) else type(exc).__name__
        print(f"CREATE DATABASE failed ({code}). Falling back to sqlite empty replay.")
        return _sqlite_replay()

    os.environ["ALEMBIC_DB_NAME"] = TEST_DB
    try:
        cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(cfg, "head")
    finally:
        os.environ.pop("ALEMBIC_DB_NAME", None)

    conn = _connect(settings, TEST_DB)
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            tables = sorted(row[0] for row in cur.fetchall())
    finally:
        conn.close()

    required = {
        "user", "audit_log", "device", "topology", "deploy_task",
        "copilot_conversation", "ai_log", "training_lab",
    }
    missing = required - set(tables)
    if missing:
        print(f"upgrade head missing tables: {sorted(missing)}")
        _drop_test_db(settings)
        return 1
    print(f"alembic empty-db replay ok: {len(tables)} tables")
    _drop_test_db(settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
