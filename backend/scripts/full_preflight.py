"""Authenticated, read-only full-mode prerequisite checks; never initializes a DB.

Imports do not read configuration. CLI configuration is confined to the requested
root, with backend/.env then process variables taking precedence. Secrets and
external response bodies are never included in the report.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from urllib.parse import quote, urlparse

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def load_config(root: Path, environ=None) -> dict[str, str]:
    from core.config import Settings
    from dotenv import dotenv_values
    config = {name.upper(): str(field.default) for name, field in Settings.model_fields.items()}
    for path in (root / ".env", root / "backend/.env"):
        if path.is_file():
            # Profile values must be literals, not substitutions from another profile.
            config.update({k.upper(): v or "" for k, v in dotenv_values(path, interpolate=False).items()})
    config.update({k.upper(): v for k, v in (os.environ if environ is None else environ).items()})
    return config


def _placeholder(value: str) -> bool:
    return not value.strip() or bool(re.search(r"(?i)<[^>]+>|\$\{|change[_-]?me|placeholder|your[_-]", value))


def validate_config(config: dict[str, str], *, llm_only=False) -> list[dict]:
    issues = []
    def require(key, ok, message):
        if not ok:
            issues.append({"key": key, "message": message})
    require("LLM_PROVIDER", config.get("LLM_PROVIDER", "").replace("-", "_").lower() in {"openai", "openai_compatible"}, "full 需要真实 OpenAI-compatible DeepSeek 接口")
    for key in ("LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL"):
        require(key, not _placeholder(config.get(key, "")), "缺少有效配置（不接受模板占位值）")
    for key in ("LLM_BASE_URL",) if llm_only else ("LLM_BASE_URL", "KNOWLEDGE_BASE_URL"):
        parsed = urlparse(config.get(key, ""))
        require(key, parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment, "需要不含用户信息、查询参数或片段的 HTTP(S) 服务地址")
    require("LLM_MODEL", "deepseek" in (config.get("LLM_MODEL", "") + config.get("LLM_BASE_URL", "")).lower(), "请明确配置 DeepSeek 模型或 DeepSeek 服务地址")
    if llm_only:
        return issues
    require("DB_BACKEND", config.get("DB_BACKEND", "").lower() == "mysql", "full 必须使用 MySQL，不能沿用 minimal 的 SQLite")
    require("DEVICE_MODE", config.get("DEVICE_MODE", "").lower() == "ssh", "full 必须使用 SSH，不能沿用 sim")
    require("KNOWLEDGE_PROVIDER", config.get("KNOWLEDGE_PROVIDER", "").lower() == "anythingllm", "full 必须使用 AnythingLLM")
    required = ["JWT_SECRET_KEY", "FERNET_KEY", "ADMIN_PASSWORD", "DEVICE_DEFAULT_USERNAME", "DEVICE_DEFAULT_PASSWORD", "KNOWLEDGE_API_KEY", "KNOWLEDGE_WORKSPACE_SLUG"]
    if config.get("DB_URL"):
        from sqlalchemy.engine import make_url
        try:
            url = make_url(config["DB_URL"])
            require("DB_URL", url.get_backend_name() == "mysql" and bool(url.host and url.database and url.username and url.password) and not _placeholder(url.password or ""), "DB_URL 必须为完整 MySQL 连接；不接受 SQLite 或匿名连接")
        except Exception:
            require("DB_URL", False, "数据库连接串格式错误")
    else:
        required += ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"]
        require("DB_PORT", config.get("DB_PORT", "").isdigit() and 0 < int(config["DB_PORT"]) < 65536, "数据库端口无效")
    for key in required:
        require(key, not _placeholder(config.get(key, "")), "缺少有效配置（不接受模板占位值）")
    require("ADMIN_PASSWORD", len(config.get("ADMIN_PASSWORD", "").encode("utf-8")) <= 72, "管理员口令 UTF-8 编码不能超过 72 字节")
    require("JWT_SECRET_KEY", len(config.get("JWT_SECRET_KEY", "")) >= 32, "JWT 密钥至少需要 32 字符")
    try:
        from cryptography.fernet import Fernet
        Fernet(config.get("FERNET_KEY", "").encode())
    except Exception:
        require("FERNET_KEY", False, "Fernet 密钥格式无效；恢复旧库须沿用对应密钥")
    return issues


def probe_mysql(config: dict[str, str]) -> dict:
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.engine import URL, make_url
    from core.migrations import _head, _assert_unversioned_baseline
    url = make_url(config["DB_URL"]) if config.get("DB_URL") else URL.create(
        "mysql+pymysql", username=config["DB_USER"], password=config["DB_PASSWORD"],
        host=config["DB_HOST"], port=int(config["DB_PORT"]), database=config["DB_NAME"])
    url = url.set(drivername="mysql+pymysql")
    engine = create_engine(url, connect_args={"connect_timeout": 8, "read_timeout": 10, "write_timeout": 10})
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            tables = set(inspect(conn).get_table_names())
            revisions = list(conn.execute(text("SELECT version_num FROM alembic_version")).scalars()) if "alembic_version" in tables else []
            if not tables:
                state = "empty"
            elif revisions == [_head()]:
                state = "ready"
            elif not revisions or revisions == ["0001_initial"]:
                _assert_unversioned_baseline(conn)  # Schema reflection only; no stamp/DDL.
                state = "legacy"
            else:
                state = "unknown"
            overrides = {row[0]: row[1] for row in conn.execute(text("SELECT config_key, config_value FROM system_config WHERE config_key LIKE 'llm.%'"))} if "system_config" in tables else {}
            return {"state": state, "overrides": overrides}
    finally:
        engine.dispose()


def probe_llm(config: dict[str, str]) -> dict:
    import httpx
    body = {"model": config["LLM_MODEL"], "messages": [{"role": "user", "content": "Reply with OK."}], "max_tokens": 256, "stream": False}
    # DeepSeek supports explicitly disabling reasoning for a short readiness probe.
    body["thinking"] = {"type": "disabled"}
    with httpx.Client(timeout=45, trust_env=False, follow_redirects=False) as client:
        response = client.post(config["LLM_BASE_URL"].rstrip("/") + "/chat/completions", headers={"Authorization": "Bearer " + config["LLM_API_KEY"]}, json=body)
        response.raise_for_status()
        data = response.json()
    if not any(str(item.get("message", {}).get("content") or "").strip() for item in data.get("choices", [])):
        raise ValueError("empty_model_response")
    return {"authenticated_generation": True}


def probe_knowledge(config: dict[str, str]) -> dict:
    import httpx
    slug = quote(config["KNOWLEDGE_WORKSPACE_SLUG"], safe="")
    with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
        response = client.get(config["KNOWLEDGE_BASE_URL"].rstrip("/") + "/api/v1/workspace/" + slug, headers={"Authorization": "Bearer " + config["KNOWLEDGE_API_KEY"]})
        response.raise_for_status()
        data = response.json()
    workspace = data.get("workspace")
    if isinstance(workspace, list):
        workspace = workspace[0] if workspace else None
    if not isinstance(workspace, dict) or workspace.get("slug") != config["KNOWLEDGE_WORKSPACE_SLUG"]:
        raise ValueError("workspace_not_found")
    return {"authenticated_workspace": True, "documents": len(workspace.get("documents") or [])}


def preflight(root: Path, phase="start", backup_file: Path | None = None, environ=None) -> dict:
    config = load_config(root, environ)
    initial_issues = validate_config(config)
    # The application allows model settings to come entirely from system_config.
    # Check that effective configuration after authenticating to the database.
    issues = [item for item in initial_issues if not item["key"].startswith("LLM_")]
    report = {"ok": False, "phase": phase, "issues": issues, "checks": [], "scope": "配置与服务认证预检；不代表三台设备及业务全流程验收"}
    if issues:
        report["issues"] = initial_issues
        return report
    try:
        database = probe_mysql(config)
        state = database["state"]
        report["database_state"] = state
        if state not in {"ready", "empty", "legacy"} or (phase == "start" and state != "ready"):
            issues.append({"key": "DB_SCHEMA", "message": "数据库未准备完成或版本未知；请先核对副本与备份，再显式 bootstrap"})
            return report
        if state == "legacy" and not (backup_file and backup_file.is_file() and backup_file.stat().st_size > 0):
            issues.append({"key": "BACKUP_FILE", "message": "旧 MySQL 需要已导出并核验的非空备份文件；此预检不会迁移"})
            return report
        report["checks"].append({"name": "mysql", "ok": True})
        # Share the application's empty/invalid-value fallback, including whitespace.
        from modules.system.runtime_config import resolve_value
        for key in ("provider", "model", "base_url", "api_key"):
            value = database.get("overrides", {}).get("llm." + key)
            setting = "LLM_" + key.upper()
            config[setting] = resolve_value("llm." + key, value, config[setting])[0]
        issues.extend(validate_config(config, llm_only=True))
        if issues:
            return report
        for name, probe in (("llm", probe_llm), ("knowledge", probe_knowledge)):
            try:
                report["checks"].append({"name": name, "ok": True, **probe(config)})
            except Exception as exc:
                issues.append({"key": name.upper(), "message": "认证探测失败；检查该服务地址、权限及运行状态", "error_type": type(exc).__name__})
    except Exception as exc:
        issues.append({"key": "MYSQL", "message": "MySQL 认证或结构检查失败；确认服务已启动、目标数据库已创建且账号有权限", "error_type": type(exc).__name__})
    report["ok"] = not issues
    return report


def verify_backend(root: Path, base_url: str, expected_pid: int, environ=None, *, expected_launch_id: str = "") -> dict:
    """Authenticate to the launched app and bind it to this profile/root/PID."""
    import httpx
    from core.runtime_identity import runtime_identity, same_runtime
    config = load_config(root, environ)
    report = {"ok": False, "issues": [], "scope": "当前工作区、数据库配置和启动进程身份"}
    try:
        settings = SimpleNamespace(**{name: config[name.upper()] for name in (
            "db_url", "db_backend", "db_host", "db_name", "db_user", "db_password",
            "db_sqlite_path", "device_mode", "knowledge_provider")},
            db_port=int(config["DB_PORT"]), deploy_simulate_only=config["DEPLOY_SIMULATE_ONLY"].lower() in {"1", "true", "yes", "on"})
        expected = runtime_identity(settings, root=root)
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("invalid_backend_url")
        with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
            response = client.post(base_url.rstrip("/") + "/api/v1/auth/login", json={"username": config["ADMIN_USERNAME"], "password": config["ADMIN_PASSWORD"]})
            response.raise_for_status()
            token = response.json()["access_token"]
            response = client.get(base_url.rstrip("/") + "/api/v1/system/runtime-identity", headers={"Authorization": "Bearer " + token})
            response.raise_for_status()
            actual = response.json()
        # Windows venv python.exe redirects to a child interpreter. Both forms
        # must carry this launch's nonce; a matching port/root alone is not proof.
        related_pid = actual.get("pid") == expected_pid or actual.get("parent_pid") == expected_pid
        if not expected_launch_id or actual.get("launch_id") != expected_launch_id or not same_runtime(expected, actual) or not related_pid:
            raise ValueError("runtime_identity_mismatch")
        report["ok"] = True
        report["process"] = {key: actual.get(key) for key in ("pid", "parent_pid")}
        report["binding"] = {key: actual[key] for key in (
            "root_fingerprint", "database_fingerprint", "device_mode", "knowledge_provider", "deploy_simulate_only"
        )}
    except Exception as exc:
        report["issues"].append({"key": "RUNTIME_IDENTITY", "message": "管理员认证或实例身份不匹配；拒绝把另一进程/目录/数据库当作本次启动", "error_type": type(exc).__name__})
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=BACKEND.parent)
    parser.add_argument("--phase", choices=("prepare", "start"), default="start")
    parser.add_argument("--backup-file", type=Path)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--verify-backend-url")
    action.add_argument("--validate-only", action="store_true", help="Local effective configuration validation; no service probes")
    action.add_argument("--validate-config-stdin", action="store_true", help="Validate a new literal string configuration from stdin; no files or network")
    parser.add_argument("--expected-pid", type=int)
    parser.add_argument("--expected-launch-id")
    args = parser.parse_args(argv)
    if args.validate_config_stdin:
        try:
            # Windows PowerShell can prefix redirected UTF-8 stdin with a BOM.
            config = json.loads(sys.stdin.read(1024 * 1024 + 1).removeprefix("\ufeff"))
            if (not isinstance(config, dict) or len(config) > 200
                    or any(not isinstance(k, str) or not isinstance(v, str) for k, v in config.items())):
                raise ValueError("literal_string_configuration_required")
            issues = validate_config(config)
            report = {"ok": not issues, "issues": issues, "scope": "本地配置格式校验；未探测服务、未写文件"}
        except Exception:
            report = {"ok": False, "issues": [{"key": "CONFIG_INPUT", "message": "需要有效的字符串配置对象；输入内容未回显"}]}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    try:
        root = args.root.resolve(strict=True)
        if args.validate_only:
            issues = validate_config(load_config(root))
            report = {"ok": not issues, "issues": issues, "scope": "本地有效配置格式校验；未探测服务、未迁移或写文件"}
        elif args.verify_backend_url:
            if not args.expected_pid or not args.expected_launch_id:
                parser.error("--verify-backend-url requires --expected-pid and --expected-launch-id")
            report = verify_backend(root, args.verify_backend_url, args.expected_pid, expected_launch_id=args.expected_launch_id)
        else:
            report = preflight(root, args.phase, args.backup_file)
    except Exception as exc:
        report = {"ok": False, "issues": [{"key": "CONFIG", "message": "无法读取有效配置", "error_type": type(exc).__name__}]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
