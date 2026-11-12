"""Live WebSSH + monitor evidence against an explicitly selected local clone.

Requires LIVE_VERIFY_TOKEN from an ordinary authenticated login. Never prints it.
Only fixed display/session-paging commands are sent to devices. Monitor requests
and terminal auditing write business evidence to the clone database. Stop other
SSH clients and background collection before running. No device status is forged.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
from scripts.verify_live_readonly import ProbeRefused, parse_target, summarize_output, validate_runtime, validate_targets
from core.live_evidence import capture_binding, binding_unchanged

REQUIRED_METRICS = {"cpu_usage", "memory_usage", "interface_up", "interface_down"}
_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*\x07)")


def require(condition, reason):
    if not condition:
        raise ProbeRefused(reason)


def validate_api_url(value):
    parts = urlsplit(value)
    require(parts.scheme in {"http", "https"} and parts.hostname in {"127.0.0.1", "localhost", "::1"}
            and not parts.username and not parts.password and not parts.query and not parts.fragment,
            "uncredentialed_loopback_api_required")
    return value.rstrip("/")


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError, AttributeError):
        raise ProbeRefused("invalid_evidence_timestamp") from None


def validate_monitor_result(result, device_ids, topology_id, *, inspection=False):
    task, summary = result.get("task", {}), result.get("summary", {})
    require(task.get("status") == "success" and task.get("topology_id") == topology_id,
            "monitor_task_not_success")
    require(task.get("device_count") == task.get("success_count") == len(device_ids)
            and task.get("failure_count") == 0, "monitor_task_incomplete")
    require(all(summary.get(key) == len(device_ids) for key in ("expected", "attempted", "success"))
            and summary.get("failed") == summary.get("skipped") == 0 and summary.get("errors") == [],
            "monitor_collection_incomplete")
    devices = summary.get("devices", [])
    require(len(devices) == len(device_ids) and {d.get("device_id") for d in devices} == device_ids,
            "monitor_device_identity_mismatch")
    started, finished = timestamp(task.get("started_at")), timestamp(task.get("finished_at"))
    points = 0
    for device in devices:
        require(device.get("status") == "success", "monitor_device_failed")
        # MySQL DATETIME has second precision while summary_json retains microseconds.
        # Bound the sample to the persisted finishing second, not a later job/window.
        upper_bound = finished + timedelta(seconds=1) if finished.microsecond == 0 else finished + timedelta(microseconds=1)
        require(started <= timestamp(device.get("collected_at")) < upper_bound, "stale_monitor_evidence")
        metrics = device.get("metrics", [])
        values = {m.get("metric_type"): m.get("value") for m in metrics}
        require(REQUIRED_METRICS <= values.keys(), "required_monitor_metrics_missing")
        require(all(isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
                    for value in values.values()), "monitor_metric_invalid")
        require(values["cpu_usage"] <= 100 and values["memory_usage"] <= 100, "monitor_percentage_invalid")
        require(values["interface_up"] + values["interface_down"] > 0, "monitor_interfaces_missing")
        points += len(metrics)
    if inspection:
        report = result.get("report", {})
        require(report.get("evidence_scope") == "current_job" and report.get("job_id") == task.get("id")
                and report.get("topology_id") == topology_id and report.get("devices") == devices
                and report.get("summary", {}).get("metric_points") == points, "inspection_evidence_mismatch")
    return {"ok": True, "task_id": task["id"], "topology_id": topology_id,
            "device_count": len(devices), "metric_points": points,
            **{key: summary[key] for key in ("expected", "attempted", "success", "failed", "skipped")},
            "device_ids": sorted(device_ids),
            "started_at": task["started_at"], "finished_at": task["finished_at"],
            "evidence_scope": "current_job"}


async def check_webssh(socket, hostname):
    started = time.monotonic()
    buffer = ""
    connected = False
    prompt = re.compile(r"<" + re.escape(hostname) + r">\s*$")

    async def receive():
        nonlocal buffer, connected
        event = json.loads(await socket.recv())
        require(event.get("type") != "error", "webssh_server_error")
        require(event.get("mode") != "sim", "simulated_webssh_rejected")
        if event.get("type") == "connected":
            connected = True
        if event.get("type") == "output":
            buffer += event.get("data", "")
            require(len(buffer) <= 1_000_000, "webssh_output_too_large")
            buffer = _ANSI.sub("", buffer)
            require(not re.search(r"security\s+risks\s+in\s+the\s+configuration\s+file", buffer, re.I),
                    "webssh_configuration_prompt_refused")
            require("模拟终端" not in buffer and "offline sim" not in buffer.lower(), "simulated_webssh_rejected")

    async with asyncio.timeout(90):
        while not (connected and prompt.search(buffer)):
            await receive()
        for command in ("screen-length 0 temporary", "display version"):
            buffer = ""
            await socket.send(json.dumps({"type": "input", "data": command + "\r"}))
            while not prompt.search(buffer):
                await receive()
            require(not re.search(r"(?im)^\s*Error:", buffer), "webssh_command_failed")
        summary = summarize_output("display version", buffer, hostname)
    return {"ok": True, "hostname": hostname, "version": summary,
            "elapsed_ms": round((time.monotonic() - started) * 1000)}


async def _run(args, settings):
    import httpx
    from sqlalchemy.engine import make_url
    from websockets.asyncio.client import connect
    from core.database import resolve_database_url
    from core.runtime_identity import runtime_identity, same_runtime

    url = resolve_database_url(settings)
    validate_runtime(url, settings.device_mode, exclusive_window=args.exclusive_window)
    parsed = make_url(url)
    require(parsed.host in {"127.0.0.1", "localhost", "::1"} and parsed.port == args.expect_db_port,
            "expected_local_clone_database_required")
    require(args.allow_clone_evidence_writes, "clone_evidence_write_scope_required")
    token = os.environ.get("LIVE_VERIFY_TOKEN", "")
    require(bool(token), "live_verify_token_required")
    api = validate_api_url(args.base_url)
    expected_identity = runtime_identity(settings)
    report = {"schema": 1, "scope": "live_webssh_and_monitor", "ok": False,
              "created_at": datetime.now(timezone.utc).isoformat(), "steps": []}
    async with httpx.AsyncClient(timeout=180, trust_env=False, follow_redirects=False,
                                 headers={"Authorization": "Bearer " + token}) as client:
        async def request(method, path):
            response = await client.request(method, api + path)
            require(response.status_code == 200, "api_http_failure")
            return response.json()

        # Read-only authenticated identity gate precedes WebSSH/monitor audit writes.
        actual_identity = await request("GET", "/system/runtime-identity")
        require(same_runtime(expected_identity, actual_identity), "server_runtime_identity_mismatch")
        report["runtime_identity"] = actual_identity
        inventory = await request("GET", f"/devices?topology_id={args.topology_id}")
        validate_targets([SimpleNamespace(**device) for device in inventory], args.expect)
        require(all(device.get("status") == "online" for device in inventory), "devices_not_verified_online")
        report["targets"] = [{"id": t.device_id, "hostname": t.hostname, "mgmt_ip": t.host, "ssh_port": t.port}
                             for t in args.expect]
        parts = urlsplit(api)
        websocket_base = urlunsplit(("wss" if parts.scheme == "https" else "ws", parts.netloc, parts.path, "", ""))
        for target in args.expect:
            item = {"name": "webssh", "device_id": target.device_id, "ok": False, "closed": False}
            report["steps"].append(item)
            try:
                async with connect(websocket_base + f"/ws/ssh/{target.device_id}", subprotocols=[token],
                                   open_timeout=20, close_timeout=5, proxy=None) as socket:
                    item.update(await check_webssh(socket, target.hostname))
                item["closed"] = True
            except Exception as exc:
                item["ok"] = False
                item["reason"] = str(exc) if isinstance(exc, ProbeRefused) else type(exc).__name__
                return report
        for kind in ("collect", "inspections"):
            item = {"name": kind, "ok": False}
            report["steps"].append(item)
            try:
                result = await request("POST", f"/monitor/{kind}/{args.topology_id}")
                item.update(validate_monitor_result(result, {t.device_id for t in args.expect},
                                                    args.topology_id, inspection=kind == "inspections"))
                stored = await request("GET", f"/monitor/tasks?topology_id={args.topology_id}&limit=100")
                require(any(job.get("id") == item["task_id"] and job.get("status") == "success"
                            for job in stored), "monitor_job_not_persisted")
            except Exception as exc:
                item["ok"] = False
                item["reason"] = str(exc) if isinstance(exc, ProbeRefused) else type(exc).__name__
                return report
    report["ok"] = True
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return report


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
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expect-db-port", type=int, required=True)
    parser.add_argument("--topology-id", type=int, required=True)
    parser.add_argument("--expect", action="append", type=parse_target, required=True)
    parser.add_argument("--exclusive-window", action="store_true")
    parser.add_argument("--allow-clone-evidence-writes", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)
    try:
        report = asyncio.run(run(args))
    except Exception as exc:
        report = {"ok": False, "reason": str(exc) if isinstance(exc, ProbeRefused) else type(exc).__name__}
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(encoded + "\n")
    print(encoded)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
