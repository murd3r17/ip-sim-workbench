"""Live-verification gates are tested without loading .env or making I/O calls."""
import ast
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
import uuid

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/verify_full_stack.py"


def module():
    # Old verifier loaded .env at import; do not execute those calls in the red phase.
    tree = ast.parse(PATH.read_text(encoding="utf-8"))
    tree.body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                 and isinstance(n.value.func, ast.Name) and n.value.func.id == "load_dotenv")]
    m = ModuleType("full_stack_under_test")
    m.__file__ = str(PATH)
    exec(compile(tree, str(PATH), "exec"), m.__dict__)
    return m


def settings():
    return SimpleNamespace(admin_username="admin", admin_password="", db_backend="mysql", db_url="", device_mode="ssh")


def facts():
    return {"identity": {"schema": 1, "database_fingerprint": "one", "root_fingerprint": "root", "device_mode": "ssh", "deploy_simulate_only": False, "knowledge_provider": "anythingllm", "pid": 1},
            "devices": [{"id": i, "hostname": f"node-{i}", "mgmt_ip": f"192.0.2.{i}", "ssh_port": 22, "model": "NE40E"} for i in range(1, 4)],
            "llm_model": "deepseek-chat", "llm_source": "env", "max_ai_log_id": 0, "max_audit_id": 0}


ENDPOINTS = "192.0.2.1:22,192.0.2.2:22,192.0.2.3:22"


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["missing_password", "login_failed", "wrong_database", "db_failed", "two_targets", "duplicate_targets"])
async def test_preconditions_stop_before_any_business_api_write(monkeypatch, reason):
    m = module()
    config = settings()
    config.admin_password = "" if reason == "missing_password" else "fixture-not-a-real-credential"
    async def read(_):
        if reason == "db_failed":
            raise RuntimeError("must not continue")
        return facts()
    monkeypatch.setattr(m, "db_facts", read)
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url))
        if url.endswith("/auth/login"):
            return (401, {}) if reason == "login_failed" else (200, {"access_token": "fixture-token"})
        if url.endswith("/system/runtime-identity"):
            return 200, {**facts()["identity"], "database_fingerprint": "other"}
        pytest.fail("unexpected request after failed prerequisites")
    monkeypatch.setattr(m, "http_json", request)
    endpoints = "192.0.2.1:22,192.0.2.2:22" if reason == "two_targets" else "192.0.2.1:22,192.0.2.1:22,192.0.2.3:22" if reason == "duplicate_targets" else ENDPOINTS
    report = await m.verify(config, endpoints, "http://127.0.0.1:18080/api/v1")
    assert report["verdict"]["ok"] is False
    assert all(method == "GET" or url.endswith("/auth/login") for method, url in calls)
    assert "fixture-token" not in json.dumps(report)


def test_sse_requires_successful_terminal_event_and_real_nonfallback_content():
    m = module()
    good = [{"type": "token", "text": "设备检查回答"}, {"type": "done", "status": "ok"}]
    assert m.stream_succeeded(good)
    for events in [good[:-1], [{"type": "done", "status": "ok"}],
                   [{"type": "token", "text": "当前AI服务不可用"}, good[-1]],
                   [*good[:-1], {"type": "error"}, good[-1]],
                   [good[0], {"type": "done", "status": "failed"}],
                   [*good, {"type": "token", "text": "after completion"}]]:
        assert not m.stream_succeeded(events)


def test_training_score_does_not_accept_fabricated_grade():
    m = module()
    score = {"score": None, "passed": None, "detail": {"verification_status": "unverified", "reference_score": 50}}
    assert m.honest_score(score)
    assert not m.honest_score({**score, "score": 100, "passed": True})
    assert not m.honest_score({"detail": {"verification_status": "unverified"}})


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "inventory", "missing_log", "failed_sse", "wrong_tool_user", "degraded_hint", "fallback_report", "fabricated_score"])
async def test_complete_api_pipeline_retains_evidence_and_never_turns_fallbacks_green(monkeypatch, failure):
    m = module()
    config = settings()
    config.admin_password = uuid.uuid4().hex
    token = uuid.uuid4().hex
    logs, calls = [], []
    async def read(_):
        return facts()
    async def audits(_, after_id):
        assert after_id == 0
        return [{"id": 8, "user_id": 999 if failure == "wrong_tool_user" else 4, "result": "success", "detail": json.dumps({"device_id": 1, "command": "display version"})}]
    monkeypatch.setattr(m, "db_facts", read)
    monkeypatch.setattr(m, "tool_audits", audits)
    def log(kind, prompt, response):
        logs.append({"id": len(logs) + 1, "user_id": 4, "request_type": kind, "prompt": prompt,
                     "response": json.dumps(response, ensure_ascii=False), "model_used": "deepseek-chat", "latency_ms": 1})
    def request(method, url, *, body=None, **kwargs):
        calls.append((method, url, body))
        route = url.split("/api/v1", 1)[1]
        assert url.startswith("http://127.0.0.1:18080/api/v1")
        if route == "/auth/login": return 200, {"access_token": token}
        if route == "/system/runtime-identity": return 200, facts()["identity"]
        if route == "/auth/me": return 200, {"id": 4, "role": "admin"}
        if route == "/devices": return 200, [] if failure == "inventory" else facts()["devices"]
        if route == "/health": return 200, {"components": {"mysql": {"status": "healthy"}, "knowledge": {"status": "healthy"}, "llm": {"status": "healthy", "model": "deepseek-chat", "config_source": "env"}}}
        if route == "/ai/logs?page_size=100": return 200, {"items": [] if failure == "missing_log" else logs}
        if route == "/ai/knowledge/health": return 200, {"available": True, "provider": "anythingllm", "document_count": 135}
        if route == "/ai/knowledge/search": return 200, [{"text": "可信教材内容", "score": 0.9}]
        if route == "/ai/generate-cli":
            response = {"commands": ["display version"]}
            log("generate_cli", body["natural_language"], response)
            return 200, response
        if route == "/deploy/validate": return 200, {"valid": True, "errors": []}
        if route == "/ai/review-config":
            response = {"summary": "该配置可作为预览草稿", "issues": []}
            log("review_config", body["config_text"], response)
            return 200, response
        if route == "/ai/ask": return 200, {"status": "ok", "provider": "anythingllm", "answer": "基于参考资料的回答", "sources": [{"text": "可信教材内容"}]}
        if route == "/training/labs": return 200, [{"id": 2, "status": "published"}]
        if route == "/training/sessions": return 200, {"id": 7, "status": "in_progress"}
        if route.endswith("/log"):
            assert body["success"] is False and body["meta"]["verification_status"] == "unverified"
            return 200, {"id": 3}
        if route.endswith(("/hint", "/report")):
            hint = route.endswith("/hint")
            response = {"session_id": 7, "degraded": bool(hint and failure == "degraded_hint"), "knowledge_status": "ok", "summary": "训练复盘与过程记录" if not hint and failure == "fallback_report" else "依据该会话过程给出的具体建议", "sources": [{"text": "可信教材内容"}]}
            log("coach_training" if hint else "generate_report", "实验标题", response)
            return 200, response
        if route.endswith("/complete"): return 200, {"session_id": 7}
        if route.endswith("/score"): return 200, {"score": 100 if failure == "fabricated_score" else None, "passed": True if failure == "fabricated_score" else None, "detail": {"verification_status": "unverified", "reference_score": 50}}
        if route == "/training/sessions/7": return 200, {"status": "completed", "score": None, "passed": None}
        pytest.fail("Unexpected business API " + route)
    def stream(url, *, body, **kwargs):
        calls.append(("POST", url, body))
        log("copilot_chat", body["message"], "已根据版本回显回答")
        return [{"type": "tool", "name": "run_display_command", "status": "done"}, {"type": "token", "text": "已根据版本回显回答"}, {"type": "done", "status": "failed" if failure == "failed_sse" else "ok"}]
    monkeypatch.setattr(m, "http_json", request)
    monkeypatch.setattr(m, "http_sse", stream)
    report = await m.verify(config, ENDPOINTS, "http://127.0.0.1:18080")
    assert report["verdict"]["ok"] is (failure is None), report["verdict"]
    assert report["verdict"]["full_delivery"] is False
    assert all(method != "DELETE" for method, *_ in calls)
    if failure == "inventory":
        assert all(method == "GET" or url.endswith("/auth/login") for method, url, _ in calls)
    else:
        assert report["session_ids"] == [7]
    serialized = json.dumps(report)
    assert token not in serialized and config.admin_password not in serialized
    assert "可信教材内容" not in serialized and "依据该会话过程" not in serialized


@pytest.mark.asyncio
async def test_db_facts_only_selects_never_initializes_migrates_or_cleans(monkeypatch):
    from sqlalchemy import event, text
    import sqlalchemy.ext.asyncio
    from core.config import Settings
    m = module()
    engine = sqlalchemy.ext.asyncio.create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        for statement in ["CREATE TABLE system_config (config_key TEXT, config_value TEXT)",
                          "CREATE TABLE device (id INTEGER, hostname TEXT, mgmt_ip TEXT, ssh_port INTEGER, model TEXT)",
                          "CREATE TABLE ai_log (id INTEGER)", "CREATE TABLE audit_log (id INTEGER)"]:
            await connection.execute(text(statement))
    seen = []
    event.listen(engine.sync_engine, "before_cursor_execute", lambda conn, cursor, statement, *args: seen.append(statement))
    monkeypatch.setattr(sqlalchemy.ext.asyncio, "create_async_engine", lambda *args, **kwargs: engine)
    config = Settings(_env_file=None, db_url="", db_backend="mysql", db_host="db.example.invalid", device_mode="ssh", llm_provider="openai_compatible", llm_model="deepseek-chat", llm_base_url="https://api.deepseek.com/v1")
    snapshot = await m.db_facts(config)
    assert snapshot["llm_model"] == "deepseek-chat"
    assert seen and all(statement.strip().upper().startswith("SELECT") for statement in seen)


@pytest.mark.asyncio
async def test_cli_returns_nonzero_and_writes_safe_report_when_required_setup_fails(monkeypatch, tmp_path):
    import core.config
    m = module()
    monkeypatch.setattr(core.config, "get_settings", settings)
    monkeypatch.setattr(m, "capture_run_binding", lambda _: {**facts()["identity"], "source_fingerprint": "a" * 64, "captured_at": "2026-10-11T01:00:00+00:00"})
    async def fail(*args):
        return {"verdict": {"ok": False, "full_delivery": False}}
    monkeypatch.setattr(m, "verify", fail)
    output = tmp_path / "failed.json"
    assert await m.main(["--expected-endpoints", ENDPOINTS, "--report", str(output)]) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["verdict"]["ok"] is False


@pytest.mark.asyncio
async def test_cli_rejects_source_changes_during_an_otherwise_successful_run(monkeypatch, tmp_path):
    import core.config
    m = module()
    monkeypatch.setattr(core.config, "get_settings", settings)
    fingerprints = iter(["a" * 64, "b" * 64])
    monkeypatch.setattr(m, "capture_run_binding", lambda _: {**facts()["identity"], "source_fingerprint": next(fingerprints), "captured_at": "2026-10-11T01:00:00+00:00"})
    async def success(*args):
        return {"verdict": {"ok": True, "full_delivery": False}}
    monkeypatch.setattr(m, "verify", success)
    output = tmp_path / "changed.json"
    assert await m.main(["--expected-endpoints", ENDPOINTS, "--report", str(output)]) == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["verdict"]["failed"] == ["source_unchanged_during_run", "build_runtime_unchanged"]
    assert report["source_fingerprint"] == "a" * 64


def test_model_endpoint_does_not_hide_unsafe_url_credentials():
    m = module()
    assert m.public_service_url("https://api.deepseek.com/v1/") == "https://api.deepseek.com/v1"
    for endpoint in ("https://user@example.invalid/v1", "https://example.invalid/v1?key=fixture", "file:///tmp/model"):
        with pytest.raises(ValueError):
            m.public_service_url(endpoint)
