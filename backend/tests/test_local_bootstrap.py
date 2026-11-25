"""Regressions for first-run recovery and separate localhost demo state."""

import importlib.util
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def bootstrap(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[2] / "scripts" / "bootstrap_local.py"
    spec = importlib.util.spec_from_file_location("workbench_launcher", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DEMO_DIR", tmp_path / ".runtime" / "demo")
    return module


def test_missing_ensurepip_fails_cleanly_and_can_retry(bootstrap, tmp_path, monkeypatch):
    interpreter = tmp_path / ".venv" / "bin" / "python"
    usable = False

    def create(command, *, check):
        assert command[-3:-1] == ["-m", "venv"]
        (command[-1] / "pyvenv.cfg").write_text("fixture\n", encoding="utf-8")
        if not usable:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(bootstrap, "_pip_available", lambda _: usable and (tmp_path / ".venv/pyvenv.cfg").exists())
    monkeypatch.setattr(bootstrap.subprocess, "run", create)
    with pytest.raises(RuntimeError, match="python3.12-venv"):
        bootstrap._prepare_venv(interpreter)
    assert not (tmp_path / ".venv").exists()

    usable = True
    bootstrap._prepare_venv(interpreter)
    assert (tmp_path / ".venv/pyvenv.cfg").is_file()


def test_repairs_recognized_partial_venv_in_place(bootstrap, tmp_path, monkeypatch):
    path = tmp_path / ".venv"
    path.mkdir()
    (path / "pyvenv.cfg").write_text("fixture\n", encoding="utf-8")
    note = path / "local-note"
    note.touch()
    results = iter((False, True))
    calls = []
    monkeypatch.setattr(bootstrap, "_pip_available", lambda _: next(results))
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda command, **_: calls.append(command))
    bootstrap._prepare_venv(path / "bin" / "python")
    assert len(calls) == 1 and calls[0][-1] == path
    assert note.is_file()


def test_demo_uses_bundled_corpus_and_persistent_isolated_keys(bootstrap, monkeypatch, tmp_path):
    monkeypatch.setenv("JWT_SECRET_KEY", "example-personal-signing-secret")
    monkeypatch.setenv("LLM_API_KEY", "example-personal-model-key")
    demo = bootstrap.prepare_environment(demo=True)
    assert demo["IP_SIM_DEMO"] == "1"
    assert demo["DB_SQLITE_PATH"] == str(tmp_path / ".runtime/demo/workbench.sqlite3")
    assert demo["KNOWLEDGE_CORPUS_DIR"] == str(tmp_path / "knowledge/corpus/huawei-ip")
    assert demo["DEVICE_MODE"] == "sim" and demo["LLM_API_KEY"] == ""
    assert demo["JWT_SECRET_KEY"] != "example-personal-signing-secret"
    reopened = bootstrap.prepare_environment(demo=True)
    assert all(demo[key] == reopened[key] for key in ("JWT_SECRET_KEY", "FERNET_KEY"))
    assert not (tmp_path / ".env").exists()
