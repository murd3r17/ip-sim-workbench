"""Opt-in live DeepSeek / AnythingLLM probe; no DB writes or device operations.

Run from the extracted repository with its configured Python environment:
    python backend/scripts/verify_live_ai.py --output .runtime/logs/live-ai.json

This spends two small model requests when run. It reads the effective DB + env
LLM configuration, bypasses static and alternate-model fallback, and records
only identities, counts and hashes. It does NOT certify business API/UI flows,
AnythingLLM's separate chat model, vision, tools, or real-device operations.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import math
from pathlib import Path
import re
import secrets
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class ProbeFailure(Exception):
    """Only fixed, non-sensitive gate names may be used as the message."""


def require(condition, code):
    if not condition:
        raise ProbeFailure(code)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def public_url(value):
    parsed = urlsplit(str(value))
    require(parsed.scheme in {"http", "https"} and parsed.hostname, "invalid_service_url")
    require(not parsed.username and not parsed.password and not parsed.query and not parsed.fragment,
            "service_url_must_not_contain_credentials_or_query")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def database_identity(url):
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    # Neither credentials, URL query parameters, nor machine-local SQLite paths
    # enter the evidence. The hash still binds the particular DB location.
    # URL.set(None) leaves existing values unchanged; construct explicitly.
    safe = type(parsed).create(parsed.drivername, host=parsed.host, port=parsed.port, database=parsed.database)
    return {
        "driver": parsed.drivername,
        "host": parsed.host,
        "port": parsed.port,
        "database": "sqlite-file" if parsed.drivername.startswith("sqlite") else parsed.database,
        "identity_sha256": digest(safe.render_as_string(hide_password=True)),
    }


async def load_runtime():
    """SELECT-only access; never init_db(), migrate, seed, or create a DB."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.engine import make_url
    from core.config import get_settings
    from core.database import resolve_database_url
    from core.migrations import assert_schema_ready
    from modules.system.service import SystemService

    settings = get_settings()
    url = resolve_database_url(settings)
    parsed = make_url(url)
    if parsed.drivername.startswith("sqlite"):
        require(bool(parsed.database) and Path(parsed.database).is_file(), "existing_migrated_database_required")
    engine = create_async_engine(url, echo=False)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(assert_schema_ready)
            async with AsyncSession(bind=connection, autoflush=False) as session:
                runtime = await SystemService.get_llm_runtime_config(session)
        return runtime, settings, database_identity(url)
    finally:
        await engine.dispose()


def build_primary(runtime):
    from core.llm_provider import OpenAICompatibleProvider

    # Deliberately avoid create_llm_provider: its wrappers can turn an upstream
    # failure into a static answer or a different model's successful response.
    return OpenAICompatibleProvider(
        base_url=runtime["llm_base_url"], model=runtime["llm_model"], api_key=runtime["llm_api_key"],
        max_tokens=runtime.get("llm_max_tokens"), temperature=runtime.get("llm_temperature"),
        timeout=runtime.get("llm_timeout"),
    )


def build_knowledge():
    from modules.knowledge.service import KnowledgeService

    return KnowledgeService.from_settings()


def retrieval_evidence(sources):
    evidence = []
    for item in sources:
        if not isinstance(item, dict):
            continue
        raw = item.get("raw")
        metadata = item.get("metadata")
        raw = raw if isinstance(raw, dict) else {}
        metadata = metadata if isinstance(metadata, dict) else {}
        identifier = next((mapping[key] for mapping in (metadata, raw)
                           for key in ("docId", "document_id", "doc_id", "docpath", "location", "source", "url", "id")
                           if mapping.get(key)), None)
        text = item.get("text")
        score = next((raw[key] for key in ("score", "similarity", "confidence") if key in raw), None)
        if not identifier or not isinstance(text, str) or not text.strip():
            continue
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            continue
        evidence.append({"source_identity_sha256": digest(identifier), "chunk_sha256": digest(text),
                         "characters": len(text), "score": score})
    require(bool(evidence), "no_identifiable_retrieved_chunks")
    return {"returned_count": len(sources), "verified_chunk_count": len(evidence), "chunks": evidence}


async def run_probe(runtime, settings, database, expected_documents=135):
    report = {
        "schema_version": 1,
        "scope": "deepseek_and_anythingllm_readonly",
        "started_at": utc_now(), "ok": False, "checks": [],
        "not_verified": ["business_api_and_ui", "copilot_tool_execution", "three_real_devices",
                         "monitoring", "configuration_write_and_rollback", "anythingllm_chat_model", "vision"],
    }
    try:
        base_url = public_url(runtime.get("llm_base_url", ""))
        model = runtime.get("llm_model", "")
        require(runtime.get("llm_provider", "").lower() in {"openai", "openai_compatible"}, "deepseek_provider_required")
        parsed = urlsplit(base_url)
        require(parsed.scheme == "https" and parsed.hostname == "api.deepseek.com"
                and parsed.port in {None, 443}, "official_deepseek_endpoint_required")
        require(bool(re.fullmatch(r"deepseek[A-Za-z0-9_.:-]*", model, re.IGNORECASE)), "deepseek_model_required")
        require(bool(runtime.get("llm_api_key", "").strip()), "deepseek_key_required")
        require(settings.knowledge_provider.lower() == "anythingllm", "anythingllm_provider_required")
        require(bool(settings.knowledge_api_key.strip()), "anythingllm_key_required")
        report["identity"] = {
            "llm": {"provider": runtime["llm_provider"], "base_url": base_url, "model": model,
                    "configuration": "effective_db_overrides_with_env_defaults", "fallback_used": False,
                    "fallback_configured": bool(runtime.get("llm_fallback_model"))},
            "knowledge": {"provider": settings.knowledge_provider,
                          "base_url": public_url(settings.knowledge_base_url),
                          "workspace": settings.knowledge_workspace_slug, "expected_documents": expected_documents},
            "device_mode": settings.device_mode, "database": database,
        }
        primary, knowledge = build_primary(runtime), build_knowledge()
    except Exception as exc:
        report["checks"].append({"name": "configuration", "ok": False,
                                 "error": str(exc) if isinstance(exc, ProbeFailure) else type(exc).__name__})
        report["finished_at"] = utc_now()
        return report

    async def check(name, action):
        started = time.monotonic()
        entry = {"name": name, "started_at": utc_now()}
        try:
            entry.update(ok=True, evidence=await action())
        except Exception as exc:
            entry.update(ok=False, error=str(exc) if isinstance(exc, ProbeFailure) else type(exc).__name__)
        entry["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        report["checks"].append(entry)

    async def generate():
        marker = "probe-" + secrets.token_hex(8)
        answer = await primary.generate("Reply with only this exact marker: " + marker)
        require(isinstance(answer, str) and bool(answer.strip()), "empty_generation")
        require("当前AI服务不可用" not in answer and marker in answer, "generation_is_not_live_challenge_response")
        return {"characters": len(answer), "response_sha256": digest(answer), "challenge_matched": True}

    async def stream():
        marker = "probe-" + secrets.token_hex(8)
        content = []
        async for part in primary.stream_parts("Reply with only this exact marker: " + marker):
            if part.get("kind") == "content" and part.get("text"):
                content.append(part["text"])
        # OpenAICompatibleProvider rejects EOF without [DONE]/finish_reason.
        answer = "".join(content)
        require(bool(answer.strip()), "stream_has_no_content")
        require("当前AI服务不可用" not in answer and marker in answer, "stream_is_not_live_challenge_response")
        return {"characters": len(answer), "content_chunks": len(content), "response_sha256": digest(answer),
                "terminal_marker_validated_by_provider": True, "challenge_matched": True}

    async def health():
        result = await knowledge.health_check()
        require(result.get("provider") == "anythingllm" and result.get("available") is True, "anythingllm_unavailable")
        require(not result.get("error") and not result.get("warnings")
                and not (result.get("workspace") or {}).get("error"), "anythingllm_health_degraded")
        require(result.get("document_count") == expected_documents, "unexpected_document_count")
        return {"document_count": result["document_count"]}

    async def retrieve():
        result = await knowledge.search("OSPF 区域与邻居建立条件", top_k=3)
        return retrieval_evidence(result)

    await check("deepseek_generate", generate)
    await check("deepseek_stream", stream)
    await check("anythingllm_health", health)
    await check("anythingllm_retrieval", retrieve)
    report["ok"] = all(item["ok"] for item in report["checks"])
    report["finished_at"] = utc_now()
    return report


async def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime/logs/verify_live_ai.json")
    args = parser.parse_args(argv)
    # Do not let third-party HTTP exceptions print bodies, authenticated URLs or
    # headers through application logging. Evidence uses fixed error codes only.
    previous_log_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        from core.live_evidence import capture_binding, binding_unchanged
        runtime, settings, database = await load_runtime()
        before = capture_binding(settings)
        report = await run_probe(runtime, settings, database)
        after = capture_binding(settings)
        report["binding"] = {"start": before, "finish": after}
        if not binding_unchanged(before, after):
            report["checks"].append({"name": "runtime_unchanged", "ok": False,
                                     "error": "runtime_or_source_changed"})
            report["ok"] = False
    except Exception as exc:
        report = {"schema_version": 1, "scope": "deepseek_and_anythingllm_readonly", "ok": False,
                  "finished_at": utc_now(), "checks": [{"name": "configuration", "ok": False,
                  "error": str(exc) if isinstance(exc, ProbeFailure) else type(exc).__name__}]}
    finally:
        try:
            from core.shared_http import close_all_clients
            await close_all_clients()
        finally:
            logging.disable(previous_log_disable)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    except OSError as exc:
        print(json.dumps({"ok": False, "error": "evidence_write_failed", "type": type(exc).__name__}))
        return 1
    print(encoded)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
