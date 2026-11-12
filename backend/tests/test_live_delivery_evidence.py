"""Acceptance consumes bound probe observations, never a checklist of booleans."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("delivery_live", Path(__file__).resolve().parents[2] / "scripts/delivery.py")
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)
NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
INVENTORY = {"backend/main.py": "1" * 64, "knowledge/corpus/book.md": "2" * 64, "sim-frontend/dist/index.html": "4" * 64}
TARGETS = [{"id": n, "hostname": f"R{n}", "mgmt_ip": "192.0.2.1", "ssh_port": 2200 + n} for n in (1, 2, 3)]
LLM = {"provider": "openai", "base_url": "https://api.deepseek.com", "model": "deepseek-chat"}


def stamp(minutes):
    return {"schema": 1, "database_fingerprint": "d" * 64, "root_fingerprint": "e" * 64,
            "device_mode": "ssh", "knowledge_provider": "anythingllm", "deploy_simulate_only": True,
            "source_fingerprint": delivery.code_fingerprint(INVENTORY),
            "captured_at": (NOW - timedelta(minutes=minutes)).isoformat()}


def raw_ai():
    return {"schema_version": 1, "scope": "deepseek_and_anythingllm_readonly", "ok": True,
            "binding": {"start": stamp(9), "finish": stamp(2)},
            "started_at": (NOW - timedelta(minutes=8)).isoformat(),
            "finished_at": (NOW - timedelta(minutes=3)).isoformat(),
            "identity": {"llm": {**LLM, "fallback_used": False}, "device_mode": "ssh",
                         "knowledge": {"provider": "anythingllm", "expected_documents": 135}},
            "checks": [
                {"name": "deepseek_generate", "ok": True, "evidence": {"characters": 20, "response_sha256": "a" * 64, "challenge_matched": True}},
                {"name": "deepseek_stream", "ok": True, "evidence": {"characters": 20, "response_sha256": "b" * 64, "challenge_matched": True, "content_chunks": 1, "terminal_marker_validated_by_provider": True}},
                {"name": "anythingllm_health", "ok": True, "evidence": {"document_count": 135}},
                {"name": "anythingllm_retrieval", "ok": True, "evidence": {"returned_count": 1, "verified_chunk_count": 1, "chunks": [{"source_identity_sha256": "c" * 64, "chunk_sha256": "a" * 64, "characters": 50, "score": 0.8}]}},
            ]}


def bundle(raw=None, name="external_providers"):
    raw = raw or raw_ai()
    digest = delivery.canonical_report_hash(raw)
    return {"schema": 2, "scope": "full_live_acceptance", "source_fingerprint": delivery.code_fingerprint(INVENTORY),
            "started_at": stamp(10)["captured_at"], "finished_at": stamp(1)["captured_at"],
            "identity": {**stamp(10), "llm": LLM, "targets": TARGETS},
            "reports": [{"sha256": digest, "report": raw}],
            "checks": {name: {"state": "PASS", "report_sha256": [digest]}}}


def state(proof, name="external_providers"):
    return next(row["state"] for row in delivery.validate_live_evidence(proof, INVENTORY, now=NOW) if row["name"] == name)


def test_manual_booleans_and_hashes_without_embedded_reports_never_pass():
    proof = {"schema": 1, "scope": "full_live_acceptance", "source_fingerprint": delivery.code_fingerprint(INVENTORY),
             "started_at": stamp(10)["captured_at"], "finished_at": stamp(1)["captured_at"],
             "checks": {"external_providers": {"state": "PASS", "report_sha256": ["a" * 64],
                         "assertions": dict.fromkeys(("deepseek_generate_challenge", "deepseek_stream_terminal", "knowledge_135", "knowledge_real_chunks"), True)}}}
    assert state(proof) != "PASS"


def test_complete_current_raw_provider_observations_pass_only_their_scope():
    proof = bundle()
    rows = delivery.validate_live_evidence(proof, INVENTORY, now=NOW)
    assert [row["name"] for row in rows if row["state"] == "PASS"] == ["external_providers"]


@pytest.mark.parametrize("mutation", [
    lambda p: p["reports"][0]["report"]["checks"][0]["evidence"].update(characters=0),
    lambda p: p["reports"][0].update(sha256="0" * 64),
    lambda p: p.update(reports=[]),
    lambda p: p["identity"].update(database_fingerprint="f" * 64),
    lambda p: p["identity"].update(deploy_simulate_only=False),
    lambda p: p["identity"]["targets"].__setitem__(2, deepcopy(TARGETS[0])),
    lambda p: p["identity"]["llm"].update(model="different-model"),
    lambda p: p.update(started_at=(NOW - timedelta(days=8)).isoformat()),
])
def test_tampering_mixed_runtime_missing_reports_and_stale_runs_fail_closed(mutation):
    proof = deepcopy(bundle())
    mutation(proof)
    assert state(proof) != "PASS"


@pytest.mark.parametrize("mutation", [
    lambda r: r["checks"][0]["evidence"].update(challenge_matched=False),
    lambda r: r["checks"][1]["evidence"].update(content_chunks=0),
    lambda r: r["checks"][1]["evidence"].update(terminal_marker_validated_by_provider=False),
    lambda r: r["checks"][2]["evidence"].update(document_count=134),
    lambda r: r["checks"][3]["evidence"]["chunks"][0].update(source_identity_sha256=""),
    lambda r: r["binding"]["finish"].update(source_fingerprint="0" * 64),
    lambda r: r["binding"]["finish"].update(database_fingerprint="0" * 64),
    lambda r: r["binding"]["start"].update(captured_at=NOW.isoformat()),
    lambda r: r["identity"]["llm"].update(fallback_used=True),
    lambda r: r["checks"].append(deepcopy(r["checks"][0])),
])
def test_rehashed_but_invalid_underlying_observations_still_do_not_pass(mutation):
    raw = raw_ai()
    mutation(raw)
    assert state(bundle(raw)) != "PASS"


def raw_devices():
    return {"schema": 1, "scope": "serial_device_readonly", "ok": True, "core_readonly_ok": True,
            "device_mode": "ssh", "binding": {"start": stamp(9), "finish": stamp(2)},
            "created_at": stamp(8)["captured_at"], "finished_at": stamp(3)["captured_at"],
            "devices": [{"device_id": t["id"], "hostname": t["hostname"], "host": t["mgmt_ip"], "port": t["ssh_port"], "adapter": "ssh", "ok": True, "closed": True,
                         "commands": [{"command": command, "redacted_sha256": "a" * 64, "line_count": 5, **detail} for command, detail in [
                             ("display version", {"huawei_vrp": True}), ("display current-configuration", {"identity_matches": True, "interface_count": 2}),
                             ("display interface brief", {"interface_count": 2}), ("display lldp neighbor brief", {"neighbor_count": 0})]]} for t in TARGETS]}


def test_device_evidence_requires_exact_endpoints_complete_commands_and_closed_sessions():
    raw = raw_devices()
    assert state(bundle(raw, "live_devices"), "live_devices") == "PASS"
    for path, value in (("closed", False), ("port", 23), ("adapter", "sim")):
        broken = deepcopy(raw)
        broken["devices"][0][path] = value
        assert state(bundle(broken, "live_devices"), "live_devices") != "PASS"
    raw["devices"][0]["commands"][-1] = {"command": "display lldp neighbor brief", "ok": False, "reason": "lldp_disabled"}
    assert state(bundle(raw, "live_devices"), "live_devices") != "PASS"


def test_unsupported_producer_cannot_become_deployment_or_recipient_proof():
    for name in ("real_deployment", "recipient_first_run", "abnormal_concurrency", "isolated_mysql", "live_browser", "browser_webssh"):
        assert state(bundle(raw_ai(), name), name) != "PASS"


def test_knowledge_content_changes_invalidate_source_fingerprint():
    assert delivery.code_fingerprint(INVENTORY) != delivery.code_fingerprint({**INVENTORY, "knowledge/corpus/book.md": "3" * 64})


def test_business_steps_need_matching_model_log_ids_session_and_real_tool_audit():
    required = ("database_and_three_targets", "admin_login", "runtime_identity", "admin_identity",
                "api_targets_match_database", "effective_authenticated_health", "anythingllm_health",
                "knowledge_retrieval", "deepseek_generate_cli", "configuration_preview_validation",
                "deepseek_review", "knowledge_answer", "copilot_real_display_tool", "training_session_create",
                "training_honest_process_record", "training_hint", "training_report", "training_complete",
                "training_score_unverified", "training_evidence_retained", "source_unchanged_during_run")
    raw = {"schema": 2, "producer": "verify_full_stack", "scope": "business API", "verdict": {"ok": True, "failed": []},
           "binding": {"start": stamp(9), "finish": stamp(2)}, "created_at": stamp(8)["captured_at"], "finished_at": stamp(3)["captured_at"],
           "expected_identity": stamp(9), "runtime_identity": stamp(9), "targets": TARGETS, "llm": LLM,
           "steps": [{"name": name, "ok": True} for name in required], "session_ids": [3], "tool_audit_ids": [4],
           "ai_logs": [{"id": n, "model_used": LLM["model"], "request_type": kind} for n, kind in enumerate(("generate_cli", "review_config", "copilot_chat", "coach_training", "generate_report"), 1)]}
    assert state(bundle(raw, "business_workflows"), "business_workflows") == "PASS"
    raw["tool_audit_ids"] = []
    assert state(bundle(raw, "business_workflows"), "business_workflows") != "PASS"
    raw["tool_audit_ids"] = [4]
    raw["ai_logs"][0]["model_used"] = "static-fallback"
    assert state(bundle(raw, "business_workflows"), "business_workflows") != "PASS"


def test_webssh_and_current_monitor_jobs_need_exact_devices_closed_sessions_and_no_partial_counts():
    raw = {"schema": 1, "scope": "live_webssh_and_monitor", "ok": True, "runtime_identity": stamp(9),
           "binding": {"start": stamp(9), "finish": stamp(2)}, "created_at": stamp(8)["captured_at"], "finished_at": stamp(3)["captured_at"],
           "targets": TARGETS, "steps": [
               {"name": "webssh", "device_id": t["id"], "hostname": t["hostname"], "ok": True, "closed": True,
                "version": {"command": "display version", "huawei_vrp": True, "redacted_sha256": "a" * 64, "line_count": 2}} for t in TARGETS] + [
               {"name": name, "ok": True, "task_id": ident, "topology_id": 4, "device_count": 3, "metric_points": 12,
                "expected": 3, "attempted": 3, "success": 3, "failed": 0, "skipped": 0, "device_ids": [1, 2, 3],
                "evidence_scope": "current_job", "started_at": stamp(7)["captured_at"], "finished_at": stamp(4)["captured_at"]} for ident, name in ((1, "collect"), (2, "inspections"))]}
    assert state(bundle(raw, "browser_webssh"), "browser_webssh") == "PASS"
    for key, value in (("device_ids", [1, 2, 4]), ("success", 2), ("skipped", 1), ("started_at", stamp(100)["captured_at"])):
        bad = deepcopy(raw)
        bad["steps"][-1][key] = value
        assert state(bundle(bad, "browser_webssh"), "browser_webssh") != "PASS"
    raw["steps"][0]["closed"] = False
    assert state(bundle(raw, "browser_webssh"), "browser_webssh") != "PASS"


def browser_report():
    raw = {"schema": 2, "producer": "verify_live_browser", "ok": True, "errors": [], "runtime_identity": stamp(9),
           "binding": {"start": stamp(9), "finish": stamp(2)}, "started_at": stamp(8)["captured_at"], "finished_at": stamp(3)["captured_at"],
           "llm": LLM, "vision": {"model": "vision-test"}, "targets": TARGETS,
           "checks": [{"name": name, "ok": True, "mode": "live"} for name in ("login", "dashboard", "devices", "topology", "deployment", "monitor", "training", "system")] + [
               {"name": "copilot_vision", "ok": True, "mode": "live", "evidence": {"content_characters": 12, "terminal_ok": True, "fallback_used": False, "ai_log_id": 9, "model_used": "vision-test", "challenge_not_in_prompt": True, "source_image_sha256": "a" * 64}},
               {"name": "copilot", "ok": True, "mode": "live", "evidence": {"content_characters": 12, "terminal_ok": True, "fallback_used": False, "ai_log_id": 8, "model_used": LLM["model"]}}]}
    return raw


def test_browser_requires_real_copilot_and_does_not_accept_injected_or_read_ui_only():
    raw = browser_report()
    assert state(bundle(raw, "live_browser"), "live_browser") == "PASS"
    raw["checks"][-1]["mode"] = "injected"
    assert state(bundle(raw, "live_browser"), "live_browser") != "PASS"
    raw["checks"].pop()
    assert state(bundle(raw, "live_browser"), "live_browser") != "PASS"


def test_assembly_preserves_raw_reports_and_derives_only_supported_verified_states(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(delivery, "datetime", Clock)
    ai, devices = raw_ai(), raw_devices()
    assembled = delivery.assemble_live_evidence([ai, devices], INVENTORY)
    assert assembled["reports"][0]["report"] is ai
    assert assembled["checks"]["external_providers"]["state"] == "PASS"
    assert assembled["checks"]["live_devices"]["state"] == "PASS"
    assert assembled["checks"]["recipient_first_run"]["state"] == "SKIP"
    devices["devices"][0]["closed"] = False
    assembled = delivery.assemble_live_evidence([ai, devices], INVENTORY)
    assert assembled["checks"]["live_devices"]["state"] == "SKIP"


def recipient_report():
    own = {**stamp(9), "database_fingerprint": "b" * 64, "root_fingerprint": "c" * 64}
    finish = {**own, "captured_at": stamp(2)["captured_at"]}
    ai, devices = raw_ai(), raw_devices()
    for child in (ai, devices):
        child["binding"] = {"start": own, "finish": finish}
    devices.update(ok=False, running_saved_equivalent=True)
    for row in devices["devices"]:
        row["running_saved_equivalent"] = True
        saved = deepcopy(row["commands"][1])
        saved["command"] = "display saved-configuration"
        row["commands"][-1] = {"command": "display lldp neighbor brief", "ok": False, "reason": "lldp_disabled"}
        row["commands"].append(saved)
    required = ("independent_empty_mysql", "bootstrap_full", "import_manifest", "corpus_prepared", "start_full_1", "start_full_2",
                "authenticated_start_1", "authenticated_start_2", "live_provider_probe", "live_device_probe", "three_core_devices_and_saved_state",
                "restart_persistence", "owned_process_stopped_1", "owned_process_stopped_2", "build_runtime_unchanged")
    manifest = {"schema": 1, "topology": {"name": "New"}, "devices": [{key: target[key] for key in ("hostname", "mgmt_ip", "ssh_port")} for target in TARGETS]}
    imported = {"table_count": 25, "device_count": 3, "lab_count": 7, "topology_ids": [1], "targets": TARGETS, "retained_sha256": "f" * 64}
    return {"schema": 1, "producer": "verify_recipient_first_run", "ok": True, "binding": {"start": own, "finish": finish},
            "started_at": own["captured_at"], "finished_at": finish["captured_at"],
            "reference": {key: stamp(9)[key] for key in ("source_fingerprint", "database_fingerprint", "root_fingerprint")},
            "steps": [{"name": name, "ok": True} for name in required], "database_before": {"table_count": 0},
            "configuration": {"source": "recipient_root_and_process_environment", "recipient_asserted": True, "device_writes_disabled": True, "scheduler_disabled": True},
            "manifest": manifest, "manifest_sha256": delivery.canonical_report_hash(manifest), "imported": imported, "after_restart": deepcopy(imported),
            "corpus": {"document_count": 135, "uploaded": False, "manifest_sha256": "a" * 64},
            "starts": [{"ok": True, "runtime_identity": {**own, "launch_id": str(n), "pid": n}, "launcher": {"pid": n, "created_ms": 1000 + n, "launch_id": str(n)},
                        "frontend_file_sha256": INVENTORY["sim-frontend/dist/index.html"], "components": dict.fromkeys(("mysql", "llm", "knowledge"), "healthy")} for n in (10, 20)],
            "reports": [{"sha256": delivery.canonical_report_hash(child), "report": child} for child in (ai, devices)]}


def test_recipient_accepts_deliberately_distinct_database_and_root_with_real_subprobe_contracts():
    raw = recipient_report()
    assert state(bundle(raw, "recipient_first_run"), "recipient_first_run") == "PASS"
    assert raw["reports"][1]["report"]["ok"] is False  # LLDP scope remains visibly unmet.


@pytest.mark.parametrize("mutation", [
    lambda r: r["database_before"].update(table_count=1),
    lambda r: r["reference"].update(database_fingerprint="0" * 64),
    lambda r: r["after_restart"].update(retained_sha256="0" * 64),
    lambda r: r["starts"][1]["runtime_identity"].update(launch_id="10"),
    lambda r: r["starts"][0].update(frontend_file_sha256="0" * 64),
    lambda r: r["starts"][0]["launcher"].update(launch_id="wrong"),
    lambda r: r["reports"][1]["report"].update(running_saved_equivalent=False),
    lambda r: r.update(reports=[]),
])
def test_recipient_gate_rejects_nonfresh_store_reference_tamper_stale_restart_and_missing_live_proof(mutation):
    raw = recipient_report()
    mutation(raw)
    assert state(bundle(raw, "recipient_first_run"), "recipient_first_run") != "PASS"


def multi_bundle(raws, name):
    proof = bundle(raws[0], name)
    if name == "real_deployment":
        proof["identity"]["deploy_simulate_only"] = False
    proof["reports"] = [{"sha256": delivery.canonical_report_hash(r), "report": r} for r in raws]
    proof["checks"][name]["report_sha256"] = [item["sha256"] for item in proof["reports"]]
    return proof


def test_migration_requires_full_table_content_preservation_repeat_and_distinct_target():
    from core.migrations import _head
    head = _head()
    tables = ("user device topology topology_link topology_version topology_runtime_check deploy_batch deploy_task device_write_lock config_template config_version audit_log metric_record metric_aggregated alarm monitor_job training_lab training_session fault_injection operation_log ai_log copilot_conversation system_config background_task").split()
    before = {"revision": "0001_initial", "tables": {name: {"columns": ["id"], "rows": 1, "content_sha256": "a" * 64} for name in tables}}
    own = {**stamp(9), "database_fingerprint": "c" * 64}
    raw = {"schema": 1, "producer": "verify_live_migration", "ok": True,
           "binding": {"start": own, "finish": {**own, "captured_at": stamp(2)["captured_at"]}}, "started_at": stamp(8)["captured_at"], "finished_at": stamp(3)["captured_at"],
           "source_identity": {**own, "database_fingerprint": "f" * 64}, "target_identity": own,
           "backup": {"encrypted_sha256": "a" * 64, "sql_sha256": "b" * 64, "encrypted_bytes": 100},
           "restore_privilege_scope": {"database": "new_migration_replay", "new_account": True, "global_privileges": False, "show_grants_sha256": "b" * 64},
           "source_before": deepcopy(before), "restored_before": deepcopy(before), "source_after": deepcopy(before), "expected_after_original_columns": deepcopy(before),
           "target_after": {**deepcopy(before), "revision": head}, "target_repeated": {**deepcopy(before), "revision": head},
           "repeat_was_noop": True, "expected_runtime_promotions": [],
           "checks": dict.fromkeys(("restore_matches_source", "all_original_data_preserved", "only_proven_runtime_promotions", "upgraded_to_head", "repeat_idempotent", "source_unchanged", "build_runtime_unchanged"), True)}
    assert state(bundle(raw, "isolated_mysql"), "isolated_mysql") == "PASS"
    old = deepcopy(raw)
    old["target_after"]["revision"] = old["target_repeated"]["revision"] = "0002_delivery_maintenance"
    assert state(bundle(old, "isolated_mysql"), "isolated_mysql") != "PASS"
    raw["target_after"]["tables"]["user"]["content_sha256"] = "0" * 64
    assert state(bundle(raw, "isolated_mysql"), "isolated_mysql") != "PASS"


def deployment_reports():
    prepared_devices = [{"device_id": t["id"], "hostname": t["hostname"], "original_version_id": t["id"],
                         "original_sha256": "a" * 64, "original_running_sha256": "a" * 64, "original_saved_sha256": "a" * 64,
                         "original_state_sha256": "a" * 64, "original_running_saved_equivalent": True,
                         "apply_task_id": t["id"], "applied": False, "restored": False} for t in TARGETS]
    profile = {"device_ids": [1, 2, 3], "mgmt_ips": ["192.0.2.1"], "topology_id": 8, "baseline_version": 2, "baseline_sha256": "c" * 64}
    reports = []
    for seq, phase in enumerate(("prepare", "apply", "restore")):
        before, after = stamp(9 - seq * 2), stamp(8 - seq * 2)
        before["deploy_simulate_only"] = after["deploy_simulate_only"] = phase == "prepare"
        rows = deepcopy(prepared_devices if seq == 0 else reports[-1]["devices"])
        if phase != "prepare":
            for row in rows:
                task_id = row["device_id"] + (100 if phase == "restore" else 0)
                row[f"{phase}_task_id"] = task_id
                row["restored" if phase == "restore" else "applied"] = True
                created_action = "deploy_rollback_task_created" if phase == "restore" else "deploy_task_created"
                base = task_id * 10
                # Real audit vocabulary, as verify_live_deploy.py documents it: the
                # execute step succeeds as "executed", the write lock is released
                # BEFORE the verification row is written, and a high-risk rollback
                # is confirmed twice (awaiting risk confirmation, then confirmed).
                audit = [{"id": base + 1, "action": created_action, "result": "success"},
                         {"id": base + 2, "action": "deploy_task_confirmed", "result": "success"}]
                if phase == "restore":
                    audit.append({"id": base + 3, "action": "deploy_task_confirmed", "result": "success"})
                audit += [{"id": base + 4, "action": "deploy_task_executed", "result": "executed"},
                          {"id": base + 5, "action": "device_write_lock_released", "result": "success"},
                          {"id": base + 6, "action": "deploy_task_verified", "result": "success"}]
                row[phase] = {"task_id": task_id, "device_id": row["device_id"], "ok": True, "status": "success", "mode": "real", "verified": True, "locks": 0, "closed": True,
                              "running_saved_equivalent": True, "backup_sha256": "b" * 64, "result_sha256": "c" * 64, "running_sha256": "c" * 64, "saved_sha256": "c" * 64,
                              "running_state_sha256": "a" * 64, "saved_state_sha256": "a" * 64, "config_version_id": task_id,
                              "audit": audit, "original_restored": phase == "restore"}
        reports.append({"schema": 1, "scope": "live_controlled_deployment", "ok": True, "phase": phase, "state": {"prepare": "prepared", "apply": "applied", "restore": "restored"}[phase],
                        "run_id": "same-run", "batch_id": 1, "targets": TARGETS, "operation_plan_sha256": "a" * 64, "approval_reference_sha256": "b" * 64,
                        "binding": {"start": before, "finish": after}, "started_at": before["captured_at"], "finished_at": after["captured_at"], "write_profile": profile, "devices": rows})
    return reports


def test_deployment_needs_all_three_phases_real_tasks_audits_and_semantic_restore():
    reports = deployment_reports()
    assert state(multi_bundle(reports, "real_deployment"), "real_deployment") == "PASS"
    assert state(multi_bundle(reports[:2], "real_deployment"), "real_deployment") != "PASS"
    reports[-1]["devices"][0]["restore"]["running_state_sha256"] = "d" * 64
    assert state(multi_bundle(reports, "real_deployment"), "real_deployment") != "PASS"
    reports = deployment_reports()
    audit = reports[1]["devices"][0]["apply"]["audit"]
    executed = next(row for row in audit if row["action"] == "deploy_task_executed")
    released = next(row for row in audit if row["action"] == "device_write_lock_released")
    verified = next(row for row in audit if row["action"] == "deploy_task_verified")
    released_id, verified_id = released["id"], verified["id"]
    # The real success literal is "executed"; a generic or failed result must not pass.
    for literal in ("success", "error", None):
        executed["result"] = literal
        assert state(multi_bundle(reports, "real_deployment"), "real_deployment") != "PASS"
    executed["result"] = "executed"
    assert state(multi_bundle(reports, "real_deployment"), "real_deployment") == "PASS"
    # Every chain row needs its own id, and the ordered steps must stay ordered.
    released["id"] = executed["id"]
    assert state(multi_bundle(reports, "real_deployment"), "real_deployment") != "PASS"
    released["id"] = released_id
    verified["id"] = audit[0]["id"]
    assert state(multi_bundle(reports, "real_deployment"), "real_deployment") != "PASS"
    verified["id"] = verified_id
    audit.remove(verified)
    assert state(multi_bundle(reports, "real_deployment"), "real_deployment") != "PASS"
    audit.append(verified)
    assert state(multi_bundle(reports, "real_deployment"), "real_deployment") == "PASS"


def test_prepare_profile_exception_keeps_all_other_identity_fields_strict():
    reports = deployment_reports()
    proof = multi_bundle(reports, "real_deployment")
    proof["identity"]["deploy_simulate_only"] = True
    assert state(proof, "real_deployment") != "PASS"
    for stamp_value in reports[0]["binding"].values():
        stamp_value["database_fingerprint"] = "f" * 64
    assert state(multi_bundle(reports, "real_deployment"), "real_deployment") != "PASS"


def test_recipient_safe_profile_is_allowed_with_main_real_write_profile():
    proof = bundle(recipient_report(), "recipient_first_run")
    proof["identity"]["deploy_simulate_only"] = False
    assert state(proof, "recipient_first_run") == "PASS"


def test_abnormal_gate_combines_live_load_isolated_faults_permissions_and_real_restart():
    resilience = {"schema": 1, "producer": "verify_live_resilience", "ok": True, "runtime_identity": stamp(9), "llm": LLM, "targets": TARGETS,
                  "binding": {"start": stamp(9), "finish": stamp(2)}, "started_at": stamp(8)["captured_at"], "finished_at": stamp(3)["captured_at"],
                  "steps": [{"name": name, "ok": True, "http_status": 401} for name in ("anonymous_rejected", "invalid_token_rejected", "concurrent_readers", "webssh_contention_recovery", "build_runtime_unchanged")],
                  "load": {"users": 30, "duration_seconds": 30, "passed": True, "total_requests": 70, "identity_scope": "one_administrator_login_with_concurrent_virtual_readers",
                           "endpoints": [{"endpoint": name, "requests": 10, "errors": 0, "error_rate": 0, "violations": [], "p95_ms": 50, "p95_threshold_ms": threshold} for name, threshold in (
                               ("dashboard/summary", 2000), ("devices", 1000), ("deploy/tasks", 1000), ("training/labs", 1000), ("alarms", 1000), ("system/info", 1000), ("monitor/stats", 1000))]},
                  "webssh_contention": {"device_id": 1, "ok": True, "first_closed": True, "second_closed": True, "busy_reported": True, "second_session_rejected": True, "recovery_closed": True,
                                        "recovery": {"ok": True, "hostname": "R1", "version": {"command": "display version", "huawei_vrp": True, "line_count": 5, "redacted_sha256": "a" * 64}}}}
    fault_start, fault_finish = {**stamp(9), "database_fingerprint": "9" * 64}, {**stamp(2), "database_fingerprint": "9" * 64}
    faults = {"schema": 1, "producer": "verify_live_dependency_faults", "scope": "isolated_dependency_fault_injection", "ok": True,
              "binding": {"start": fault_start, "finish": fault_finish}, "started_at": stamp(8)["captured_at"], "finished_at": stamp(3)["captured_at"],
              "isolation": {"configuration": "init_only", "external_targets": 0, "database_migrated": False, "scheduler_started": False, "existing_services_modified": False, "host": "127.0.0.1", "http_port": 40111, "refused_port": 40112},
              "secrets_clean": True, "synthetic_markers_checked": 5, "resources_closed": True, "failure_type": None, "fault_request_count": 10,
              "network_guard": {"allowed_host": "127.0.0.1", "allowed_ports": [40111, 40112], "connection_or_resolution_attempts": 10, "blocked_attempts": 0},
              "components": {"database": {"ok": True, "health_http_status": 503, "health_status": "unhealthy", "mysql_status": "unhealthy"},
                             "llm": {"ok": True, "generate_exception": "HTTPStatusError", "application_generate_status": "degraded", "stream_error": True, "stream_done_status": "failed", "stream_done_count": 1},
                             "knowledge": {"ok": True, "available": False, "retrieve_exception": "HTTPStatusError", "ask_status": "degraded", "ask_sources_count": 0, "ask_answer_characters": 0},
                             "ssh": {"ok": True, "exception": "ConnectionRefusedError", "closed": True, "lock_reacquired": True}}}
    browser = browser_report()
    browser["checks"] += [
        {"name": "permissions_anonymous", "ok": True, "mode": "live", "evidence": {"backend_status": 401, "copilot_sse_status": 401, "protected_route_redirected": True}},
        {"name": "permissions_readonly", "ok": True, "mode": "live", "evidence": {"backend_status": 403, "frontend_redirected": True, "other_owner_conversation_status": 200, "other_owner_conversation_hidden": True}}]
    reports = [resilience, faults, recipient_report(), browser]
    assert state(multi_bundle(reports, "abnormal_concurrency"), "abnormal_concurrency") == "PASS"
    assert state(multi_bundle(reports[:2], "abnormal_concurrency"), "abnormal_concurrency") != "PASS"
    resilience["load"]["users"] = 16
    assert state(multi_bundle(reports, "abnormal_concurrency"), "abnormal_concurrency") != "PASS"
    resilience["load"]["users"] = 30
    faults["components"]["knowledge"]["ask_sources_count"] = 1
    assert state(multi_bundle(reports, "abnormal_concurrency"), "abnormal_concurrency") != "PASS"
    faults["components"]["knowledge"]["ask_sources_count"] = 0
    faults["network_guard"]["blocked_attempts"] = 1
    assert state(multi_bundle(reports, "abnormal_concurrency"), "abnormal_concurrency") != "PASS"
    faults["network_guard"]["blocked_attempts"] = 0
    faults["components"]["database"]["ok"] = False
    assert state(multi_bundle(reports, "abnormal_concurrency"), "abnormal_concurrency") != "PASS"
    faults["components"]["database"]["ok"] = True
    # The producer checks four synthetic fault credentials plus the generated JWT key.
    # An older four-marker report, a loose or stringly-typed count and a missing field
    # must all stay rejected; only the exact five-marker observation is accepted.
    for markers in (4, 6, "5", True):
        faults["synthetic_markers_checked"] = markers
        assert state(multi_bundle(reports, "abnormal_concurrency"), "abnormal_concurrency") != "PASS"
    faults["synthetic_markers_checked"] = 5
    faults["secrets_clean"] = False
    assert state(multi_bundle(reports, "abnormal_concurrency"), "abnormal_concurrency") != "PASS"
    faults["secrets_clean"] = True
    del faults["network_guard"]["connection_or_resolution_attempts"]
    assert state(multi_bundle(reports, "abnormal_concurrency"), "abnormal_concurrency") != "PASS"
    faults["network_guard"]["connection_or_resolution_attempts"] = 10
    assert state(multi_bundle(reports, "abnormal_concurrency"), "abnormal_concurrency") == "PASS"


@pytest.mark.parametrize("malformed", [None, [], "PASS", {"schema": 2, "checks": []}, {"schema": 2, "reports": "bad"}])
def test_malformed_input_is_incomplete_not_an_exception(malformed):
    assert all(row["state"] != "PASS" for row in delivery.validate_live_evidence(malformed, INVENTORY, now=NOW))
