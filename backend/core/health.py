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
            result["error"] = str(khealth.get("error"))
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

    try:
        from core.llm_provider import cached_llm_health_check, create_llm_provider
        provider = create_llm_provider(runtime)
        is_healthy = await cached_llm_health_check(provider)
        return {
            "status": "healthy" if is_healthy else "unavailable",
            "provider": (runtime or {}).get("llm_provider") or settings.llm_provider,
            "model": (runtime or {}).get("llm_model") or settings.llm_model,
            "config_source": config_source,
        }
    except Exception:
        return {
            "status": "unavailable",
            "provider": (runtime or {}).get("llm_provider") or settings.llm_provider,
            "model": (runtime or {}).get("llm_model") or settings.llm_model,
            "config_source": config_source,
        }


async def get_health_status(db=None) -> dict:
    """获取系统健康状态。对话走 DeepSeek，Ollama 只服务嵌入，失败标 optional 不拖死整体。"""
    settings = get_settings()
    overall_status = "healthy"
    components = {}

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
        components["mysql"] = {"status": "healthy", "latency_ms": latency}
    except Exception as e:
        overall_status = "unhealthy"
        components["mysql"] = {"status": "unhealthy", "error": str(e)}

    components["llm"] = await _probe_llm(settings, db)
    if components["llm"].get("status") != "healthy":
        overall_status = _mark_degraded(overall_status)

    components["minio"] = await _probe_minio(settings)
    if components["minio"].get("status") != "healthy":
        overall_status = _mark_degraded(overall_status)

    components["ollama"] = await _probe_ollama()
    if components["ollama"].get("status") != "healthy":
        components["ollama"]["optional"] = True
        components["ollama"]["role"] = "knowledge_embedding"

    components["knowledge"] = await _probe_knowledge()
    if components["knowledge"].get("status") != "healthy":
        overall_status = _mark_degraded(overall_status)

    return {
        "status": overall_status,
        "version": settings.app_version,
        "uptime_seconds": round(time.monotonic() - _app_start_time, 1),
        "components": components,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }
