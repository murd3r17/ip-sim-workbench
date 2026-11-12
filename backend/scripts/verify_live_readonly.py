"""Serial, device-read-only evidence; never initializes/migrates/writes the database.

Run from backend with three explicit --expect ID,HOSTNAME,IP,PORT arguments.
--exclusive-window asserts schedulers/other SSH clients are stopped: the adapter's
lock is process-local, so this standalone program cannot enforce service isolation.
No write or save commands are exposed. Optional snapshots are Fernet ciphertext;
keep the existing key separately and do not include snapshots in delivery archives.
This proves readable device state, not deployment, WebSSH or topology correctness.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import logging
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
from core.live_evidence import capture_binding, binding_unchanged

COMMANDS = (
    "display version",
    "display current-configuration",
    "display interface brief",
    "display lldp neighbor brief",
)
SAVED_COMMAND = "display saved-configuration"
_CLI_ERROR = re.compile(
    r"(?im)^\s*(?:Error\s*:|%\s*(?:Error|Invalid|Unrecognized)|"
    r"Unrecognized command|Incomplete command|Wrong parameter|Warning\s*:)|----\s*More\s*----"
)


class ProbeRefused(ValueError):
    """Only fixed, non-sensitive reason codes belong in this exception."""


@dataclass(frozen=True)
class ExpectedTarget:
    device_id: int
    hostname: str
    host: str
    port: int


def validate_runtime(database_url: str, device_mode: str, *, exclusive_window: bool):
    from sqlalchemy.engine import make_url

    try:
        driver = make_url(database_url).drivername
    except Exception:
        raise ProbeRefused("invalid_database_url") from None
    if driver != "mysql+aiomysql":
        raise ProbeRefused("mysql_aiomysql_required")
    if device_mode.strip().lower() != "ssh":
        raise ProbeRefused("real_ssh_mode_required")
    if not exclusive_window:
        raise ProbeRefused("exclusive_maintenance_window_required")


def validate_targets(devices, expected):
    if (len(expected) != 3 or len({t.device_id for t in expected}) != 3
            or len({(t.host, t.port) for t in expected}) != 3
            or len({t.hostname for t in expected}) != 3
            or any(not t.hostname or not t.host or not 0 < t.port < 65536 for t in expected)):
        raise ProbeRefused("exactly_three_unique_targets_required")
    actual = [(d.id, d.hostname, d.mgmt_ip, d.ssh_port) for d in devices]
    wanted = [(t.device_id, t.hostname, t.host, t.port) for t in expected]
    if len(actual) != 3 or set(actual) != set(wanted):
        raise ProbeRefused("inventory_identity_mismatch")


def summarize_output(command: str, output: str, hostname: str) -> dict:
    from core.redaction import redact_sensitive

    if command == COMMANDS[3] and re.fullmatch(
        r"\s*Error:\s*Global LLDP is not enabled\.?\s*", output, re.I
    ):
        raise ProbeRefused("lldp_disabled")
    if not output.strip() or _CLI_ERROR.search(output):
        raise ProbeRefused("empty_error_or_paginated_output")
    normalized = output.replace("\r\n", "\n").replace("\r", "\n")
    safe = redact_sensitive(normalized) or ""
    summary = {"command": command, "redacted_sha256": hashlib.sha256(safe.encode()).hexdigest(),
               "line_count": len(normalized.splitlines())}
    if command == COMMANDS[0]:
        if not re.search(r"Huawei|VRP", output, re.I) or not re.search(r"\bVersion\b", output, re.I):
            raise ProbeRefused("version_not_recognized")
        summary["huawei_vrp"] = True
    elif command in {COMMANDS[1], SAVED_COMMAND}:
        names = re.findall(r"(?im)^\s*sysname\s+(\S+)\s*$", normalized)
        if names != [hostname]:
            raise ProbeRefused("configuration_identity_mismatch")
        if not re.search(r"(?m)^\s*return\s*$", normalized):
            raise ProbeRefused("configuration_incomplete")
        summary["identity_matches"] = True
        summary["interface_count"] = len(re.findall(r"(?im)^\s*interface\s+\S+", normalized))
    elif command == COMMANDS[2]:
        rows = re.findall(r"(?im)^\s*\S+\s+(?:\*?down|up|administratively\s+down)\s+"
                          r"(?:\*?down|up)(?:\([^\n)]*\))?(?:\s|$)", normalized)
        if not re.search(r"Interface\s+PHY\s+Protocol", output, re.I) or not rows:
            raise ProbeRefused("interfaces_not_recognized")
        summary["interface_count"] = len(rows)
    elif command == COMMANDS[3]:
        from modules.device.lldp_parser import parse_lldp_neighbor_brief

        if not re.search(r"Local\s+(?:Intf|Interface).*Neighbor", output, re.I):
            raise ProbeRefused("lldp_not_recognized")
        summary["neighbor_count"] = len(parse_lldp_neighbor_brief(output))
    else:
        raise ProbeRefused("command_not_allowed")
    return summary


def save_encrypted_snapshot(directory: Path, run_id: str, device, configuration: str, cipher,
                            *, configuration_type="running") -> Path:
    payload = {"schema": 1, "run_id": run_id, "captured_at": datetime.now(timezone.utc).isoformat(),
               "device_id": device.id, "hostname": device.hostname, "host": device.mgmt_ip,
               "port": device.ssh_port, "configuration": configuration, "configuration_type": configuration_type}
    encrypted = cipher.encrypt(json.dumps(payload, ensure_ascii=False).encode())
    directory.mkdir(parents=True, exist_ok=True)
    suffix = "-saved" if configuration_type == "saved" else ""
    path = directory / f"{run_id}-device-{device.id}{suffix}.fernet"
    # Exclusive create prevents replacing an existing recovery baseline.
    with path.open("xb") as handle:
        handle.write(encrypted)
    return path


async def probe_devices(devices, expected, adapter_factory, *, is_locked=None,
                        snapshot_dir=None, cipher=None, run_id=None, capture_saved=False):
    validate_targets(devices, expected)
    if snapshot_dir is not None and cipher is None:
        raise ProbeRefused("snapshot_encryption_required")
    run_id = run_id or uuid.uuid4().hex
    report = {"schema": 1, "run_id": run_id, "device_mode": "ssh", "ok": False,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "scope": "serial_device_readonly", "devices": []}
    by_id = {d.id: d for d in devices}
    for target in expected:
        device = by_id[target.device_id]
        item = {"device_id": device.id, "hostname": device.hostname, "host": device.mgmt_ip,
                "port": device.ssh_port, "ok": False, "closed": False, "commands": []}
        report["devices"].append(item)
        adapter = None
        running_config = None
        started = time.monotonic()
        try:
            if is_locked is not None and await is_locked(device.id):
                raise ProbeRefused("device_write_locked")
            candidate = adapter_factory(device)
            adapter = await candidate if inspect.isawaitable(candidate) else candidate
            if adapter.name != "ssh":
                raise ProbeRefused("real_adapter_required")
            item["adapter"] = adapter.name
            commands = (*COMMANDS[:3], SAVED_COMMAND, COMMANDS[3]) if capture_saved else COMMANDS
            for command in commands:
                # Use the executor's configured read timeout. Cancelling its coroutine
                # would not terminate the SSH thread, so do not move to another device
                # behind a still-running asyncio.wait_for timeout.
                command_start = time.monotonic()
                text = await adapter.run_command(command)
                summary = summarize_output(command, text, device.hostname)
                summary["elapsed_ms"] = round((time.monotonic() - command_start) * 1000)
                item["commands"].append(summary)
                if command == COMMANDS[1]:
                    running_config = text
                if command == COMMANDS[2]:
                    item["core_readonly_ok"] = True
                if command == COMMANDS[1] and snapshot_dir is not None:
                    path = save_encrypted_snapshot(Path(snapshot_dir), run_id, device, text, cipher)
                    item["encrypted_snapshot"] = path.name
                if command == SAVED_COMMAND:
                    from modules.deploy.config_verifier import ConfigVerifier

                    item["running_saved_equivalent"] = ConfigVerifier.verify_snapshot(running_config, text) is None
                    if snapshot_dir is not None:
                        path = save_encrypted_snapshot(Path(snapshot_dir), run_id, device, text, cipher,
                                                       configuration_type="saved")
                        item["encrypted_saved_snapshot"] = path.name
            item["ok"] = True
            if capture_saved and not item.get("running_saved_equivalent"):
                item["ok"] = False
                item["reason"] = "running_saved_configuration_mismatch"
        except ProbeRefused as exc:
            item["reason"] = str(exc)
            if str(exc) == "lldp_disabled":
                item["commands"].append({"command": COMMANDS[3], "ok": False, "reason": "lldp_disabled"})
        except Exception as exc:
            # Exception text can embed a command/configuration/password/connection URL.
            item["reason"] = "adapter_or_snapshot_error"
            item["error_type"] = type(exc).__name__
        finally:
            if adapter is not None:
                try:
                    await adapter.close()
                    item["closed"] = True
                except Exception as exc:
                    item["ok"] = False
                    item["reason"] = "adapter_close_error"
                    item["error_type"] = type(exc).__name__
            item["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        if not item["ok"] and not (
            item.get("reason") in {"lldp_disabled", "running_saved_configuration_mismatch"}
            and item.get("core_readonly_ok") and item["closed"]
        ):
            break
    report["ok"] = len(report["devices"]) == 3 and all(d["ok"] for d in report["devices"])
    report["core_readonly_ok"] = len(report["devices"]) == 3 and all(
        d.get("core_readonly_ok", False) and d["closed"] for d in report["devices"]
    )
    if capture_saved:
        report["running_saved_equivalent"] = len(report["devices"]) == 3 and all(
            d.get("running_saved_equivalent", False) for d in report["devices"]
        )
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return report


def parse_target(value):
    try:
        ident, hostname, host, port = value.split(",")
        return ExpectedTarget(int(ident), hostname.strip(), host.strip(), int(port))
    except ValueError:
        raise argparse.ArgumentTypeError("expected ID,HOSTNAME,IP,PORT") from None


async def _run(args, settings):
    from core.database import resolve_database_url
    from sqlalchemy import bindparam, text
    from sqlalchemy.ext.asyncio import create_async_engine

    # Reject SQLite before resolve_database_url can even create its parent directory.
    if not settings.db_url and settings.db_backend.lower() != "mysql":
        raise ProbeRefused("mysql_aiomysql_required")
    url = resolve_database_url(settings)
    validate_runtime(url, settings.device_mode, exclusive_window=args.exclusive_window)
    cipher = None
    if args.snapshot_dir:
        from cryptography.fernet import Fernet

        try:
            cipher = Fernet(settings.fernet_key.encode())
        except Exception:
            raise ProbeRefused("valid_existing_fernet_key_required") from None
    engine = create_async_engine(url, echo=False, pool_size=1, max_overflow=0,
                                 connect_args={"connect_timeout": 10})
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
            statement = text("SELECT id, hostname, mgmt_ip, ssh_port, username_encrypted, "
                             "password_encrypted, enable_encrypted FROM device WHERE id IN :ids"
                             ).bindparams(bindparam("ids", expanding=True))
            rows = (await conn.execute(statement, {"ids": [t.device_id for t in args.expect]})).mappings()
            devices = [SimpleNamespace(**row) for row in rows]
            validate_targets(devices, args.expect)
            # No init_db(), model migrations, schema creation or application startup.
            async def is_locked(device_id):
                # READ COMMITTED is not assumed: end the old read transaction so every
                # device preflight observes newly committed locks (still not an IPC lock).
                await conn.rollback()
                return bool((await conn.execute(text(
                    "SELECT device_id FROM device_write_lock WHERE device_id=:id"
                ), {"id": device_id})).first())

            from engines.device_adapter import get_device_adapter

            report = await probe_devices(devices, args.expect, get_device_adapter, is_locked=is_locked,
                                         snapshot_dir=args.snapshot_dir, cipher=cipher, capture_saved=args.capture_saved)
            from sqlalchemy.engine import make_url

            parsed = make_url(url)
            report["environment"] = {"db_backend": "mysql", "db_host": parsed.host,
                                     "db_port": parsed.port or 3306, "database": parsed.database,
                                     "ssh_command_timeout": settings.ssh_command_timeout,
                                     "exclusive_window_asserted": True}
            return report
    finally:
        await engine.dispose()


async def run(args):
    from core.config import get_settings

    settings = get_settings()
    start = capture_binding(settings)
    report = await _run(args, settings)
    finish = capture_binding(settings)
    report["binding"] = {"start": start, "finish": finish}
    report["started_at"] = start["captured_at"]
    report["finished_at"] = finish["captured_at"]
    if not binding_unchanged(start, finish):
        report.update(ok=False, reason="runtime_or_source_changed_during_probe")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect", action="append", type=parse_target, required=True)
    parser.add_argument("--exclusive-window", action="store_true")
    parser.add_argument("--snapshot-dir", type=Path)
    parser.add_argument("--capture-saved", action="store_true",
                        help="Also encrypt/read startup configuration and require running/saved equivalence")
    parser.add_argument("--output", type=Path, help="Optional summary JSON; never contains raw configuration")
    args = parser.parse_args(argv)
    # Do not allow third-party/library exception logging to leak command buffers.
    logging.disable(logging.CRITICAL)
    try:
        report = asyncio.run(run(args))
    except ProbeRefused as exc:
        report = {"ok": False, "reason": str(exc)}
    except Exception as exc:
        report = {"ok": False, "reason": "probe_failed", "error_type": type(exc).__name__}
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
    print(encoded)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
