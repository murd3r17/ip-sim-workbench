"""Dry-run never creates/migrates an unconfigured database."""
from types import SimpleNamespace
import sqlite3
import pytest

from scripts.migrate_training_content_v7d import run


@pytest.mark.asyncio
async def test_cli_refuses_missing_database_before_connecting(monkeypatch,tmp_path):
    path=tmp_path/'not-created.sqlite3'
    monkeypatch.setattr('core.database.resolve_database_url',lambda _settings:'sqlite+aiosqlite:///'+path.as_posix())
    with pytest.raises(ValueError,match='不会创建空库'):
        await run(SimpleNamespace(apply=False,restore=None,backup=None))
    assert not path.exists()


@pytest.mark.asyncio
async def test_cli_refuses_empty_schema_without_bootstrapping(monkeypatch,tmp_path):
    path=tmp_path/'empty.sqlite3'
    with sqlite3.connect(path): pass
    monkeypatch.setattr('core.database.resolve_database_url',lambda _settings:'sqlite+aiosqlite:///'+path.as_posix())
    with pytest.raises(RuntimeError,match='数据库结构需要升级'):
        await run(SimpleNamespace(apply=False,restore=None,backup=None))
    with sqlite3.connect(path) as db:
        assert db.execute("select name from sqlite_master where type='table'").fetchall()==[]
