"""Explicit live acceptance in a recipient-owned fresh MySQL and independent root.

Runs the shipped bootstrap/start entries and live probes. It never reads the
reference workspace configuration, migrates an existing store, or writes devices.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))


def require(value, reason):
    if not value:
        raise ValueError(reason)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical_hash(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def run_command(command, root, timeout=300):
    # The full controller leaves a durable receipt even if it times out after
    # spawning. The caller's finally block recovers through that receipt.
    child = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        output, _ = child.communicate(timeout=timeout)
        return child.returncode, output
    except BaseException:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)
        raise


def owned_from_receipt(path, earliest):
    from scripts.full_lifecycle import read_receipt, receipt_path
    data = read_receipt(ROOT, receipt_path(ROOT, path, 8000))
    require(type(data.get("started_ms")) is int and earliest <= data["started_ms"] <= int(time.time() * 1000),
            "recipient_launch_receipt_invalid")
    return None if data["state"] == "STOPPED" else data


def stop_owned(record):
    from scripts.full_lifecycle import operation_lock, receipt_path, read_receipt, stop
    path = receipt_path(ROOT, Path(record["receipt"]), record["port"])
    with operation_lock(ROOT / ".runtime"):
        require(read_receipt(ROOT, path)["launch_id"] == record["launch_id"], "recipient_launch_receipt_replaced")
        stop(ROOT, path)


async def wait_port_closed(port):
    for _ in range(30):
        with socket.socket() as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return
        await asyncio.sleep(0.1)
    raise ValueError("recipient_owned_server_still_listening")


async def database_facts(settings):
    from sqlalchemy import inspect, select
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from core.database import resolve_database_url, _import_all_models
    from core.migrations import assert_schema_ready

    engine = create_async_engine(resolve_database_url(settings), echo=False)
    try:
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
            if not tables:
                return {"table_count": 0}
            _import_all_models()
            await conn.run_sync(assert_schema_ready)
        from modules.device.models import Device
        from modules.device.baseline_service import TopologyBaselineService
        from modules.training.models import TrainingLab
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            devices = list((await db.scalars(select(Device).order_by(Device.hostname))).all())
            targets = [{"id": d.id, "hostname": d.hostname, "mgmt_ip": d.mgmt_ip, "ssh_port": d.ssh_port} for d in devices]
            topologies = sorted({d.topology_id for d in devices})
            snapshots = [await TopologyBaselineService._snapshot(db, ident) for ident in topologies]
            labs = list((await db.scalars(select(TrainingLab).order_by(TrainingLab.id))).all())
            retained = {"snapshots": snapshots, "labs": [{"id": lab.id, "title": lab.title, "description": lab.description,
                        "objectives": lab.objectives, "scoring_rules": lab.scoring_rules, "topology_id": lab.topology_id} for lab in labs]}
            return {"table_count": len(tables), "device_count": len(devices), "lab_count": len(labs), "targets": targets,
                    "topology_ids": topologies, "retained_sha256": canonical_hash(retained)}
    finally:
        await engine.dispose()


async def authenticated_start(settings, base, expected, launcher):
    import httpx
    from core.runtime_identity import same_runtime

    async with httpx.AsyncClient(timeout=45, trust_env=False) as client:
        login = await client.post(base + "/api/v1/auth/login", json={"username": settings.admin_username, "password": settings.admin_password})
        require(login.status_code == 200, "recipient_login_failed")
        token = login.json()["access_token"]
        response = await client.get(base + "/api/v1/system/runtime-identity", headers={"Authorization": "Bearer " + token})
        require(response.status_code == 200, "recipient_identity_failed")
        actual = response.json()
        require(same_runtime(expected, actual), "recipient_runtime_mismatch")
        require(actual.get("pid") == launcher["pid"] or actual.get("parent_pid") == launcher["pid"], "recipient_launch_pid_mismatch")
        require(actual.get("launch_id") == launcher["launch_id"], "recipient_launch_identity_mismatch")
        health = await client.get(base + "/api/v1/health")
        require(health.status_code == 200, "recipient_health_failed")
        components = health.json().get("components", {})
        require(all(components.get(key, {}).get("status") == "healthy" for key in ("mysql", "llm", "knowledge")), "recipient_components_unhealthy")
        page = await client.get(base + "/")
        # Compare the exact bytes the server returned with the packaged file.
        # A text-mode read translates CRLF to LF while an HTTP body keeps CRLF,
        # so identical content used to look different. No strip or normalisation:
        # any byte difference is a real mismatch.
        raw = (ROOT / "sim-frontend/dist/index.html").read_bytes()
        require(page.status_code == 200 and page.content == raw, "recipient_static_build_mismatch")
        # frontend_sha256 used to be a digest of the normalised text; both fields are
        # now the raw-bytes digest of the same packaged file.
        return {"ok": True, "runtime_identity": actual, "frontend_sha256": digest(raw),
                "frontend_file_sha256": digest(raw),
                "components": {key: components[key]["status"] for key in ("mysql", "llm", "knowledge")}}


def target_keys(targets):
    require(isinstance(targets, list) and len(targets) == 3, "recipient_three_targets_required")
    require(all(type(t.get("id")) is int and t["id"] > 0 for t in targets)
            and len({t["id"] for t in targets}) == 3, "recipient_unique_target_ids_required")
    keys = {(t["id"], t["hostname"], t["mgmt_ip"], t["ssh_port"]) for t in targets}
    require(len({(t[1], t[2], t[3]) for t in keys}) == 3
            and len({(t[2], t[3]) for t in keys}) == 3, "recipient_unique_targets_required")
    return keys


def core_device_smoke(raw, targets):
    """LLDP is a separate topology acceptance; startup credentials need core SSH."""
    require(raw.get("core_readonly_ok") is True and raw.get("running_saved_equivalent") is True, "recipient_core_device_probe_failed")
    require(len(raw.get("devices", [])) == 3, "recipient_three_device_probe_required")
    observed = [{"id": d.get("device_id"), "hostname": d.get("hostname"), "mgmt_ip": d.get("host"), "ssh_port": d.get("port")} for d in raw["devices"]]
    require(target_keys(observed) == target_keys(targets), "recipient_device_targets_mismatch")
    for device in raw["devices"]:
        require(device.get("closed") is True and device.get("adapter") == "ssh" and device.get("running_saved_equivalent") is True, "recipient_device_probe_incomplete")
        commands = {c["command"]: c for c in device["commands"]}
        for name in ("display version", "display current-configuration", "display saved-configuration", "display interface brief"):
            item = commands[name]
            require(item.get("line_count", 0) > 0 and re.fullmatch(r"[a-f0-9]{64}", item.get("redacted_sha256", "")), "recipient_device_observation_missing")
        require(commands["display version"].get("huawei_vrp") is True and all(commands[name].get("identity_matches") is True for name in ("display current-configuration", "display saved-configuration")), "recipient_device_identity_failed")
        require(type(commands["display interface brief"].get("interface_count")) is int
                and commands["display interface brief"]["interface_count"] > 0, "recipient_device_interfaces_missing")


async def verify(args):
    from core.config import get_settings
    from core.live_evidence import capture_binding, binding_unchanged
    from core.database import resolve_database_url
    from core.runtime_identity import same_runtime
    from sqlalchemy.engine import make_url
    from scripts.setup_full_workspace import validate_manifest, prepare_corpus

    settings = get_settings()
    start = capture_binding(settings)
    report = {"schema": 1, "producer": "verify_recipient_first_run", "scope": "independent_fresh_mysql_recipient",
              "run_id": uuid.uuid4().hex, "ok": False, "steps": [], "reports": []}
    owned = None
    receipt = None
    launched_at = None
    def add(name, ok, **observations):
        report["steps"].append({"name": name, "ok": bool(ok), **observations})
    async def command(name, argv, *, timeout=300, acceptable=(0,)):
        status, output = await asyncio.to_thread(run_command, argv, ROOT, timeout)
        add(name, status in acceptable, exit_code=status, output_sha256=digest(output))
        require(status in acceptable, name + "_failed")
        return output
    def accept_child(raw):
        begin, end = raw["binding"]["start"], raw["binding"]["finish"]
        require(binding_unchanged(begin, end) and same_runtime(start, begin)
                and begin["source_fingerprint"] == start["source_fingerprint"], "recipient_child_binding_mismatch")
        report["reports"].append({"sha256": canonical_hash(raw), "report": raw})
    python = ROOT / "backend/.venv/Scripts/python.exe"
    powershell = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]
    try:
        reference = json.loads(args.reference_identity.read_text(encoding="utf-8-sig"))
        require(all(isinstance(reference.get(key), str) and re.fullmatch(r"[a-f0-9]{64}", reference[key]) for key in ("source_fingerprint", "root_fingerprint", "database_fingerprint")), "reference_fingerprints_required")
        require(start["source_fingerprint"] == reference["source_fingerprint"], "recipient_build_mismatch")
        require(start["root_fingerprint"] != reference["root_fingerprint"] and start["database_fingerprint"] != reference["database_fingerprint"], "independent_root_and_database_required")
        report["reference"] = {key: reference[key] for key in ("source_fingerprint", "root_fingerprint", "database_fingerprint")}
        parsed = make_url(resolve_database_url(settings))
        require(parsed.get_backend_name() == "mysql" and parsed.database == args.expect_database, "recipient_mysql_database_mismatch")
        require(settings.device_mode == "ssh" and settings.knowledge_provider == "anythingllm"
                and settings.deploy_simulate_only and not settings.monitor_scheduler_enabled, "recipient_safe_full_profile_required")
        require(args.exclusive_window and args.recipient_configured, "recipient_configuration_and_exclusive_window_required")
        require((ROOT / ".env").is_file() and python.is_file() and (ROOT / "backend/requirements.lock").is_file()
                and (ROOT / "sim-frontend/dist/index.html").is_file(), "recipient_package_or_own_configuration_missing")
        manifest = validate_manifest(json.loads(args.manifest.read_text(encoding="utf-8-sig")))
        report["manifest_sha256"] = canonical_hash(manifest)
        report["manifest"] = manifest
        report["manifest_targets"] = manifest["devices"]
        report["configuration"] = {"source": "recipient_root_and_process_environment", "recipient_asserted": True,
                                    "device_writes_disabled": True, "scheduler_disabled": True}
        before = await database_facts(settings)
        require(before["table_count"] == 0, "recipient_mysql_must_be_completely_empty")
        report["database_before"] = before
        add("independent_empty_mysql", True)
        await command("bootstrap_full", powershell + [str(ROOT / "scripts/bootstrap-local.ps1"), "-Mode", "full", "-NoStart"], timeout=900)
        await command("import_manifest", [str(python), str(ROOT / "backend/scripts/setup_full_workspace.py"), "import-devices", "--manifest", str(args.manifest.resolve()), "--expect-database", args.expect_database])
        imported = await database_facts(settings)
        require(imported["device_count"] == 3 and imported["lab_count"] == 7 and len(imported["topology_ids"]) == 1, "recipient_inventory_incomplete")
        actual_targets = target_keys(imported["targets"])
        require({t[1:] for t in actual_targets} == {(t["hostname"], t["mgmt_ip"], t["ssh_port"]) for t in manifest["devices"]}, "recipient_import_manifest_mismatch")
        report["imported"] = imported
        corpus = prepare_corpus(ROOT / "knowledge/corpus/huawei-ip", args.output / "corpus-upload")
        report["corpus"] = {"document_count": corpus["document_count"], "uploaded": False, "manifest_sha256": canonical_hash(corpus)}
        add("corpus_prepared", corpus["document_count"] == 135)
        base = f"http://127.0.0.1:{args.backend_port}"
        report["starts"] = []
        for attempt in (1, 2):
            launched_at = int(time.time() * 1000)
            receipt = args.output / f"launch-{attempt}-{uuid.uuid4().hex}.json"
            output = await command(f"start_full_{attempt}", powershell + [str(ROOT / "scripts/start-full.ps1"), "-Root", str(ROOT), "-BackendPort", str(args.backend_port), "-LaunchReceipt", str(receipt)], timeout=300)
            owned = await asyncio.to_thread(owned_from_receipt, receipt, launched_at)
            require(owned is not None and owned["state"] == "READY", "recipient_launch_process_exited")
            matches = re.findall(rb"PID=(\d+)", output)
            require(len(matches) == 1, "recipient_launch_pid_missing")
            require(int(matches[0]) == owned["pid"], "recipient_launch_pid_mismatch")
            authenticated = await authenticated_start(settings, base, start, owned)
            report["starts"].append({**authenticated, "launcher": owned})
            add(f"authenticated_start_{attempt}", authenticated["ok"])
            if attempt == 1:
                ai_file = args.output / "providers.json"
                await command("live_provider_probe", [str(python), str(ROOT / "backend/scripts/verify_live_ai.py"), "--output", str(ai_file)], timeout=300)
                ai = json.loads(ai_file.read_text(encoding="utf-8"))
                require(ai.get("ok") is True, "recipient_provider_probe_failed")
                accept_child(ai)
                device_file = args.output / "devices.json"
                device_command = [str(python), str(ROOT / "backend/scripts/verify_live_readonly.py"), "--exclusive-window", "--capture-saved", "--output", str(device_file)]
                for target in imported["targets"]:
                    device_command += ["--expect", f"{target['id']},{target['hostname']},{target['mgmt_ip']},{target['ssh_port']}"]
                # LLDP-disabled makes this broader probe exit 1. Evaluate its
                # explicit core + saved-equivalence evidence, never waive errors.
                await command("live_device_probe", device_command, timeout=600, acceptable=(0, 1))
                devices = json.loads(device_file.read_text(encoding="utf-8"))
                core_device_smoke(devices, imported["targets"])
                accept_child(devices)
                add("three_core_devices_and_saved_state", True, topology_lldp_acceptance=False)
            else:
                retained = await database_facts(settings)
                report["after_restart"] = retained
                require(retained["retained_sha256"] == imported["retained_sha256"], "recipient_inventory_not_persistent")
                require(report["starts"][0]["runtime_identity"]["launch_id"] != authenticated["runtime_identity"]["launch_id"], "recipient_restart_not_new_process")
                add("restart_persistence", True)
            await asyncio.to_thread(stop_owned, owned)
            await wait_port_closed(args.backend_port)
            owned = None
            receipt = None
            add(f"owned_process_stopped_{attempt}", True)
        report["ok"] = all(step["ok"] for step in report["steps"])
    except Exception as exc:
        add("recipient_run_failed", False, error_type=type(exc).__name__, reason=str(exc) if type(exc) is ValueError and re.fullmatch(r"[a-z_]+", str(exc)) else "probe_failed")
    finally:
        if owned is None and receipt is not None and receipt.is_file():
            try:
                owned = await asyncio.to_thread(owned_from_receipt, receipt, launched_at)
                if owned is None:
                    await wait_port_closed(args.backend_port)
                    add("owned_process_cleanup", True, already_exited=True)
            except Exception as exc:
                add("owned_process_cleanup", False, error_type=type(exc).__name__)
                report["ok"] = False
        if owned is not None:
            try:
                await asyncio.to_thread(stop_owned, owned)
                await wait_port_closed(args.backend_port)
                add("owned_process_cleanup", True)
            except Exception as exc:
                add("owned_process_cleanup", False, error_type=type(exc).__name__)
                report["ok"] = False
        finish = capture_binding(settings)
        report.update(binding={"start": start, "finish": finish}, started_at=start["captured_at"], finished_at=finish["captured_at"])
        if not binding_unchanged(start, finish):
            add("build_runtime_unchanged", False)
            report["ok"] = False
        else:
            add("build_runtime_unchanged", True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-identity", type=Path, required=True, help="Non-secret source/root/database fingerprints only")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expect-database", required=True)
    parser.add_argument("--backend-port", type=int, required=True)
    parser.add_argument("--exclusive-window", action="store_true")
    parser.add_argument("--recipient-configured", action="store_true")
    parser.add_argument("--output", type=Path, required=True, help="New run directory inside this root's .runtime")
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)
    try:
        args.output = args.output.resolve()
        require(args.output.is_relative_to((ROOT / ".runtime").resolve()) and not args.output.exists(), "new_recipient_runtime_output_required")
        require(0 < args.backend_port < 65536, "invalid_backend_port")
        args.output.mkdir(parents=True, exist_ok=False)
        report = asyncio.run(verify(args))
        with (args.output / "report.json").open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}))
        return 1
    print(json.dumps({"ok": report["ok"], "report": str(args.output / "report.json"), "steps": report["steps"]}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
