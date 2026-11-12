"""Real AI and training API acceptance against one explicitly bound workbench.

This creates AI logs and one retained training session, and asks Copilot to run
one read-only display command. It never initializes/migrates a DB or removes
records. Device collection, WebSSH and configuration restore have separate gates.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse
import uuid

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
SCOPE = "DeepSeek/AnythingLLM 与 AI/实训业务 API；不代表设备采集、WebSSH、配置下发/回读/恢复或完整交付通过"
FALLBACKS = (
    "当前AI服务不可用", "当前知识库不可用", "已根据当前训练进度生成步骤提示",
    "已根据当前训练场景给出下一步建议", "已根据训练过程、操作记录和故障注入生成复盘摘要",
    "已根据输入生成报告草稿", "流式生成失败", "[生成失败]", "LLM输出格式异常",
)


def good_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not any(s in value for s in FALLBACKS)


def stream_succeeded(events: list[dict]) -> bool:
    done = [i for i, event in enumerate(events) if event.get("type") == "done"]
    return bool(events) and done == [len(events) - 1] and events[-1].get("status") == "ok" and not any(
        event.get("type") in {"error", "raw"} or event.get("status") in {"failed", "error", "degraded"}
        for event in events
    ) and good_text("".join(str(e.get("text") or "") for e in events if e.get("type") == "token"))


def honest_score(value: dict) -> bool:
    detail = value.get("detail") or {}
    return "score" in value and "passed" in value and value["score"] is None and value["passed"] is None and (
        detail.get("verification_status") == "unverified" and type(detail.get("reference_score")) in {int, float}
    )


def api_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("invalid_api_url")
    base = value.rstrip("/")
    return base if base.endswith("/api/v1") else base + "/api/v1"


def public_service_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("unsafe_model_base_url")
    return value.rstrip("/")


def capture_run_binding(settings) -> dict:
    from sqlalchemy.engine import make_url
    from core.live_evidence import capture_binding
    if settings.db_backend != "mysql" or settings.device_mode != "ssh" or settings.knowledge_provider != "anythingllm":
        raise ValueError("full_requires_mysql_ssh_anythingllm")
    if settings.db_url and make_url(settings.db_url).get_backend_name() != "mysql":
        raise ValueError("full_requires_mysql_url")
    return capture_binding(settings, root=ROOT)


def selected_devices(value: str, devices: list[dict]) -> list[dict]:
    endpoints = []
    for part in value.split(","):
        host, port = part.strip().rsplit(":", 1)
        endpoint = (host.strip("[]").lower(), int(port))
        if not endpoint[0] or not 0 < endpoint[1] < 65536:
            raise ValueError("invalid_endpoint")
        endpoints.append(endpoint)
    if len(endpoints) != 3 or len(set(endpoints)) != 3:
        raise ValueError("exactly_three_unique_endpoints_required")
    chosen = []
    for host, port in endpoints:
        matches = [d for d in devices if str(d["mgmt_ip"]).lower() == host and int(d["ssh_port"]) == port]
        if len(matches) != 1:
            raise ValueError("endpoint_missing_or_ambiguous")
        chosen.append(matches[0])
    return chosen


def http_json(method: str, url: str, *, body=None, token=None, timeout=60):
    import httpx
    headers = {"Authorization": "Bearer " + token} if token else {}
    try:
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            response = client.request(method, url, json=body, headers=headers)
            return response.status_code, response.json()
    except Exception as exc:
        return 0, {"error_type": type(exc).__name__}


def http_sse(url: str, *, body: dict, token: str, timeout=180) -> list[dict]:
    import httpx
    events = []
    with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
        with client.stream("POST", url, json=body, headers={"Authorization": "Bearer " + token}) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith("data:"):
                    value = json.loads(line[5:].strip())
                    if not isinstance(value, dict):
                        raise ValueError("invalid_sse_event")
                    events.append(value)
    return events


async def _read_database(settings, *, after_audit: int | None = None) -> dict | list:
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine
    from core.database import resolve_database_url
    from core.runtime_identity import runtime_identity
    from modules.system.service import LLM_CONFIG_KEYS, SystemService

    if settings.db_backend != "mysql" or settings.device_mode != "ssh":
        raise ValueError("full_requires_mysql_ssh")
    if settings.db_url and make_url(settings.db_url).get_backend_name() != "mysql":
        raise ValueError("full_requires_mysql_url")
    engine = create_async_engine(resolve_database_url(settings), connect_args={"connect_timeout": 10})
    try:
        async with engine.connect() as conn:
            if after_audit is not None:
                rows = await conn.execute(text("SELECT id, user_id, detail, result FROM audit_log WHERE id>:id AND action='ai_display_command' ORDER BY id"), {"id": after_audit})
                return [dict(row) for row in rows.mappings()]
            rows = await conn.execute(text("SELECT config_key, config_value FROM system_config WHERE config_key LIKE 'llm.%'"))
            overrides = dict(rows.all())
            effective = {name: SystemService._parse_runtime_value(key, overrides.get(key), getattr(settings, name)) for key, name in LLM_CONFIG_KEYS.items()}
            if effective["llm_provider"].replace("-", "_").lower() not in {"openai", "openai_compatible"} or "deepseek" not in (effective["llm_model"] + effective["llm_base_url"]).lower():
                raise ValueError("real_deepseek_configuration_required")
            devices = await conn.execute(text("SELECT id, hostname, mgmt_ip, ssh_port, model FROM device ORDER BY id"))
            return {"identity": runtime_identity(settings), "devices": [dict(row) for row in devices.mappings()],
                    "llm": {"provider": effective["llm_provider"], "base_url": public_service_url(effective["llm_base_url"]), "model": effective["llm_model"]},
                    "llm_model": effective["llm_model"], "llm_source": "system_config" if any(key in overrides for key in LLM_CONFIG_KEYS) else "env",
                    "max_ai_log_id": int((await conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM ai_log"))).scalar_one()),
                    "max_audit_id": int((await conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM audit_log"))).scalar_one())}
    finally:
        await engine.dispose()


async def db_facts(settings) -> dict:
    return await _read_database(settings)


async def tool_audits(settings, after_id: int) -> list[dict]:
    return await _read_database(settings, after_audit=after_id)


def matching_tool_audits(rows: list[dict], device_id: int, user_id: int) -> list[int]:
    matches = []
    for row in rows:
        detail = row.get("detail") or {}
        if isinstance(detail, str):
            if len(detail) > 4096:
                continue
            try:
                detail = json.loads(detail)
            except ValueError:
                # AuditService historically stored str(dict). literal_eval only
                # accepts literals; never execute an audit string as Python code.
                try:
                    detail = ast.literal_eval(detail)
                except (ValueError, SyntaxError, TypeError, RecursionError):
                    continue
        if not isinstance(detail, dict) or not set(detail) <= {"device_id", "hostname", "command", "error"}:
            continue
        if row.get("result") == "success" and row.get("user_id") == user_id and isinstance(detail, dict) and detail.get("device_id") == device_id and str(detail.get("command", "")).strip().lower() == "display version":
            matches.append(row["id"])
    return matches


async def verify(settings, endpoints: str, base_url: str) -> dict:
    from core.runtime_identity import same_runtime
    report = {"schema": 2, "producer": "verify_full_stack", "run_id": uuid.uuid4().hex, "created_at": datetime.now(timezone.utc).isoformat(), "scope": SCOPE,
              "steps": [], "session_ids": [], "ai_logs": [], "tool_audit_ids": []}
    def add(name, ok, **extra):
        report["steps"].append({"name": name, "ok": bool(ok), **extra})
    def finish():
        failed = [s["name"] for s in report["steps"] if not s["ok"]]
        report["verdict"] = {"ok": bool(report["steps"]) and not failed, "failed": failed, "full_delivery": False}
        return report
    try:
        api = api_url(base_url)
        snapshot = await db_facts(settings)
        targets = selected_devices(endpoints, snapshot["devices"])
        if snapshot["identity"].get("device_mode") != "ssh" or snapshot["identity"].get("knowledge_provider") != "anythingllm":
            raise ValueError("wrong_runtime_profile")
        report["targets"] = [{key: d[key] for key in ("id", "hostname", "mgmt_ip", "ssh_port")} for d in targets]
        report["expected_identity"] = snapshot["identity"]
        report["llm"] = snapshot.get("llm", {})
        add("database_and_three_targets", True)
    except Exception as exc:
        add("database_and_three_targets", False, error_type=type(exc).__name__)
        return finish()
    password = settings.admin_password or ""
    if not password:
        add("admin_login", False, reason="missing_admin_password")
        return finish()
    status, login = http_json("POST", api + "/auth/login", body={"username": settings.admin_username or "admin", "password": password})
    token = login.get("access_token") if status == 200 and isinstance(login, dict) else None
    authenticated = isinstance(token, str) and bool(token)
    add("admin_login", authenticated, http_status=status)
    if not authenticated:
        return finish()
    status, actual = http_json("GET", api + "/system/runtime-identity", token=token)
    bound = status == 200 and isinstance(actual, dict) and same_runtime(snapshot["identity"], actual)
    add("runtime_identity", bound, http_status=status)
    if not bound:
        return finish()
    report["runtime_identity"] = {key: actual.get(key) for key in snapshot["identity"]}
    status, me = http_json("GET", api + "/auth/me", token=token)
    admin = status == 200 and isinstance(me, dict) and me.get("role") == "admin" and bool(me.get("id"))
    add("admin_identity", admin)
    if not admin:
        return finish()
    status, inventory = http_json("GET", api + "/devices", token=token)
    rows = inventory if isinstance(inventory, list) else inventory.get("items", []) if isinstance(inventory, dict) else []
    bound = status == 200 and all(any(d.get("id") == target["id"] and d.get("mgmt_ip") == target["mgmt_ip"] and d.get("ssh_port") == target["ssh_port"] for d in rows) for target in targets)
    add("api_targets_match_database", bound)
    if not bound:
        return finish()
    status, health = http_json("GET", api + "/health", timeout=45)
    components = health.get("components", {}) if isinstance(health, dict) else {}
    model = components.get("llm", {})
    ready = status == 200 and all(components.get(name, {}).get("status") == "healthy" for name in ("mysql", "llm", "knowledge")) and model.get("model") == snapshot["llm_model"] and model.get("config_source") == snapshot["llm_source"]
    add("effective_authenticated_health", ready)
    if not ready:
        return finish()
    cursor = snapshot["max_ai_log_id"]
    def llm_log(kind, marker=None, response_fragment=None):
        nonlocal cursor
        status, data = http_json("GET", api + "/ai/logs?page_size=100", token=token)
        rows = data.get("items", []) if isinstance(data, dict) else []
        matches = [row for row in rows if row.get("id", 0) > cursor and row.get("request_type") == kind and row.get("model_used") == snapshot["llm_model"] and good_text(row.get("response")) and (marker is None or marker in (row.get("prompt") or "")) and (response_fragment is None or response_fragment in row["response"])]
        cursor = max([cursor] + [row.get("id", 0) for row in rows])
        report["ai_logs"].extend({key: row.get(key) for key in ("id", "request_type", "model_used", "latency_ms")} for row in matches)
        return status == 200 and bool(matches)
    marker = report["run_id"]
    try:
        status, kh = http_json("GET", api + "/ai/knowledge/health", token=token)
        add("anythingllm_health", status == 200 and kh.get("available") is True and kh.get("provider") == "anythingllm" and int(kh.get("document_count") or 0) > 0)
        status, sources = http_json("POST", api + "/ai/knowledge/search", token=token, body={"question": "OSPF Silent-Interface 配置方法", "top_k": 3})
        add("knowledge_retrieval", status == 200 and isinstance(sources, list) and bool(sources) and all(good_text(s.get("text") or s.get("content")) and s.get("score") is not None for s in sources))
        status, cli = http_json("POST", api + "/ai/generate-cli", token=token, body={"natural_language": "仅生成华为设备查看版本的 display version 命令，不执行。验收编号 " + marker, "device_model": "NE40E"}, timeout=120)
        logged = llm_log("generate_cli", marker)
        add("deepseek_generate_cli", status == 200 and bool(cli.get("commands")) and all(good_text(c) for c in cli["commands"]) and logged)
        draft = "system-view\nospf 1 router-id 10.0.1.1\narea 0.0.0.0\nnetwork 10.0.1.1 0.0.0.0\nquit\nquit\n"
        status, validation = http_json("POST", api + "/deploy/validate", token=token, body={"config_content": draft, "device_model": "NE40E"})
        add("configuration_preview_validation", status == 200 and validation.get("valid") is True and not validation.get("errors"))
        status, review = http_json("POST", api + "/ai/review-config", token=token, body={"config_text": "# 验收编号 " + marker + "\n" + draft, "device_model": "NE40E"}, timeout=120)
        logged = llm_log("review_config", marker)
        add("deepseek_review", status == 200 and good_text(review.get("summary")) and isinstance(review.get("issues"), list) and logged)
        status, answer = http_json("POST", api + "/ai/ask", token=token, body={"question": "OSPF silent-interface 的作用与注意事项？验收编号 " + marker, "top_k": 3}, timeout=120)
        add("knowledge_answer", status == 200 and answer.get("status") == "ok" and answer.get("provider") == "anythingllm" and good_text(answer.get("answer")) and bool(answer.get("sources")))
        # Fresh cursor and user/device/command matching prevent historical audit rows
        # or another operator's successful call from satisfying this run's evidence.
        baseline = await db_facts(settings)
        if not same_runtime(snapshot["identity"], baseline["identity"]):
            raise ValueError("database_identity_changed")
        target = targets[0]
        events = http_sse(api + "/ai/copilot/chat/stream", token=token, body={"message": f"验收编号 {marker}。必须调用 run_display_command 工具，只对 device_id={target['id']} 执行一次 display version，只读查看版本并依据真实回显回答。不要操作其他设备，不要生成或执行配置。", "page_data": f"{target['hostname']} id={target['id']}", "top_k": 3}, timeout=180)
        logged = llm_log("copilot_chat", marker)
        audits = await tool_audits(settings, baseline["max_audit_id"])
        report["tool_audit_ids"] = matching_tool_audits(audits, target["id"], me["id"])
        tool_done = any(e.get("type") == "tool" and e.get("name") == "run_display_command" and e.get("status") == "done" for e in events)
        add("copilot_real_display_tool", stream_succeeded(events) and tool_done and bool(report["tool_audit_ids"]) and logged, evidence_scope="本轮管理员对指定设备的 display version 调用成功审计；设备回显有效性另由设备工作流验收")
        status, labs = http_json("GET", api + "/training/labs", token=token)
        available = [lab for lab in labs if lab.get("status") != "draft"] if status == 200 and isinstance(labs, list) else []
        if not available:
            add("training_lab_available", False)
            return finish()
        lab_id = available[0]["id"]
        status, session = http_json("POST", api + "/training/sessions", token=token, body={"lab_id": lab_id})
        sid = session.get("id")
        created = status == 200 and bool(sid) and session.get("status") == "in_progress"
        add("training_session_create", created)
        if not created:
            return finish()
        report["session_ids"].append(sid)
        prefix = api + f"/training/sessions/{sid}"
        status, operation = http_json("POST", prefix + "/log", token=token, body={"lab_id": lab_id, "action": "acceptance_note", "result": "验收编号 " + marker + "；API 过程记录，未执行设备配置，未经技能验证", "success": False, "meta": {"acceptance_run_id": marker, "verification_status": "unverified"}})
        add("training_honest_process_record", status == 200 and bool(operation.get("id")))
        for endpoint, kind in (("hint", "coach_training"), ("report", "generate_report")):
            status, content = http_json("GET", prefix + "/" + endpoint, token=token, timeout=120)
            summary = content.get("summary") or ""
            logged = llm_log(kind, response_fragment=summary)
            parsed_model_content = summary not in {"训练复盘与过程记录", "已生成报告草稿。", "已生成训练建议。", "已生成训练提示。"}
            add("training_" + endpoint, status == 200 and content.get("session_id") == sid and content.get("degraded") is False and content.get("knowledge_status") == "ok" and good_text(summary) and parsed_model_content and bool(content.get("sources")) and logged)
        status, completed = http_json("POST", prefix + "/complete", token=token)
        add("training_complete", status == 200 and completed.get("session_id") == sid)
        status, score = http_json("POST", prefix + "/score", token=token)
        add("training_score_unverified", status == 200 and honest_score(score))
        status, retained = http_json("GET", prefix, token=token)
        add("training_evidence_retained", status == 200 and retained.get("status") == "completed" and "score" in retained and "passed" in retained and retained["score"] is None and retained["passed"] is None)
    except Exception as exc:
        add("business_api_exception", False, error_type=type(exc).__name__)
    return finish()


async def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.environ.get("WORKBENCH_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--expected-endpoints", default=os.environ.get("WORKBENCH_EXPECTED_ENDPOINTS", ""), help="Exactly three comma-separated management host:SSH-port endpoints")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        from core.config import get_settings
        from core.live_evidence import binding_unchanged
        settings = get_settings()
        start = capture_run_binding(settings)
        report = await verify(settings, args.expected_endpoints, args.api_url)
        finish = capture_run_binding(settings)
        unchanged = start["source_fingerprint"] == finish["source_fingerprint"]
        runtime_unchanged = binding_unchanged(start, finish)
        report.update(binding={"start": start, "finish": finish}, source_fingerprint=start["source_fingerprint"], started_at=start["captured_at"], finished_at=finish["captured_at"])
        report.setdefault("steps", []).append({"name": "source_unchanged_during_run", "ok": unchanged})
        report["steps"].append({"name": "build_runtime_unchanged", "ok": runtime_unchanged})
        if not unchanged or not runtime_unchanged:
            report["verdict"]["ok"] = False
            report["verdict"].setdefault("failed", []).extend(s["name"] for s in report["steps"][-2:] if not s["ok"])
    except Exception as exc:
        report = {"schema": 2, "scope": SCOPE, "verdict": {"ok": False, "full_delivery": False}, "error_type": type(exc).__name__}
    path = args.report or ROOT / ".runtime/logs" / ("verify-full-ai-" + uuid.uuid4().hex + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(path), "scope": SCOPE, "verdict": report["verdict"]}, ensure_ascii=False))
    return 0 if report["verdict"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
