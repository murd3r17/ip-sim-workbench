"""Manage only a full backend started from this root and launch receipt."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts/final_delegation"))
import process_owner as owner  # noqa: E402
from scripts.full_preflight import preflight, verify_backend  # noqa: E402

SCHEMA = "workbench-full-1"
SUCCESSFUL_STOP = {"stopped", "already_exited"}


def receipt_path(root: Path, path: Path | None, port: int) -> Path:
    runtime = root / ".runtime"
    path = path or runtime / f"full-launch-{port}.json"
    path = Path(os.path.abspath(path))
    if runtime not in path.parents:
        raise ValueError("启动收据必须位于当前工作区 .runtime 内。")
    for entry in (path, *path.parents):
        if entry == root:
            break
        if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
            raise ValueError("启动收据路径不能包含符号链接或目录联接。")
    return path


@contextmanager
def operation_lock(runtime: Path):
    import msvcrt

    runtime.mkdir(parents=True, exist_ok=True)
    # Windows releases the byte lock even if the controller is interrupted.
    with (runtime / "full-lifecycle.lock").open("a+b") as handle:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise ValueError("当前工作区已有启动、停止或重启操作，请稍后重试。") from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def checkpoint(path: Path, data: dict) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with tmp.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def command_tail(root: Path, path: Path, data: dict) -> list[str]:
    return [str(root / "backend/scripts/full_lifecycle.py"), "serve", "--root", str(root),
            "--receipt", str(path), "--host", data["host"], "--port", str(data["port"]),
            "--launch-id", data["launch_id"]]


def check_record(record: dict, root: Path, path: Path, data: dict) -> None:
    suffix = " " + subprocess.list2cmdline(command_tail(root, path, data))
    if (not isinstance(record, dict) or type(record.get("pid")) is not int or record["pid"] <= 0
            or type(record.get("created_ticks")) is not int or record["created_ticks"] <= 0
            or type(record.get("parent_pid")) is not int or not record.get("executable")
            or not isinstance(record.get("command"), str) or not record["command"].endswith(suffix)):
        raise ValueError("启动收据的进程身份不完整或与本次启动不匹配。")


def read_receipt(root: Path, path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if (not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("root") != str(root)
            or data.get("receipt") != str(path) or not re.fullmatch("[a-f0-9]{32}", data.get("launch_id", ""))
            or data.get("state") not in {"STARTING", "READY", "STOP_FAILED", "STOPPED"}
            or type(data.get("port")) is not int or not 1 <= data["port"] <= 65535
            or not isinstance(data.get("processes"), list)):
        raise ValueError("拒绝外来、旧版或身份不完整的 full 启动收据。")
    ipaddress.ip_address(data["host"])
    for record in data["processes"]:
        check_record(record, root, path, data)
    if data["state"] == "READY":
        pids = {row["pid"] for row in data["processes"]}
        binding = data.get("runtime_binding") or {}
        root_digest = hashlib.sha256(os.path.normcase(str(root)).encode()).hexdigest()
        if (data.get("pid") not in pids or data.get("runtime_pid") not in pids
                or binding.get("root_fingerprint") != root_digest
                or not re.fullmatch("[a-f0-9]{64}", binding.get("database_fingerprint", ""))):
            raise ValueError("启动收据缺少已验证的工作区、数据库或进程绑定。")
    return data


def discover_starting(root: Path, path: Path, data: dict) -> list[dict]:
    # Recovery is only for a launch whose exact command was written before
    # creating a process. A port listener is never a source of ownership.
    launch_id = data["launch_id"]
    candidates = owner.powershell_json(
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
        f"@(Get-CimInstance Win32_Process -Filter \"CommandLine LIKE '%{launch_id}%'\" | "
        "Select-Object -ExpandProperty ProcessId) | ConvertTo-Json -Compress"
    )
    records = []
    suffix = " " + subprocess.list2cmdline(command_tail(root, path, data))
    for pid in candidates if isinstance(candidates, list) else [candidates] if candidates else []:
        record = owner.snapshot(pid)
        if record and record["command"].endswith(suffix):
            check_record(record, root, path, data)
            records.append(record)
    return records


def stop_signal(path: Path, data: dict) -> Path:
    return path.with_name(".full-stop-" + data["launch_id"])


async def serve(root: Path, path: Path, launch_id: str) -> None:
    import uvicorn

    data = read_receipt(root, path)
    if data["state"] != "STARTING" or data["launch_id"] != launch_id:
        raise ValueError("启动收据与工作进程不匹配。")
    server = uvicorn.Server(uvicorn.Config("main:app", host=data["host"], port=data["port"],
                                         workers=1, timeout_graceful_shutdown=10))
    signal = stop_signal(path, data)

    async def watch_stop():
        while not signal.is_file():
            await asyncio.sleep(0.25)
        server.should_exit = True

    watcher = asyncio.create_task(watch_stop())
    try:
        await server.serve()
    finally:
        watcher.cancel()


def stop(root: Path, path: Path) -> dict:
    data = read_receipt(root, path)
    if data["state"] == "STOPPED":
        return data
    records = {row["pid"]: row for row in data["processes"]}
    # Capture the venv interpreter as well as its launcher, including an
    # interruption before startup could record the listener.
    if not data.get("runtime_pid"):
        for row in discover_starting(root, path, data):
            records.setdefault(row["pid"], row)
    active = []
    for row in records.values():
        current = owner.snapshot(row["pid"])
        if current and not owner.same_process(row, current):
            raise ValueError("PID 已被其他进程使用，拒绝停止。")
        if current:
            active.append(row["pid"])
    signal = stop_signal(path, data)
    if active:
        if not signal.exists():
            with signal.open("x", encoding="ascii") as file:
                file.write(data["launch_id"])
        until = time.monotonic() + 15
        while active and time.monotonic() < until:
            active = [pid for pid in active if owner.snapshot(pid) is not None]
            if active:
                time.sleep(0.4)
    order = sorted(records.values(), key=lambda row: row["parent_pid"] not in records)
    result = [{"pid": row["pid"], "status": owner.stop_verified(row)} for row in order]
    stopped = all(row["status"] in SUCCESSFUL_STOP for row in result)
    data.update(processes=list(records.values()), stop_results=result, forced=any(row["status"] == "stopped" for row in result),
                state="STOPPED" if stopped else "STOP_FAILED")
    checkpoint(path, data)
    if not stopped:
        raise ValueError("部分实例进程未能安全停止，请核对启动收据。")
    signal.unlink(missing_ok=True)
    return data


def assert_port_available(host: str, port: int) -> None:
    address = ipaddress.ip_address(host)
    with socket.socket(socket.AF_INET6 if address.version == 6 else socket.AF_INET) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind((host, port))
        except OSError as exc:
            raise ValueError(f"端口 {port} 已被占用或不可绑定，请选择其它端口。") from exc


def prepare_start(root: Path) -> bytes:
    index = root / "sim-frontend/dist/index.html"
    if not index.is_file():
        raise ValueError("缺少前端 dist，请使用完整交付候选或重建前端。")
    report = preflight(root, phase="start")
    if not report["ok"]:
        print(json.dumps(report, ensure_ascii=False))
        raise ValueError("full 认证预检失败，未启动后端。")
    return index.read_bytes()


def start(root: Path, path: Path, host: str, port: int, expected_page: bytes | None = None) -> dict:
    import httpx

    if path.exists() and read_receipt(root, path)["state"] != "STOPPED":
        raise ValueError("该收据对应的上次启动尚未收尾，请先按收据停止。")
    assert_port_available(host, port)
    if expected_page is None:
        expected_page = prepare_start(root)
    launch_id = uuid.uuid4().hex
    data = {"schema": SCHEMA, "root": str(root), "receipt": str(path), "state": "STARTING",
            "started_ms": time.time_ns() // 1_000_000,
            "host": host, "port": port, "launch_id": launch_id, "processes": []}
    path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint(path, data)
    logs = receipt_path(root, root / ".runtime/logs" / f"full-{launch_id}.out", port).parent
    logs.mkdir(exist_ok=True)
    probe_host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    base = f"http://[{probe_host}]:{port}" if ":" in probe_host else f"http://{probe_host}:{port}"
    try:
        with (logs / f"full-{launch_id}.out").open("xb") as stdout, (logs / f"full-{launch_id}.err").open("xb") as stderr:
            process = subprocess.Popen([sys.executable, *command_tail(root, path, data)], cwd=root / "backend",
                                       stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, close_fds=True,
                                       env=dict(os.environ, PYTHONUTF8="1", WORKBENCH_LAUNCH_ID=launch_id),
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        launcher = owner.snapshot(process.pid)
        if not launcher:
            raise ValueError("后端启动进程提前退出，请查看本次日志。")
        check_record(launcher, root, path, data)
        data.update(pid=process.pid, processes=[launcher])
        checkpoint(path, data)
        with httpx.Client(timeout=8, trust_env=False) as client:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    listener_pids = owner.listener_pids(port)
                    if not listener_pids:
                        time.sleep(0.4)
                        continue
                    records = {row["pid"]: row for row in discover_starting(root, path, data)}
                    if (len(listener_pids) != 1 or not listener_pids.issubset(records)
                            or not owner.same_process(launcher, records.get(launcher["pid"]))):
                        raise ValueError("监听端口归属其他进程，拒绝接管。")
                    pid = next(iter(listener_pids))
                    if pid != launcher["pid"] and records[pid]["parent_pid"] != launcher["pid"]:
                        raise ValueError("监听进程与本次启动器关系不匹配。")
                    data["processes"] = list(records.values())
                    checkpoint(path, data)
                    health = client.get(base + "/api/v1/health")
                    if health.is_success:
                        components = health.json().get("components", {})
                        if all(components.get(k, {}).get("status") == "healthy" for k in ("mysql", "llm", "knowledge")):
                            page = client.get(base + "/")
                            if page.is_success and page.content == expected_page:
                                verified = verify_backend(root, base, launcher["pid"], expected_launch_id=launch_id)
                                if not verified["ok"] or verified["process"]["pid"] != pid:
                                    raise ValueError("管理员认证或当前工作区、数据库、进程身份校验失败。")
                                data.update(state="READY", runtime_pid=pid, frontend_sha256=hashlib.sha256(expected_page).hexdigest(),
                                            runtime_binding=verified["binding"])
                                checkpoint(path, data)
                                return data
                except httpx.RequestError:
                    pass
                time.sleep(0.5)
        raise ValueError("后端未通过组件健康、前端构建和身份检查，请查看本次 full 日志。")
    except BaseException:
        stop(root, path)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "restart", "serve"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--launch-id")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if root != ROOT:
        parser.error("请使用目标工作区自己的启动脚本。")
    try:
        if not 1 <= args.port <= 65535:
            raise ValueError("端口须在 1 到 65535 之间。")
        path = receipt_path(root, args.receipt, args.port)
        if args.action == "serve":
            if not args.launch_id or os.environ.get("WORKBENCH_LAUNCH_ID") != args.launch_id:
                raise ValueError("缺少本次启动标识。")
            asyncio.run(serve(root, path, args.launch_id))
            return 0
        receipt_path(root, root / ".runtime/full-lifecycle.lock", args.port)
        with operation_lock(root / ".runtime"):
            expected_page = None
            if args.action in {"stop", "restart"}:
                if not path.is_file():
                    raise ValueError("未找到启动收据，请传入启动时的 -LaunchReceipt 或 -BackendPort。")
                if args.action == "restart":
                    read_receipt(root, path)
                    expected_page = prepare_start(root)
                previous = stop(root, path)
                if args.action == "stop":
                    print(f"[full] 实例已停止。收据 {path}")
                    return 0
                args.host, args.port = previous["host"], previous["port"]
            data = start(root, path, args.host, args.port, expected_page)
            address = f"[{args.host}]" if ":" in args.host else args.host
            print(f"[full] 已启动当前工作区后端（PID={data['pid']}）。打开 http://{address}:{args.port}")
            print(f"[full] 启动收据 {path}")
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"[full] {exc if type(exc) is ValueError else type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
