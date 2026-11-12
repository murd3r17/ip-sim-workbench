"""Alembic baseline presence tests (does not touch the live MySQL volume)."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_alembic_initial_revision_exists():
    versions = ROOT / "alembic" / "versions"
    files = list(versions.glob("*.py"))
    assert any("0001_initial" in p.name for p in files)


def test_alembic_env_imports_all_model_modules():
    from core.database import Base, _import_all_models

    env = (ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "_import_all_models()" in env
    _import_all_models()
    assert {"device", "deploy_task", "training_session", "copilot_conversation",
            "system_config", "environment_profile", "read_only_observation"} <= set(Base.metadata.tables)


def test_alembic_upgrade_head_on_empty_sqlite(tmp_path, monkeypatch):
    db = tmp_path / "empty.db"
    monkeypatch.setenv("ALEMBIC_URL", f"sqlite:///{db.as_posix()}")
    from alembic.config import Config
    from alembic import command
    from sqlalchemy import create_engine, inspect

    cfg = Config(str(ROOT / "alembic.ini"))
    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    tables = set(inspect(engine).get_table_names())
    assert "alembic_version" in tables
    assert "copilot_conversation" in tables
    assert "deploy_task" in tables
    assert len(tables) >= 20


def test_alembic_schema_matches_models_column_by_column(tmp_path, monkeypatch):
    """列级比对：只断言"表存在/>=20 张"发现不了列漂移。

    从冻结的初始版本逐步升级到 head 后必须与当前模型一致；
    修改模型但漏写新 revision 时，此用例应失败。
    """
    db = tmp_path / "schema.db"
    monkeypatch.setenv("ALEMBIC_URL", f"sqlite:///{db.as_posix()}")
    from alembic.config import Config
    from alembic import command
    from sqlalchemy import create_engine, inspect

    from core.database import Base
    import modules.auth.models  # noqa: F401
    import modules.device.models  # noqa: F401
    import modules.deploy.models  # noqa: F401
    import modules.monitor.models  # noqa: F401
    import modules.training.models  # noqa: F401
    import modules.ai_text.models  # noqa: F401
    import modules.system.models  # noqa: F401

    cfg = Config(str(ROOT / "alembic.ini"))
    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    inspector = inspect(engine)

    missing_tables = sorted(set(Base.metadata.tables) - set(inspector.get_table_names()))
    assert missing_tables == [], f"迁移后缺少表: {missing_tables}"

    mismatched: dict[str, list[str]] = {}
    for table_name, table in Base.metadata.tables.items():
        actual = {col["name"] for col in inspector.get_columns(table_name)}
        expected = {col.name for col in table.columns}
        if actual != expected:
            mismatched[table_name] = sorted(expected ^ actual)
    assert mismatched == {}, f"列级漂移（模型 vs 迁移）: {mismatched}"
