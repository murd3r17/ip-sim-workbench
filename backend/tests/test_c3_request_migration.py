import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from core.migrations import prepare_database, assert_schema_ready
from tests.test_delivery_migrations import config_for


@pytest.mark.parametrize("drift", [False, True])
def test_previous_head_upgrade_is_backed_up_and_strict(tmp_path, monkeypatch, drift):
    path = tmp_path / "previous.db"
    command.upgrade(config_for(path, monkeypatch), "0011_v7b_bf5_instance")
    url = f"sqlite:///{path.as_posix()}"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO user (id, username, hashed_password, role, is_active, token_version) VALUES (1, 'preserved', 'hash', 'admin', 1, 0)"))
        conn.execute(text("INSERT INTO copilot_conversation (id, user_id, title, messages, revision) VALUES ('kept', 1, 'title', '[]', 3)"))
        if drift:
            conn.execute(text("DROP INDEX ix_user_username"))
    with engine.connect() as conn:
        with pytest.raises(RuntimeError, match="启动未修改旧库"):
            assert_schema_ready(conn)
    with pytest.raises(RuntimeError):
        prepare_database(url)
    assert "copilot_request" not in inspect(engine).get_table_names()
    if drift:
        with pytest.raises(RuntimeError, match="拒绝升级"):
            prepare_database(url, str(tmp_path / "backup"))
        assert "copilot_request" not in inspect(engine).get_table_names()
    else:
        backup = prepare_database(url, str(tmp_path / "backup"))
        old = create_engine(f"sqlite:///{backup.as_posix()}")
        with old.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0011_v7b_bf5_instance"
            assert conn.execute(text("SELECT revision FROM copilot_conversation")).scalar_one() == 3
        old.dispose()
        with engine.connect() as conn:
            assert_schema_ready(conn)
            assert conn.execute(text("SELECT username FROM user")).scalar_one() == "preserved"
            assert conn.execute(text("SELECT revision FROM copilot_conversation")).scalar_one() == 3
        assert prepare_database(url) is None
    engine.dispose()
