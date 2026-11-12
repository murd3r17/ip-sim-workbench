"""FastAPI应用入口"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from core.config import get_settings
from core.database import init_db, close_db, get_engine, get_session_factory
from core.exceptions import register_exception_handlers
from core.logger import setup_logging
from scheduler.monitor_scheduler import start_monitor_scheduler, shutdown_monitor_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging

    from core.preflight import check_startup_config

    preflight = check_startup_config(settings)
    for issue in preflight.issues:
        level = {"fatal": logging.ERROR, "warn": logging.WARNING, "info": logging.INFO}.get(issue.level, logging.INFO)
        logging.getLogger("preflight").log(
            level, "%s: %s%s", issue.key, issue.message, f" → {issue.hint}" if issue.hint else ""
        )
    if preflight.fatal:
        raise RuntimeError(
            "启动配置不完整：\n" + preflight.summary()
            + "\n\n检查【根目录 .env】（参考 .env.example）与 backend/.env。"
            "最快的办法：powershell -ExecutionPolicy Bypass -File scripts\\bootstrap-local.ps1"
        )
    # 预检里已包含 JWT/FERNET 的缺失与长度检查，这里只负责把问题暴露出来
    setup_logging()
    engine, session_factory = await init_db()
    start_monitor_scheduler()
    yield
    shutdown_monitor_scheduler()
    from core.shared_http import close_all_clients
    await close_all_clients()
    from modules.webssh.router import shutdown_terminal_tasks
    await shutdown_terminal_tasks()
    await close_db()


settings = get_settings()

app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    """基础安全响应头。

    前端由后端托管（最小运行模式）时，此前页面没有任何安全头；
    nginx 路径虽有配置，但直连 8000 时缺失，这里统一补上。
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # 允许同源、data: 图片与 blob:（xterm/echarts 需要）；内联样式是 Element Plus 的既有依赖
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' ws: wss:",
    )
    return response

register_exception_handlers(app)


@app.get("/api/v1/health")
async def health_check():
    from core.health import get_health_status
    from fastapi.responses import JSONResponse
    result = await get_health_status()
    status_code = 503 if result["status"] == "unhealthy" else 200
    return JSONResponse(content=result, status_code=status_code)


# 导入所有模型（确保SQLAlchemy能解析所有关系）
from modules.auth.models import User, AuditLog
from modules.device.models import Device, Topology, TopologyLink, TopologyVersion, TopologyRuntimeCheck
from modules.deploy.models import DeployTask, ConfigTemplate, ConfigVersion
from modules.monitor.models import MetricRecord, Alarm, MonitorJob
from modules.training.models import TrainingLab, TrainingSession, FaultInjection, OperationLog
from modules.ai_text.models import AILog

# 注册路由
from modules.auth.router import router as auth_router
from modules.device.router import router as device_router
from modules.webssh.router import router as webssh_router
from modules.ai_text.router import router as ai_router
from modules.deploy.router import router as deploy_router
from modules.monitor.router import router as monitor_router
from modules.training.router import router as training_router
from modules.system.router import router as system_router
from modules.dashboard.router import router as dashboard_router
from modules.trust.router import router as trust_router

app.include_router(auth_router, prefix="/api/v1")
app.include_router(device_router, prefix="/api/v1")
app.include_router(webssh_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")
app.include_router(deploy_router, prefix="/api/v1")
app.include_router(monitor_router, prefix="/api/v1")
app.include_router(training_router, prefix="/api/v1")
app.include_router(system_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(trust_router, prefix="/api/v1")


# ── 前端静态托管（可选）───────────────────────────────────────────────
# sim-frontend/dist 存在时由后端直接托管 SPA，运行期不再需要 Node/Vite。
# 这是"最小运行模式"的关键：他人克隆后只装 Python 就能打开界面。
_DIST_DIR = Path(__file__).resolve().parents[1] / "sim-frontend" / "dist"

if _DIST_DIR.is_dir():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    _assets_dir = _DIST_DIR / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """SPA 兜底：静态文件优先，其余交给 index.html 由前端路由处理。"""
        if full_path.startswith(("api/", "ws/")):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (_DIST_DIR / full_path).resolve()
        try:
            candidate.relative_to(_DIST_DIR)
        except ValueError:
            raise HTTPException(status_code=404, detail="Not Found")
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST_DIR / "index.html")
