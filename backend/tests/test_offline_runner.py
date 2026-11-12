"""Isolation contracts for scripts/run-offline-tests.py, without real external I/O."""
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import faulthandler

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("offline_runner", ROOT / "scripts" / "run-offline-tests.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_hard_timeout_survives_pytest_cancelling_faulthandler_timer():
    expired = threading.Event()
    done = runner.start_timeout_watchdog(0.02, expired.set)
    faulthandler.cancel_dump_traceback_later()
    assert expired.wait(1)
    done.set()


def test_completed_run_cancels_its_watchdog():
    expired = threading.Event()
    done = runner.start_timeout_watchdog(0.02, expired.set)
    done.set()
    assert not expired.wait(0.06)


@pytest.mark.parametrize("target", [ROOT, ROOT / ".runtime/redevelopment", ROOT / ".runtime/redevelopment-other/run"])
def test_output_cannot_reuse_root_or_escape(target):
    with pytest.raises(ValueError):
        runner.validate_run_directory(target)


def test_existing_run_is_never_reused(tmp_path):
    with pytest.raises(ValueError):
        runner.validate_run_directory(tmp_path)


def test_inherited_application_credentials_and_database_are_removed(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_API_KEY", "synthetic-secret")
    monkeypatch.setenv("DB_URL", "mysql://synthetic")
    monkeypatch.setenv("UNRELATED_SECRET", "synthetic-secret")
    env = runner.isolated_environment(tmp_path, "sim")
    assert env['USERNAME'] == 'offline-test-user'
    assert env["LLM_API_KEY"] == ""
    assert env["DB_URL"] == "sqlite+aiosqlite:///:memory:"
    assert "UNRELATED_SECRET" not in env
    assert env["LOG_DIR"] == str(tmp_path / "logs")


@pytest.mark.parametrize("target", [ROOT / ".env", ROOT / "backend/.env", ROOT / ".runtime/old-run/data.json"])
def test_private_configuration_and_previous_runs_are_not_readable(target, tmp_path):
    with pytest.raises(PermissionError):
        runner.OfflineGuard(tmp_path).check_path(target)


def test_source_is_readable_but_not_writable_and_own_artifacts_are_writable(tmp_path):
    guard = runner.OfflineGuard(tmp_path)
    guard.check_path(ROOT / "backend/core/config.py")
    guard.check_path(tmp_path / "result.json", write=True)
    with pytest.raises(PermissionError):
        guard.check_path(ROOT / "backend/core/config.py", write=True)
    with pytest.raises(PermissionError):
        guard.check_path(tmp_path.parent / "other-run/result.json", write=True)


@pytest.mark.skipif(os.environ.get("WORKBENCH_OFFLINE_TEST") != "1", reason="Requires active offline runner guard")
def test_installed_guard_blocks_actual_io_and_allows_own_files(tmp_path):
    # These operations must fail at the audit event, before actual external I/O.
    with pytest.raises(PermissionError, match="private configuration"):
        (ROOT / ".env").read_bytes()
    with pytest.raises(PermissionError, match="only write"):
        (ROOT / "offline-guard-must-not-exist.txt").write_text("should never be written")
    with socket.socket() as sock:
        with pytest.raises(RuntimeError, match="network I/O"):
            sock.connect(("127.0.0.1", 9))
    with pytest.raises(RuntimeError, match="process execution"):
        subprocess.run([sys.executable, "-c", "raise SystemExit(99)"], check=False)
    target = tmp_path / "result.txt"
    target.write_text("own artifact", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "own artifact"
