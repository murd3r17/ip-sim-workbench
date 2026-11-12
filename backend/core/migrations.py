"""Explicit, backed-up upgrades; startup never silently upgrades an existing store."""
from __future__ import annotations

import importlib.util
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Index, MetaData, Table, create_engine, inspect, text
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]


def migration_config(connection=None):
    cfg = Config(str(BACKEND / "alembic.ini"))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def _tables(connection):
    return set(inspect(connection).get_table_names()) - {"alembic_version"}


def _revision(connection):
    if "alembic_version" not in inspect(connection).get_table_names():
        return None
    versions = list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    if len(versions) > 1:
        raise RuntimeError("数据库包含多个迁移分支，请先人工核对备份和版本")
    return versions[0] if versions else None


def _head():
    return ScriptDirectory.from_config(migration_config()).get_current_head()


def upgrade_connection(connection):
    command.upgrade(migration_config(connection), "head")


def _schema_differences(connection, metadata):
    context = MigrationContext.configure(connection, opts={
        "compare_type": True,
        "compare_server_default": True,
    })
    differences = compare_metadata(context, metadata)
    # Alembic autogeneration does not detect changes to primary-key constraints.
    inspector = inspect(connection)
    for name in _tables(connection) & set(metadata.tables):
        expected_pk = [column.name for column in metadata.tables[name].primary_key.columns]
        if inspector.get_pk_constraint(name)["constrained_columns"] != expected_pk:
            differences.append(("primary_key", name))
        # Native enum membership/order is significant, including retained legacy
        # values. Do not rely on type-length heuristics to identify a profile.
        for column in inspector.get_columns(name):
            if column["name"] not in metadata.tables[name].c:
                continue
            actual_enum = getattr(column["type"], "enums", None)
            expected_enum = getattr(metadata.tables[name].c[column["name"]].type, "enums", None)
            if actual_enum is not None and expected_enum is not None and actual_enum != expected_enum:
                differences.append(("enum_values", name, column["name"]))
    return differences


def assert_schema_ready(connection):
    if _revision(connection) != _head():
        raise RuntimeError("数据库结构需要升级。请停止工作台并备份，然后运行 "
                           "backend/scripts/bootstrap_local.py --backup-dir <备份目录>；"
                           "MySQL 请先导出备份并使用 --backup-file <备份文件>。启动未修改旧库。")
    from core.database import Base, _import_all_models
    _import_all_models()
    differences = _schema_differences(connection, Base.metadata)
    from core.legacy_schema import matches_legacy_profile
    if differences and not matches_legacy_profile(connection, Base.metadata, repaired=True):
        raise RuntimeError("数据库已标记最新版但结构不匹配，停止启动：" + str(differences))


def _baseline_metadata():
    """Capture the frozen revision's declarations without executing its DDL.

    Reflecting a temporary SQLite database would lose native MySQL enums and
    the BigInteger SQLite variants before comparing against a MySQL store.
    """
    spec = importlib.util.spec_from_file_location("frozen_baseline", BACKEND / "alembic/versions/0001_initial.py")
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    metadata = MetaData()

    class CaptureDefinitions:
        @staticmethod
        def create_table(name, *columns_and_constraints, **kwargs):
            return Table(name, metadata, *columns_and_constraints, **kwargs)

        @staticmethod
        def create_index(name, table_name, columns, **kwargs):
            return Index(name, *(metadata.tables[table_name].c[column] for column in columns), **kwargs)

        @staticmethod
        def f(name):
            return name

    baseline.op = CaptureDefinitions()
    baseline.upgrade()
    return metadata


def _assert_unversioned_baseline(connection):
    """Adopt only the exact frozen baseline, never stamp an arbitrary old schema."""
    baseline = _baseline_metadata()
    differences = _schema_differences(connection, baseline)
    if differences:
        from core.legacy_schema import PROFILE, matches_legacy_profile
        if matches_legacy_profile(connection, baseline, repaired=False):
            return PROFILE
        raise RuntimeError("旧库与 V6 基线结构不一致，拒绝升级或自动标记版本：" + str(differences))
    return "baseline"


def _assert_upgrade_source(connection, revision):
    if revision in {None, "0001_initial"}:
        return _assert_unversioned_baseline(connection)
    if revision == "0011_v7b_bf5_instance" and _head() == "0012_copilot_request":
        # This additive upgrade changes only copilot_request. Keep the check
        # explicitly tied to this head; a future schema needs its own profile.
        from core.database import Base, _import_all_models
        from core.legacy_schema import matches_legacy_profile
        _import_all_models()
        previous = MetaData()
        for name, table in Base.metadata.tables.items():
            if name != "copilot_request":
                table.to_metadata(previous)
        differences = _schema_differences(connection, previous)
        if not differences or matches_legacy_profile(connection, previous, repaired=True):
            return "versioned"
        raise RuntimeError("旧库版本结构不一致，拒绝升级：" + str(differences))
    raise RuntimeError("未知数据库迁移版本，拒绝升级：" + str(revision))


def prepare_database(url: str, backup_dir: str | None = None, backup_file: str | None = None):
    """Called only by explicit bootstrap. Returns the backup path, if one was made."""
    sync_url = make_url(url.replace("sqlite+aiosqlite", "sqlite").replace("mysql+aiomysql", "mysql+pymysql"))
    engine = create_engine(sync_url)
    backup = None
    try:
        with engine.connect() as conn:
            tables = _tables(conn)
            revision = _revision(conn)
            if revision == _head():
                assert_schema_ready(conn)
                return None
            if revision not in {None, "0001_initial", "0011_v7b_bf5_instance"}:
                raise RuntimeError("未知数据库迁移版本，拒绝升级：" + str(revision))
            if tables:
                _assert_upgrade_source(conn, revision)
        if tables:
            if sync_url.get_backend_name() == "sqlite":
                if not backup_dir:
                    raise RuntimeError("已有数据库升级前必须提供 --backup-dir；未修改旧库")
                target_dir = Path(backup_dir).resolve()
                target_dir.mkdir(parents=True, exist_ok=True)
                backup = target_dir / ("workbench-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8] + ".db")
                source = Path(sync_url.database).resolve()
                with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
                    with sqlite3.connect(backup) as target:
                        original.backup(target)
                        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise RuntimeError("备份完整性检查失败，已停止迁移")
            else:
                if not backup_file or not Path(backup_file).is_file() or Path(backup_file).stat().st_size == 0:
                    raise RuntimeError("MySQL 旧库升级前请完成并核验备份，使用 --backup-file 指定非空备份文件；未修改旧库")
                backup = Path(backup_file).resolve()
        with engine.begin() as conn:
            if tables:
                # Recheck after backup; only the recognized profile receives
                # its two explicit repairs. Unknown drift still stops here.
                if _revision(conn) != revision:
                    raise RuntimeError("备份期间数据库版本发生变化，停止升级")
                profile = _assert_upgrade_source(conn, revision)
                from core.legacy_schema import PROFILE, repair_legacy_constraints
                if profile == PROFILE:
                    repair_legacy_constraints(conn)
            if tables and revision is None:
                command.stamp(migration_config(conn), "0001_initial")
            upgrade_connection(conn)
            assert_schema_ready(conn)
        return backup
    finally:
        engine.dispose()
