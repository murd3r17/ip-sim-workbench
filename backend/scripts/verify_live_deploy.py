"""Three-device LLDP/LoopBack0 acceptance via the controlled deployment API.

prepare captures original versions and creates an unconfirmed batch; it never
confirms or writes a device. apply/restore require a human approval reference and
the SHA256 of the reviewed operation plan. Fixed display commands through the
unified adapter independently check running/saved state. All configuration writes
use confirm/execute/verify API endpoints. A durable unresolved POST is never retried.
LIVE_VERIFY_TOKEN must contain an ordinary authenticated admin token.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
from core.live_evidence import capture_binding, binding_unchanged
from core.runtime_identity import runtime_identity, same_runtime
from modules.deploy.config_verifier import ConfigVerifier
from scripts.verify_live_readonly import ExpectedTarget, ProbeRefused, parse_target, summarize_output, validate_runtime, validate_targets
from scripts.verify_live_workflows import require, validate_api_url


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def state_digest(configuration: str) -> str:
    """Stable bounded snapshot state; preserve every unknown positive/undo line.

    Only the two default-off/on equivalents already reviewed by verify_snapshot
    are omitted. VRP block/command ordering and comment timestamps are irrelevant.
    """
    canonical = []
    for path, commands_at_path in sorted(ConfigVerifier._state(configuration).items()):
        commands_at_path = {
            line for line in commands_at_path
            if not (not path and line == "undo lldp enable")
            and not (len(path) == 1 and path[0].startswith("interface ") and line == "undo shutdown")
        }
        if commands_at_path:
            canonical.append([list(path), sorted(commands_at_path)])
    return digest(json.dumps(canonical, ensure_ascii=False, separators=(",", ":")))


def load_journal(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_journal(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def require_same_build(before: dict, current: dict) -> None:
    # prepare may run safely with simulation enabled; switching to the explicitly
    # approved real write profile is the sole permitted cross-phase identity change.
    require(binding_unchanged({**before, "deploy_simulate_only": False},
                              {**current, "deploy_simulate_only": False}), "prepared_build_or_database_changed")


def write_profile(args, settings, targets) -> dict:
    require(bool(args.approval_reference and args.approval_reference.strip()), "human_approval_reference_required")
    require(settings.deploy_simulate_only is False, "real_execution_profile_required")
    ids = {int(value) for value in settings.deploy_allowlist_device_ids.split(",") if value.strip().isdigit()}
    hosts = {value.strip() for value in settings.deploy_allowlist_mgmt_ips.split(",") if value.strip()}
    require(ids == {t.device_id for t in targets} and hosts == {t.host for t in targets}, "exact_target_allowlist_required")
    require(settings.deploy_allowlist_topology_id == args.topology_id
            and settings.deploy_allowlist_baseline_version > 0, "versioned_topology_allowlist_required")
    return {"device_ids": sorted(ids), "mgmt_ips": sorted(hosts), "topology_id": args.topology_id,
            "baseline_version": settings.deploy_allowlist_baseline_version}


def commands(hostname: str, prefix: str) -> str:
    require(bool(re.fullmatch(r"[A-Za-z0-9_]{1,48}", prefix)) and hostname in {"R1", "R2", "R3"}, "invalid_probe_marker_or_name")
    return f"lldp enable\ninterface LoopBack0\ndescription {prefix}_{hostname}\nquit"


def require_original(configuration: str, hostname: str) -> None:
    summarize_output("display current-configuration", configuration, hostname)
    state = ConfigVerifier._state(configuration)
    loopback = state.get(("interface loopback0",))
    require(loopback is not None and not any(line.startswith("description ") for line in loopback),
            "original_loopback0_must_exist_without_description")
    require("lldp enable" not in state.get((), set()), "original_global_lldp_must_be_disabled")


def require_only_probe_change(original: str, current: str, content: str) -> None:
    require(ConfigVerifier._compare_config(content, current) is None, "probe_intent_not_present")
    inverse = ConfigVerifier.build_restore_commands(current, original)
    allowed = {"system-view", "undo lldp enable", "interface loopback0", "undo description", "quit", "return"}
    require(bool(inverse) and all(line.strip().lower() in allowed for line in inverse), "unapproved_configuration_difference")


class Api:
    def __init__(self, client, base, journal, path):
        self.client, self.base, self.journal, self.path = client, base, journal, path

    async def get(self, path):
        response = await self.client.request("GET", self.base + path)
        require(response.status_code == 200, "api_read_failed")
        return response.json()

    async def post(self, path, payload=None, *, allow_risk_pending=False):
        require(not self.journal.get("inflight"), "unresolved_operation_requires_manual_diagnosis")
        self.journal["inflight"] = {"path": path, "started_at": datetime.now(timezone.utc).isoformat()}
        save_journal(self.path, self.journal)  # Durable before any request can reach the server.
        response = await self.client.request("POST", self.base + path, json=payload)
        if (allow_risk_pending and response.status_code == 422
                and response.json().get("detail") == "高风险任务需要二次确认"):
            result = {"awaiting_risk_confirmation": True}
        else:
            require(response.status_code == 200, "api_operation_failed_requires_manual_diagnosis")
            result = response.json()
        self.journal["last_completed_request"] = self.journal.pop("inflight")
        save_journal(self.path, self.journal)
        return result


async def execute_confirmed(api, task_id: int, *, pre_execute=None) -> None:
    path = f"/deploy/tasks/{task_id}"
    confirmation = await api.post(path + "/confirm", {"risk_confirm": False}, allow_risk_pending=True)
    if confirmation.get("awaiting_risk_confirmation"):
        confirmation = await api.post(path + "/confirm", {"risk_confirm": True})
    require(confirmation.get("status") == "confirmed", "task_not_confirmed")
    if pre_execute is not None:
        await pre_execute()  # Recheck under the server's confirmed task lock.
    executed = await api.post(path + "/execute")
    require(executed.get("mode") == "real" and not executed.get("error_category"), "real_execution_failed")
    verified = await api.post(path + "/verify")
    require(verified.get("mode") == "real" and verified.get("verification") == "passed"
            and verified.get("result") == "success", "real_verification_failed")


class EvidenceDB:
    """Read-only connection to the exact clone also used by the API."""
    def __init__(self, connection):
        self.connection = connection

    async def rows(self, query, **params):
        from sqlalchemy import text
        await self.connection.rollback()  # Refresh the read snapshot after every API mutation.
        return list((await self.connection.execute(text(query), params)).mappings())

    async def device(self, target):
        rows = await self.rows("SELECT id,hostname,mgmt_ip,ssh_port,topology_id,model,username_encrypted,"
                               "password_encrypted,enable_encrypted FROM device WHERE id=:id", id=target.device_id)
        require(len(rows) == 1, "device_missing")
        return SimpleNamespace(**rows[0])

    async def version(self, version_id, device_id):
        rows = await self.rows("SELECT id,device_id,config_snapshot,deploy_task_id FROM config_version WHERE id=:id", id=version_id)
        require(len(rows) == 1 and rows[0]["device_id"] == device_id, "configuration_version_identity_mismatch")
        return rows[0]

    async def no_lock(self, device_id, *, owned_task=None):
        rows = await self.rows("SELECT task_id FROM device_write_lock WHERE device_id=:id", id=device_id)
        if owned_task is None:
            require(not rows, "device_write_lock_present")
        else:
            require(len(rows) == 1 and rows[0]["task_id"] == owned_task, "confirmed_task_lock_required")

    async def target_baseline(self, profile, targets):
        from modules.deploy.service import DeployService
        rows = await self.rows("SELECT snapshot_json FROM topology_version WHERE topology_id=:topology AND version=:version",
                               topology=profile["topology_id"], version=profile["baseline_version"])
        require(len(rows) == 1, "allowlist_baseline_missing")
        for target in targets:
            device = await self.device(target)
            require(device.topology_id == profile["topology_id"] and DeployService._device_in_snapshot(rows[0]["snapshot_json"], device),
                    "allowlist_baseline_identity_mismatch")
        return digest(rows[0]["snapshot_json"])

    async def task_evidence(self, task_id, device_id, original, content, *, restore):
        rows = await self.rows("SELECT * FROM deploy_task WHERE id=:id", id=task_id)
        require(len(rows) == 1, "task_missing")
        task = rows[0]
        require(task["device_id"] == device_id and task["status"] == "success" and task["verified"]
                and not task["error_message"] and not task["verify_diff"] and task["engine"] == "netmiko", "task_not_verified_success")
        backup, result = task["backup_config"], task["result_output"]
        require(bool(backup and result), "real_backup_and_readback_required")
        if restore:
            require(ConfigVerifier.verify_snapshot(original, task["config_content"]) is None
                    and ConfigVerifier.verify_snapshot(original, result) is None, "restored_snapshot_mismatch")
            require_only_probe_change(original, backup, content)
        else:
            require(task["config_content"] == content and ConfigVerifier.verify_snapshot(original, backup) is None,
                    "execution_backup_or_intent_changed")
            require_only_probe_change(original, result, content)
        versions = await self.rows("SELECT id,config_snapshot FROM config_version WHERE deploy_task_id=:id", id=task_id)
        require(len(versions) == 1 and ConfigVerifier.verify_snapshot(result, versions[0]["config_snapshot"]) is None,
                "verified_config_version_missing")
        audits = await self.rows("SELECT id,action,result,detail FROM audit_log WHERE module='deploy' AND resource_type='deploy_task' "
                                "AND resource_id=:id ORDER BY id", id=str(task_id))
        actions = {row["action"]: row for row in audits}
        created = "deploy_rollback_task_created" if restore else "deploy_task_created"
        chain = [created, "deploy_task_confirmed", "deploy_task_executed", "deploy_task_verified"]
        require(all(name in actions for name in [*chain, "device_write_lock_released"]), "audit_chain_incomplete")
        require([actions[name]["id"] for name in chain] == sorted(actions[name]["id"] for name in chain), "audit_chain_out_of_order")
        execution = ast.literal_eval(actions["deploy_task_executed"]["detail"])
        require(execution.get("mode") == "real" and execution.get("result") == "executed", "real_execution_audit_missing")
        await self.no_lock(device_id)
        return {"task_id": task_id, "device_id": device_id, "ok": True, "status": "success", "mode": "real",
                "verified": True, "locks": 0, "backup_sha256": digest(backup), "result_sha256": digest(result),
                "config_version_id": versions[0]["id"], "audit": [{k: row[k] for k in ("id", "action", "result")} for row in audits]}


async def read_current_saved(db, target, *, owned_task=None):
    from engines.device_adapter import get_device_adapter
    await db.no_lock(target.device_id, owned_task=owned_task)
    device = await db.device(target)
    require((device.hostname, device.mgmt_ip, device.ssh_port) == (target.hostname, target.host, target.port), "target_changed")
    adapter = await get_device_adapter(device)
    try:
        require(adapter.name == "ssh", "simulated_adapter_rejected")
        version = await adapter.run_command("display version")
        require(bool(re.search(r"\bVRP\b[^\r\n]*\bVersion\s+8\.\d+\s+\(NE40E\b", version, re.I)), "actual_ne40e_vrp8_required")
        running = await adapter.run_command("display current-configuration")
        saved = await adapter.run_command("display saved-configuration")
        for command, output in (("display current-configuration", running), ("display saved-configuration", saved)):
            summarize_output(command, output, target.hostname)
        require(ConfigVerifier.verify_snapshot(running, saved) is None, "running_saved_differ")
        return running, saved
    finally:
        await adapter.close()


async def prepare(api, db, args, journal):
    journal["devices"] = []
    for target in args.expect:
        captures = await api.post("/config-versions/capture", {"device_ids": [target.device_id]})
        require(len(captures) == 1 and captures[0]["device_id"] == target.device_id, "capture_identity_mismatch")
        before = await db.version(captures[0]["version_id"], target.device_id)
        original = before["config_snapshot"]
        require_original(original, target.hostname)
        running, saved = await read_current_saved(db, target)
        require(ConfigVerifier.verify_snapshot(original, running) is None, "capture_changed_before_prepare")
        journal["devices"].append({"device_id": target.device_id, "hostname": target.hostname,
                                   "original_version_id": before["id"], "original_sha256": digest(original),
                                   "original_state_sha256": state_digest(original),
                                   "original_running_sha256": digest(running), "original_saved_sha256": digest(saved),
                                   "original_running_saved_equivalent": True,
                                   "applied": False, "restored": False})
        save_journal(args.journal, journal)
    result = await api.post("/deploy/batches", {
        "name": "Live acceptance " + journal["run_id"], "source": "live_acceptance",
        "description": "LLDP + LoopBack0 temporary probe; operation plan " + args.plan_sha256,
        "items": [{"device_id": t.device_id, "config_content": commands(t.hostname, args.marker_prefix)} for t in args.expect],
    })
    require(len(result.get("items", [])) == 3, "prepared_batch_incomplete")
    journal["batch_id"] = result["id"]
    for item in journal["devices"]:
        task = next((task for task in result["items"] if task["device_id"] == item["device_id"]), None)
        require(task is not None and task["status"] == "awaiting_confirmation", "prepared_task_not_pending")
        item["apply_task_id"] = task["id"]
    journal["state"] = "prepared"
    save_journal(args.journal, journal)


async def mutate(api, db, args, settings, journal, *, restore):
    permitted = {"applied", "restoring"} if restore else {"prepared", "applying"}
    require(not journal.get("inflight") and journal["state"] in permitted,
            "unresolved_operation_requires_manual_diagnosis")
    if restore:
        require(len(journal["devices"]) == 3 and all(item["applied"] for item in journal["devices"]),
                "incomplete_apply_requires_manual_diagnosis")
    profile = write_profile(args, settings, args.expect)
    profile["baseline_sha256"] = await db.target_baseline(profile, args.expect)
    if journal.get("write_profile"):
        require(journal["write_profile"] == profile, "approved_write_profile_changed")
    journal["write_profile"] = profile
    journal["approval_reference_sha256"] = digest(args.approval_reference)
    journal["state"] = "restoring" if restore else "applying"
    save_journal(args.journal, journal)
    targets = list(reversed(args.expect)) if restore else args.expect
    for target in targets:
        item = next(row for row in journal["devices"] if row["device_id"] == target.device_id)
        completed = item["restored"] if restore else item["applied"]
        require_same_build(journal["prepare_binding"], capture_binding(settings))
        require(same_runtime(runtime_identity(settings), await api.get("/system/runtime-identity")), "server_runtime_identity_changed")
        original_row = await db.version(item["original_version_id"], target.device_id)
        original = original_row["config_snapshot"]
        require(digest(original) == item["original_sha256"], "original_version_changed")
        content = commands(target.hostname, args.marker_prefix)
        running, _ = await read_current_saved(db, target)
        if completed:
            if restore:
                require(ConfigVerifier.verify_snapshot(original, running) is None, "completed_restore_state_changed")
            else:
                require_only_probe_change(original, running, content)
            continue
        if restore:
            require_only_probe_change(original, running, content)
            response = await api.post(f"/deploy/config-versions/{item['original_version_id']}/rollback-task")
            require(response.get("device_id") == target.device_id and response.get("source_version_id") == item["original_version_id"],
                    "restore_task_identity_mismatch")
            task_id = item["restore_task_id"] = response["task_id"]
        else:
            require(ConfigVerifier.verify_snapshot(original, running) is None, "original_state_changed_before_apply")
            task_id = item["apply_task_id"]
        save_journal(args.journal, journal)
        task = await api.get(f"/deploy/tasks/{task_id}")
        require(task.get("device_id") == target.device_id and task.get("status") == "awaiting_confirmation"
                and not task.get("has_lock"), "task_state_requires_manual_diagnosis")
        if not restore:
            require(task.get("config_content") == content, "prepared_task_content_changed")
        async def check_locked_state():
            current, _ = await read_current_saved(db, target, owned_task=task_id)
            if restore:
                require_only_probe_change(original, current, content)
            else:
                require(ConfigVerifier.verify_snapshot(original, current) is None, "original_changed_after_confirmation")
        await execute_confirmed(api, task_id, pre_execute=check_locked_state)
        evidence = await db.task_evidence(task_id, target.device_id, original, content, restore=restore)
        running, saved = await read_current_saved(db, target)
        if restore:
            require(ConfigVerifier.verify_snapshot(original, running) is None and ConfigVerifier.verify_snapshot(original, saved) is None,
                    "final_original_running_saved_mismatch")
        else:
            require_only_probe_change(original, running, content)
        evidence.update(running_sha256=digest(running), saved_sha256=digest(saved), running_saved_equivalent=True,
                        running_state_sha256=state_digest(running), saved_state_sha256=state_digest(saved),
                        closed=True, original_restored=restore)
        item["restore" if restore else "apply"] = evidence
        item["restored" if restore else "applied"] = True
        save_journal(args.journal, journal)
    journal["state"] = "restored" if restore else "applied"
    for target in args.expect:
        await db.no_lock(target.device_id)
    save_journal(args.journal, journal)


async def run(args):
    import httpx
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine
    from core.config import get_settings
    from core.database import resolve_database_url

    settings = get_settings()
    start = capture_binding(settings)
    url = resolve_database_url(settings)
    validate_runtime(url, settings.device_mode, exclusive_window=args.exclusive_window)
    parsed = make_url(url)
    require(parsed.host in {"127.0.0.1", "localhost", "::1"} and parsed.port == args.expect_db_port
            and args.allow_clone_evidence_writes, "explicit_local_clone_required")
    api_url = validate_api_url(args.base_url)
    token = os.environ.get("LIVE_VERIFY_TOKEN", "")
    require(bool(token), "live_verify_token_required")
    require(hashlib.sha256(args.operation_plan.read_bytes()).hexdigest() == args.plan_sha256, "reviewed_operation_plan_sha256_mismatch")
    plan = args.operation_plan.read_text(encoding="utf-8-sig")
    require(len(args.expect) == 3 and [t.hostname for t in args.expect] == ["R1", "R2", "R3"], "ordered_three_device_plan_required")
    for target in args.expect:
        commands(target.hostname, args.marker_prefix)
        row = (r"(?m)^\|\s*" + re.escape(target.hostname) + r"\s*\|\s*" + str(target.device_id)
               + r"\s*\|\s*" + re.escape(target.host) + r"\s*\|\s*" + str(target.port) + r"\s*\|")
        require(bool(re.search(row, plan)) and commands("R1", args.marker_prefix) in plan.replace("\r\n", "\n"),
                "targets_or_marker_absent_from_reviewed_plan")
    targets = [{"id": t.device_id, "hostname": t.hostname, "mgmt_ip": t.host, "ssh_port": t.port} for t in args.expect]
    if args.phase == "prepare":
        require(not args.journal.exists(), "journal_already_exists_do_not_repeat_prepare")
        journal = {"schema": 1, "scope": "live_controlled_deployment", "run_id": uuid.uuid4().hex,
                   "state": "preparing", "targets": targets, "topology_id": args.topology_id,
                   "operation_plan_sha256": args.plan_sha256, "marker_prefix": args.marker_prefix,
                   "prepare_binding": start, "steps": []}
        args.journal.parent.mkdir(parents=True, exist_ok=True)
        with args.journal.open("x", encoding="utf-8") as handle:
            json.dump(journal, handle)
    else:
        journal = load_journal(args.journal)
        require(journal.get("targets") == targets and journal.get("topology_id") == args.topology_id
                and journal.get("operation_plan_sha256") == args.plan_sha256
                and journal.get("marker_prefix") == args.marker_prefix, "prepared_plan_or_targets_changed")
        require_same_build(journal["prepare_binding"], start)
        write_profile(args, settings, args.expect)  # Before any device/API mutation.
    phase_report = {"phase": args.phase, "started_at": start["captured_at"], "ok": False}
    journal["steps"].append(phase_report)
    engine = create_async_engine(url, echo=False, pool_size=1, max_overflow=0, connect_args={"connect_timeout": 10})
    try:
        async with engine.connect() as conn, httpx.AsyncClient(timeout=240, trust_env=False, follow_redirects=False,
                                                             headers={"Authorization": "Bearer " + token}) as client:
            await conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
            api, db = Api(client, api_url, journal, args.journal), EvidenceDB(conn)
            require(same_runtime(runtime_identity(settings), await api.get("/system/runtime-identity")), "server_runtime_identity_mismatch")
            inventory = await api.get(f"/devices?topology_id={args.topology_id}")
            validate_targets([SimpleNamespace(**device) for device in inventory], args.expect)
            require(all(device.get("status") == "online" for device in inventory), "devices_not_verified_online")
            if args.phase == "prepare":
                await prepare(api, db, args, journal)
            else:
                await mutate(api, db, args, settings, journal, restore=args.phase == "restore")
            phase_report["ok"] = True
    except Exception as exc:
        phase_report["reason"] = str(exc) if isinstance(exc, ProbeRefused) else type(exc).__name__
        journal["state"] = "requires_manual_diagnosis"
    finally:
        await engine.dispose()
        finish = capture_binding(settings)
        phase_report.update(binding={"start": start, "finish": finish}, finished_at=finish["captured_at"])
        if not binding_unchanged(start, finish):
            phase_report.update(ok=False, reason="runtime_or_source_changed_during_probe")
            journal["state"] = "requires_manual_diagnosis"
        save_journal(args.journal, journal)
    return {"schema": 1, "scope": "live_controlled_deployment", "ok": phase_report["ok"],
            "phase": args.phase, "state": journal["state"], "targets": targets,
            "run_id": journal["run_id"], "batch_id": journal.get("batch_id"), "write_profile": journal.get("write_profile"),
            "operation_plan_sha256": args.plan_sha256, "approval_reference_sha256": journal.get("approval_reference_sha256"),
            "devices": journal.get("devices", []), **{k: phase_report[k] for k in ("binding", "started_at", "finished_at")},
            "reason": phase_report.get("reason")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "apply", "restore"))
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expect-db-port", type=int, required=True)
    parser.add_argument("--topology-id", type=int, required=True)
    parser.add_argument("--expect", action="append", type=parse_target, required=True)
    parser.add_argument("--operation-plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--marker-prefix", default="IP_SIM_V6_ACCEPT_20261011")
    parser.add_argument("--approval-reference")
    parser.add_argument("--exclusive-window", action="store_true")
    parser.add_argument("--allow-clone-evidence-writes", action="store_true")
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)
    lock_path = args.journal.with_name(args.journal.name + ".lock")
    lock_created = False
    try:
        require(not args.output.exists(), "report_already_exists")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with lock_path.open("x", encoding="utf-8") as handle:
                handle.write(str(os.getpid()))
            lock_created = True
        except FileExistsError:
            raise ProbeRefused("journal_in_use_or_interrupted_requires_manual_diagnosis") from None
        report = asyncio.run(run(args))
    except Exception as exc:
        report = {"ok": False, "reason": str(exc) if isinstance(exc, ProbeRefused) else type(exc).__name__}
    finally:
        if lock_created:
            lock_path.unlink(missing_ok=True)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(encoded + "\n")
    print(encoded)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
