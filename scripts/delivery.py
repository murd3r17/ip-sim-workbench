"""Read-only delivery gates, isolated preparation, and manifest-based clean export.

No application imports at module level; check/package never load local .env files.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
import uuid
import zipfile

EVIDENCE = "delivery-evidence.json"
ROOT_FILES = {"README.md", "AGENTS.md", ".env.example", ".gitignore", ".gitattributes", "DELIVERY-REDACTIONS.json",
              "环境与部署上下文.md", "最小清单交付说明.md"}
TREE_ROOTS = {"backend", "sim-frontend", "scripts", "knowledge", "init-sql", "nginx", "docs"}
EXCLUDED_DIRS = {".git", ".runtime", ".venv", "venv", "node_modules", "__pycache__",
                 ".pytest_cache", ".mypy_cache", "logs", "uploads", "test-results",
                 "playwright-report", "archive-ragflow", "plans-legacy", "superpowers"}
EXCLUDED_SUFFIXES = {".pyc", ".log", ".db", ".sqlite", ".sqlite3", ".bak", ".tmp",
                     ".pem", ".key", ".p12", ".pfx", ".docx", ".pdf"}
REQUIRED = {"backend/requirements.lock", "sim-frontend/package-lock.json", "sim-frontend/dist/index.html",
            ".env.example", "backend/main.py", "scripts/bootstrap-local.ps1"}
MINIMAL_STEPS = {"backend_tests", "frontend_types", "frontend_lint", "frontend_contracts",
                 "frontend_build", "minimal_bootstrap", "sim_devices", "sim_training", "minimal_smoke",
                 "browser_inventory", "browser_e2e"}
FULL_STEPS = {"isolated_mysql", "external_providers", "live_devices", "browser_webssh",
              "business_workflows", "real_deployment", "live_browser",
              "abnormal_concurrency", "recipient_first_run"}


def code_fingerprint(inventory: dict[str, str]) -> str:
    """Bind live evidence to the exact executable payload, independent of reports."""
    code = {name: digest for name, digest in inventory.items()
            if name.startswith(("backend/", "scripts/", "sim-frontend/", "init-sql/", "nginx/", "knowledge/"))
            or name == ".env.example"}
    return hashlib.sha256(json.dumps(code, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def canonical_report_hash(report: dict) -> str:
    """Stable JSON digest of the embedded redacted report, not its filename."""
    return hashlib.sha256(json.dumps(report, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _positive(value):
    return type(value) is int and value > 0


def _timestamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("timezone_required")
    return result


def _named(items, key="name"):
    if not isinstance(items, list) or not items or any(not isinstance(item, dict) for item in items):
        raise ValueError("observations_required")
    result = {item[key]: item for item in items}
    if len(result) != len(items):
        raise ValueError("duplicate_observations")
    return result


def _targets(items):
    if not isinstance(items, list) or len(items) != 3:
        raise ValueError("three_targets_required")
    rows = [(item["id"], item["hostname"], item["mgmt_ip"], item["ssh_port"]) for item in items]
    if (len({r[0] for r in rows}) != 3 or len({r[1] for r in rows}) != 3
            or len({(r[2], r[3]) for r in rows}) != 3
            or any(not _positive(r[0]) or not isinstance(r[1], str) or not r[1].strip()
                   or not isinstance(r[2], str) or not r[2].strip()
                   or not _positive(r[3]) or r[3] > 65535 for r in rows)):
        raise ValueError("invalid_targets")
    return sorted(rows)


def _llm(value):
    provider, base, model = value["provider"], value["base_url"], value["model"]
    parsed = urlsplit(base)
    if (provider not in {"openai", "openai_compatible"} or parsed.scheme != "https"
            or parsed.hostname != "api.deepseek.com" or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not isinstance(model, str) or re.fullmatch(r"deepseek[-\w.]*", model, re.I) is None):
        raise ValueError("live_deepseek_required")
    return provider, base.rstrip("/"), model


def _runtime_matches(actual, expected):
    keys = ("database_fingerprint", "root_fingerprint", "device_mode", "knowledge_provider", "deploy_simulate_only")
    return actual.get("schema") == 1 and all(key in actual and actual[key] == expected[key] for key in keys)


def _bound_report(raw, identity, fingerprint, window):
    binding = raw["binding"]
    start, finish = binding["start"], binding["finish"]
    keys = ("schema", "database_fingerprint", "root_fingerprint", "device_mode",
            "deploy_simulate_only", "knowledge_provider", "source_fingerprint")
    if (not all(key in start and key in finish and start[key] == finish[key] for key in keys)
            or type(start["deploy_simulate_only"]) is not bool
            or start["source_fingerprint"] != fingerprint or not _runtime_matches(start, identity)):
        return False
    first, last = _timestamp(start["captured_at"]), _timestamp(finish["captured_at"])
    created = _timestamp(raw.get("started_at") or raw["created_at"])
    completed = _timestamp(raw["finished_at"])
    return window[0] <= first <= created <= completed <= last <= window[1]


def _deployment_bound_report(raw, identity, fingerprint, window):
    # Preparation is read-only and may precede the explicitly approved change
    # from safe mode to real writes. Every other identity field stays identical.
    if identity.get("deploy_simulate_only") is not False:
        return False
    expected = identity
    if raw.get("phase") == "prepare":
        expected = {**identity, "deploy_simulate_only": raw["binding"]["start"]["deploy_simulate_only"]}
    return _bound_report(raw, expected, fingerprint, window)


def _provider_observations(raw, identity):
    if (raw.get("schema_version") != 1 or raw.get("scope") != "deepseek_and_anythingllm_readonly"
            or raw.get("ok") is not True or raw["identity"].get("device_mode") != "ssh"
            or _llm(raw["identity"]["llm"]) != _llm(identity["llm"])
            or raw["identity"]["llm"].get("fallback_used") is not False
            or raw["identity"]["knowledge"].get("provider") != "anythingllm"
            or raw["identity"]["knowledge"].get("expected_documents") != 135):
        return False
    checks = _named(raw["checks"])
    if not all(item.get("ok") is True for item in checks.values()):
        return False
    for name in ("deepseek_generate", "deepseek_stream"):
        evidence = checks[name]["evidence"]
        if not (_positive(evidence["characters"]) and _hash(evidence["response_sha256"])
                and evidence.get("challenge_matched") is True):
            return False
    stream = checks["deepseek_stream"]["evidence"]
    if not (_positive(stream["content_chunks"]) and stream.get("terminal_marker_validated_by_provider") is True):
        return False
    if checks["anythingllm_health"]["evidence"].get("document_count") != 135:
        return False
    retrieved = checks["anythingllm_retrieval"]["evidence"]
    chunks = retrieved["chunks"]
    return (isinstance(chunks, list) and bool(chunks)
            and retrieved.get("verified_chunk_count") == len(chunks)
            and type(retrieved.get("returned_count")) is int and retrieved["returned_count"] >= len(chunks)
            and all(_hash(chunk["source_identity_sha256"]) and _hash(chunk["chunk_sha256"])
                    and _positive(chunk["characters"]) and type(chunk["score"]) in (int, float)
                    and math.isfinite(chunk["score"]) for chunk in chunks))


def _device_observations(raw, identity):
    if (raw.get("schema") != 1 or raw.get("scope") != "serial_device_readonly"
            or raw.get("ok") is not True or raw.get("core_readonly_ok") is not True or raw.get("device_mode") != "ssh"):
        return False
    targets = [{"id": d["device_id"], "hostname": d["hostname"], "mgmt_ip": d["host"], "ssh_port": d["port"]} for d in raw["devices"]]
    if _targets(targets) != _targets(identity["targets"]):
        return False
    for device in raw["devices"]:
        if device.get("ok") is not True or device.get("closed") is not True or device.get("adapter") != "ssh":
            return False
        commands = _named(device["commands"], "command")
        for name in ("display version", "display current-configuration", "display interface brief", "display lldp neighbor brief"):
            command = commands[name]
            if command.get("ok") is False or not _hash(command["redacted_sha256"]) or not _positive(command["line_count"]):
                return False
        if (commands["display version"].get("huawei_vrp") is not True
                or commands["display current-configuration"].get("identity_matches") is not True
                or not _positive(commands["display current-configuration"]["interface_count"])
                or not _positive(commands["display interface brief"]["interface_count"])
                or type(commands["display lldp neighbor brief"]["neighbor_count"]) is not int
                or commands["display lldp neighbor brief"]["neighbor_count"] < 0):
            return False
    return True


def _business_observations(raw, identity):
    required = {"database_and_three_targets", "admin_login", "runtime_identity", "admin_identity",
                "api_targets_match_database", "effective_authenticated_health", "anythingllm_health",
                "knowledge_retrieval", "deepseek_generate_cli", "configuration_preview_validation",
                "deepseek_review", "knowledge_answer", "copilot_real_display_tool", "training_session_create",
                "training_honest_process_record", "training_hint", "training_report", "training_complete",
                "training_score_unverified", "training_evidence_retained", "source_unchanged_during_run"}
    if (raw.get("schema") != 2 or raw.get("producer") != "verify_full_stack"
            or raw["verdict"].get("ok") is not True or raw["verdict"].get("failed") != []
            or not _runtime_matches(raw["expected_identity"], identity)
            or not _runtime_matches(raw["runtime_identity"], identity)
            or _targets(raw["targets"]) != _targets(identity["targets"])
            or _llm(raw["llm"]) != _llm(identity["llm"])):
        return False
    steps = _named(raw["steps"])
    if not required <= steps.keys() or not all(s.get("ok") is True for s in steps.values()):
        return False
    logs = raw["ai_logs"]
    kinds = {"generate_cli", "review_config", "copilot_chat", "coach_training", "generate_report"}
    return (isinstance(logs, list) and kinds <= {row["request_type"] for row in logs}
            and all(_positive(row["id"]) and row["model_used"] == identity["llm"]["model"] for row in logs)
            and bool(raw["session_ids"]) and all(_positive(i) for i in raw["session_ids"])
            and bool(raw["tool_audit_ids"]) and all(_positive(i) for i in raw["tool_audit_ids"]))


def _workflow_observations(raw, identity):
    if (raw.get("schema") != 1 or raw.get("scope") != "live_webssh_and_monitor"
            or raw.get("ok") is not True or not _runtime_matches(raw["runtime_identity"], identity)
            or _targets(raw["targets"]) != _targets(identity["targets"])):
        return False
    steps = raw["steps"]
    if not isinstance(steps, list) or len(steps) != 5 or any(s.get("ok") is not True for s in steps):
        return False
    terminals = _named([s for s in steps if s.get("name") == "webssh"], "device_id")
    targets = {t["id"]: t for t in identity["targets"]}
    if terminals.keys() != targets.keys():
        return False
    for ident, terminal in terminals.items():
        version = terminal["version"]
        if (terminal.get("closed") is not True or terminal["hostname"] != targets[ident]["hostname"]
                or version.get("command") != "display version" or version.get("huawei_vrp") is not True
                or not _positive(version["line_count"]) or not _hash(version["redacted_sha256"])):
            return False
    jobs = _named([s for s in steps if s.get("name") in {"collect", "inspections"}])
    if set(jobs) != {"collect", "inspections"}:
        return False
    if jobs["collect"]["task_id"] == jobs["inspections"]["task_id"] or jobs["collect"]["topology_id"] != jobs["inspections"]["topology_id"]:
        return False
    for job in jobs.values():
        if (not _positive(job["task_id"]) or not _positive(job["topology_id"])
                or job.get("evidence_scope") != "current_job" or job.get("device_count") != 3
                or sorted(job["device_ids"]) != sorted(targets) or job.get("metric_points", 0) < 12
                or any(type(job[key]) is not int or job[key] != expected
                       for key, expected in (("expected", 3), ("attempted", 3), ("success", 3), ("failed", 0), ("skipped", 0)))):
            return False
        # Persisted MySQL DATETIME uses UTC with second precision and no offset.
        start, end = (datetime.fromisoformat(job[key]) for key in ("started_at", "finished_at"))
        start = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start
        end = end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end
        if not (_timestamp(raw["binding"]["start"]["captured_at"]) - timedelta(seconds=1) <= start <= end
                <= _timestamp(raw["binding"]["finish"]["captured_at"]) + timedelta(seconds=1)):
            return False
    return True


def _browser_observations(raw, identity):
    if (raw.get("schema") != 2 or raw.get("producer") != "verify_live_browser" or raw.get("ok") is not True
            or raw.get("errors") != [] or not _runtime_matches(raw["runtime_identity"], identity)
            or _llm(raw["llm"]) != _llm(identity["llm"]) or _targets(raw["targets"]) != _targets(identity["targets"])):
        return False
    checks = _named(raw["checks"])
    names = {"login", "dashboard", "devices", "topology", "deployment", "monitor", "copilot", "training", "system"}
    if not all(checks[name].get("ok") is True and checks[name].get("mode") == "live" for name in names):
        return False
    for name, model in (("copilot", identity["llm"]["model"]), ("copilot_vision", raw["vision"]["model"])):
        check = checks[name]
        evidence = check["evidence"]
        if not (check.get("ok") is True and check.get("mode") == "live" and _positive(evidence["content_characters"])
                and evidence.get("terminal_ok") is True and evidence.get("fallback_used") is False
                and _positive(evidence["ai_log_id"]) and evidence["model_used"] == model and isinstance(model, str) and model):
            return False
        if name == "copilot_vision" and not (evidence.get("challenge_not_in_prompt") is True and _hash(evidence["source_image_sha256"])):
            return False
    return True


def _recipient_observations(raw, identity, inventory):
    if raw.get("schema") != 1 or raw.get("producer") != "verify_recipient_first_run" or raw.get("ok") is not True:
        return False
    fingerprint = code_fingerprint(inventory)
    own = raw["binding"]["start"]
    reference = raw["reference"]
    if (reference.get("source_fingerprint") != fingerprint
            or any(reference.get(key) != identity[key] or own[key] == identity[key]
                   for key in ("root_fingerprint", "database_fingerprint"))
            or own.get("device_mode") != "ssh" or own.get("knowledge_provider") != "anythingllm"
            or own.get("deploy_simulate_only") is not True):
        return False
    required = {"independent_empty_mysql", "bootstrap_full", "import_manifest", "corpus_prepared", "start_full_1", "start_full_2",
                "authenticated_start_1", "authenticated_start_2", "live_provider_probe", "live_device_probe",
                "three_core_devices_and_saved_state", "restart_persistence", "owned_process_stopped_1", "owned_process_stopped_2", "build_runtime_unchanged"}
    steps = _named(raw["steps"])
    if not required <= steps.keys() or any(s.get("ok") is not True for s in steps.values()):
        return False
    if raw["database_before"].get("table_count") != 0 or raw["configuration"].get("source") != "recipient_root_and_process_environment":
        return False
    if any(raw["configuration"].get(key) is not True for key in ("recipient_asserted", "device_writes_disabled", "scheduler_disabled")):
        return False
    manifest = raw["manifest"]
    if raw["manifest_sha256"] != canonical_report_hash(manifest):
        return False
    imported, retained = raw["imported"], raw["after_restart"]
    targets = _targets(imported["targets"])
    supplied = sorted((d["hostname"], d["mgmt_ip"], d["ssh_port"]) for d in manifest["devices"])
    if supplied != sorted((t[1], t[2], t[3]) for t in targets):
        return False
    if (imported.get("device_count") != 3 or imported.get("lab_count") != 7 or len(imported["topology_ids"]) != 1
            or not _hash(imported["retained_sha256"]) or imported != retained
            or raw["corpus"].get("document_count") != 135 or raw["corpus"].get("uploaded") is not False
            or not _hash(raw["corpus"]["manifest_sha256"])):
        return False
    starts = raw["starts"]
    if not isinstance(starts, list) or len(starts) != 2:
        return False
    for start in starts:
        actual, launcher = start["runtime_identity"], start["launcher"]
        if (start.get("ok") is not True or not _runtime_matches(actual, own)
                or not _positive(launcher["pid"]) or not _positive(launcher["created_ms"])
                or launcher["pid"] not in (actual.get("pid"), actual.get("parent_pid"))
                or not actual.get("launch_id") or actual["launch_id"] != launcher.get("launch_id")
                or start.get("frontend_file_sha256") != inventory.get("sim-frontend/dist/index.html")
                or any(start["components"].get(key) != "healthy" for key in ("mysql", "llm", "knowledge"))):
            return False
    if starts[0]["runtime_identity"]["launch_id"] == starts[1]["runtime_identity"]["launch_id"]:
        return False
    children = raw["reports"]
    if not isinstance(children, list) or len(children) != 2:
        return False
    by_scope = {}
    for child in children:
        value = child["report"]
        if child["sha256"] != canonical_report_hash(value) or value["scope"] in by_scope:
            return False
        by_scope[value["scope"]] = value
    ai, devices = by_scope["deepseek_and_anythingllm_readonly"], by_scope["serial_device_readonly"]
    own = {**own, "llm": ai["identity"]["llm"], "targets": imported["targets"]}
    window = (_timestamp(raw["started_at"]), _timestamp(raw["finished_at"]))
    if not all(_bound_report(child, own, fingerprint, window) for child in (ai, devices)) or not _provider_observations(ai, own):
        return False
    if (devices.get("schema") != 1 or devices.get("core_readonly_ok") is not True or devices.get("running_saved_equivalent") is not True
            or _targets([{"id": d["device_id"], "hostname": d["hostname"], "mgmt_ip": d["host"], "ssh_port": d["port"]} for d in devices["devices"]]) != targets):
        return False
    for device in devices["devices"]:
        if device.get("closed") is not True or device.get("adapter") != "ssh" or device.get("running_saved_equivalent") is not True:
            return False
        commands = _named(device["commands"], "command")
        for name in ("display version", "display current-configuration", "display saved-configuration", "display interface brief"):
            command = commands[name]
            if not _hash(command["redacted_sha256"]) or not _positive(command["line_count"]):
                return False
        if (commands["display version"].get("huawei_vrp") is not True
                or commands["display current-configuration"].get("identity_matches") is not True
                or commands["display saved-configuration"].get("identity_matches") is not True
                or not _positive(commands["display interface brief"]["interface_count"])):
            return False
    return True


def current_migration_head():
    """Read the candidate's Alembic graph, without application/settings imports."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    config = Config(str(Path(__file__).resolve().parents[1] / 'backend/alembic.ini'))
    return ScriptDirectory.from_config(config).get_current_head()


def _migration_observations(raw, identity):
    if raw.get("schema") != 1 or raw.get("producer") != "verify_live_migration" or raw.get("ok") is not True:
        return False
    source, target = raw["source_identity"], raw["target_identity"]
    if (not _hash(source["database_fingerprint"]) or source["database_fingerprint"] == target["database_fingerprint"]
            or not _runtime_matches(target, raw["binding"]["start"])
            or source.get("root_fingerprint") != target.get("root_fingerprint")):
        return False
    backup, privileges = raw["backup"], raw["restore_privilege_scope"]
    if (not _hash(backup["encrypted_sha256"]) or not _hash(backup["sql_sha256"]) or not _positive(backup["encrypted_bytes"])
            or privileges.get("new_account") is not True or privileges.get("global_privileges") is not False
            or not privileges.get("database") or not _hash(privileges["show_grants_sha256"])):
        return False
    required = {"restore_matches_source", "all_original_data_preserved", "only_proven_runtime_promotions",
                "upgraded_to_head", "repeat_idempotent", "source_unchanged", "build_runtime_unchanged"}
    if not required <= raw["checks"].keys() or not all(value is True for value in raw["checks"].values()):
        return False
    before, restored, expected = raw["source_before"], raw["restored_before"], raw["expected_after_original_columns"]
    after, repeated = raw["target_after"], raw["target_repeated"]
    if (before.get("revision") != "0001_initial" or before != restored or before != raw["source_after"]
            or after.get("revision") != current_migration_head() or after != repeated
            or raw.get("repeat_was_noop") is not True or after["tables"] != expected["tables"]):
        return False
    # A full legacy schema is captured, not a selected successful table sample.
    mandatory = {"user", "device", "topology", "topology_link", "topology_version", "topology_runtime_check",
                 "deploy_batch", "deploy_task", "device_write_lock", "config_template", "config_version", "audit_log",
                 "metric_record", "metric_aggregated", "alarm", "monitor_job", "training_lab", "training_session",
                 "fault_injection", "operation_log", "ai_log", "copilot_conversation", "system_config", "background_task"}
    if not mandatory <= before["tables"].keys() or before["tables"].keys() != expected["tables"].keys():
        return False
    promotions = raw["expected_runtime_promotions"]
    if not isinstance(promotions, list) or len({p["check_id"] for p in promotions}) != len(promotions):
        return False
    if not all(_positive(p["check_id"]) and _positive(p["old_version_id"]) and p["confirmed_version_id"] == p["old_version_id"] for p in promotions):
        return False
    for name, table in before["tables"].items():
        other = expected["tables"][name]
        if (type(table["rows"]) is not int or table["rows"] < 0 or not _hash(table["content_sha256"])
                or not isinstance(table["columns"], list) or not table["columns"] or len(set(table["columns"])) != len(table["columns"])
                or table["columns"] != other["columns"] or table["rows"] != other["rows"] or not _hash(other["content_sha256"])):
            return False
        if table != other and (name != "topology_runtime_check" or not promotions):
            return False
    return True


def _deployment_observations(reports, identity):
    phases = _named(reports, "phase")
    if set(phases) != {"prepare", "apply", "restore"}:
        return False
    prepare, applied, restored = (phases[name] for name in ("prepare", "apply", "restore"))
    for name, phase in phases.items():
        if (phase.get("schema") != 1 or phase.get("scope") != "live_controlled_deployment" or phase.get("ok") is not True
                or phase.get("state") != {"prepare": "prepared", "apply": "applied", "restore": "restored"}[name]
                or _targets(phase["targets"]) != _targets(identity["targets"])
                or any(phase[key] != prepare[key] for key in ("run_id", "batch_id", "operation_plan_sha256"))):
            return False
        if name != "prepare" and phase["binding"]["start"].get("deploy_simulate_only") is not False:
            return False
    if (not prepare["run_id"] or not _positive(prepare["batch_id"]) or not _hash(prepare["operation_plan_sha256"])
            or not _hash(applied["approval_reference_sha256"]) or applied["approval_reference_sha256"] != restored["approval_reference_sha256"]
            or not (_timestamp(prepare["finished_at"]) <= _timestamp(applied["started_at"])
                    <= _timestamp(applied["finished_at"]) <= _timestamp(restored["started_at"]))):
        return False
    profile = applied["write_profile"]
    if (profile != restored["write_profile"] or sorted(profile["device_ids"]) != sorted(t["id"] for t in identity["targets"])
            or sorted(profile["mgmt_ips"]) != sorted({t["mgmt_ip"] for t in identity["targets"]})
            or not _positive(profile["topology_id"]) or not _positive(profile["baseline_version"]) or not _hash(profile["baseline_sha256"])):
        return False
    device_phases = [_named(phase["devices"], "device_id") for phase in (prepare, applied, restored)]
    if any(set(rows) != {t["id"] for t in identity["targets"]} for rows in device_phases):
        return False
    tasks = []
    original_keys = ("hostname", "original_version_id", "original_sha256", "original_running_sha256", "original_saved_sha256", "original_state_sha256", "original_running_saved_equivalent", "apply_task_id")
    for target in identity["targets"]:
        first, second, last = (rows[target["id"]] for rows in device_phases)
        if (any(first[key] != row[key] for row in (second, last) for key in original_keys)
                or first["hostname"] != target["hostname"] or not _positive(first["original_version_id"])
                or first.get("original_running_saved_equivalent") is not True
                or any(not _hash(first[key]) for key in ("original_sha256", "original_running_sha256", "original_saved_sha256", "original_state_sha256"))
                or second.get("applied") is not True or last.get("applied") is not True or last.get("restored") is not True
                or second["apply"] != last["apply"]):
            return False
        for phase, evidence in (("apply", last["apply"]), ("restore", last["restore"])):
            tasks.append(evidence["task_id"])
            if (evidence.get("ok") is not True or evidence.get("status") != "success" or evidence.get("mode") != "real"
                    or evidence.get("verified") is not True or evidence.get("locks") != 0 or evidence.get("closed") is not True
                    or evidence.get("running_saved_equivalent") is not True or evidence["device_id"] != target["id"]
                    or evidence["task_id"] != last[f"{phase}_task_id"] or not _positive(evidence["task_id"])
                    or not _positive(evidence["config_version_id"]) or any(not _hash(evidence[key]) for key in ("backup_sha256", "result_sha256", "running_sha256", "saved_sha256", "running_state_sha256", "saved_state_sha256"))):
                return False
            # Audit rows carry the product's own vocabulary, and the producer
            # applies exactly these rules in verify_live_deploy.py: the execute step
            # succeeds as "executed" (a failure is "error"), the write lock is
            # released BEFORE the verification row is written, and a high-risk
            # rollback is confirmed twice (awaiting risk confirmation, then
            # confirmed), so one action may legitimately appear more than once.
            # Take the last row per action, as the producer does, and never assume
            # a single "success" row per action.
            audits = evidence["audit"]
            if not isinstance(audits, list) or any(not isinstance(row, dict) for row in audits):
                return False
            latest = {row.get("action"): row for row in audits}
            created = "deploy_rollback_task_created" if phase == "restore" else "deploy_task_created"
            chain = [created, "deploy_task_confirmed", "deploy_task_executed", "deploy_task_verified"]
            if (any(name not in latest for name in [*chain, "device_write_lock_released"])
                    or any(not _positive(latest[name].get("id")) for name in [*chain, "device_write_lock_released"])
                    or latest["deploy_task_executed"].get("result") != "executed"
                    or any(latest[name].get("result") != "success"
                           for name in (created, "deploy_task_confirmed", "device_write_lock_released", "deploy_task_verified"))):
                return False
            ids = [latest[name]["id"] for name in chain]
            if ids != sorted(ids) or len({latest[name]["id"] for name in [*chain, "device_write_lock_released"]}) != 5:
                return False
            if phase == "restore" and (evidence.get("original_restored") is not True
                    or evidence["running_state_sha256"] != first["original_state_sha256"] or evidence["saved_state_sha256"] != first["original_state_sha256"]):
                return False
    return len(set(tasks)) == 6


def _resilience_observations(raw, identity):
    if (raw.get("schema") != 1 or raw.get("producer") != "verify_live_resilience" or raw.get("ok") is not True
            or not _runtime_matches(raw["runtime_identity"], identity) or _llm(raw["llm"]) != _llm(identity["llm"])
            or _targets(raw["targets"]) != _targets(identity["targets"])):
        return False
    steps = _named(raw["steps"])
    names = {"anonymous_rejected", "invalid_token_rejected", "concurrent_readers", "webssh_contention_recovery", "build_runtime_unchanged"}
    if not names <= steps.keys() or any(s.get("ok") is not True for s in steps.values()):
        return False
    if any(steps[name].get("http_status") != 401 for name in ("anonymous_rejected", "invalid_token_rejected")):
        return False
    load = raw["load"]
    if (load.get("users") != 30 or not 30 <= load["duration_seconds"] <= 300 or load.get("passed") is not True
            or load.get("identity_scope") != "one_administrator_login_with_concurrent_virtual_readers"
            or (_timestamp(raw["finished_at"]) - _timestamp(raw["started_at"])).total_seconds() < load["duration_seconds"]):
        return False
    endpoints = _named(load["endpoints"], "endpoint")
    expected = {"dashboard/summary": 2000, "devices": 1000, "deploy/tasks": 1000, "training/labs": 1000,
                "alarms": 1000, "system/info": 1000, "monitor/stats": 1000}
    if set(endpoints) != set(expected) or sum(row["requests"] for row in endpoints.values()) != load["total_requests"]:
        return False
    for name, row in endpoints.items():
        if (not _positive(row["requests"]) or row.get("errors") != 0 or row.get("error_rate") != 0
                or row.get("violations") != [] or row.get("p95_threshold_ms") != expected[name]
                or type(row["p95_ms"]) not in (int, float) or not math.isfinite(row["p95_ms"])
                or not 0 <= row["p95_ms"] <= expected[name]):
            return False
    contention = raw["webssh_contention"]
    if (contention["device_id"] not in {t["id"] for t in identity["targets"]}
            or any(contention.get(key) is not True for key in ("ok", "first_closed", "second_closed", "busy_reported", "second_session_rejected", "recovery_closed"))):
        return False
    recovered = contention["recovery"]
    target = next(t for t in identity["targets"] if t["id"] == contention["device_id"])
    return (recovered.get("ok") is True and recovered.get("hostname") == target["hostname"]
            and recovered["version"].get("huawei_vrp") is True and recovered["version"].get("command") == "display version"
            and _positive(recovered["version"]["line_count"]) and _hash(recovered["version"]["redacted_sha256"]))


def _fault_observations(raw, identity):
    if (raw.get("schema") != 1 or raw.get("producer") != "verify_live_dependency_faults"
            or raw.get("scope") != "isolated_dependency_fault_injection" or raw.get("ok") is not True
            or raw["binding"]["start"]["root_fingerprint"] != identity["root_fingerprint"]):
        return False
    isolation = raw["isolation"]
    if (isolation.get("configuration") != "init_only" or isolation.get("external_targets") != 0 or isolation.get("host") != "127.0.0.1"
            or any(isolation.get(key) is not False for key in ("database_migrated", "scheduler_started", "existing_services_modified"))
            or not all(_positive(isolation[key]) and isolation[key] < 65536 for key in ("http_port", "refused_port"))
            or isolation["http_port"] == isolation["refused_port"] or raw.get("secrets_clean") is not True
            # Four synthetic fault credentials plus the per-run generated JWT key.
            or raw.get("synthetic_markers_checked") != 5 or raw.get("resources_closed") is not True
            or raw.get("failure_type") is not None or not _positive(raw["fault_request_count"])):
        return False
    components = raw["components"]
    guard = raw["network_guard"]
    if (guard.get("allowed_host") != "127.0.0.1"
            or sorted(guard["allowed_ports"]) != sorted((isolation["http_port"], isolation["refused_port"]))
            or not _positive(guard["connection_or_resolution_attempts"]) or guard.get("blocked_attempts") != 0):
        return False
    if set(components) != {"database", "llm", "knowledge", "ssh"} or any(c.get("ok") is not True for c in components.values()):
        return False
    db, llm, kb, ssh = (components[key] for key in ("database", "llm", "knowledge", "ssh"))
    return (db.get("health_http_status") == 503 and db.get("health_status") == "unhealthy" and db.get("mysql_status") == "unhealthy"
            and llm.get("generate_exception") == "HTTPStatusError" and llm.get("application_generate_status") in {"degraded", "failed", "unavailable"}
            and llm.get("stream_error") is True and llm.get("stream_done_status") == "failed" and llm.get("stream_done_count") == 1
            and kb.get("available") is False and kb.get("retrieve_exception") == "HTTPStatusError" and kb.get("ask_status") == "degraded"
            and kb.get("ask_sources_count") == 0 and kb.get("ask_answer_characters") == 0
            and bool(ssh.get("exception")) and ssh.get("closed") is True and ssh.get("lock_reacquired") is True)


def _abnormal_observations(reports, identity, inventory, window):
    producers = _named(reports, "producer")
    if set(producers) != {"verify_live_resilience", "verify_live_dependency_faults", "verify_recipient_first_run", "verify_live_browser"}:
        return False
    for producer, raw in producers.items():
        own = raw["binding"]["start"] if producer in {"verify_live_dependency_faults", "verify_recipient_first_run"} else identity
        if not _bound_report(raw, own, code_fingerprint(inventory), window):
            return False
    browser = producers["verify_live_browser"]
    if not (_resilience_observations(producers["verify_live_resilience"], identity)
            and _fault_observations(producers["verify_live_dependency_faults"], identity)
            and _recipient_observations(producers["verify_recipient_first_run"], identity, inventory)
            and _browser_observations(browser, identity)):
        return False
    permissions = _named(browser["checks"])
    for name in ("permissions_anonymous", "permissions_readonly"):
        if permissions[name].get("ok") is not True or permissions[name].get("mode") != "live":
            return False
    anonymous, readonly = (permissions[name]["evidence"] for name in ("permissions_anonymous", "permissions_readonly"))
    return (anonymous.get("backend_status") == 401 and anonymous.get("copilot_sse_status") == 401 and anonymous.get("protected_route_redirected") is True
            and readonly.get("backend_status") == 403 and readonly.get("frontend_redirected") is True
            and readonly.get("other_owner_conversation_status") == 200 and readonly.get("other_owner_conversation_hidden") is True)


def validate_live_evidence(report: dict, inventory: dict[str, str], *, now=None) -> list[dict]:
    """Fail closed on incomplete producers, mismatched runtimes or fabricated checklists.

    Schema 2 embeds original redacted reports with canonical hashes. These are
    integrity checks, not signatures or a substitute for trusted probe execution.
    Producers without a defined complete observation schema remain SKIP.
    """
    now = now or datetime.now(timezone.utc)
    validators = {"external_providers": _provider_observations,
                  "live_devices": _device_observations, "business_workflows": _business_observations,
                  "browser_webssh": _workflow_observations, "live_browser": _browser_observations,
                  "recipient_first_run": lambda raw, ident: _recipient_observations(raw, ident, inventory),
                  "isolated_mysql": _migration_observations, "real_deployment": _deployment_observations,
                  "abnormal_concurrency": _abnormal_observations}
    checks, catalog, valid = {}, {}, False
    try:
        checks = report.get("checks", {})
        if not isinstance(checks, dict):
            checks = {}
        window = (_timestamp(report["started_at"]), _timestamp(report["finished_at"]))
        identity = report["identity"]
        fingerprint = code_fingerprint(inventory)
        valid = (report.get("schema") == 2 and report.get("scope") == "full_live_acceptance"
                 and report.get("source_fingerprint") == fingerprint
                 and window[0] <= window[1] <= now and (now - window[0]).total_seconds() <= 7 * 86400
                 and identity.get("device_mode") == "ssh" and identity.get("knowledge_provider") == "anythingllm"
                 and type(identity.get("deploy_simulate_only")) is bool
                 and _hash(identity.get("database_fingerprint")) and _hash(identity.get("root_fingerprint")))
        _targets(identity["targets"])
        _llm(identity["llm"])
        if not isinstance(report["reports"], list):
            raise ValueError("embedded_reports_required")
        for attachment in report["reports"]:
            digest, raw = attachment["sha256"], attachment["report"]
            if not isinstance(raw, dict) or digest in catalog or canonical_report_hash(raw) != digest:
                raise ValueError("report_hash_mismatch_or_duplicate")
            catalog[digest] = raw
    except (KeyError, TypeError, ValueError, AttributeError):
        valid = False
    rows = []
    for name in sorted(FULL_STEPS):
        entry = checks.get(name, {})
        entry = entry if isinstance(entry, dict) else {}
        passed, failed = False, entry.get("state") == "FAIL"
        if valid and name in validators and entry.get("state") == "PASS":
            try:
                hashes = entry["report_sha256"]
                required_count = {"real_deployment": 3, "abnormal_concurrency": 4}.get(name, 1)
                if not isinstance(hashes, list) or len(hashes) != required_count or len(set(hashes)) != required_count or not all(_hash(h) for h in hashes):
                    raise ValueError("original_reports_required")
                if name in {"real_deployment", "abnormal_concurrency"}:
                    originals = [catalog[h] for h in hashes]
                    failed = any(r.get("ok") is False for r in originals)
                    passed = (_abnormal_observations(originals, identity, inventory, window) if name == "abnormal_concurrency" else
                              all(_deployment_bound_report(r, identity, fingerprint, window) for r in originals) and _deployment_observations(originals, identity))
                    rows.append({"name": name, "state": "PASS" if passed else "FAIL" if failed else "SKIP",
                                 "detail": "bound original observations verified" if passed else "incomplete multi-report observations"})
                    continue
                raw = catalog[hashes[0]]
                failed = raw.get("ok") is False or raw.get("verdict", {}).get("ok") is False
                # Recipient startup deliberately uses another root and new DB;
                # its schema validates the reference and target separately.
                target_identity = raw["binding"]["start"] if name in {"recipient_first_run", "isolated_mysql"} else identity
                passed = _bound_report(raw, target_identity, fingerprint, window) and validators[name](raw, identity)
            except (KeyError, TypeError, ValueError, AttributeError):
                passed = False
        rows.append({"name": name, "state": "PASS" if passed else "FAIL" if failed else "SKIP",
                     "detail": "original bound probe observations verified" if passed else
                     "producer schema not yet complete; checklist cannot substitute" if name not in validators else
                     "missing, failed, stale, mixed-runtime or incomplete original probe evidence"})
    return rows


def assemble_live_evidence(reports: list[dict], inventory: dict[str, str]) -> dict:
    """Bundle existing observations without inventing stamps or PASS assertions.

    Requires the provider/device reports to supply the common model and target
    inventory. The validator still rejects stale, failed or mismatched reports.
    """
    providers = [r for r in reports if r.get("scope") == "deepseek_and_anythingllm_readonly"]
    devices = [r for r in reports if r.get("scope") == "serial_device_readonly"]
    if len(providers) != 1 or len(devices) != 1:
        raise ValueError("exactly_one_provider_and_device_report_required")
    identity = dict(providers[0]["binding"]["start"])
    identity["llm"] = {key: providers[0]["identity"]["llm"][key] for key in ("provider", "base_url", "model")}
    identity["targets"] = [{"id": d["device_id"], "hostname": d["hostname"], "mgmt_ip": d["host"], "ssh_port": d["port"]} for d in devices[0]["devices"]]
    _targets(identity["targets"])
    _llm(identity["llm"])
    checks = {name: {"state": "SKIP", "report_sha256": []} for name in FULL_STEPS}
    attachments, times = [], []
    for raw in reports:
        digest = canonical_report_hash(raw)
        attachments.append({"sha256": digest, "report": raw})
        for stamp in raw.get("binding", {}).values():
            times.append(_timestamp(stamp["captured_at"]))
        name = ("external_providers" if raw.get("scope") == "deepseek_and_anythingllm_readonly" else
                "live_devices" if raw.get("scope") == "serial_device_readonly" else
                "business_workflows" if raw.get("producer") == "verify_full_stack" else
                "browser_webssh" if raw.get("scope") == "live_webssh_and_monitor" else
                "live_browser" if raw.get("producer") == "verify_live_browser" else
                "recipient_first_run" if raw.get("producer") == "verify_recipient_first_run" else
                "isolated_mysql" if raw.get("producer") == "verify_live_migration" else
                "real_deployment" if raw.get("scope") == "live_controlled_deployment" else None)
        if name:
            checks[name]["report_sha256"].append(digest)
            checks[name]["state"] = "FAIL" if raw.get("ok") is False or raw.get("verdict", {}).get("ok") is False else "PASS"
        if raw.get("producer") in {"verify_live_resilience", "verify_live_dependency_faults", "verify_recipient_first_run", "verify_live_browser"}:
            checks["abnormal_concurrency"]["report_sha256"].append(digest)
            checks["abnormal_concurrency"]["state"] = "PASS"
    bundle = {"schema": 2, "scope": "full_live_acceptance", "source_fingerprint": code_fingerprint(inventory),
              "started_at": min(times).isoformat(), "finished_at": max(times).isoformat(),
              "identity": identity, "reports": attachments, "checks": checks}
    # PASS is derived from observations. Even a producer's top-level ok is not enough.
    for row in validate_live_evidence(bundle, inventory):
        checks[row["name"]]["state"] = row["state"]
    return bundle


def files(root: Path, *, tests: bool = False) -> list[Path]:
    """Enumerate real files, including untracked work; never follow links/junctions."""
    result = []
    for current, dirs, names in os.walk(root, followlinks=False):
        folder = Path(current)
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith(".")
                         and not (folder / d).is_symlink()
                         and not (getattr((folder / d).lstat(), "st_file_attributes", 0)
                                  & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
                         and (tests or d not in {"tests", "e2e"}))
        if folder == root:
            dirs[:] = [d for d in dirs if d in TREE_ROOTS]
        if folder == root / "docs":
            dirs[:] = [d for d in dirs if d != "assets"]
        for name in sorted(names):
            path = folder / name
            if path.is_symlink() or (name.startswith(".") and name not in ROOT_FILES):
                continue
            if name.startswith(".env") and name != ".env.example":
                continue
            if path.suffix.lower() in EXCLUDED_SUFFIXES or name.startswith("~$"):
                continue
            if folder == root and name not in ROOT_FILES:
                continue
            if any(part in {"docs"} for part in path.relative_to(root).parts) and path.suffix != ".md":
                continue
            result.append(path)
    return sorted(result)


def manifest(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files(root)}


# Only literal assignments are scanned; variable references and empty example fields
# are not credentials. Test source is not shipped and therefore not allowlisted here.
ASSIGNMENT = re.compile(
    r'''(?ix)(?<![.\w])\b(?:[a-z0-9_]*(?:password|passwd|secret|api_key|access_token|auth_token|fernet_key)[a-z0-9_]*)
        ["']?\s*[:=]\s*["']([A-Za-z0-9_+/=.!@#$%^&*(){}:;?~-]{6,})["']'''
)
ENV_LITERAL = re.compile(r"(?m)^\s*[A-Z0-9_]*(?:PASSWORD|SECRET|API_KEY|TOKEN|FERNET_KEY)[A-Z0-9_]*=([^\s\"']{6,})\s*$")
KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:gh[pousr]_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9_-]{24,})\b")
URL_CREDENTIAL = re.compile(r"[a-z][a-z0-9+.-]*://[A-Za-z0-9._~%-]+:([A-Za-z0-9.!#$%&'*+;=_~%-]{4,})@", re.I)
DEVICE_SECRET = re.compile(r"(?im)^\s*(?:local-user\s+\S+\s+)?(?:password|authentication-key)\s+(?:cipher|simple)\s+(\S+)")
PLACEHOLDER = re.compile(r"(?i)^(?:\*+|x+|__probe__|<[^>]+>|\$\{[^}]+\}|.*(?:placeholder|redacted|changeme|your[_-]|example[_-]).*)$")


def scan(root: Path) -> list[dict]:
    findings = []
    for path in files(root):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeError:
            continue
        for rule, pattern in (("literal_secret", ASSIGNMENT), ("env_secret", ENV_LITERAL),
                              ("private_key_or_token", KEY), ("credential_url", URL_CREDENTIAL),
                              ("device_secret", DEVICE_SECRET)):
            for match in pattern.finditer(text):
                value = match.group(1) if match.lastindex else match.group(0)
                if PLACEHOLDER.fullmatch(value):
                    continue
                if rule == "env_secret" and path.suffix not in {".example", ".ini", ".cfg", ".md", ".txt", ".yaml", ".yml"}:
                    continue
                findings.append({"path": path.relative_to(root).as_posix(),
                                 "line": text.count("\n", 0, match.start()) + 1, "rule": rule})
    return findings


def redact_documents(stage: Path) -> None:
    """User-authorized removal of teaching example secrets from copied documents only."""
    findings = [item for item in scan(stage) if item["path"].endswith(".md")
                and (item["path"].startswith(("docs/", "knowledge/")) or item["path"] in ROOT_FILES)]
    for name in sorted({item["path"] for item in findings}):
        path = stage / name
        text = path.read_text(encoding="utf-8-sig")
        text = re.sub(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                      "<REDACTED PRIVATE KEY>", text, flags=re.S)
        for pattern in (ASSIGNMENT, ENV_LITERAL, URL_CREDENTIAL, DEVICE_SECRET, KEY):
            def replace(match):
                if match.group(0).startswith("-----BEGIN"):
                    return match.group(0)  # Incomplete key block stays blocked, never strip only its marker.
                if match.lastindex:
                    start, end = match.span(1)
                    return match.group(0)[:start - match.start()] + "<REDACTED>" + match.group(0)[end - match.start():]
                return "<REDACTED>"
            text = pattern.sub(replace, text)
        path.write_text(text, encoding="utf-8")
    (stage / "DELIVERY-REDACTIONS.json").write_text(json.dumps({
        "scope": "Copied teaching documents only; source files remain unchanged. No secret values recorded.",
        "changes": findings,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def gate(root: Path, mode: str = "minimal") -> tuple[int, list[dict]]:
    actual = manifest(root)
    rows = []
    missing = sorted(REQUIRED - actual.keys())
    rows.append({"name": "required_files", "state": "FAIL" if missing else "PASS", "detail": missing})
    index = root / "sim-frontend/dist/index.html"
    refs = re.findall(r'''(?:src|href)=["'](/assets/[^"'#?]+)''', index.read_text(encoding="utf-8")) if index.is_file() else []
    missing_assets = [ref for ref in refs if "sim-frontend/dist" + ref not in actual]
    rows.append({"name": "frontend_assets", "state": "PASS" if refs and not missing_assets else "FAIL",
                 "detail": missing_assets})
    findings = scan(root)
    rows.append({"name": "secrets", "state": "FAIL" if findings else "PASS", "detail": findings})
    encoding = [name for name in actual if name.endswith(".ps1")
                and not (root / name).read_bytes().startswith(b"\xef\xbb\xbf")]
    rows.append({"name": "powershell_encoding", "state": "FAIL" if encoding else "PASS", "detail": encoding})
    lock = root / "backend/requirements.lock"
    locked = lock.is_file() and all("==" in line for line in lock.read_text().splitlines()
                                   if line.strip() and not line.lstrip().startswith("#"))
    rows.append({"name": "locked_python_dependencies", "state": "PASS" if locked else "FAIL"})
    evidence_path = root / EVIDENCE
    evidence = {}
    if evidence_path.is_file():
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    matches = bool(evidence) and evidence.get("manifest") == actual
    rows.append({"name": "verified_manifest", "state": "PASS" if matches else "SKIP",
                 "detail": "exact prepared files" if matches else "missing or stale preparation evidence"})
    for name in sorted(MINIMAL_STEPS):
        state = evidence.get("steps", {}).get(name, "SKIP") if matches else "SKIP"
        rows.append({"name": name, "state": state if state in {"PASS", "FAIL", "SKIP"} else "FAIL"})
    if mode == "full":
        rows.extend(validate_live_evidence(evidence.get("live_acceptance", {}) if matches else {}, actual))
    code = 1 if any(r["state"] == "FAIL" for r in rows) else 2 if any(r["state"] == "SKIP" for r in rows) else 0
    return code, rows


def print_rows(code: int, rows: list[dict]) -> None:
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    print({0: "PASS: selected mode complete", 1: "FAIL: delivery blocked", 2: "INCOMPLETE: skipped or stale gates are not a pass"}[code])


def record_live(root: Path, report_path: Path) -> int:
    evidence_path = root / EVIDENCE
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    current = manifest(root)
    if evidence.get("manifest") != current:
        raise ValueError("prepared files changed; rerun preparation")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = validate_live_evidence(report, current)
    evidence["live_acceptance"] = report
    evidence["live_acceptance_sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(row["state"] == "PASS" for row in rows) else 1


def export(root: Path, output_root: Path, mode: str) -> Path:
    code, rows = gate(root, mode)
    if code:
        print_rows(code, rows)
        raise ValueError("delivery gates incomplete")
    inventory = json.loads((root / EVIDENCE).read_text(encoding="utf-8"))["manifest"]
    if manifest(root) != inventory:
        raise ValueError("file changed after verification")
    output_root.mkdir(parents=True, exist_ok=True)
    archive = output_root / f"ip-sim-workbench-{mode}-{uuid.uuid4().hex[:12]}.zip"
    partial = archive.with_suffix(".zip.partial")
    with zipfile.ZipFile(partial, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in inventory:
            data = (root / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != inventory[name]:
                raise ValueError("file changed during export")
            bundle.writestr(name, data)
        bundle.writestr("DELIVERY-MANIFEST.json", json.dumps(inventory, ensure_ascii=False, indent=2))
        bundle.writestr(EVIDENCE, (root / EVIDENCE).read_bytes())
        if mode == "candidate":
            bundle.writestr("DELIVERY-SCOPE.json", json.dumps({
                "scope": "V7_E_engineering_candidate",
                "verified_gate": "local_engineering",
                "full_integration_acceptance": "pending_F",
            }, indent=2))
    if manifest(root) != inventory:
        raise ValueError("file changed during export")
    partial.rename(archive)
    return archive


def browser_tests(report: dict) -> dict[str, dict]:
    found = {}
    def visit(suites):
        for suite in suites:
            for spec in suite.get("specs", []):
                for test in spec.get("tests", []):
                    found[str(spec.get("id")) + "::" + str(test.get("projectId", ""))] = test
            visit(suite.get("suites", []))
    visit(report.get("suites", []))
    return found


def record_browser(root: Path, report_path: Path) -> int:
    """Attach strict Playwright evidence for this exact prepared tree."""
    evidence_path = root / EVIDENCE
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence.get("manifest") != manifest(root):
        raise ValueError("prepared files changed; rerun preparation")
    raw = report_path.read_bytes()
    report = json.loads(raw)
    report_root = Path(report.get("config", {}).get("rootDir", "")).resolve()
    if report_root != (root / "sim-frontend/e2e").resolve():
        raise ValueError("browser report does not belong to this prepared tree")
    stats = report.get("stats", {})
    actual = browser_tests(report)
    expected = evidence.get("browser_inventory", [])
    passed = (bool(expected) and sorted(actual) == expected and stats.get("expected") == len(expected)
              and stats.get("unexpected") == 0 and stats.get("flaky") == 0 and stats.get("skipped") == 0
              and not report.get("errors")
              and all(test.get("status") == "expected" and test.get("results")
                      and all(result.get("status") == "passed" for result in test["results"])
                      for test in actual.values()))
    evidence.setdefault("steps", {})["browser_e2e"] = "PASS" if passed else "FAIL"
    evidence["browser_evidence"] = {"sha256": hashlib.sha256(raw).hexdigest(), "stats": stats,
                                    "scope": "prepared sim tree; no real device acceptance implied"}
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if passed else 1


def run_browser(root: Path) -> int:
    """Drive the exact prepared minimal stage on an owned loopback process."""
    import socket
    import sysconfig
    import time
    from urllib.request import urlopen

    if root.parent.name != ".runtime" or not re.fullmatch(r"delivery-stage-[a-f0-9]{12}", root.name):
        raise ValueError("browser_requires_disposable_delivery_stage")
    evidence = json.loads((root / EVIDENCE).read_bytes())
    if evidence.get("manifest") != manifest(root) or not evidence.get("browser_inventory"):
        raise ValueError("browser_requires_current_prepared_tree")
    env = isolated_env(root)
    settings = {}
    keys = ("ADMIN_USERNAME", "ADMIN_PASSWORD", "FERNET_KEY", "JWT_SECRET_KEY")
    for line in (root / ".env").read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key in keys:
            settings[key] = value
    if not all(settings.get(key) for key in keys):
        raise ValueError("browser_requires_prepared_local_credentials")
    env.update(settings)
    env["PYTHONPATH"] = os.pathsep.join((str(root / "backend"), sysconfig.get_path("purelib")))
    env["DEPLOY_SIMULATE_ONLY"] = "true"
    env["MONITOR_SCHEDULER_ENABLED"] = "false"
    env["WORKBENCH_LAUNCH_ID"] = uuid.uuid4().hex
    env["E2E_ROOT_FINGERPRINT"] = hashlib.sha256(os.path.normcase(str(root)).encode()).hexdigest()
    env["E2E_ADMIN_USER"], env["E2E_ADMIN_PASSWORD"] = settings["ADMIN_USERNAME"], settings["ADMIN_PASSWORD"]
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        env["PLAYWRIGHT_BROWSERS_PATH"] = os.environ["PLAYWRIGHT_BROWSERS_PATH"]
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = env["E2E_BASE_URL"] = f"http://127.0.0.1:{port}"
    logs = root / ".runtime/logs"
    log_prefix = env["WORKBENCH_LAUNCH_ID"]
    with (logs / f"browser-backend-{log_prefix}.log").open("xb") as server_log:
        # Run the base interpreter directly, so Popen owns the listener instead
        # of a Windows venv redirector and an untracked child.
        process = subprocess.Popen([sys._base_executable, "-m", "uvicorn", "main:app",
                                    "--host", "127.0.0.1", "--port", str(port)],
                                   cwd=root / "backend", env=env, stdin=subprocess.DEVNULL,
                                   stdout=server_log, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    with urlopen(base + "/api/v1/health", timeout=3) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.4)
            else:
                raise ValueError("isolated_browser_backend_not_ready")
            report = logs / f"browser-report-{log_prefix}.json"
            front = root / "sim-frontend"
            node = shutil.which("node")
            if not node:
                raise ValueError("node_required_for_browser")
            with report.open("xb") as stdout, (logs / f"browser-errors-{log_prefix}.log").open("xb") as stderr:
                result = subprocess.run([node, str(front / "node_modules/@playwright/test/cli.js"),
                                         "test", "--reporter=json"], cwd=front, env=env,
                                        stdout=stdout, stderr=stderr, timeout=420, check=False)
            status = record_browser(root, report)
            print("Browser evidence:", report)
            return 1 if result.returncode or status else 0
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)


def isolated_env(stage: Path) -> dict[str, str]:
    allowed = {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT", "LOCALAPPDATA",
               "APPDATA", "USERPROFILE", "PROGRAMFILES", "PROGRAMFILES(X86)", "NUMBER_OF_PROCESSORS"}
    # Windows resolves these names case-insensitively, so normalise what is
    # inherited to one predictable spelling instead of the host's own casing.
    env = {key.upper(): value for key, value in os.environ.items() if key.upper() in allowed}
    # aiomysql resolves a default OS username at import time. Windows cannot
    # fall back to Unix pwd when the deliberately isolated environment is bare.
    env.update(USERNAME="delivery-isolated-user", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", DB_BACKEND="sqlite", DB_URL="",
               DB_SQLITE_PATH=str(stage / ".runtime/sim.db"), DEVICE_MODE="sim", KNOWLEDGE_PROVIDER="local",
               E2E_PROFILE="minimal", E2E_REQUIRE_UP="1",
               LLM_API_KEY="", KNOWLEDGE_API_KEY="", LLM_BASE_URL="http://127.0.0.1:1",
               JWT_SECRET_KEY=secrets.token_urlsafe(48), ADMIN_PASSWORD=secrets.token_urlsafe(24),
               FERNET_KEY=base64.urlsafe_b64encode(os.urandom(32)).decode(),
               LOG_DIR=str(stage / ".runtime/logs"))
    # The host input method expands this while Chromium starts. Without it the
    # browser working folder receives a literal "%SystemDrive%" directory.
    env["SYSTEMDRIVE"] = env.get("SYSTEMDRIVE") or "C:"
    return env


def pytest_temp(stage: Path) -> Path:
    """Create a disposable pytest basetemp inside this stage's own .runtime.

    The earlier implementation used ``root.parent`` and left ``ip-sim-pytest-*``
    directories next to the project, where they looked like unexplained
    artifacts. Never reuse an existing directory here: a fresh basetemp proves
    the path belongs to this run and cannot alias kept acceptance evidence.
    """
    runtime = stage / ".runtime"
    temp = runtime / ("pytest-" + uuid.uuid4().hex)
    temp.mkdir(parents=True, exist_ok=False)
    if runtime.resolve() not in temp.resolve().parents:
        raise ValueError("pytest_temp_outside_stage_runtime")
    return temp


def prepare(root: Path, mode: str, *, skip_slow: bool = False) -> tuple[Path, int]:
    stage = root / ".runtime" / ("delivery-stage-" + uuid.uuid4().hex[:12])
    stage.mkdir(parents=True, exist_ok=False)
    for source in files(root, tests=True):
        relative = source.relative_to(root)
        if relative.parts[:2] == ("sim-frontend", "dist"):
            continue  # Never validate stale dist from the source checkout.
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    source_manifest = manifest(stage)
    redact_documents(stage)
    (stage / ".runtime/logs").mkdir(parents=True)
    env = isolated_env(stage)
    # Disposable credentials are local to the isolated smoke test and never shipped.
    runtime_keys = ("DB_BACKEND", "DB_URL", "DB_SQLITE_PATH", "DEVICE_MODE", "KNOWLEDGE_PROVIDER",
                    "LLM_API_KEY", "KNOWLEDGE_API_KEY", "LLM_BASE_URL", "JWT_SECRET_KEY", "ADMIN_PASSWORD",
                    "FERNET_KEY", "LOG_DIR")
    (stage / ".env").write_text("ADMIN_USERNAME=admin\n" + "".join(key + "=" + env[key] + "\n" for key in runtime_keys), encoding="utf-8")
    steps = {}
    browser_inventory = []
    python = root / "backend/.venv/Scripts/python.exe"
    if not python.exists():
        python = Path(sys.executable)
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    node = shutil.which("node")

    def run(name: str, command: list[str], cwd: Path) -> bool:
        try:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=600, check=False)
            (stage / ".runtime/logs" / f"{name}.log").write_bytes(result.stdout)
            steps[name] = "PASS" if result.returncode == 0 else "FAIL"
        except (OSError, subprocess.TimeoutExpired):
            steps[name] = "FAIL"
        print(f"[{steps[name]}] {name}", flush=True)
        return steps[name] == "PASS"

    front = stage / "sim-frontend"
    dependencies = root / "sim-frontend/node_modules"
    if npm and node and dependencies.is_dir():
        shutil.copytree(dependencies, front / "node_modules")
        run("frontend_types", [npm, "run", "typecheck"], front)
        run("frontend_lint", [npm, "run", "lint"], front)
        contracts = sorted((front / "tests").rglob("*.test.mjs"))
        contract_results = [run("contract_" + str(i), [node, str(path)], front) for i, path in enumerate(contracts)]
        steps["frontend_contracts"] = "PASS" if contract_results and all(contract_results) else "FAIL"
        run("frontend_build", [npm, "run", "build"], front)
        if run("browser_inventory", [node, str(front / "node_modules/@playwright/test/cli.js"),
                                     "test", "--list", "--reporter=json"], front):
            try:
                report = json.loads((stage / ".runtime/logs/browser_inventory.log").read_bytes())
                browser_inventory = sorted(browser_tests(report))
                if not browser_inventory or report.get("errors"):
                    steps["browser_inventory"] = "FAIL"
            except ValueError:
                steps["browser_inventory"] = "FAIL"
    else:
        for name in ("frontend_types", "frontend_lint", "frontend_contracts", "frontend_build"):
            steps[name] = "SKIP"
    backend = stage / "backend"
    if skip_slow:
        steps["backend_tests"] = "SKIP"
    else:
        test_temp = pytest_temp(stage)
        # Unit tests own their sim/fake-SSH mocks; forcing sim globally would skip
        # the mocked SSH code paths. Never load even the stage .env in unit tests.
        code = ("import os; os.environ.pop('DEVICE_MODE', None); import core.config as c; "
                "c.Settings.model_config['env_file']=None; import pytest; raise SystemExit(pytest.main("
                + repr(["tests", "-q", "--no-header", "-p", "no:cacheprovider", "--basetemp=" + str(test_temp)]) + "))")
        run("backend_tests", [str(python), "-c", code], backend)
    boot_ok = run("minimal_bootstrap", [str(python), "scripts/bootstrap_local.py"], backend)
    if boot_ok:
        devices_ok = run("sim_devices", [str(python), "scripts/seed_sim_devices.py"], backend)
        training_ok = run("sim_training", [str(python), "scripts/seed_training_labs.py"], backend)
        if devices_ok and training_ok and steps.get("frontend_build") == "PASS":
            run("minimal_smoke", [str(python), "scripts/verify_minimal_mode.py"], backend)
    # Real integrations are never inferred from sim evidence or contacted here.
    for name in FULL_STEPS:
        steps[name] = "SKIP"
    evidence = {"schema": 1, "created_at": datetime.now(timezone.utc).isoformat(), "mode": mode,
                "device_mode": "sim", "database": "isolated_sqlite", "steps": steps, "browser_inventory": browser_inventory,
                "source_manifest": source_manifest, "manifest": manifest(stage)}
    (stage / EVIDENCE).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    code, rows = gate(stage, mode)
    print_rows(code, rows)
    print("Prepared directory:", stage)
    return stage, code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "prepare", "package", "scan", "browser", "record-browser", "record-live"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--mode", choices=("minimal", "full", "candidate"), default="minimal")
    parser.add_argument("--skip-slow", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve(strict=True)
    if args.mode == "candidate" and args.action not in {"check", "package"}:
        parser.error("candidate mode is only for checking or archiving a prepared engineering candidate")
    if args.action == "browser":
        try:
            return run_browser(root)
        except (ValueError, OSError, subprocess.TimeoutExpired):
            print("FAIL: prepared browser validation did not complete", file=sys.stderr)
            return 1
    if args.action == "record-live":
        if not args.report:
            parser.error("record-live requires --report")
        return record_live(root, args.report)
    if args.action == "record-browser":
        if not args.report:
            parser.error("record-browser requires --report")
        return record_browser(root, args.report)
    if args.action == "scan":
        findings = scan(root)
        for finding in findings:
            print(json.dumps(finding, ensure_ascii=False))
        print(f"Scanned {len(files(root))} delivery files; findings: {len(findings)}")
        return 1 if findings else 0
    if args.action == "prepare":
        return prepare(root, args.mode, skip_slow=args.skip_slow)[1]
    if args.action == "package":
        try:
            print("Archive:", export(root, root / ".runtime/delivery", args.mode))
            return 0
        except ValueError:
            return 1
    code, rows = gate(root, args.mode)
    print_rows(code, rows)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
