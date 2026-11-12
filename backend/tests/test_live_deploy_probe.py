"""Controlled deployment acceptance is never run against devices by these tests."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import verify_live_deploy as probe


def binding(simulated):
    return {"schema": 1, "database_fingerprint": "db", "root_fingerprint": "root", "source_fingerprint": "source",
            "knowledge_provider": "local", "device_mode": "ssh", "deploy_simulate_only": simulated,
            "captured_at": "2026-10-11T00:00:00+00:00"}


def test_profile_transition_only_allows_explicit_simulation_switch():
    probe.require_same_build(binding(True), binding(False))
    for key in ("database_fingerprint", "root_fingerprint", "source_fingerprint", "device_mode"):
        altered = {**binding(False), key: "changed"}
        with pytest.raises(probe.ProbeRefused):
            probe.require_same_build(binding(True), altered)


def test_baseline_requires_existing_undescribed_loopback_and_lldp_disabled():
    before = "sysname R1\n#\ninterface LoopBack0\n ip address 192.0.2.1 255.255.255.255\n#\nreturn"
    probe.require_original(before, "R1")
    for invalid in (before.replace("#\ninterface", "lldp enable\n#\ninterface"),
                    before.replace(" ip address", " description existing\n ip address"),
                    before.replace("LoopBack0", "LoopBack1"), before.replace("R1", "R2")):
        with pytest.raises(probe.ProbeRefused):
            probe.require_original(invalid, "R1")


@pytest.mark.asyncio
async def test_execute_failure_never_verifies_or_retries(tmp_path):
    calls = []

    class Api:
        async def post(self, path, payload=None, **kwargs):
            calls.append(path)
            if path.endswith("confirm"):
                return {"status": "confirmed"}
            return {"mode": "real", "error_category": "ReadTimeout"}

    with pytest.raises(probe.ProbeRefused):
        await probe.execute_confirmed(Api(), 12)
    assert calls == ["/deploy/tasks/12/confirm", "/deploy/tasks/12/execute"]


@pytest.mark.asyncio
async def test_explicit_approved_risk_path_requires_both_confirmation_steps():
    calls = []

    class Api:
        async def post(self, path, payload=None, **kwargs):
            calls.append((path, payload))
            if path.endswith("confirm"):
                return {"awaiting_risk_confirmation": True} if len(calls) == 1 else {"status": "confirmed"}
            if path.endswith("execute"):
                return {"mode": "real"}
            return {"mode": "real", "verification": "passed", "result": "success"}

    await probe.execute_confirmed(Api(), 12)
    assert [payload for path, payload in calls if path.endswith("confirm")] == [
        {"risk_confirm": False}, {"risk_confirm": True}]


@pytest.mark.asyncio
async def test_unknown_post_outcome_retains_durable_intent_and_blocks_retry(tmp_path):
    class Client:
        async def request(self, *args, **kwargs):
            raise TimeoutError("fixture network outcome unknown")

    path = tmp_path / "journal.json"
    journal = {"steps": []}
    api = probe.Api(Client(), "http://127.0.0.1/api/v1", journal, path)
    with pytest.raises(TimeoutError):
        await api.post("/deploy/tasks/12/execute")
    persisted = probe.load_journal(path)
    assert persisted["inflight"]["path"] == "/deploy/tasks/12/execute"
    with pytest.raises(probe.ProbeRefused, match="unresolved_operation"):
        await api.post("/deploy/tasks/12/execute")


def test_write_gate_needs_approval_real_mode_and_exact_allowlist():
    targets = [probe.ExpectedTarget(i, f"R{i}", "192.0.2.1", 2000 + i) for i in (1, 2, 3)]
    args = SimpleNamespace(approval_reference="human-message-fixture", topology_id=3)
    settings = SimpleNamespace(deploy_simulate_only=False, deploy_allowlist_device_ids="1,2,3",
                               deploy_allowlist_mgmt_ips="192.0.2.1", deploy_allowlist_topology_id=3,
                               deploy_allowlist_baseline_version=2)
    assert probe.write_profile(args, settings, targets)["baseline_version"] == 2
    for field, value in (("approval_reference", ""),):
        with pytest.raises(probe.ProbeRefused):
            probe.write_profile(SimpleNamespace(**{**vars(args), field: value}), settings, targets)
    for field, value in (("deploy_simulate_only", True), ("deploy_allowlist_device_ids", "1,2,3,4"),
                         ("deploy_allowlist_baseline_version", 0)):
        with pytest.raises(probe.ProbeRefused):
            probe.write_profile(args, SimpleNamespace(**{**vars(settings), field: value}), targets)


def original(hostname):
    return f"sysname {hostname}\n#\ninterface LoopBack0\n ip address 192.0.2.1 255.255.255.255\n#\nreturn"


def changed(hostname):
    return original(hostname).replace("#\ninterface", "lldp enable\n#\ninterface").replace(
        " ip address", f" description ACCEPT_{hostname}\n ip address")


def test_unrelated_configuration_change_is_not_an_approved_restore():
    probe.require_only_probe_change(original("R1"), changed("R1"), probe.commands("R1", "ACCEPT"))
    with pytest.raises(probe.ProbeRefused, match="unapproved"):
        probe.require_only_probe_change(original("R1"), changed("R1").replace("192.0.2.1", "192.0.2.2"), probe.commands("R1", "ACCEPT"))


def test_semantic_hash_ignores_only_order_comments_and_reviewed_defaults():
    before = original("R1")
    equivalent = before.replace("sysname R1", "# timestamp changes\nundo lldp enable\nsysname R1").replace(
        " ip address", " undo shutdown\n ip address")
    assert probe.ConfigVerifier.verify_snapshot(before, equivalent) is None
    assert probe.state_digest(before) == probe.state_digest(equivalent)
    reordered = "interface LoopBack0\n ip address 192.0.2.1 255.255.255.255\n#\nsysname R1\nreturn"
    assert probe.state_digest(before) == probe.state_digest(reordered)
    for changed_state in (before.replace(" ip address", " undo portswitch\n ip address"),
                          before.replace("LoopBack0", "LoopBack1"), changed("R1")):
        assert probe.state_digest(before) != probe.state_digest(changed_state)


@pytest.mark.asyncio
async def test_prepare_creates_versions_and_batch_but_never_confirms(tmp_path, monkeypatch):
    targets = [probe.ExpectedTarget(i, f"R{i}", "192.0.2.1", 2000 + i) for i in (1, 2, 3)]
    args = SimpleNamespace(expect=targets, journal=tmp_path / "prepare.json", marker_prefix="ACCEPT", plan_sha256="plan")
    calls = []

    class Api:
        async def post(self, path, payload):
            calls.append(path)
            if path == "/config-versions/capture":
                ident = payload["device_ids"][0]
                return [{"device_id": ident, "version_id": ident * 10}]
            assert path == "/deploy/batches"
            assert payload["name"].startswith("Live acceptance")
            return {"id": 1, "items": [{"device_id": i, "id": i * 100, "status": "awaiting_confirmation"} for i in (1, 2, 3)]}

    class DB:
        async def version(self, version_id, device_id):
            return {"id": version_id, "config_snapshot": original(f"R{device_id}")}

    async def read(db, target):
        return original(target.hostname), original(target.hostname)

    monkeypatch.setattr(probe, "read_current_saved", read)
    journal = {"run_id": "test", "steps": []}
    await probe.prepare(Api(), DB(), args, journal)
    assert journal["state"] == "prepared" and len(journal["devices"]) == 3
    assert all(item["original_state_sha256"] == probe.state_digest(original(item["hostname"])) for item in journal["devices"])
    assert calls == ["/config-versions/capture"] * 3 + ["/deploy/batches"]
    assert "sysname" not in args.journal.read_text()  # No plaintext snapshots in journal.


@pytest.mark.asyncio
async def test_apply_and_restore_are_serial_and_use_controlled_api(tmp_path, monkeypatch):
    targets = [probe.ExpectedTarget(i, f"R{i}", "192.0.2.1", 2000 + i) for i in (1, 2, 3)]
    args = SimpleNamespace(expect=targets, journal=tmp_path / "run.json", marker_prefix="ACCEPT",
                           topology_id=3, approval_reference="approved-human-message")
    settings = SimpleNamespace(deploy_simulate_only=False, deploy_allowlist_device_ids="1,2,3",
                               deploy_allowlist_mgmt_ips="192.0.2.1", deploy_allowlist_topology_id=3,
                               deploy_allowlist_baseline_version=2)
    journal = {"state": "prepared", "prepare_binding": binding(True), "devices": [
        {"device_id": i, "hostname": f"R{i}", "original_version_id": i * 10,
         "original_sha256": probe.digest(original(f"R{i}")), "apply_task_id": i * 100,
         "applied": False, "restored": False} for i in (1, 2, 3)]}
    state = {i: original(f"R{i}") for i in (1, 2, 3)}
    calls, locked_checks = [], []
    monkeypatch.setattr(probe, "capture_binding", lambda _: binding(False))
    monkeypatch.setattr(probe, "runtime_identity", lambda _: binding(False))

    class DB:
        no_lock = AsyncMock()
        target_baseline = AsyncMock(return_value="baseline")

        async def version(self, version_id, device_id):
            return {"config_snapshot": original(f"R{device_id}")}

        async def task_evidence(self, task_id, device_id, *args, **kwargs):
            return {"task_id": task_id, "device_id": device_id, "ok": True}

    class Api:
        async def get(self, path):
            if path == "/system/runtime-identity":
                return binding(False)
            task_id = int(path.rsplit("/", 1)[1])
            ident = task_id % 100 if task_id > 1000 else task_id // 100
            return {"device_id": ident, "status": "awaiting_confirmation", "has_lock": False,
                    "config_content": probe.commands(f"R{ident}", "ACCEPT")}

        async def post(self, path, payload=None, **kwargs):
            calls.append(path)
            if path.endswith("rollback-task"):
                version_id = int(path.split("/")[-2])
                return {"device_id": version_id // 10, "source_version_id": version_id, "task_id": 1000 + version_id // 10}
            task_id = int(path.split("/")[-2])
            ident = task_id % 100 if task_id > 1000 else task_id // 100
            if path.endswith("confirm"):
                return {"status": "confirmed"}
            if path.endswith("execute"):
                assert locked_checks[-1] == task_id
                state[ident] = original(f"R{ident}") if task_id > 1000 else changed(f"R{ident}")
                return {"mode": "real"}
            return {"mode": "real", "verification": "passed", "result": "success"}

    async def read(db, target, *, owned_task=None):
        if owned_task is not None:
            locked_checks.append(owned_task)
        return state[target.device_id], state[target.device_id]

    monkeypatch.setattr(probe, "read_current_saved", read)
    await probe.mutate(Api(), DB(), args, settings, journal, restore=False)
    assert journal["state"] == "applied" and all(item["applied"] for item in journal["devices"])
    await probe.mutate(Api(), DB(), args, settings, journal, restore=True)
    assert journal["state"] == "restored" and all(item["restored"] for item in journal["devices"])
    assert all(item["restore"]["running_state_sha256"] == item["restore"]["saved_state_sha256"]
               == probe.state_digest(original(item["hostname"])) for item in journal["devices"])
    assert [path for path in calls if path.endswith("execute")] == [
        f"/deploy/tasks/{ident}/execute" for ident in (100, 200, 300, 1003, 1002, 1001)]
    assert all(state[i] == original(f"R{i}") for i in (1, 2, 3))


@pytest.mark.asyncio
async def test_restore_never_reports_success_when_nothing_was_applied():
    with pytest.raises(probe.ProbeRefused):
        await probe.mutate(None, None, None, None, {"state": "prepared", "devices": []}, restore=True)


@pytest.mark.asyncio
async def test_changed_state_under_confirmed_lock_prevents_execute():
    api = SimpleNamespace(post=AsyncMock(return_value={"status": "confirmed"}))

    async def refused():
        raise probe.ProbeRefused("original_changed_after_confirmation")

    with pytest.raises(probe.ProbeRefused):
        await probe.execute_confirmed(api, 12, pre_execute=refused)
    assert api.post.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [None, "backup", "simulated_audit", "missing_release", "version"])
async def test_database_evidence_requires_original_backup_real_audit_and_verified_version(invalid):
    before, after = original("R1"), changed("R1")
    task = {"device_id": 1, "status": "success", "verified": True, "error_message": None,
            "verify_diff": None, "engine": "netmiko", "backup_config": before, "result_output": after,
            "config_content": probe.commands("R1", "ACCEPT")}
    version = {"id": 42, "config_snapshot": after}
    audits = [{"id": i, "action": name, "result": "success", "detail": "{}"} for i, name in enumerate([
        "deploy_task_created", "deploy_task_confirmed", "deploy_task_executed", "device_write_lock_released",
        "deploy_task_verified"], 1)]
    audits[2]["detail"] = "{'mode': 'real', 'result': 'executed'}"
    if invalid == "backup":
        task["backup_config"] = before.replace("192.0.2.1", "192.0.2.2")
    elif invalid == "simulated_audit":
        audits[2]["detail"] = "{'mode': 'simulated', 'result': 'executed'}"
    elif invalid == "missing_release":
        audits.pop(3)
    elif invalid == "version":
        version["config_snapshot"] = before
    db = probe.EvidenceDB(None)
    db.rows = AsyncMock(side_effect=[[task], [version], audits, []])
    if invalid:
        with pytest.raises(probe.ProbeRefused):
            await db.task_evidence(12, 1, before, probe.commands("R1", "ACCEPT"), restore=False)
    else:
        result = await db.task_evidence(12, 1, before, probe.commands("R1", "ACCEPT"), restore=False)
        assert result["ok"] and result["locks"] == 0 and len(result["audit"]) == 5
        assert "sysname" not in str(result)


@pytest.mark.asyncio
async def test_independent_readback_always_closes_and_never_saves(monkeypatch):
    from engines import device_adapter
    target = probe.ExpectedTarget(1, "R1", "192.0.2.1", 2001)
    device = SimpleNamespace(id=1, hostname="R1", mgmt_ip="192.0.2.1", ssh_port=2001)
    adapter = SimpleNamespace(name="ssh", run_command=AsyncMock(side_effect=[
        "VRP (R) software, Version 8.241 (NE40E-X16 V800R024)", original("R1"), changed("R1")]),
        close=AsyncMock(), send_config=AsyncMock(), save_config=AsyncMock())
    monkeypatch.setattr(device_adapter, "get_device_adapter", AsyncMock(return_value=adapter))
    db = SimpleNamespace(no_lock=AsyncMock(), device=AsyncMock(return_value=device))
    with pytest.raises(probe.ProbeRefused, match="running_saved_differ"):
        await probe.read_current_saved(db, target)
    adapter.close.assert_awaited_once()
    adapter.send_config.assert_not_awaited()
    adapter.save_config.assert_not_awaited()
    assert [call.args[0] for call in adapter.run_command.await_args_list] == [
        "display version", "display current-configuration", "display saved-configuration"]
