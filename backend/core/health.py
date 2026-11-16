"""健康检查探针"""
import time
from datetime import datetime, timezone
from core.config import get_settings
from core.logger import get_logger

logger = get_logger("health")
_app_start_time = time.monotonic()

_SIDE_HEALTH_CACHE: dict[str, tuple[float, dict]] = {}
_SIDE_HEALTH_TTL_SECONDS = 60.0


def _cache_get(key: str) -> dict | None:
    hit = _SIDE_HEALTH_CACHE.get(key)
    if hit is None:
        return None
    ts, value = hit
    if time.monotonic() - ts >= _SIDE_HEALTH_TTL_SECONDS:
        return None
    return value


def _cache_set(key: str, value: dict) -> dict:
    _SIDE_HEALTH_CACHE[key] = (time.monotonic(), value)
    return value


def _mark_degraded(overall: str) -> str:
    return "unhealthy" if overall == "unhealthy" else "degraded"


def database_component(components: dict) -> dict:
    """Read current and historical full-mode health payloads."""
    return components.get("database") or components.get("mysql") or {}


def _configured_value(value) -> bool:
    return bool(value and not str(value).strip().startswith("<"))


def llm_is_configured(settings, runtime=None) -> bool:
    values = runtime or {}
    def field(name):
        return values[name] if name in values else getattr(settings, name, "")

    provider = str(field("llm_provider") or "").lower()
    return bool(field("llm_base_url") and field("llm_model") and
                (provider == "ollama" or _configured_value(field("llm_api_key"))
                 or (field("llm_fallback_model") and _configured_value(field("llm_fallback_api_key")))))


async def _probe_minio(settings) -> dict:
    cached = _cache_get("minio")
    if cached is not None:
        return cached
    endpoint = (settings.minio_endpoint or "127.0.0.1:9002").strip()
    # 容错：配置里若带 scheme（http://host:9000）会拼出 http://http://… 恒不可用
    if "://" in endpoint:
        endpoint = endpoint.split("://", 1)[1].rstrip("/")
    scheme = "https" if settings.minio_secure else "http"
    url = f"{scheme}://{endpoint}/minio/health/live"
    try:
        from core.shared_http import get_managed_client
        client = get_managed_client(timeout=3.0, trust_env=False, follow_redirects=True)
        start = time.monotonic()
        resp = await client.get(url)
        latency = round((time.monotonic() - start) * 1000, 1)
        if resp.status_code < 400:
            return _cache_set("minio", {"status": "healthy", "latency_ms": latency})
        return _cache_set("minio", {"status": "unavailable", "http_status": resp.status_code})
    except Exception as exc:
        logger.warning("health_minio_failed", error=type(exc).__name__)
        return _cache_set("minio", {"status": "unavailable", "error": type(exc).__name__})


async def _probe_ollama() -> dict:
    cached = _cache_get("ollama")
    if cached is not None:
        return cached
    try:
        from core.shared_http import get_managed_client
        client = get_managed_client(timeout=3.0, trust_env=False, follow_redirects=True)
        start = time.monotonic()
        resp = await client.get("http://127.0.0.1:11434/api/tags")
        latency = round((time.monotonic() - start) * 1000, 1)
        if resp.status_code < 400:
            return _cache_set("ollama", {"status": "healthy", "latency_ms": latency})
        return _cache_set("ollama", {"status": "unavailable", "http_status": resp.status_code})
    except Exception as exc:
        logger.warning("health_ollama_failed", error=type(exc).__name__)
        return _cache_set("ollama", {"status": "unavailable", "error": type(exc).__name__})


async def _probe_knowledge() -> dict:
    cached = _cache_get("knowledge")
    if cached is not None:
        return cached
    settings = get_settings()
    try:
        from modules.knowledge.service import KnowledgeService
        khealth = await KnowledgeService.from_settings().health_check()
        available = bool(khealth.get("available"))
        result = {
            "status": "healthy" if available else "unavailable",
            "provider": khealth.get("provider") or settings.knowledge_provider,
            "document_count": khealth.get("document_count") or 0,
            "workspace_slug": khealth.get("workspace_slug") or settings.knowledge_workspace_slug,
        }
        if not available and khealth.get("error"):
            result["reason"] = "knowledge_probe_failed"
        return _cache_set("knowledge", result)
    except Exception as exc:
        logger.warning("health_knowledge_failed", error=type(exc).__name__)
        return _cache_set("knowledge", {
            "status": "unavailable",
            "provider": settings.knowledge_provider,
            "error": type(exc).__name__,
        })


async def get_knowledge_health_cached() -> dict:
    """带 TTL 缓存的知识库健康探测（公开入口）。

    首页聚合接口需要展示知识库状态；若每次请求都直连 AnythingLLM，外部服务慢/不可用时
    会把 `/dashboard/summary` 拖到 2s 以上（实测 P50≈2.1s，超过设计 §16 的 P95≤2s 底线）。
    这里复用 `/health` 的同一份探测与缓存，避免重复打外部服务。
    """
    return await _probe_knowledge()


async def _probe_llm(settings, db=None) -> dict:
    """LLM 探测优先读 system_config，失败再回退 .env。config_source 标明来源。"""
    runtime = None
    config_source = "env"
    try:
        from modules.system.service import SystemService
        if db is not None:
            runtime = await SystemService.get_llm_runtime_config(db)
            config_source = await SystemService.get_llm_config_source(db)
        else:
            from core.database import get_session_factory
            factory = get_session_factory()
            if factory is not None:
                async with factory() as session:
                    runtime = await SystemService.get_llm_runtime_config(session)
                    config_source = await SystemService.get_llm_config_source(session)
    except Exception as exc:
        logger.warning("health_llm_runtime_config_failed", error=type(exc).__name__)
        runtime = None
        config_source = "env"

    if not llm_is_configured(settings, runtime):
        return {"status": "disabled", "configured": False, "config_source": config_source,
                "provider": (runtime or {}).get("llm_provider") or settings.llm_provider}
    try:
        from core.llm_provider import cached_llm_health_check, create_llm_provider
        provider = create_llm_provider(runtime)
        is_healthy = await cached_llm_health_check(provider)
        return {
            "status": "healthy" if is_healthy else "unavailable",
            "provider": (runtime or {}).get("llm_provider") or settings.llm_provider,
            "model": (runtime or {}).get("llm_model") or settings.llm_model,
            "config_source": config_source,
            "configured": True,
        }
    except Exception:
        return {
            "status": "unavailable",
            "provider": (runtime or {}).get("llm_provider") or settings.llm_provider,
            "model": (runtime or {}).get("llm_model") or settings.llm_model,
            "config_source": config_source,
            "configured": True,
        }


async def get_health_status(db=None) -> dict:
    """获取系统健康状态。对话走 DeepSeek，Ollama 只服务嵌入，失败标 optional 不拖死整体。"""
    settings = get_settings()
    overall_status = "healthy"
    components = {}
    from core.database import get_engine
    engine = get_engine()
    db_backend = (db.get_bind().dialect.name if db is not None else engine.dialect.name if engine else
                  (settings.db_url.split(":", 1)[0].split("+", 1)[0] if settings.db_url else settings.db_backend))
    full = settings.workbench_mode == "full"
    profile = settings.workbench_mode if settings.workbench_mode != "auto" else (
        "minimal" if db_backend == "sqlite" and settings.device_mode == "sim" else "configured")

    # MySQL检查 —— 唯一能把整站打成 unhealthy 的组件
    try:
        from core.database import get_session_factory
        from sqlalchemy import text
        session_factory = get_session_factory()
        if session_factory is None:
            raise RuntimeError("数据库未初始化")
        start = time.monotonic()
        if db is not None:
            await db.execute(text("SELECT 1"))
        else:
            async with session_factory() as session:
                await session.execute(text("SELECT 1"))
        latency = round((time.monotonic() - start) * 1000, 1)
        components["database"] = {"status": "healthy", "latency_ms": latency}
    except Exception as e:
        overall_status = "unhealthy"
        components["database"] = {"status": "unhealthy", "error": type(e).__name__}
    components["database"].update(backend=db_backend, required=True, configured=True)
    if db_backend == "mysql":
        components["mysql"] = {**components["database"], "legacy_alias": True}

    components["llm"] = await _probe_llm(settings, db)
    components["llm"]["required"] = full

    minio_configured = all(_configured_value(getattr(settings, name)) for name in
                           ("minio_endpoint", "minio_access_key", "minio_secret_key"))
    components["minio"] = await _probe_minio(settings) if minio_configured else {"status": "disabled"}
    components["minio"].update(required=settings.minio_required, configured=minio_configured)

    embedding_configured = settings.knowledge_provider == "anythingllm" and _configured_value(settings.knowledge_api_key)
    components["ollama"] = dict(await _probe_ollama()) if embedding_configured else {"status": "disabled"}
    components["ollama"].update(optional=True, required=False, role="knowledge_embedding")

    components["knowledge"] = {**await _probe_knowledge(), "required": full or profile == "minimal"}
    for name in ("llm", "minio", "knowledge"):
        part = components[name]
        if part["status"] != "healthy" and (part.get("required") or part["status"] != "disabled"):
            overall_status = _mark_degraded(overall_status)
    ready = all(not part.get("required") or part["status"] == "healthy" for part in components.values())

    return {
        "status": overall_status,
        "ready": ready,
        "profile": profile,
        "version": settings.app_version,
        "uptime_seconds": round(time.monotonic() - _app_start_time, 1),
        "components": components,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }
