"""Isolated dependency fault injection, not an outage of deployed services.

Run as a dedicated process. Settings are init-only: no .env or production
credentials are loaded. A private loopback FastAPI server serves the real health
handler and HTTP 503 dependency stubs. MySQL and SSH use a bound, non-listening
loopback port. No scheduler, migration, existing server or device is touched.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import time
import uuid

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def isolated_settings(http_port, refused_port, log_dir, markers):
    from core.config import Settings
    from pydantic_settings import SettingsConfigDict

    class IsolatedSettings(Settings):
        model_config = SettingsConfigDict(env_file=None, extra="ignore")

        @classmethod
        def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
            return (init_settings,)

    endpoint = f"http://127.0.0.1:{http_port}"
    return IsolatedSettings(
        db_backend="mysql", db_url="", db_host="127.0.0.1", db_port=refused_port,
        db_name="isolated_fault_fixture", db_user="fault_fixture", db_password=markers["database"],
        db_auto_create=False, llm_provider="openai_compatible", llm_base_url=endpoint,
        llm_api_key=markers["llm"], llm_model="isolated-fault-model", llm_timeout=2,
        llm_fallback_model="", llm_fallback_api_key="", llm_vision_model="", llm_thinking_enabled=False,
        knowledge_provider="anythingllm", knowledge_base_url=endpoint,
        knowledge_api_key=markers["knowledge"], knowledge_workspace_slug="fault-fixture",
        knowledge_request_timeout=2, minio_endpoint=f"127.0.0.1:{http_port}",
        device_mode="ssh", ssh_connect_timeout=1, ssh_command_timeout=5, deploy_simulate_only=True,
        jwt_secret_key=secrets.token_urlsafe(32), log_dir=str(log_dir), debug=False,
    )


def successful(components, *, secrets_clean, closed):
    return (set(components) == {"database", "llm", "knowledge", "ssh"}
            and all(item.get("ok") is True for item in components.values()) and secrets_clean and closed)


def restrict_process_connections(http_port, refused_port):
    """Dedicated-process guard: even accidental default clients cannot escape."""
    allowed = {("127.0.0.1", http_port), ("127.0.0.1", refused_port)}
    evidence = {"attempted": 0, "blocked": 0}

    def audit(event, args):
        if event == "socket.connect":
            address = args[1]
        elif event == "socket.getaddrinfo":
            address = args[:2]
        else:
            return
        if not isinstance(address, tuple) or tuple(address[:2]) not in allowed:
            evidence["blocked"] += 1
            raise PermissionError("isolated_probe_external_connection_blocked")
        evidence["attempted"] += 1

    # Audit hooks intentionally last for this short-lived isolated process.
    sys.addaudithook(audit)
    return evidence


async def checks(settings, endpoint, refused_port, markers):
    import httpx
    from core.llm_provider import OpenAICompatibleProvider, create_llm_provider
    from engines.device_adapter import SSHDeviceAdapter
    from engines.device_lock import acquire_device_lock
    from modules.ai_text.llm_service import LLMService
    from modules.knowledge.service import KnowledgeService

    observed = []
    components = {}
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        started = time.monotonic()
        health = await client.get(endpoint + "/api/v1/health")
        observed.append(health.text)
        body = health.json()
        components["database"] = {
            "ok": health.status_code == 503 and body.get("status") == "unhealthy"
                  and body.get("components", {}).get("mysql", {}).get("status") == "unhealthy",
            "fault": "loopback_connection_refused", "health_http_status": health.status_code,
            "health_status": body.get("status"), "elapsed_ms": round((time.monotonic() - started) * 1000),
            "mysql_status": body.get("components", {}).get("mysql", {}).get("status"),
        }

    started = time.monotonic()
    raw = OpenAICompatibleProvider()
    generate_exception = None
    try:
        await raw.generate("isolated availability probe", max_tokens=8)
    except Exception as exc:
        observed.append(str(exc))
        generate_exception = type(exc).__name__
    # Exercise the actual application wrapper too: static fallback must be degraded,
    # never a successful model answer. This intentionally detects false green states.
    service = LLMService(provider=create_llm_provider())
    generated = await service.copilot_chat("isolated availability probe")
    events = [event async for event in service.copilot_chat_stream("isolated availability probe")]
    observed.append(json.dumps([generated, events], ensure_ascii=False))
    done = [event for event in events if event.get("type") == "done"]
    components["llm"] = {
        "ok": generate_exception == "HTTPStatusError" and generated.get("status") in {"degraded", "failed", "unavailable"}
              and any(event.get("type") == "error" for event in events) and len(done) == 1 and done[0].get("status") == "failed",
        "fault": "loopback_http_503", "generate_exception": generate_exception,
        "application_generate_status": generated.get("status"),
        "stream_error": any(event.get("type") == "error" for event in events),
        "stream_done_status": done[-1].get("status") if done else None,
        "stream_done_count": len(done),
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }

    started = time.monotonic()
    knowledge = KnowledgeService.from_settings()
    kb_health = await knowledge.health_check()
    retrieve_exception = None
    try:
        await knowledge.search("isolated retrieval probe")
    except Exception as exc:
        observed.append(str(exc))
        retrieve_exception = type(exc).__name__
    answer = await knowledge.ask("isolated retrieval probe")
    observed.append(json.dumps([kb_health, answer], ensure_ascii=False))
    components["knowledge"] = {
        "ok": kb_health.get("available") is False and retrieve_exception == "HTTPStatusError"
              and answer.get("status") == "degraded" and not answer.get("sources") and not answer.get("answer"),
        "fault": "loopback_http_503", "available": kb_health.get("available"),
        "retrieve_exception": retrieve_exception, "ask_status": answer.get("status"),
        "ask_sources_count": len(answer.get("sources") or []),
        "ask_answer_characters": len(answer.get("answer") or ""),
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }

    started = time.monotonic()
    adapter = SSHDeviceAdapter("127.0.0.1", "fault-fixture", markers["ssh"], port=refused_port, timeout=1, device_model="NE40E-X16")
    ssh_exception = None
    try:
        await adapter.run_command("display version", timeout=2)
    except Exception as exc:
        observed.append(str(exc))
        ssh_exception = type(exc).__name__
    finally:
        await adapter.close()
    async with acquire_device_lock("127.0.0.1", refused_port, timeout=0.5):
        lock_reacquired = True
    components["ssh"] = {"ok": ssh_exception is not None and adapter._executor is None and lock_reacquired,
                         "fault": "loopback_connection_refused", "exception": ssh_exception,
                         "closed": adapter._executor is None, "lock_reacquired": lock_reacquired,
                         "elapsed_ms": round((time.monotonic() - started) * 1000)}
    return components, observed


async def run_isolated(log_dir):
    # These changes affect only this explicitly dedicated process.
    for name in tuple(os.environ):
        if name.lower().endswith("_proxy"):
            os.environ.pop(name)
    markers = {key: "FAULT_SECRET_" + uuid.uuid4().hex for key in ("database", "llm", "knowledge", "ssh")}
    refused = socket.socket()
    refused.bind(("127.0.0.1", 0))  # Reserving without listen deterministically refuses connections.
    refused_port = refused.getsockname()[1]
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    http_port = listener.getsockname()[1]
    network = restrict_process_connections(http_port, refused_port)
    settings = isolated_settings(http_port, refused_port, log_dir, markers)
    markers["jwt"] = settings.jwt_secret_key
    import core.config as config
    config.get_settings = lambda: settings
    from core.live_evidence import capture_binding, binding_unchanged
    start = capture_binding(settings)
    import core.database as database
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from core.shared_http import close_all_clients
    engine = create_async_engine(database.resolve_database_url(settings), connect_args={"connect_timeout": 1}, echo=False)
    database._engine = engine
    database._session_factory = async_sessionmaker(engine, expire_on_commit=False)
    from main import health_check
    from core import health
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    import uvicorn

    # The optional Ollama endpoint is hard-coded to an existing port in the product.
    # Exclude it explicitly; do not contact or claim to test that existing service.
    health._cache_set("ollama", {"status": "not_tested", "optional": True})
    app = FastAPI()
    app.add_api_route("/api/v1/health", health_check, methods=["GET"])
    fault_requests = []

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def unavailable(path: str):
        fault_requests.append(path)
        return JSONResponse({"error": "isolated dependency deliberately unavailable"}, status_code=503)

    server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False, lifespan="off"))
    server_task = asyncio.create_task(server.serve(sockets=[listener]))
    components, observed = {}, []
    failure = None
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if server_task.done():
                    await server_task
                    raise RuntimeError("isolated_backend_start_failed")
                await asyncio.sleep(0.01)
        async with asyncio.timeout(45):
            components, observed = await checks(settings, f"http://127.0.0.1:{http_port}", refused_port, markers)
    except Exception as exc:
        observed.append(str(exc))
        failure = type(exc).__name__
    finally:
        server.should_exit = True
        await server_task
        await close_all_clients()
        await engine.dispose()
        refused.close()
        listener.close()
    for handler in logging.getLogger().handlers:
        handler.flush()
    log_text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in log_dir.glob("*.log"))
    secrets_clean = all(marker not in log_text + "\n".join(observed) for marker in markers.values())
    finish = capture_binding(settings)
    closed = server_task.done() and listener.fileno() == -1 and refused.fileno() == -1
    return {"schema": 1, "producer": "verify_live_dependency_faults", "scope": "isolated_dependency_fault_injection",
            "ok": successful(components, secrets_clean=secrets_clean, closed=closed) and binding_unchanged(start, finish)
                  and network["blocked"] == 0 and network["attempted"] > 0,
            "isolation": {"configuration": "init_only", "external_targets": 0, "database_migrated": False,
                          "scheduler_started": False, "existing_services_modified": False, "host": "127.0.0.1",
                          "http_port": http_port, "refused_port": refused_port, "excluded": ["existing_ollama_embedding"]},
            "network_guard": {"allowed_host": "127.0.0.1", "allowed_ports": [http_port, refused_port],
                              "connection_or_resolution_attempts": network["attempted"], "blocked_attempts": network["blocked"]},
            "components": components, "secrets_clean": secrets_clean, "synthetic_markers_checked": len(markers),
            "resources_closed": closed, "fault_request_count": len(fault_requests), "failure_type": failure,
            "binding": {"start": start, "finish": finish}, "started_at": start["captured_at"], "finished_at": finish["captured_at"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.exists():
        raise SystemExit("report_already_exists")
    with tempfile.TemporaryDirectory(prefix="ip-sim-dependency-fault-") as directory:
        try:
            report = asyncio.run(run_isolated(Path(directory)))
        except Exception as exc:
            report = {"schema": 1, "scope": "isolated_dependency_fault_injection", "ok": False, "failure_type": type(exc).__name__}
        finally:
            logging.shutdown()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
