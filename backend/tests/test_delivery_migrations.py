"""Maintenance upgrades must preserve existing rows and run without the live database."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[1]


def config_for(path, monkeypatch):
    monkeypatch.setenv("ALEMBIC_URL", f"sqlite:///{path.as_posix()}")
    return Config(str(ROOT / "alembic.ini"))


def test_initial_revision_is_frozen():
    source = (ROOT / "alembic/versions/0001_initial.py").read_text(encoding="utf-8")
    assert "modules." not in source
    assert "Base.metadata" not in source


def test_upgrade_existing_baseline_preserves_data_and_backfills_only_proven_promotions(tmp_path, monkeypatch):
    path = tmp_path / "upgrade.db"
    cfg = config_for(path, monkeypatch)
    command.upgrade(cfg, "0001_initial")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    assert "token_version" not in {c["name"] for c in inspect(engine).get_columns("user")}
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO user (id, username, hashed_password, role, is_active) VALUES (1, 'preserved', 'hash-kept', 'admin', 1)"))
        conn.execute(text("INSERT INTO topology (id, name, topology_type) VALUES (1, 'baseline', 'lab')"))
        conn.execute(text("INSERT INTO topology_version (id, topology_id, version, batch_id, source_name, source_type, snapshot_json) VALUES (1, 1, 1, 'b1', 'ensp-runtime-check-1', 'ensp', '{}'), (2, 1, 2, 'b2', 'regular-import', 'excel', '{}')"))
        conn.execute(text("INSERT INTO topology_runtime_check (id, topology_id, version_id, status, observed_links_json, diff_json) VALUES (1, 1, 1, 'completed', '[]', '{}'), (2, 1, 2, 'completed', '[]', '{}')"))
        conn.execute(text("INSERT INTO copilot_conversation (id, user_id, title, messages) VALUES ('kept', 1, 'keep-title', '[]')"))
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT hashed_password, token_version FROM user WHERE id=1")).one() == ("hash-kept", 0)
        assert conn.execute(text("SELECT title, revision FROM copilot_conversation WHERE id='kept'")).one() == ("keep-title", 0)
        assert conn.execute(text("SELECT version_id, confirmed_version_id, baseline_fingerprint FROM topology_runtime_check WHERE id=1")).one() == (None, 1, None)
        assert conn.execute(text("SELECT version_id, confirmed_version_id FROM topology_runtime_check WHERE id=2")).one() == (2, None)
    assert any(fk["constrained_columns"] == ["confirmed_version_id"] for fk in inspect(engine).get_foreign_keys("topology_runtime_check"))
    engine.dispose()


@pytest.mark.asyncio
async def test_runtime_sqlite_enforces_foreign_keys_and_records_revision(tmp_path, monkeypatch):
    from core import database
    from core.config import get_settings
    path = tmp_path / "runtime.db"
    settings = get_settings().model_copy(update={"db_url": f"sqlite+aiosqlite:///{path.as_posix()}", "debug": False})
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)
    engine, _ = await database.init_db()
    try:
        async with engine.connect() as conn:
            assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
            assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "0012_copilot_request"
    finally:
        await database.close_db()


def test_explicit_upgrade_requires_backup_and_adopts_exact_unversioned_baseline(tmp_path, monkeypatch):
    from core.migrations import prepare_database
    path = tmp_path / "unversioned.db"
    command.upgrade(config_for(path, monkeypatch), "0001_initial")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE alembic_version"))
        conn.execute(text("INSERT INTO user (username, hashed_password, role) VALUES ('kept', 'hash-kept', 'user')"))
    with pytest.raises(RuntimeError, match="backup-dir"):
        prepare_database(f"sqlite+aiosqlite:///{path.as_posix()}")
    assert "alembic_version" not in inspect(engine).get_table_names()
    backup = prepare_database(f"sqlite+aiosqlite:///{path.as_posix()}", str(tmp_path / "backups"))
    assert backup.is_file()
    backup_engine = create_engine(f"sqlite:///{backup.as_posix()}")
    assert "alembic_version" not in inspect(backup_engine).get_table_names()
    with backup_engine.connect() as conn:
        assert conn.execute(text("SELECT username FROM user")).scalar_one() == "kept"
    assert prepare_database(f"sqlite+aiosqlite:///{path.as_posix()}") is None
    backup_engine.dispose()
    engine.dispose()


def test_unrecognized_unversioned_schema_is_not_stamped(tmp_path, monkeypatch):
    from core.migrations import prepare_database
    path = tmp_path / "unknown.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE user (id INTEGER PRIMARY KEY, note TEXT)"))
        conn.execute(text("INSERT INTO user VALUES (1, 'preserved')"))
    with pytest.raises(RuntimeError, match="拒绝"):
        prepare_database(f"sqlite+aiosqlite:///{path.as_posix()}", str(tmp_path / "backups"))
    assert inspect(engine).get_table_names() == ["user"]
    with engine.connect() as conn:
        assert conn.execute(text("SELECT note FROM user")).scalar_one() == "preserved"
    engine.dispose()


def test_stamped_baseline_drift_is_rejected_before_any_upgrade_ddl(tmp_path, monkeypatch):
    from core.migrations import prepare_database
    path = tmp_path / "stamped-drift.db"
    command.upgrade(config_for(path, monkeypatch), "0001_initial")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO user (username, hashed_password, role) VALUES ('kept', 'hash-kept', 'user')"))
        conn.execute(text("DROP INDEX ix_user_username"))
    with pytest.raises(RuntimeError):
        prepare_database(f"sqlite+aiosqlite:///{path.as_posix()}", str(tmp_path / "backups"))
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0001_initial"
        assert conn.execute(text("SELECT username FROM user")).scalar_one() == "kept"
    assert "token_version" not in {c["name"] for c in inspect(engine).get_columns("user")}
    engine.dispose()


@pytest.mark.parametrize("drift", ["unique", "type"])
def test_baseline_schema_drift_is_rejected_before_stamp(tmp_path, monkeypatch, drift):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import String
    from core.migrations import prepare_database

    path = tmp_path / "baseline-drift.db"
    command.upgrade(config_for(path, monkeypatch), "0001_initial")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE alembic_version"))
        if drift == "unique":
            conn.execute(text("DROP INDEX ix_user_username"))
        else:
            with Operations(MigrationContext.configure(conn)).batch_alter_table("user") as batch:
                batch.alter_column("username", type_=String(32), existing_type=String(64))
    with pytest.raises(RuntimeError, match="拒绝"):
        prepare_database(f"sqlite+aiosqlite:///{path.as_posix()}", str(tmp_path / "backups"))
    assert "alembic_version" not in inspect(engine).get_table_names()
    assert "token_version" not in {c["name"] for c in inspect(engine).get_columns("user")}
    engine.dispose()


@pytest.mark.parametrize("drift", ["unique", "nullable", "default", "foreign_key"])
def test_head_schema_drift_is_not_reported_ready(tmp_path, monkeypatch, drift):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from core.migrations import assert_schema_ready

    path = tmp_path / "head-drift.db"
    command.upgrade(config_for(path, monkeypatch), "head")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as conn:
        operations = Operations(MigrationContext.configure(conn))
        if drift == "unique":
            conn.execute(text("DROP INDEX ix_user_username"))
        elif drift == "foreign_key":
            with operations.batch_alter_table("copilot_conversation", naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}) as batch:
                batch.drop_constraint("fk_copilot_conversation_user_id_user", type_="foreignkey")
        else:
            with operations.batch_alter_table("user") as batch:
                if drift == "nullable":
                    batch.alter_column("username", nullable=True)
                else:
                    batch.alter_column("token_version", server_default="9")
        with pytest.raises(RuntimeError, match="结构不匹配"):
            assert_schema_ready(conn)
    engine.dispose()


def test_sync_bootstrap_uses_migrations_and_revokes_tokens_on_explicit_reset(tmp_path, monkeypatch, capsys):
    import importlib.util
    import secrets
    import sys
    from core.config import get_settings

    # Importing the standalone entry point changes cwd; restore it after this test.
    monkeypatch.chdir(Path.cwd())
    spec = importlib.util.spec_from_file_location("bootstrap_sync_test", ROOT / "scripts/bootstrap_local_sync.py")
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    path = tmp_path / "sync-bootstrap.db"
    settings = get_settings().model_copy(update={
        "db_url": f"sqlite+aiosqlite:///{path.as_posix()}",
        "admin_username": "isolated-admin",
    })
    monkeypatch.setattr(bootstrap, "get_settings", lambda: settings)
    monkeypatch.setattr(bootstrap, "_resolve_admin_password", lambda: (secrets.token_urlsafe(16), False))
    monkeypatch.setattr(bootstrap, "hash_password", lambda _value: "isolated-test-hash")
    monkeypatch.setattr(sys, "argv", ["bootstrap_local_sync.py"])
    assert bootstrap.main() == 0
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0012_copilot_request"
        assert conn.execute(text("SELECT token_version FROM user WHERE username='isolated-admin'")).scalar_one() == 0
    assert bootstrap.main() == 0
    monkeypatch.setattr(sys, "argv", ["bootstrap_local_sync.py", "--reset-password"])
    assert bootstrap.main() == 0
    with engine.connect() as conn:
        assert conn.execute(text("SELECT token_version FROM user WHERE username='isolated-admin'")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM user")).scalar_one() == 1
    assert "schema: ok" in capsys.readouterr().out
    engine.dispose()


@pytest.mark.asyncio
async def test_startup_refuses_existing_old_store_without_modifying_it(tmp_path, monkeypatch):
    from core import database
    from core.config import get_settings
    path = tmp_path / "old.db"
    command.upgrade(config_for(path, monkeypatch), "0001_initial")
    settings = get_settings().model_copy(update={"db_url": f"sqlite+aiosqlite:///{path.as_posix()}", "debug": False})
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)
    with pytest.raises(RuntimeError, match="需要升级"):
        await database.init_db()
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0001_initial"
    assert "token_version" not in {c["name"] for c in inspect(engine).get_columns("user")}
    assert database.get_engine() is None
    assert database.get_session_factory() is None
    engine.dispose()
