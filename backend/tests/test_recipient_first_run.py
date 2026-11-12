"""Fresh recipient live producer contract with all external operations replaced."""
from copy import deepcopy
import hashlib
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.config import Settings
from scripts import verify_recipient_first_run as probe


@pytest.fixture
def rig(tmp_path, monkeypatch):
    import core.config
    import core.live_evidence
    import scripts.setup_full_workspace as setup

    root = tmp_path / "recipient"
    for name in (".env", "backend/.venv/Scripts/python.exe", "backend/requirements.lock", "sim-frontend/dist/index.html"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(probe, "ROOT", root)
    settings = Settings(_env_file=None, db_backend="mysql", db_url="", db_name="fresh_recipient", device_mode="ssh", knowledge_provider="anythingllm", deploy_simulate_only=True, monitor_scheduler_enabled=False)
    monkeypatch.setattr(core.config, "get_settings", lambda: settings)
    stamp = {"schema": 1, "source_fingerprint": "a" * 64, "root_fingerprint": "b" * 64, "database_fingerprint": "c" * 64,
             "device_mode": "ssh", "knowledge_provider": "anythingllm", "deploy_simulate_only": True,
             "captured_at": "2026-10-11T10:00:00+00:00"}
    monkeypatch.setattr(core.live_evidence, "capture_binding", lambda settings: deepcopy(stamp))
    reference = root / "reference.json"
    reference.write_text(json.dumps({"source_fingerprint": "a" * 64, "root_fingerprint": "d" * 64, "database_fingerprint": "e" * 64}))
    devices = [{"hostname": f"R{n}", "mgmt_ip": "192.0.2.1", "ssh_port": n + 2200, "device_type": "router", "vendor": "huawei"} for n in (1, 2, 3)]
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"schema": 1, "topology": {"name": "New"}, "devices": devices}))
    targets = [{"id": n, **{key: d[key] for key in ("hostname", "mgmt_ip", "ssh_port")}} for n, d in enumerate(devices, 1)]
    facts = {"table_count": 25, "device_count": 3, "lab_count": 7, "topology_ids": [1], "targets": targets, "retained_sha256": "f" * 64}
    state = SimpleNamespace(calls=[], stopped=[], provider_failed=False, old_pid=False, facts=facts, stamp=stamp,
                            launch_failure=None, device_mismatch=None)
    reader = AsyncMock(side_effect=[{"table_count": 0}, deepcopy(facts), deepcopy(facts)])
    monkeypatch.setattr(probe, "database_facts", reader)
    state.reader = reader
    monkeypatch.setattr(setup, "prepare_corpus", lambda *a: {"document_count": 135, "uploaded": False, "documents": []})
    output = root / ".runtime/test"
    output.mkdir(parents=True)
    args = SimpleNamespace(reference_identity=reference, manifest=manifest, expect_database="fresh_recipient", exclusive_window=True,
                           recipient_configured=True, output=output, backend_port=18099)
    state.args = args

    def command(argv, root, timeout):
        state.calls.append(argv)
        if any(str(a).endswith("start-full.ps1") for a in argv):
            receipt = argv[argv.index("-LaunchReceipt") + 1]
            from pathlib import Path
            Path(receipt).write_text(json.dumps({"pid": 100, "created_ms": 1000000, "launch_id": "fixture-launch"}))
            if state.launch_failure == "timeout":
                raise subprocess.TimeoutExpired(argv, timeout)
            if state.launch_failure == "exit":
                return 1, b"launcher failed after process creation"
            if state.launch_failure == "missing_pid":
                return 0, b"launcher stdout truncated"
            return 0, b"[full] PID=100"
        if any(str(a).endswith("verify_live_ai.py") for a in argv):
            if state.provider_failed:
                return 1, b"private upstream failure never printed"
            (output / "providers.json").write_text(json.dumps({"schema_version": 1, "scope": "deepseek_and_anythingllm_readonly", "ok": True, "binding": {"start": stamp, "finish": stamp}}))
        if any(str(a).endswith("verify_live_readonly.py") for a in argv):
            rows = []
            for target in targets:
                rows.append({"device_id": target["id"], "hostname": target["hostname"], "host": target["mgmt_ip"], "port": target["ssh_port"],
                             "closed": True, "adapter": "ssh", "running_saved_equivalent": True,
                             "commands": [{"command": name, "line_count": 5, "interface_count": 3, "redacted_sha256": "f" * 64, "identity_matches": True, "huawei_vrp": True} for name in (
                                 "display version", "display current-configuration", "display saved-configuration", "display interface brief")]})
            if state.device_mismatch == "duplicate":
                rows[2] = deepcopy(rows[0])
            elif state.device_mismatch:
                rows[0][state.device_mismatch] = "wrong" if state.device_mismatch in ("hostname", "host") else 999
            (output / "devices.json").write_text(json.dumps({"schema": 1, "scope": "serial_device_readonly", "ok": False, "core_readonly_ok": True,
                "running_saved_equivalent": True, "devices": rows, "binding": {"start": stamp, "finish": stamp}}))
            return 1, b"lldp disabled; core and saved equivalent observed"
        return 0, b"local fixture output"
    monkeypatch.setattr(probe, "run_command", command)
    monkeypatch.setattr(probe.time, "time", lambda: 1000.0)
    def owned_from_receipt(path, earliest):
        if state.old_pid:
            raise ValueError("recipient_launch_receipt_invalid")
        return {**json.loads(path.read_text()), "state": "READY"}
    monkeypatch.setattr(probe, "owned_from_receipt", owned_from_receipt)
    monkeypatch.setattr(probe, "stop_owned", lambda record: state.stopped.append(record["pid"]))
    monkeypatch.setattr(probe, "wait_port_closed", AsyncMock())
    authenticated = AsyncMock(side_effect=[{"ok": True, "runtime_identity": {**stamp, "launch_id": "first"}},
                                           {"ok": True, "runtime_identity": {**stamp, "launch_id": "second"}}])
    monkeypatch.setattr(probe, "authenticated_start", authenticated)
    return state


@pytest.mark.asyncio
async def test_recipient_run_executes_real_entry_contract_twice_and_keeps_original_probe_reports(rig):
    report = await probe.verify(rig.args)
    assert report["ok"] is True and rig.stopped == [100, 100]
    assert len(report["starts"]) == 2 and len(report["reports"]) == 2
    assert report["reports"][1]["report"]["ok"] is False  # LLDP scope was not rewritten.
    assert report["steps"][-1] == {"name": "build_runtime_unchanged", "ok": True}


@pytest.mark.asyncio
async def test_nonempty_database_refuses_before_bootstrap_or_any_external_command(rig):
    rig.reader.side_effect = [{"table_count": 1}]
    report = await probe.verify(rig.args)
    assert report["ok"] is False and rig.calls == [] and rig.stopped == []


@pytest.mark.asyncio
async def test_failed_model_probe_cannot_pass_and_owned_process_is_cleaned_up(rig):
    rig.provider_failed = True
    report = await probe.verify(rig.args)
    assert report["ok"] is False and rig.stopped == [100]
    assert "private upstream failure" not in json.dumps(report)


@pytest.mark.asyncio
async def test_unowned_recycled_pid_is_never_killed(rig):
    rig.old_pid = True
    report = await probe.verify(rig.args)
    assert report["ok"] is False and rig.stopped == []


@pytest.mark.asyncio
async def test_restart_must_preserve_inventory_not_only_authenticate(rig):
    rig.reader.side_effect = [{"table_count": 0}, deepcopy(rig.facts), {**rig.facts, "retained_sha256": "0" * 64}]
    report = await probe.verify(rig.args)
    assert report["ok"] is False and rig.stopped == [100, 100]


def test_core_smoke_rejects_saved_state_mismatch_even_with_core_ok():
    with pytest.raises(ValueError, match="recipient_core_device_probe_failed"):
        probe.core_device_smoke({"core_readonly_ok": True, "running_saved_equivalent": False}, [])


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "exit", "missing_pid"])
async def test_launcher_failure_receipt_still_cleans_up_owned_process(rig, failure):
    rig.launch_failure = failure
    report = await probe.verify(rig.args)
    assert report["ok"] is False and rig.stopped == [100]
    assert any(step["name"] == "owned_process_cleanup" and step["ok"] for step in report["steps"])


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["device_id", "hostname", "host", "port", "duplicate"])
async def test_three_device_report_must_match_exact_imported_targets(rig, field):
    rig.device_mismatch = field
    report = await probe.verify(rig.args)
    assert report["ok"] is False and rig.stopped == [100]
    assert not any(step["name"] == "three_core_devices_and_saved_state" for step in report["steps"])


@pytest.mark.asyncio
async def test_imported_database_targets_must_match_manifest_before_start(rig):
    incorrect = deepcopy(rig.facts)
    incorrect["targets"][0]["ssh_port"] = 9999
    rig.reader.side_effect = [{"table_count": 0}, incorrect]
    report = await probe.verify(rig.args)
    assert report["ok"] is False and rig.stopped == []
    assert not any(any(str(arg).endswith("start-full.ps1") for arg in command) for command in rig.calls)


def test_launcher_timeout_ends_only_the_controller_and_preserves_receipt(tmp_path, monkeypatch):
    from unittest.mock import Mock
    child = Mock(pid=321)
    child.poll.return_value = None
    child.communicate.side_effect = [subprocess.TimeoutExpired("launch", 2), (b"", None)]
    monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: child)
    with pytest.raises(subprocess.TimeoutExpired):
        probe.run_command(["powershell.exe", "-File", "start-full.ps1"], tmp_path, 2)
    child.kill.assert_called_once()


# ---------------------------------------------------------------------------
# authenticated_start: the real function runs here; only the HTTP transport is
# replaced. The previous suite replaced the whole function with an AsyncMock,
# which is exactly why the CRLF/LF page comparison defect went unnoticed.
# ---------------------------------------------------------------------------

IDENTITY = {"schema": 1, "database_fingerprint": "c" * 64, "root_fingerprint": "b" * 64,
            "device_mode": "ssh", "knowledge_provider": "anythingllm", "deploy_simulate_only": True}
HEALTHY = {"components": {name: {"status": "healthy"} for name in ("mysql", "llm", "knowledge")}}
_LF_TEXT = '<!DOCTYPE html>\n<html lang="zh-CN">\n<body>IP仿真运维工作台</body>\n</html>\n'
_CRLF_TEXT = '<!DOCTYPE html>\r\n<html lang="zh-CN">\r\n<body>IP仿真运维工作台</body>\r\n</html>\r\n'
LF_PAGE = _LF_TEXT.encode("utf-8")
CRLF_PAGE = _CRLF_TEXT.encode("utf-8")


def _install_transport(monkeypatch, *, page_bytes, page_status=200, identity=None, health=None):
    """Replace only the HTTP transport so the real function body executes."""
    import httpx

    identity = dict(IDENTITY if identity is None else identity)
    health = HEALTHY if health is None else health
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        if request.url.path == "/api/v1/system/runtime-identity":
            return httpx.Response(200, json=identity)
        if request.url.path == "/api/v1/health":
            return httpx.Response(200, json=health)
        if request.url.path == "/":
            return httpx.Response(page_status, content=page_bytes,
                                  headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *args, **kwargs: real_client(*args, **{**kwargs, "transport": transport}))
    return seen


def _prepare(tmp_path, monkeypatch, raw, *, page_bytes=None, identity=None, health=None, page_status=200):
    root = tmp_path / "recipient"
    index = root / "sim-frontend/dist/index.html"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_bytes(raw)  # bytes: the filesystem must not translate newlines
    monkeypatch.setattr(probe, "ROOT", root)
    settings = SimpleNamespace(admin_username="recipient_admin", admin_password="placeholder")
    launcher = {"pid": 4242, "created_ms": 1, "launch_id": "launch-A"}
    served_identity = {**IDENTITY, "pid": 4242, "parent_pid": 11, "launch_id": "launch-A", **(identity or {})}
    _install_transport(monkeypatch, page_bytes=raw if page_bytes is None else page_bytes,
                       identity=served_identity, health=health, page_status=page_status)
    return settings, launcher, raw


@pytest.mark.asyncio
@pytest.mark.parametrize("page", [LF_PAGE, CRLF_PAGE], ids=["lf", "crlf"])
async def test_authenticated_start_accepts_the_exact_packaged_bytes(tmp_path, monkeypatch, page):
    settings, launcher, raw = _prepare(tmp_path, monkeypatch, page)
    result = await probe.authenticated_start(settings, "http://127.0.0.1:18081", IDENTITY, launcher)
    expected = hashlib.sha256(raw).hexdigest()
    assert result["ok"] is True
    assert result["frontend_file_sha256"] == expected
    assert result["frontend_sha256"] == expected  # both fields are the raw-byte digest
    assert result["components"] == {"mysql": "healthy", "llm": "healthy", "knowledge": "healthy"}


@pytest.mark.asyncio
async def test_authenticated_start_rejects_a_single_changed_non_newline_byte(tmp_path, monkeypatch):
    tampered = CRLF_PAGE.replace("工作台".encode("utf-8"), "工作坊".encode("utf-8"))
    settings, launcher, _ = _prepare(tmp_path, monkeypatch, CRLF_PAGE, page_bytes=tampered)
    with pytest.raises(ValueError, match="recipient_static_build_mismatch"):
        await probe.authenticated_start(settings, "http://127.0.0.1:18081", IDENTITY, launcher)


@pytest.mark.asyncio
@pytest.mark.parametrize("served", [CRLF_PAGE + b"\n", b" " + CRLF_PAGE, CRLF_PAGE.replace(b"\r\n", b"\n")],
                         ids=["extra_trailing_newline", "leading_space", "crlf_to_lf_only"])
async def test_authenticated_start_rejects_whitespace_only_differences(tmp_path, monkeypatch, served):
    """No strip and no newline normalisation: a whitespace-only difference is a mismatch."""
    settings, launcher, _ = _prepare(tmp_path, monkeypatch, CRLF_PAGE, page_bytes=served)
    with pytest.raises(ValueError, match="recipient_static_build_mismatch"):
        await probe.authenticated_start(settings, "http://127.0.0.1:18081", IDENTITY, launcher)


@pytest.mark.asyncio
async def test_authenticated_start_rejects_matching_bytes_with_a_non_200_status(tmp_path, monkeypatch):
    settings, launcher, _ = _prepare(tmp_path, monkeypatch, CRLF_PAGE, page_status=503)
    with pytest.raises(ValueError, match="recipient_static_build_mismatch"):
        await probe.authenticated_start(settings, "http://127.0.0.1:18081", IDENTITY, launcher)


@pytest.mark.asyncio
@pytest.mark.parametrize("identity, health, reason", [
    ({**IDENTITY, "device_mode": "sim"}, HEALTHY, "recipient_runtime_mismatch"),
    ({**IDENTITY, "knowledge_provider": "local"}, HEALTHY, "recipient_runtime_mismatch"),
    ({**IDENTITY, "launch_id": "another-launch"}, HEALTHY, "recipient_launch_identity_mismatch"),
    ({**IDENTITY, "pid": 9, "parent_pid": 8}, HEALTHY, "recipient_launch_pid_mismatch"),
    (IDENTITY, {"components": {"mysql": {"status": "healthy"}, "llm": {"status": "healthy"},
                               "knowledge": {"status": "degraded"}}}, "recipient_components_unhealthy"),
])
async def test_authenticated_start_keeps_every_pre_existing_check(tmp_path, monkeypatch, identity, health, reason):
    settings, launcher, _ = _prepare(tmp_path, monkeypatch, CRLF_PAGE, identity=identity, health=health)
    with pytest.raises(ValueError, match=reason):
        await probe.authenticated_start(settings, "http://127.0.0.1:18081", IDENTITY, launcher)


def test_previous_text_comparison_rejected_identical_crlf_bytes(tmp_path):
    """Isolated copy of the old comparison, proving the CRLF case used to fail.

    The old code compared the served body with ``read_text()`` output, which
    translates CRLF to LF, so byte-identical content was reported as a mismatch.
    """
    index = tmp_path / "index.html"
    index.write_bytes(CRLF_PAGE)
    served_text = CRLF_PAGE.decode("utf-8")                    # what httpx returned
    old_expected = index.read_text(encoding="utf-8").strip()   # what the old code compared against
    assert served_text.strip() != old_expected                 # the defect
    assert index.read_bytes() == CRLF_PAGE                     # the bytes are in fact identical
    assert hashlib.sha256(index.read_bytes()).hexdigest() == hashlib.sha256(CRLF_PAGE).hexdigest()
