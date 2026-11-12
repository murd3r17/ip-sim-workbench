"""系统管理模块服务"""
import os
import time
import platform
import sys
import asyncio
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from core.config import get_settings
from core.health import _app_start_time, get_health_status
from core.logger import get_logger
from core.llm_provider import cached_llm_health_check, create_llm_provider
from modules.system.models import SystemConfig, BackgroundTask, TaskStatus
from modules.auth.models import User, AuditLog
from modules.device.models import Device
from .runtime_config import safe_value

logger = get_logger("system")

LLM_CONFIG_KEYS = {
    "llm.provider": "llm_provider",
    "llm.base_url": "llm_base_url",
    "llm.model": "llm_model",
    "llm.api_key": "llm_api_key",
    "llm.max_tokens": "llm_max_tokens",
    "llm.temperature": "llm_temperature",
    # A5（设计 §8 配置内容补齐）：超时与备用模型
    "llm.timeout": "llm_timeout",
    "llm.fallback_model": "llm_fallback_model",
    "llm.fallback_base_url": "llm_fallback_base_url",
    "llm.fallback_api_key": "llm_fallback_api_key",
}
SECRET_CONFIG_KEYS = {
    "llm.api_key",
    "llm.fallback_api_key",
    "llm_api_key",
    "jwt_secret_key",
    "fernet_key",
    "db_password",
    "minio_secret_key",
    "rag_password",
    "rag_jwt_token",
    "knowledge_api_key",
    "device_default_password",
    "device_default_enable",
}
SECRET_VALUE_PLACEHOLDER = "******"


class SystemService:

    @staticmethod
    def _is_secret_key(config_key: str) -> bool:
        lowered = config_key.lower().strip()
        if lowered in SECRET_CONFIG_KEYS:
            return True
        if lowered.endswith((".password", "_password", ".secret", "_secret", ".token", "_token")):
            return True
        if lowered.endswith(".api_key") or lowered.endswith("_api_key"):
            return True
        return False

    @staticmethod
    def serialize_config(config: SystemConfig) -> dict[str, Any]:
        safe = safe_value(config.config_key,config.config_value)
        is_secret = SystemService._is_secret_key(config.config_key) or safe != config.config_value
        return {
            "id": config.id,
            "config_key": config.config_key,
            "config_value": SECRET_VALUE_PLACEHOLDER if is_secret and config.config_value not in (None, '') else safe,
            "description": config.description,
            "updated_by": config.updated_by,
            "created_at": config.created_at,
            "updated_at": config.updated_at,
            "is_secret": is_secret,
        }

    @staticmethod
    def serialize_configs(configs: list[SystemConfig]) -> list[dict[str, Any]]:
        return [SystemService.serialize_config(config) for config in configs]

    @staticmethod
    def _parse_runtime_value(key: str, value: str | None, fallback: Any) -> Any:
        from .runtime_config import resolve_value
        return resolve_value(key,value,fallback)[0]

    @staticmethod
    async def get_llm_runtime_config(db: AsyncSession) -> dict[str, Any]:
        return (await SystemService.get_llm_runtime_details(db))['values']

    @staticmethod
    async def get_llm_runtime_details(db: AsyncSession) -> dict[str, Any]:
        from .runtime_config import resolve_value
        settings = get_settings()
        result = await db.execute(select(SystemConfig).where(SystemConfig.config_key.in_(LLM_CONFIG_KEYS.keys())))
        runtime_configs = {item.config_key: item.config_value for item in result.scalars().all()}
        runtime: dict[str, Any] = {}; fields = {}
        for config_key, setting_key in LLM_CONFIG_KEYS.items():
            runtime[setting_key],fields[config_key] = resolve_value(
                config_key,
                runtime_configs.get(config_key),
                getattr(settings, setting_key),
            )
            if config_key in runtime_configs and runtime_configs[config_key] is None:
                fields[config_key]['override_status']='empty_fallback'
        return {'values':runtime,'fields':fields}

    @staticmethod
    async def get_llm_config_source(db: AsyncSession) -> str:
        """Legacy aggregate label; empty/invalid database rows do not imply an override.

        The effective-config view distinguishes mixed per-field sources and the
        process startup snapshot. `env` is retained for existing health clients.
        """
        details=await SystemService.get_llm_runtime_details(db)
        # Retain the legacy API source label; per-field view uses precise process_settings.
        return "system_config" if any(m['source']=='database' for m in details['fields'].values()) else "env"

    @staticmethod
    async def build_llm_provider(db: AsyncSession):
        runtime_config = await SystemService.get_llm_runtime_config(db)
        return create_llm_provider(runtime_config)

    @staticmethod
    async def get_system_info(db: AsyncSession) -> dict:
        settings = get_settings()

        # 数据库状态
        db_status = "healthy"
        try:
            async with db.begin_nested():
                await db.execute(text("SELECT 1"))
        except Exception:
            db_status = "unhealthy"

        # LLM状态
        llm_status = "unavailable"
        runtime_llm_config = {
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model,
        }
        try:
            runtime_llm_config = await SystemService.get_llm_runtime_config(db)
            provider = create_llm_provider(runtime_llm_config)
            is_healthy = await cached_llm_health_check(provider)
            llm_status = "healthy" if is_healthy else "unavailable"
        except Exception:
            llm_status = "unavailable"

        # 设备和用户数量
        device_count_result = await db.execute(select(func.count(Device.id)))
        device_count = device_count_result.scalar() or 0

        user_count_result = await db.execute(select(func.count(User.id)))
        user_count = user_count_result.scalar() or 0

        return {
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "platform": platform.platform(),
            "database_status": db_status,
            "llm_status": llm_status,
            "llm_provider": runtime_llm_config["llm_provider"],
            "llm_model": runtime_llm_config["llm_model"],
            "device_count": device_count,
            "user_count": user_count,
            "uptime_seconds": round(time.monotonic() - _app_start_time, 1),
            "log_level": settings.log_level,
            "fernet_configured": bool(settings.fernet_key),
            "jwt_configured": bool(settings.jwt_secret_key) and settings.jwt_secret_key != "CHANGE_ME",
        }

    @staticmethod
    async def get_config(db: AsyncSession, key: str) -> SystemConfig | None:
        result = await db.execute(select(SystemConfig).where(SystemConfig.config_key == key))
        return result.scalar_one_or_none()

    @staticmethod
    async def list_configs(db: AsyncSession) -> list[SystemConfig]:
        result = await db.execute(select(SystemConfig).order_by(SystemConfig.config_key))
        return list(result.scalars().all())

    @staticmethod
    async def set_config(db: AsyncSession, key: str, value: str | None, description: str | None, username: str) -> SystemConfig:
        result = await db.execute(select(SystemConfig).where(SystemConfig.config_key == key))
        config = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if config:
            if value is not None:
                config.config_value = value
            if description is not None:
                config.description = description
            config.updated_by = username
            config.updated_at = now
        else:
            config = SystemConfig(config_key=key, config_value=value, description=description, updated_by=username, created_at=now, updated_at=now)
            db.add(config)
        await db.flush()
        await db.refresh(config)
        return config

    @staticmethod
    async def delete_config(db: AsyncSession, key: str) -> bool:
        result = await db.execute(select(SystemConfig).where(SystemConfig.config_key == key))
        config = result.scalar_one_or_none()
        if not config:
            return False
        await db.delete(config)
        await db.commit()
        return True

    @staticmethod
    def build_config_audit_detail(config_key: str, description: str | None = None) -> dict[str, Any]:
        detail = {
            "config_key": config_key,
            "is_secret": SystemService._is_secret_key(config_key),
        }
        if description:
            detail["description"] = description[:256]
        return detail

    @staticmethod
    async def get_audit_logs(db: AsyncSession, page: int = 1, page_size: int = 20, module: str | None = None, user_id: int | None = None) -> dict:
        query = select(AuditLog)
        count_query = select(func.count(AuditLog.id))

        if module:
            query = query.where(AuditLog.module == module)
            count_query = count_query.where(AuditLog.module == module)
        if user_id:
            query = query.where(AuditLog.user_id == user_id)
            count_query = count_query.where(AuditLog.user_id == user_id)

        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        query = query.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        items = list(result.scalars().all())

        return {"items": items, "total": total, "page": page, "page_size": page_size}

    @staticmethod
    async def get_log_files(log_dir: str = "logs") -> list[dict]:
        def _scan():
            files = []
            if not os.path.isdir(log_dir):
                return files
            for filename in sorted(os.listdir(log_dir)):
                filepath = os.path.join(log_dir, filename)
                if not os.path.isfile(filepath):
                    continue
                stat = os.stat(filepath)
                line_count = 0
                try:
                    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                        line_count = sum(1 for _ in f)
                except Exception:
                    pass
                files.append({
                    "filename": filename,
                    "size_bytes": stat.st_size,
                    "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    "lines": line_count,
                })
            return files
        return await asyncio.to_thread(_scan)

    @staticmethod
    async def read_log_file(log_dir: str, filename: str, tail: int = 200) -> str:
        if ".." in filename or "/" in filename or "\\" in filename:
            raise ValueError("非法文件名")
        filepath = os.path.join(log_dir, filename)
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"日志文件不存在: {filename}")
        def _read():
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            return "".join(lines[-tail:])
        return await asyncio.to_thread(_read)

    @staticmethod
    async def create_task(db: AsyncSession, task_type: str, task_name: str, created_by: int | None = None) -> BackgroundTask:
        task = BackgroundTask(task_type=task_type, task_name=task_name, status=TaskStatus.PENDING, created_by=created_by)
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task

    @staticmethod
    async def update_task_status(db: AsyncSession, task_id: int, status: TaskStatus, progress: int = 0, result: str | None = None, error_message: str | None = None) -> BackgroundTask | None:
        task = await db.get(BackgroundTask, task_id)
        if not task:
            return None
        task.status = status
        task.progress = progress
        if result is not None:
            task.result = result
        if error_message is not None:
            task.error_message = error_message
        now = datetime.now(timezone.utc)
        if status == TaskStatus.RUNNING and not task.started_at:
            task.started_at = now
        if status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
            task.finished_at = now
        await db.commit()
        await db.refresh(task)
        return task

    @staticmethod
    async def list_tasks(db: AsyncSession, status: TaskStatus | None = None) -> list[BackgroundTask]:
        query = select(BackgroundTask)
        if status:
            query = query.where(BackgroundTask.status == status)
        result = await db.execute(query.order_by(BackgroundTask.created_at.desc()))
        return list(result.scalars().all())
