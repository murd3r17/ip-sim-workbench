"""Concurrent process dispatch must not lose charges or overwrite corrupt ledgers."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from modules.ai_text import budget_store


@pytest.mark.parametrize("used", [True, -1, 1.5, "2", None])
def test_invalid_count_blocks_without_overwrite(tmp_path, monkeypatch, used):
    path = tmp_path / "ledger.json"
    original = json.dumps({"used": used})
    path.write_text(original)
    monkeypatch.setenv("AGENT_BUDGET_TEST", "1")
    monkeypatch.setenv("AGENT_BUDGET_FILE", str(path))
    with pytest.raises(budget_store.BudgetExceeded):
        budget_store.consume()
    assert path.read_text() == original
    assert budget_store.snapshot()["remaining"] is None


def test_failed_lock_never_changes_charge(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    monkeypatch.setenv("AGENT_BUDGET_TEST", "1")
    monkeypatch.setenv("AGENT_BUDGET_FILE", str(path))
    monkeypatch.setattr(budget_store, "_lock", lambda _: (_ for _ in ()).throw(OSError("lock failed")))
    with pytest.raises(budget_store.BudgetExceeded):
        budget_store.consume()
    assert not path.exists()


def test_concurrent_writers_preserve_every_charge(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    monkeypatch.setenv("AGENT_BUDGET_TEST", "1")
    monkeypatch.setenv("AGENT_BUDGET_FILE", str(path))
    monkeypatch.setattr(budget_store, "_CAP", None)
    def run(_):
        for _ in range(5):
            budget_store.consume("parallel")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(run, range(4)))
    data = json.loads(path.read_text())
    assert data["used"] == len(data["entries"]) == 20
    assert not list(tmp_path.glob("*.tmp"))
