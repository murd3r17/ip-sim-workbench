"""Full setup is exercised with temporary profiles and fake authenticated services."""
import importlib.util
import json
from pathlib import Path
import subprocess
import shutil
import socket
import sys
import uuid

import pytest


PATH = Path(__file__).resolve().parents[1] / "scripts/full_preflight.py"


def tool():
    spec = importlib.util.spec_from_file_location("full_preflight_test", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def profile():
    from cryptography.fernet import Fernet
    return dict(DB_BACKEND="mysql", DB_HOST="db.example.invalid", DB_PORT="3306", DB_NAME="workbench",
                DB_USER="owner", DB_PASSWORD=uuid.uuid4().hex, DEVICE_MODE="ssh",
                DEVICE_DEFAULT_USERNAME="operator", DEVICE_DEFAULT_PASSWORD=uuid.uuid4().hex,
                JWT_SECRET_KEY=uuid.uuid4().hex, FERNET_KEY=Fernet.generate_key().decode(),
                ADMIN_PASSWORD=uuid.uuid4().hex, LLM_PROVIDER="openai_compatible", LLM_MODEL="deepseek-chat",
                LLM_BASE_URL="https://api.deepseek.com/v1", LLM_API_KEY=uuid.uuid4().hex,
                KNOWLEDGE_PROVIDER="anythingllm", KNOWLEDGE_BASE_URL="http://kb.example.invalid:3001",
                KNOWLEDGE_WORKSPACE_SLUG="ip-ops-kb", KNOWLEDGE_API_KEY=uuid.uuid4().hex)


def write_profile(root, values):
    root.mkdir(parents=True, exist_ok=True)
    (root / ".env").write_text("\n".join(k + "=" + v for k, v in values.items()), encoding="utf-8")


def test_full_rejects_sim_sqlite_and_placeholders_before_network(tmp_path, monkeypatch):
    m = tool()
    values = profile()
    values.update(DEVICE_MODE="sim", DB_BACKEND="sqlite", LLM_API_KEY="<set-in-local-.env>")
    write_profile(tmp_path, values)
    monkeypatch.setattr(m, "probe_mysql", lambda *_: pytest.fail("invalid profile must not touch DB"))
    report = m.preflight(tmp_path, environ={})
    assert not report["ok"]
    assert {"DEVICE_MODE", "DB_BACKEND", "LLM_API_KEY"} <= {x["key"] for x in report["issues"]}
    assert values["DB_PASSWORD"] not in json.dumps(report)


def test_settings_priority_is_environment_then_backend_then_root(tmp_path):
    m = tool()
    write_profile(tmp_path, profile())
    write_profile(tmp_path / "backend", {"DEVICE_MODE": "sim", "DB_HOST": "backend.invalid"})
    config = m.load_config(tmp_path, {"device_mode": "ssh", "DB_HOST": "process.invalid"})
    assert config["DEVICE_MODE"] == "ssh"
    assert config["DB_HOST"] == "process.invalid"
    assert m.load_config(tmp_path, {})["DEVICE_MODE"] == "sim"


def test_preflight_uses_application_whitespace_override_fallback(tmp_path, monkeypatch):
    m = tool()
    values = profile()
    write_profile(tmp_path, values)
    monkeypatch.setattr(m, "probe_mysql", lambda *_: {"state": "ready", "overrides": {
        "llm.model": "   ", "llm.api_key": " \t", "llm.base_url": " "}})
    seen = []
    monkeypatch.setattr(m, "probe_llm", lambda c: seen.append(c.copy()) or {})
    monkeypatch.setattr(m, "probe_knowledge", lambda *_: {})
    assert m.preflight(tmp_path, environ={})["ok"]
    assert seen[0]["LLM_MODEL"] == values["LLM_MODEL"]
    assert seen[0]["LLM_API_KEY"] == values["LLM_API_KEY"]


@pytest.mark.parametrize("prefix", ["", "\ufeff"])
def test_config_validation_stdin_is_local_and_does_not_echo_values(tmp_path, monkeypatch, capsys, prefix):
    import io
    m = tool()
    values = profile()
    values["DB_PORT"] = "999999"
    monkeypatch.setattr(sys, "stdin", io.StringIO(prefix + json.dumps(values)))
    monkeypatch.setattr(m, "preflight", lambda *_: pytest.fail("validation must not probe services"))
    assert m.main(["--validate-config-stdin"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert "DB_PORT" in {x["key"] for x in report["issues"]}
    assert values["DB_PASSWORD"] not in json.dumps(report)


@pytest.mark.parametrize("bad", [[], {"DB_PORT": ["not-a-string"]}, None])
def test_config_validation_stdin_malformed_payload_fixed_error(bad, monkeypatch, capsys):
    import io
    m = tool()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(bad)))
    assert m.main(["--validate-config-stdin"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["issues"][0]["key"] == "CONFIG_INPUT"


def test_empty_database_is_allowed_only_for_explicit_prepare_and_order_is_readonly(tmp_path, monkeypatch):
    m = tool()
    write_profile(tmp_path, profile())
    calls = []
    monkeypatch.setattr(m, "probe_mysql", lambda *_: calls.append("mysql_auth") or {"state": "empty", "overrides": {}})
    monkeypatch.setattr(m, "probe_llm", lambda *_: calls.append("llm_auth") or {"model": "deepseek-chat"})
    monkeypatch.setattr(m, "probe_knowledge", lambda *_: calls.append("knowledge_auth") or {"documents": 135})
    assert m.preflight(tmp_path, phase="prepare", environ={})["ok"]
    assert calls == ["mysql_auth", "llm_auth", "knowledge_auth"]
    calls.clear()
    report = m.preflight(tmp_path, phase="start", environ={})
    assert not report["ok"]
    assert calls == ["mysql_auth"]


def test_legacy_requires_backup_and_unknown_schema_never_proceeds(tmp_path, monkeypatch):
    m = tool()
    write_profile(tmp_path, profile())
    monkeypatch.setattr(m, "probe_mysql", lambda *_: {"state": "legacy", "overrides": {}})
    monkeypatch.setattr(m, "probe_llm", lambda *_: {})
    monkeypatch.setattr(m, "probe_knowledge", lambda *_: {})
    assert not m.preflight(tmp_path, phase="prepare", environ={})["ok"]
    backup = tmp_path / "export.sql"
    backup.write_text("isolated-backup-fixture")
    assert m.preflight(tmp_path, phase="prepare", backup_file=backup, environ={})["ok"]
    monkeypatch.setattr(m, "probe_mysql", lambda *_: {"state": "unknown", "overrides": {}})
    assert not m.preflight(tmp_path, phase="prepare", backup_file=backup, environ={})["ok"]


def test_effective_database_model_override_is_checked_and_failures_hide_values(tmp_path, monkeypatch):
    m = tool()
    values = profile()
    write_profile(tmp_path, values)
    monkeypatch.setattr(m, "probe_mysql", lambda *_: {"state": "ready", "overrides": {"llm.provider": "ollama"}})
    monkeypatch.setattr(m, "probe_llm", lambda *_: pytest.fail("wrong effective provider must not be called"))
    report = m.preflight(tmp_path, environ={})
    assert not report["ok"]
    monkeypatch.setattr(m, "probe_mysql", lambda *_: (_ for _ in ()).throw(RuntimeError(values["DB_PASSWORD"])))
    report = m.preflight(tmp_path, environ={})
    assert not report["ok"] and values["DB_PASSWORD"] not in json.dumps(report)


def test_full_profile_moves_without_developer_runtime(tmp_path, monkeypatch):
    m = tool()
    for root in [tmp_path / "first", tmp_path / "different root 中文"]:
        write_profile(root, profile())
        monkeypatch.setattr(m, "probe_mysql", lambda *_: {"state": "ready", "overrides": {}})
        monkeypatch.setattr(m, "probe_llm", lambda *_: {})
        monkeypatch.setattr(m, "probe_knowledge", lambda *_: {})
        assert m.preflight(root, environ={})["ok"]


def test_llm_can_use_complete_database_override_with_empty_environment_key(tmp_path, monkeypatch):
    m = tool()
    values = profile()
    override_key = values.pop("LLM_API_KEY")
    write_profile(tmp_path, values)
    monkeypatch.setattr(m, "probe_mysql", lambda *_: {"state": "ready", "overrides": {"llm.api_key": override_key}})
    seen = []
    monkeypatch.setattr(m, "probe_llm", lambda c: seen.append(c["LLM_API_KEY"]) or {})
    monkeypatch.setattr(m, "probe_knowledge", lambda *_: {})
    assert m.preflight(tmp_path, environ={})["ok"]
    assert seen == [override_key]


def ps(script, cwd):
    if not shutil.which("powershell.exe"):
        pytest.skip("Windows PowerShell integration")
    script = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; " + script
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                            cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    return result.stdout


def wizard_command(root, private_marker, answers=None, *, catch=False, extra=""):
    path = PATH.parents[2] / "scripts/configure-full.ps1"
    script = r'''
    $answers=ConvertFrom-Json -InputObject '__ANSWERS__'
    function Read-Host {
      param([string]$Prompt,[switch]$AsSecureString)
      Write-Host $Prompt
      if ($AsSecureString) {
        $secure=New-Object System.Security.SecureString
        foreach ($character in '__PRIVATE__'.ToCharArray()) { $secure.AppendChar($character) }
        return $secure
      }
      foreach ($entry in $answers.PSObject.Properties) {
        if ($Prompt -like $entry.Name) {
          if ($entry.Value -eq '__INTERRUPT__') { throw 'fixture interruption' }
          return $entry.Value
        }
      }
      if ($Prompt -like '*SSH*') { return 'operator' }
      return ''
    }
    __CALL__
    '''
    call = "& '__SCRIPT__' -Root '__ROOT__' -Python '__PYTHON__' " + extra
    if catch:
        call = "try { " + call + " } catch { Write-Output $_.Exception.Message }"
    script = script.replace("__CALL__", call)
    for key, value in {"__SCRIPT__": str(path), "__ROOT__": str(root), "__PYTHON__": sys.executable,
                       "__PRIVATE__": private_marker, "__ANSWERS__": json.dumps(answers or {}, ensure_ascii=False)}.items():
        script = script.replace(key, value.replace("'", "''"))
    return script


@pytest.mark.parametrize("suffix", ["", "中文π"])
def test_wizard_interruption_resumes_nonsecret_progress_but_not_secrets(tmp_path, suffix):
    from dotenv import dotenv_values
    root = tmp_path / "recipient space"
    root.mkdir()
    marker = uuid.uuid4().hex + suffix
    ps(wizard_command(root, marker, {"MySQL 主机*": "receiver-db.invalid", "MySQL 端口*": "__INTERRUPT__"}, catch=True), tmp_path)
    draft = root / ".runtime/setup/full-draft.json"
    assert json.loads(draft.read_text(encoding="utf-8"))["values"] == {"DB_HOST": "receiver-db.invalid"}
    assert not (root / ".env").exists()
    output = ps(wizard_command(root, marker), tmp_path)
    assert "已恢复非秘密填写进度" in output
    assert dotenv_values(root / ".env")["DB_HOST"] == "receiver-db.invalid"
    assert marker not in output and marker not in draft.read_text(encoding="utf-8")
    assert not any("PASSWORD" in k or "API_KEY" in k or "FERNET" in k for k in json.loads(draft.read_text(encoding="utf-8"))["values"])


def test_wizard_invalid_config_does_not_create_env_and_can_correct_draft(tmp_path):
    from dotenv import dotenv_values
    marker = uuid.uuid4().hex
    output = ps(wizard_command(tmp_path, marker, {"MySQL 端口*": "999999"}, catch=True), tmp_path)
    assert "DB_PORT" in output and "未写入 .env" in output
    assert not (tmp_path / ".env").exists()
    ps(wizard_command(tmp_path, marker, {"MySQL 端口*": "3306"}), tmp_path)
    assert dotenv_values(tmp_path / ".env")["DB_PORT"] == "3306"


def test_wizard_check_only_keeps_existing_invalid_config_and_never_prompts(tmp_path):
    marker = uuid.uuid4().hex
    write_profile(tmp_path, {"PRIVATE": marker})
    before = (tmp_path / ".env").read_bytes()
    output = ps(wizard_command(tmp_path, marker, {"*": "__INTERRUPT__"}, catch=True, extra="-CheckOnly"), tmp_path)
    assert "配置尚未完整" in output and "fixture interruption" not in output
    assert (tmp_path / ".env").read_bytes() == before
    assert marker not in output


def test_wizard_does_not_persist_or_echo_endpoint_embedded_credentials(tmp_path):
    marker = uuid.uuid4().hex
    output = ps(wizard_command(tmp_path, marker, {"DeepSeek 兼容*": "https://user:" + marker + "@api.deepseek.com/v1"}, catch=True), tmp_path)
    assert "LLM_BASE_URL" in output
    assert not (tmp_path / ".env").exists()
    assert marker not in output
    assert marker not in (tmp_path / ".runtime/setup/full-draft.json").read_text(encoding="utf-8")


def test_wizard_untrusted_draft_does_not_restore_secrets_or_url_tokens(tmp_path):
    marker = uuid.uuid4().hex
    draft = tmp_path / ".runtime/setup/full-draft.json"
    draft.parent.mkdir(parents=True)
    draft.write_text(json.dumps({"schema": 1, "values": {
        "DB_HOST": "receiver-db.invalid", "DB_PASSWORD": marker,
        "LLM_BASE_URL": "https://api.deepseek.com/v1?token=" + marker,
        "LLM_API_KEY": marker}}), encoding="utf-8")
    output = ps(wizard_command(tmp_path, uuid.uuid4().hex), tmp_path)
    assert marker not in output and marker not in draft.read_text(encoding="utf-8")
    from dotenv import dotenv_values
    config = dotenv_values(tmp_path / ".env")
    assert config["LLM_BASE_URL"] == "https://api.deepseek.com/v1"
    assert config["DB_HOST"] == "receiver-db.invalid"


def test_cold_model_registry_resolves_trust_foreign_keys_without_test_collection_imports(tmp_path):
    code = '''
from core.config import Settings
Settings.model_config['env_file'] = None
from core.database import Base, _import_all_models
_import_all_models()
names = {table.name for table in Base.metadata.sorted_tables}
assert {'environment_profile', 'read_only_observation', 'training_session'} <= names
print('cold_registry_complete')
'''
    result = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=PATH.parents[1],
                            capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
    assert "cold_registry_complete" in result.stdout


@pytest.mark.parametrize("preflight_exit,expected", [(0, ["full_preflight.py", "bootstrap_local.py"]), (1, ["full_preflight.py"])])
def test_real_powershell_preparation_function_preserves_order_and_blocks_failure(tmp_path, preflight_exit, expected):
    path = PATH.parents[2] / "scripts/bootstrap-local.ps1"
    # Extract the actual function AST without executing the script's installer.
    script = r'''
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $errors=$null; $tokens=$null
    $ast=[System.Management.Automation.Language.Parser]::ParseFile('__SOURCE__',[ref]$tokens,[ref]$errors)
    $fn=$ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Initialize-WorkbenchDatabase'},$true)
    Invoke-Expression $fn.Extent.Text
    $script:calls=@()
    function Fake-Python { $script:calls += ,@($args); $global:LASTEXITCODE=if($args[0] -like '*full_preflight.py') { __EXIT__ } else { 0 } }
    try { Initialize-WorkbenchDatabase 'full' 'Fake-Python' 'C:\receiver space\backend' 'C:\receiver space' '' 'C:\backups\verified.sql' } catch { }
    ConvertTo-Json -InputObject $script:calls -Compress -Depth 5
    '''.replace("__SOURCE__", str(path).replace("'", "''")).replace("__EXIT__", str(preflight_exit))
    calls = json.loads(ps(script, tmp_path).strip())
    assert [Path(args[0]).name for args in calls] == expected
    assert calls[0][1:5] == ["--root", "C:\\receiver space", "--phase", "prepare"]
    for args in calls:
        assert args[-2:] == ["--backup-file", "C:\\backups\\verified.sql"]


def test_first_configure_never_overwrites_existing_env_or_prompts(tmp_path):
    path = PATH.parents[2] / "scripts/configure-full.ps1"
    write_profile(tmp_path, {"PRIVATE": uuid.uuid4().hex})
    before = (tmp_path / ".env").read_bytes()
    ps("& '" + str(path).replace("'", "''") + "' -Root '" + str(tmp_path).replace("'", "''") + "'", tmp_path)
    assert (tmp_path / ".env").read_bytes() == before


@pytest.mark.parametrize("vision_model", ["", "receiver-vision-model"])
def test_first_configure_writes_private_portable_profile_without_echo(tmp_path, vision_model):
    from dotenv import dotenv_values
    path = PATH.parents[2] / "scripts/configure-full.ps1"
    marker = uuid.uuid4().hex + '\\"$'
    script = r'''
    function Read-Host {
      param([string]$Prompt, [switch]$AsSecureString)
      if ($AsSecureString) {
        $secure = New-Object System.Security.SecureString
        foreach ($character in '__PRIVATE__'.ToCharArray()) { $secure.AppendChar($character) }
        $secure.MakeReadOnly()
        return $secure
      }
      if ($Prompt -like '*SSH*') { return 'operator' }
      if ($Prompt -like '视觉模型名 LLM_VISION_MODEL*') { return '__VISION__' }
      return ''
    }
    & '__SCRIPT__' -Root '__ROOT__' -Python '__PYTHON__'
    '''
    for key, value in {"__PRIVATE__": marker, "__SCRIPT__": str(path), "__ROOT__": str(tmp_path), "__PYTHON__": sys.executable, "__VISION__": vision_model}.items():
        script = script.replace(key, value.replace("'", "''"))
    output = ps(script, tmp_path)
    config = dotenv_values(tmp_path / ".env")
    assert marker not in output
    assert config["DB_PASSWORD"] == marker
    assert config["DEVICE_MODE"] == "ssh" and config["DB_BACKEND"] == "mysql"
    assert config["LLM_BASE_URL"] == "https://api.deepseek.com/v1"
    assert config["LLM_VISION_MODEL"] == vision_model
    assert config["DEPLOY_SIMULATE_ONLY"] == "true"
    assert not (tmp_path / ".runtime/mysql-server").exists()


def test_full_start_refuses_occupied_port_before_any_authentication(tmp_path, monkeypatch):
    from scripts import full_lifecycle as lifecycle

    def unexpected(*args, **kwargs):
        pytest.fail("occupied port must stop before preflight")

    monkeypatch.setattr(lifecycle, "preflight", unexpected)
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        with pytest.raises(ValueError, match="已被占用"):
            lifecycle.start(tmp_path, tmp_path / "receipt.json", "127.0.0.1", server.getsockname()[1])
    assert not (tmp_path / "receipt.json").exists()


def test_full_stop_refuses_foreign_receipt_and_recycled_pid(tmp_path, monkeypatch):
    import hashlib
    import os
    from scripts import full_lifecycle as lifecycle

    receipt = lifecycle.receipt_path(tmp_path, None, 8000)
    receipt.parent.mkdir()
    data = {"schema": lifecycle.SCHEMA, "root": str(tmp_path), "receipt": str(receipt),
            "state": "READY", "host": "127.0.0.1", "port": 8000, "launch_id": uuid.uuid4().hex,
            "pid": 123, "runtime_pid": 123, "processes": [],
            "runtime_binding": {"root_fingerprint": hashlib.sha256(os.path.normcase(str(tmp_path)).encode()).hexdigest(),
                                "database_fingerprint": "a" * 64}}
    record = {"pid": 123, "created_ticks": 50, "executable": "python.exe", "parent_pid": 42,
              "command": "python.exe " + subprocess.list2cmdline(lifecycle.command_tail(tmp_path, receipt, data))}
    data["processes"] = [record]
    lifecycle.checkpoint(receipt, data)
    foreign = receipt.with_name("copied.json")
    lifecycle.checkpoint(foreign, data)
    monkeypatch.setattr(lifecycle.owner, "snapshot", lambda pid: {**record, "created_ticks": 51})
    monkeypatch.setattr(lifecycle.owner, "stop_verified", lambda *args: pytest.fail("termination must be refused"))
    with pytest.raises(ValueError, match="外来"):
        lifecycle.stop(tmp_path, foreign)
    with pytest.raises(ValueError, match="PID"):
        lifecycle.stop(tmp_path, receipt)
    assert lifecycle.read_receipt(tmp_path, receipt)["state"] == "READY"


def test_authenticated_http_probes_require_real_response_and_workspace(tmp_path, monkeypatch):
    import httpx
    m = tool()
    values = profile()
    original = httpx.Client
    seen = []
    def handler(request):
        seen.append((request.method, request.url.path))
        assert request.headers["Authorization"].startswith("Bearer ")
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
        return httpx.Response(200, json={"workspace": [{"slug": "ip-ops-kb", "documents": [{}]}]})
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    assert m.probe_llm(values) == {"authenticated_generation": True}
    assert m.probe_knowledge(values)["documents"] == 1
    assert seen == [("POST", "/v1/chat/completions"), ("GET", "/api/v1/workspace/ip-ops-kb")]
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})), **kwargs))
    with pytest.raises(ValueError):
        m.probe_llm(values)
    with pytest.raises(ValueError):
        m.probe_knowledge(values)


def test_database_probe_only_reads_even_when_empty(tmp_path, monkeypatch):
    import sqlalchemy
    m = tool()
    engine = sqlalchemy.create_engine("sqlite:///:memory:")
    commands = []
    sqlalchemy.event.listen(engine, "before_cursor_execute", lambda c, cur, statement, *args: commands.append(statement))
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **kw: engine)
    assert m.probe_mysql(profile())["state"] == "empty"
    assert commands and all(sql.lstrip().upper().startswith(("SELECT", "PRAGMA")) for sql in commands)


@pytest.mark.parametrize("mismatch", [None, "pid", "root_fingerprint", "database_fingerprint", "device_mode", "launch_id", "empty_nonce", "redirector"])
def test_started_backend_identity_is_bound_to_root_database_mode_and_pid(tmp_path, monkeypatch, mismatch):
    import httpx
    from core.runtime_identity import runtime_identity
    from types import SimpleNamespace
    m = tool()
    values = profile()
    write_profile(tmp_path, values)
    config = m.load_config(tmp_path, {})
    settings = SimpleNamespace(**{key.lower(): value for key, value in config.items() if key.startswith("DB_") or key in {"DEVICE_MODE", "KNOWLEDGE_PROVIDER"}})
    settings.db_port = int(settings.db_port)
    settings.deploy_simulate_only = True
    actual = runtime_identity(settings, root=tmp_path)
    actual["pid"] = 1234
    nonce = uuid.uuid4().hex
    actual["launch_id"] = nonce
    actual["parent_pid"] = 100
    if mismatch == "redirector":
        actual.update(pid=5678, parent_pid=1234)
    elif mismatch and mismatch != "empty_nonce":
        actual[mismatch] = "mismatched"
    token = uuid.uuid4().hex
    def handler(request):
        if request.url.path.endswith("/login"):
            assert json.loads(request.content)["password"] == values["ADMIN_PASSWORD"]
            return httpx.Response(200, json={"access_token": token})
        assert request.headers["Authorization"] == "Bearer " + token
        return httpx.Response(200, json=actual)
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    report = m.verify_backend(tmp_path, "http://127.0.0.1:18080", 1234, environ={}, expected_launch_id="" if mismatch == "empty_nonce" else nonce)
    assert report["ok"] is (mismatch in {None, "redirector"})
    assert token not in json.dumps(report) and values["ADMIN_PASSWORD"] not in json.dumps(report)
