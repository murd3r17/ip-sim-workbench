"""The acceptance producer must contact only its own local fault endpoints."""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock
import uuid

from scripts import verify_live_dependency_faults as probe


def test_fault_summary_never_accepts_a_false_success():
    components = {name: {"ok": True} for name in ("database", "llm", "knowledge", "ssh")}
    assert probe.successful(components, secrets_clean=True, closed=True)
    components["llm"]["ok"] = False
    assert not probe.successful(components, secrets_clean=True, closed=True)


def test_settings_are_init_only_and_cannot_use_real_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_BASE_URL", "https://not-allowed.example")
    monkeypatch.setenv("DB_URL", "mysql+aiomysql://not-allowed.example/production")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "forbidden-fallback")
    settings = probe.isolated_settings(12345, 12346, tmp_path, {name: "fixture-secret" for name in ("database", "llm", "knowledge", "ssh")})
    assert settings.llm_base_url == "http://127.0.0.1:12345"
    assert settings.db_host == "127.0.0.1" and settings.db_port == 12346 and settings.db_url == ""
    assert settings.llm_fallback_model == "" and settings.deploy_simulate_only


def test_jwt_secret_is_generated_per_configuration_and_ignores_environment(monkeypatch, tmp_path):
    values = [uuid.uuid4().hex + uuid.uuid4().hex for _ in range(2)]
    random_key = Mock(side_effect=values)
    monkeypatch.setattr(probe.secrets, "token_urlsafe", random_key)
    monkeypatch.setenv("JWT_SECRET_KEY", "environment-must-not-be-used")
    markers = {name: "fixture-secret" for name in ("database", "llm", "knowledge", "ssh")}
    first = probe.isolated_settings(12345, 12346, tmp_path, markers)
    second = probe.isolated_settings(12345, 12346, tmp_path, markers)
    assert [first.jwt_secret_key, second.jwt_secret_key] == values
    assert first.jwt_secret_key != second.jwt_secret_key
    assert random_key.call_count == 2
    assert all(call.args == (32,) for call in random_key.call_args_list)


def test_actual_local_fault_injection_producer(tmp_path):
    report = tmp_path / "faults.json"
    script = Path(probe.__file__)
    result = subprocess.run([sys.executable, str(script), "--report", str(report)], capture_output=True,
                            text=True, encoding="utf-8", timeout=90)
    assert report.is_file(), result.stderr[-500:]
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["scope"] == "isolated_dependency_fault_injection"
    assert data["isolation"]["configuration"] == "init_only"
    assert data["isolation"]["external_targets"] == 0
    assert data["network_guard"]["blocked_attempts"] == 0
    assert data["network_guard"]["connection_or_resolution_attempts"] > 0
    assert data["resources_closed"]
    assert data["components"]["database"]["health_http_status"] == 503
    assert data["components"]["database"]["mysql_status"] == "unhealthy"
    assert data["components"]["llm"]["stream_done_count"] == 1
    assert data["components"]["llm"]["application_generate_status"] == "degraded"
    assert data["components"]["knowledge"]["ask_sources_count"] == 0
    assert data["components"]["knowledge"]["ask_answer_characters"] == 0
    assert data["components"]["ssh"]["lock_reacquired"]
    assert data["secrets_clean"]
    assert data["synthetic_markers_checked"] == 5  # Includes the generated JWT key.
    assert data["ok"], data["components"]
    assert result.returncode == 0, result.stderr[-500:]
    assert "FAULT_SECRET_" not in result.stdout + result.stderr + report.read_text(encoding="utf-8")
