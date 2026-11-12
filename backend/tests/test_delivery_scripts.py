"""Delivery tools use an actual allowlisted manifest and never touch the source DB."""
import importlib.util
import json
from pathlib import Path
import uuid
import zipfile
from types import SimpleNamespace
import inspect
import sys
import subprocess

import pytest

SPEC = importlib.util.spec_from_file_location("delivery_tool", Path(__file__).resolve().parents[2] / "scripts/delivery.py")
delivery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(delivery)


def write(root, name, data="content"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    return path


def test_isolated_environment_imports_mysql_driver_without_os_account_lookup(tmp_path, monkeypatch):
    # Windows has no pwd module: aiomysql imports getpass.getuser() before any
    # explicit database username is used. Keep this offline import working.
    for name in ("LOGNAME", "USER", "LNAME", "USERNAME"):
        monkeypatch.setenv(name, "developer-account-must-not-leak")
    result = subprocess.run(
        [sys.executable, "-c", "import getpass, aiomysql.connection; print(getpass.getuser()); print(aiomysql.connection.DEFAULT_USER)"],
        env=delivery.isolated_env(tmp_path), cwd=tmp_path, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["delivery-isolated-user", "delivery-isolated-user"]


def test_isolated_environment_inherits_windows_system_drive_but_no_credentials(monkeypatch, tmp_path):
    # Chromium expands %SystemDrive% through the host input method while it
    # starts; the isolated environment must still carry the real drive letter.
    monkeypatch.setenv("SystemDrive", "Q:")
    for name in ("LLM_API_KEY", "DB_PASSWORD", "DEVICE_DEFAULT_PASSWORD", "KNOWLEDGE_API_KEY"):
        monkeypatch.setenv(name, "host-secret-must-not-be-inherited")
    env = delivery.isolated_env(tmp_path)
    assert env["SYSTEMDRIVE"] == "Q:"
    assert env["USERNAME"] == "delivery-isolated-user"
    assert "SystemDrive" not in env
    for name in ("DB_PASSWORD", "DEVICE_DEFAULT_PASSWORD"):
        assert name not in env
    assert env["LLM_API_KEY"] == "" and env["KNOWLEDGE_API_KEY"] == ""


def test_pytest_temp_is_a_fresh_directory_inside_the_disposable_stage(tmp_path):
    stage = tmp_path / "delivery-stage-unit"
    (stage / ".runtime").mkdir(parents=True)
    first, second = delivery.pytest_temp(stage), delivery.pytest_temp(stage)
    assert first.is_dir() and second.is_dir() and first != second
    assert first.parent.resolve() == (stage / ".runtime").resolve()
    assert (stage / ".runtime").resolve() in first.resolve().parents
    # The workspace root next to the project must never receive test directories.
    assert first.parent != stage.parent
    assert not list(stage.parent.glob("ip-sim-pytest-*"))
    assert not list(stage.parent.glob("pytest-*"))


def test_prepare_places_pytest_temp_inside_the_stage_not_beside_the_project():
    source = inspect.getsource(delivery.prepare)
    assert "pytest_temp(stage)" in source
    assert "ip-sim-pytest-" not in source and "root.parent" not in source


def prepared(root):
    for name in delivery.REQUIRED:
        write(root, name, "\ufeff# bootstrap" if name.endswith(".ps1") else "example==1.0" if name.endswith("requirements.lock") else "{}")
    write(root, "sim-frontend/dist/index.html", '<script type="module" src="/assets/app.js"></script>')
    if not (root / "sim-frontend/dist/assets/app.js").exists():
        write(root, "sim-frontend/dist/assets/app.js", "export {}")
    evidence = {"manifest": delivery.manifest(root), "steps": {name: "PASS" for name in delivery.MINIMAL_STEPS}}
    write(root, delivery.EVIDENCE, json.dumps(evidence))


def test_manifest_covers_untracked_code_and_excludes_private_and_test_files(tmp_path):
    for name in ("backend/new_module.py", "sim-frontend/dist/index.html", "backend/requirements.lock"):
        write(tmp_path, name)
    for name in (".env", "backend/.env", ".git/config", ".runtime/data.db", "backend/tests/test_fixture.py",
                 "backend/uploads/private.txt", "sim-frontend/node_modules/private.txt", "backend/local.sqlite"):
        write(tmp_path, name)
    assert set(delivery.manifest(tmp_path)) == {"backend/new_module.py", "sim-frontend/dist/index.html", "backend/requirements.lock"}


def test_scan_reports_location_without_secret_and_skips_nonshipped_fixtures(tmp_path):
    marker = uuid.uuid4().hex
    write(tmp_path, "backend/untracked.py", f'api_key = "{marker}"')
    write(tmp_path, "backend/tests/test_demo.py", f'password = "{marker}"')
    findings = delivery.scan(tmp_path)
    assert findings == [{"path": "backend/untracked.py", "line": 1, "rule": "literal_secret"}]
    assert marker not in json.dumps(findings)


def test_check_is_readonly_and_missing_or_stale_evidence_is_incomplete(tmp_path):
    prepared(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert delivery.gate(tmp_path)[0] == 0
    assert delivery.gate(tmp_path, "full")[0] == 2
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    write(tmp_path, "backend/added.py")
    assert delivery.gate(tmp_path)[0] == 2


def test_full_gate_does_not_accept_manually_marked_steps_without_live_proof(tmp_path):
    prepared(tmp_path)
    evidence = json.loads((tmp_path / delivery.EVIDENCE).read_text())
    evidence["steps"].update({name: "PASS" for name in delivery.FULL_STEPS})
    write(tmp_path, delivery.EVIDENCE, json.dumps(evidence))
    code, rows = delivery.gate(tmp_path, "full")
    assert code == 2
    assert all(row["state"] == "SKIP" for row in rows if row["name"] in delivery.FULL_STEPS)


def test_legacy_live_checklist_is_incomplete_even_when_fresh_and_all_true(tmp_path):
    from datetime import datetime, timezone, timedelta
    prepared(tmp_path)
    inventory = delivery.manifest(tmp_path)
    now = datetime.now(timezone.utc)
    proof = {"schema": 1, "scope": "full_live_acceptance", "source_fingerprint": delivery.code_fingerprint(inventory),
             "started_at": (now - timedelta(minutes=10)).isoformat(),
             "finished_at": (now - timedelta(minutes=1)).isoformat(),
             "checks": {"isolated_mysql": {"state": "PASS", "report_sha256": ["a" * 64], "assertions": {
                 "backup_authenticated": True, "all_business_content_equal": True,
                 "migration_ready": True, "repeat_noop": True}}}}
    def state():
        return next(r["state"] for r in delivery.validate_live_evidence(proof, inventory, now=now) if r["name"] == "isolated_mysql")
    assert state() == "SKIP"
    proof["checks"]["isolated_mysql"]["assertions"]["repeat_noop"] = "true"
    assert state() == "SKIP"
    proof["checks"]["isolated_mysql"]["assertions"]["repeat_noop"] = True
    proof["source_fingerprint"] = "b" * 64
    assert state() == "SKIP"
    proof["source_fingerprint"] = delivery.code_fingerprint(inventory)
    proof["started_at"] = (now - timedelta(days=8)).isoformat()
    assert state() == "SKIP"


def test_live_recording_refuses_changed_prepared_tree(tmp_path):
    prepared(tmp_path)
    report = write(tmp_path, ".runtime/live.json", "{}")
    write(tmp_path, "backend/main.py", "new code")
    with pytest.raises(ValueError, match="changed"):
        delivery.record_live(tmp_path, report)


def test_failed_or_skipped_required_step_cannot_pass(tmp_path):
    prepared(tmp_path)
    evidence = json.loads((tmp_path / delivery.EVIDENCE).read_text())
    for state, code in (("SKIP", 2), ("FAIL", 1)):
        evidence["steps"]["frontend_build"] = state
        write(tmp_path, delivery.EVIDENCE, json.dumps(evidence))
        assert delivery.gate(tmp_path)[0] == code


def test_export_includes_dist_locks_inventory_but_not_private_data(tmp_path):
    asset = "sim-frontend/dist/assets/app.js"
    write(tmp_path, asset, "document.body.dataset.ready = 'yes'")
    prepared(tmp_path)
    write(tmp_path, ".env", uuid.uuid4().hex)
    write(tmp_path, ".runtime/private.json")
    archive = delivery.export(tmp_path, tmp_path / ".runtime/delivery", "minimal")
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert delivery.REQUIRED <= names
        assert "DELIVERY-MANIFEST.json" in names
        assert asset in names
        assert "dataset.ready" in bundle.read(asset).decode()
        assert not any(name.startswith((".env", ".runtime", ".git")) for name in names if name != ".env.example")


def test_stage_redaction_preserves_source_and_body_and_records_no_values(tmp_path):
    marker = uuid.uuid4().hex
    source = tmp_path / "source"
    stage = tmp_path / "stage"
    content = f'# Sample\napi_key = "{marker}"\n-----BEGIN PRIVATE KEY-----\n{marker}\n-----END PRIVATE KEY-----\nKeep body.\n'
    write(source, "docs/guides/sample.md", content)
    write(stage, "docs/guides/sample.md", content)
    delivery.redact_documents(stage)
    assert (source / "docs/guides/sample.md").read_text() == content
    assert marker not in (stage / "docs/guides/sample.md").read_text()
    assert "Keep body." in (stage / "docs/guides/sample.md").read_text()
    assert not delivery.scan(stage)
    assert marker not in (stage / "DELIVERY-REDACTIONS.json").read_text()


def test_business_source_is_never_auto_redacted(tmp_path):
    marker = uuid.uuid4().hex
    write(tmp_path, "backend/unsafe.py", f'password = "{marker}"')
    delivery.redact_documents(tmp_path)
    assert marker in (tmp_path / "backend/unsafe.py").read_text()
    assert delivery.scan(tmp_path)


def test_incomplete_private_key_block_remains_blocked(tmp_path):
    marker = uuid.uuid4().hex
    write(tmp_path, "knowledge/corpus/incomplete.md", "-----BEGIN PRIVATE KEY-----\n" + marker)
    delivery.redact_documents(tmp_path)
    assert delivery.scan(tmp_path)


def test_export_rejects_change_between_gate_and_archive(tmp_path, monkeypatch):
    prepared(tmp_path)
    original = delivery.gate
    def change_after_gate(root, mode):
        result = original(root, mode)
        write(root, "backend/main.py", "changed after verification")
        return result
    monkeypatch.setattr(delivery, "gate", change_after_gate)
    with pytest.raises(ValueError):
        delivery.export(tmp_path, tmp_path / ".runtime/delivery", "minimal")
    assert not list((tmp_path / ".runtime/delivery").glob("*.zip"))


def test_index_referencing_missing_asset_blocks_delivery(tmp_path):
    prepared(tmp_path)
    write(tmp_path, "sim-frontend/dist/index.html", '<script type="module" src="/assets/missing.js"></script>')
    code, rows = delivery.gate(tmp_path)
    assert code == 1
    assert next(row for row in rows if row["name"] == "frontend_assets")["state"] == "FAIL"


def test_browser_evidence_rejects_skips_and_another_tree(tmp_path):
    prepared(tmp_path)
    evidence = json.loads((tmp_path / delivery.EVIDENCE).read_text())
    evidence["browser_inventory"] = ["case-one::"]
    write(tmp_path, delivery.EVIDENCE, json.dumps(evidence))
    report = {"config": {"rootDir": str(tmp_path / "sim-frontend/e2e")},
              "stats": {"expected": 1, "unexpected": 0, "flaky": 0, "skipped": 1}, "errors": [],
              "suites": [{"specs": [{"id": "case-one", "tests": [{"projectId": "", "status": "expected",
                                            "results": [{"status": "passed"}]}]}]}]}
    path = write(tmp_path, ".runtime/browser.json", json.dumps(report))
    assert delivery.record_browser(tmp_path, path) == 1
    assert delivery.gate(tmp_path)[0] == 1
    report["stats"]["skipped"] = 0
    write(tmp_path, ".runtime/browser.json", json.dumps(report))
    assert delivery.record_browser(tmp_path, path) == 0
    assert delivery.gate(tmp_path)[0] == 0
    report["config"]["rootDir"] = str(tmp_path.parent / "other")
    write(tmp_path, ".runtime/browser.json", json.dumps(report))
    with pytest.raises(ValueError, match="does not belong"):
        delivery.record_browser(tmp_path, path)


def test_browser_subset_cannot_claim_full_acceptance(tmp_path):
    prepared(tmp_path)
    evidence = json.loads((tmp_path / delivery.EVIDENCE).read_text())
    evidence["browser_inventory"] = ["case-one::", "case-two::"]
    write(tmp_path, delivery.EVIDENCE, json.dumps(evidence))
    report = {"config": {"rootDir": str(tmp_path / "sim-frontend/e2e")},
              "stats": {"expected": 1, "unexpected": 0, "flaky": 0, "skipped": 0}, "errors": [],
              "suites": [{"specs": [{"id": "case-one", "tests": [{"projectId": "", "status": "expected",
                                            "results": [{"status": "passed"}]}]}]}]}
    path = write(tmp_path, ".runtime/browser.json", json.dumps(report))
    assert delivery.record_browser(tmp_path, path) == 1
    assert delivery.gate(tmp_path)[0] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["bootstrap_local.py", "bootstrap_local_sync.py"])
async def test_direct_bootstrap_without_admin_password_stops_before_database(filename, monkeypatch, capsys):
    path = Path(__file__).resolve().parents[1] / "scripts" / filename
    spec = importlib.util.spec_from_file_location("test_" + filename[:-3], path)
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(bootstrap, "get_settings", lambda: SimpleNamespace(admin_password="", admin_username="admin"))
    def forbidden(*args, **kwargs):
        raise AssertionError("database preparation must not run without explicit admin credentials")
    monkeypatch.setattr(bootstrap, "prepare_database", forbidden)
    monkeypatch.setattr(bootstrap, "resolve_database_url", lambda _settings: "sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(sys, "argv", [filename])
    result = await bootstrap.main() if inspect.iscoroutinefunction(bootstrap.main) else bootstrap.main()
    assert result == 1
    output = capsys.readouterr().out
    assert "ADMIN_PASSWORD" in output
    assert "login:" not in output
