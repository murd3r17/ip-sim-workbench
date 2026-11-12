"""Run backend tests with explicit local state and no external I/O.

This is an accidental-I/O guard, not an OS sandbox for untrusted code. Every run
uses a new directory below .runtime/redevelopment. It never starts/stops services.
"""
from __future__ import annotations

import argparse
import faulthandler
import json
import os
from pathlib import Path
import platform
import socket
import sys
import tempfile
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def start_timeout_watchdog(seconds, on_timeout):
    """Independent of pytest's faulthandler hooks, which cancel global timers."""
    completed = threading.Event()

    def watch():
        if not completed.wait(seconds):
            on_timeout()

    threading.Thread(target=watch, name="offline-test-timeout", daemon=True).start()
    return completed


def validate_run_directory(path: Path) -> Path:
    base = (ROOT / ".runtime" / "redevelopment").resolve()
    path = path.resolve()
    if path == base or not path.is_relative_to(base):
        raise ValueError("Test output must be a new child of .runtime/redevelopment")
    if path.exists():
        raise ValueError("Test output already exists; use a fresh run directory")
    return path


def isolated_environment(run_dir: Path, device_mode: str) -> dict[str, str]:
    # Preserve Windows loader/runtime variables, not inherited application keys.
    allowed = {
        "SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "SYSTEMDRIVE",
        "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA", "USERPROFILE",
        "LOCALAPPDATA", "APPDATA", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
    }
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    env.update({
        "DB_BACKEND": "sqlite", "DB_URL": "sqlite+aiosqlite:///:memory:",
        "DEVICE_MODE": device_mode, "DEPLOY_SIMULATE_ONLY": "true",
        "MONITOR_SCHEDULER_ENABLED": "false", "KNOWLEDGE_PROVIDER": "local",
        "JWT_SECRET_KEY": "offline-test-placeholder-not-a-deployment-secret",
        "LLM_API_KEY": "", "KNOWLEDGE_API_KEY": "", "LLM_FALLBACK_API_KEY": "",
        "LLM_BASE_URL": "http://127.0.0.1:9", "KNOWLEDGE_BASE_URL": "http://127.0.0.1:9",
        "KNOWLEDGE_ANYTHINGLLM_STORAGE": str(run_dir / "knowledge-storage"),
        "LOG_DIR": str(run_dir / "logs"),
        "AGENT_BUDGET_FILE": str(run_dir / "agent-budget.json"),
        "TEMP": str(run_dir / "temp"), "TMP": str(run_dir / "temp"),
        "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
        # aiomysql resolves getpass.getuser() at import time. Windows has no
        # pwd fallback; supply a synthetic identity, never inherit the account.
        "USERNAME": "offline-test-user",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "WORKBENCH_OFFLINE_TEST": "1",
    })
    return env


class OfflineGuard:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir.resolve()
        self.read_roots = tuple(p.resolve() for p in (ROOT, Path(sys.prefix), Path(sys.base_prefix)))

    def check_path(self, raw, *, write: bool = False):
        if raw is None or isinstance(raw, int):
            return
        if os.path.normcase(os.fsdecode(raw)) == os.path.normcase(os.devnull):
            return
        path = Path(os.fsdecode(raw)).resolve()
        if path == Path(os.devnull).resolve():
            return
        if path.is_relative_to(self.run_dir):
            return
        if write:
            raise PermissionError("Offline tests may only write inside their own run directory")
        # A delivery stage is itself under .runtime. Its own checked-in source
        # is readable; private state nested inside the stage remains denied.
        relative = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        parts = {part.casefold() for part in relative.parts}
        name = path.name.casefold()
        if ".runtime" in parts or ".git" in parts or name == ".env" or (
            name.startswith(".env.") and name != ".env.example"
        ):
            raise PermissionError("Offline tests cannot read private configuration or historical state")
        if not any(path.is_relative_to(root) for root in self.read_roots):
            raise PermissionError("Offline test read is outside source/runtime/fixture roots")

    def audit(self, event: str, args: tuple):
        if event == "open":
            _, mode, flags = args
            writing = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            self.check_path(args[0], write=writing or bool(mode and any(c in mode for c in "wax+")))
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.truncate"}:
            self.check_path(args[0], write=True)
        elif event in {"os.rename", "os.link", "os.symlink"}:
            self.check_path(args[0], write=True)
            self.check_path(args[1], write=True)
        elif event in {"socket.connect", "socket.bind", "socket.sendto", "socket.getaddrinfo"}:
            # Windows asyncio uses the stdlib loopback socketpair as its wakeup
            # channel. Permit that exact caller, never arbitrary localhost I/O.
            fallback = getattr(socket, "_fallback_socketpair", None)
            caller = sys._getframe(1).f_code
            if fallback is not None and caller is fallback.__code__:
                address = args[1] if event in {"socket.connect", "socket.bind"} else None
                if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
                    return
            raise RuntimeError("Offline tests forbid real network I/O")
        elif event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"}:
            raise RuntimeError("Offline tests forbid external process execution")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--device-mode", choices=("sim", "ssh"), default="sim")
    parser.add_argument("--timeout", type=int, default=180, help="Hard timeout in seconds, including startup")
    options, pytest_args = parser.parse_known_args(argv)
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    if not pytest_args:
        parser.error("Specify a targeted pytest selection after --")
    if options.timeout < 1:
        parser.error("timeout must be positive")
    if any(arg.startswith(("--basetemp", "--rootdir")) for arg in pytest_args):
        parser.error("The offline runner owns rootdir and basetemp")
    run_dir = validate_run_directory(options.run_dir or (
        ROOT / ".runtime" / "redevelopment" / "tests" / uuid.uuid4().hex
    ))
    run_dir.mkdir(parents=True)
    (run_dir / "temp").mkdir()
    (run_dir / "logs").mkdir()
    fault_file = (run_dir / "faults.log").open("w", encoding="utf-8")
    faulthandler.enable(file=fault_file)
    receipt = {
        "kind": "isolated_offline_tests", "device_mode": options.device_mode,
        "pytest_args": pytest_args, "status": "STARTING", "exit_code": None,
        "network": "application I/O blocked; stdlib socketpair allowed",
        "dotenv": "disabled", "database": "in-memory by default",
        "timeout_seconds": options.timeout, "run_dir": str(run_dir),
    }
    receipt_path = run_dir / "receipt.json"
    def save_receipt():
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    save_receipt()
    def timed_out():
        receipt.update(status="TIMED_OUT", exit_code=124)
        try:
            save_receipt()
            faulthandler.dump_traceback(file=fault_file, all_threads=True)
            fault_file.flush()
        finally:
            os._exit(124)
    watchdog = start_timeout_watchdog(options.timeout, timed_out)
    print(f"Offline run: {run_dir}", flush=True)
    environment = isolated_environment(run_dir, options.device_mode)
    os.environ.clear()
    os.environ.update(environment)
    tempfile.tempdir = str(run_dir / "temp")
    sys.dont_write_bytecode = True
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    # Windows stdlib may invoke `ver` once to populate this metadata cache.
    # Prime it before testing; application subprocesses remain forbidden.
    try:
        print("Initializing platform metadata", flush=True)
        platform.uname()
        print("Installing offline I/O guard", flush=True)
        sys.addaudithook(OfflineGuard(run_dir).audit)
        from core.config import Settings, get_settings
        Settings.model_config["env_file"] = None
        get_settings.cache_clear()
        import pytest
        args = ["-p", "pytest_asyncio.plugin", "-p", "no:cacheprovider",
                "--rootdir", str(BACKEND), "--basetemp", str(run_dir / "pytest-temp"), *pytest_args]
        receipt["status"] = "RUNNING"
        save_receipt()
        code = int(pytest.main(args))
        receipt.update(status="PASSED" if code == 0 else "FAILED", exit_code=code)
    except BaseException as exc:
        receipt.update(status="INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "ERROR",
                       error_type=type(exc).__name__)
        raise
    finally:
        watchdog.set()
        save_receipt()
        faulthandler.disable()
        fault_file.close()
    print(f"Offline test receipt: {receipt_path}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
