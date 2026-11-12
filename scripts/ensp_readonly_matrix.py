#!/usr/bin/env python3
"""Generate a read-only eNSP SSH command baseline matrix.

The report intentionally records only command status and output size. It never
prints credentials or raw device output.
"""
from __future__ import annotations

import argparse
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path

import paramiko
import pymysql


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".claude" / "ensp-readonly-command-matrix.md"
COMMANDS = [
    "display version",
    "display cpu-usage",
    "display interface brief",
]


@dataclass
class Device:
    hostname: str
    mgmt_ip: str
    ssh_port: int


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def env_value(env: dict[str, str], key: str, default: str = "") -> str:
    return os.getenv(key) or env.get(key) or default


def db_devices(env: dict[str, str]) -> list[Device]:
    host = env_value(env, "MYSQL_HOST", "127.0.0.1")
    if host in {"mysql", "sim-mysql"}:
        host = "127.0.0.1"
    port = int(env_value(env, "MYSQL_PORT", "3307"))
    user = env_value(env, "MYSQL_USER", env_value(env, "DB_USER", "sim_admin"))
    password = env_value(env, "MYSQL_PASSWORD")
    database = env_value(env, "MYSQL_DB", env_value(env, "DB_NAME", "sim_workspace"))
    conn = pymysql.connect(host=host, port=port, user=user, password=password, database=database, charset="utf8mb4")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT hostname, mgmt_ip, ssh_port FROM device ORDER BY INET_ATON(mgmt_ip)")
            return [Device(hostname=row[0], mgmt_ip=row[1], ssh_port=int(row[2] or 22)) for row in cur.fetchall()]
    finally:
        conn.close()


def open_shell(device: Device, username: str, password: str, timeout: int):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=device.mgmt_ip,
            port=device.ssh_port,
            username=username,
            password=password,
            timeout=timeout,
            auth_timeout=timeout,
            banner_timeout=timeout,
            allow_agent=False,
            look_for_keys=False,
        )
        channel = client.invoke_shell(width=120, height=40)
        return client, channel
    except paramiko.AuthenticationException:
        client.close()

    sock = socket.create_connection((device.mgmt_ip, device.ssh_port), timeout=timeout)
    transport = paramiko.Transport(sock)
    transport.start_client(timeout=timeout)

    def handler(_title, _instructions, prompt_list):
        return [password] * len(prompt_list)

    transport.auth_interactive(username, handler)
    if not transport.is_authenticated():
        transport.close()
        raise paramiko.AuthenticationException("interactive authentication failed")
    channel = transport.open_session(timeout=timeout)
    channel.get_pty(width=120, height=40)
    channel.invoke_shell()
    return transport, channel


def read_quiet(channel, timeout: int) -> str:
    end = time.monotonic() + timeout
    last_data = time.monotonic()
    chunks: list[bytes] = []
    while time.monotonic() < end:
        if channel.recv_ready():
            chunk = channel.recv(65535)
            chunks.append(chunk)
            last_data = time.monotonic()
            continue
        if chunks and time.monotonic() - last_data > 0.8:
            break
        time.sleep(0.1)
    return b"".join(chunks).decode("utf-8", errors="ignore")


def command_status(output: str, command: str) -> tuple[str, int]:
    lines = []
    for raw in output.replace("\r", "\n").splitlines():
        line = raw.strip()
        if not line or line == command:
            continue
        if line.endswith(">") or line.endswith("]"):
            continue
        if "Change now" in line or "change your password" in line.lower():
            continue
        lines.append(line)
    size = sum(len(line) for line in lines)
    return ("output" if size > 0 else "no_output"), size


def probe_device(device: Device, username: str, password: str, timeout: int) -> dict:
    started = time.monotonic()
    result = {"hostname": device.hostname, "mgmt_ip": device.mgmt_ip, "auth": "failed", "commands": []}
    session = None
    try:
        session, channel = open_shell(device, username, password, timeout)
        result["auth"] = "success"
        initial = read_quiet(channel, timeout)
        if "Change now" in initial or "change your password" in initial.lower():
            channel.send("N\n")
            read_quiet(channel, timeout)
        for command in COMMANDS:
            command_started = time.monotonic()
            channel.send(command + "\n")
            output = read_quiet(channel, timeout)
            status, size = command_status(output, command)
            result["commands"].append({
                "command": command,
                "status": status,
                "output_chars": size,
                "elapsed_ms": int((time.monotonic() - command_started) * 1000),
            })
    except Exception as exc:
        result["error"] = exc.__class__.__name__
    finally:
        if session is not None:
            session.close()
        result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return result


def write_report(results: list[dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    success = sum(1 for item in results if item["auth"] == "success")
    lines = [
        "# eNSP 只读命令基线矩阵",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 设备数量：{len(results)}",
        f"- SSH认证成功：{success}/{len(results)}",
        "- 安全说明：本报告不记录账号、密码、Token 或设备命令原始回显。",
        "",
        "| 设备 | 管理IP | SSH | display version | display cpu-usage | display interface brief |",
        "|---|---|---|---|---|---|",
    ]
    for item in results:
        statuses = {cmd["command"]: f"{cmd['status']} ({cmd['output_chars']} chars)" for cmd in item.get("commands", [])}
        lines.append(
            "| {hostname} | {mgmt_ip} | {auth} | {version} | {cpu} | {interface} |".format(
                hostname=item["hostname"],
                mgmt_ip=item["mgmt_ip"],
                auth=item["auth"],
                version=statuses.get("display version", item.get("error", "not_run")),
                cpu=statuses.get("display cpu-usage", item.get("error", "not_run")),
                interface=statuses.get("display interface brief", item.get("error", "not_run")),
            )
        )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=8)
    args = parser.parse_args()

    env = load_env(ROOT / ".env")
    username = env_value(env, "DEVICE_DEFAULT_USERNAME")
    password = env_value(env, "DEVICE_DEFAULT_PASSWORD")
    if not username or not password:
        raise SystemExit("DEVICE_DEFAULT_USERNAME/DEVICE_DEFAULT_PASSWORD must be set in environment or .env")

    results = [probe_device(device, username, password, args.timeout) for device in db_devices(env)]
    write_report(results, args.output)
    print(f"wrote {args.output}")
    print(f"ssh_success={sum(1 for item in results if item['auth'] == 'success')}/{len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
