from typing import Any
"""系统管理模块路由"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_async_session
from core.dependencies import require_role, get_current_user
from core.config import get_settings
from modules.auth.models import AuditLog
from modules.system.schemas import (
    SystemConfigCreate, SystemConfigUpdate, SystemConfigResponse,
    AuditLogResponse, AuditLogListResponse,
    BackgroundTaskResponse, BackgroundTaskListResponse,
    SystemInfoResponse, LogFileResponse,
)
from modules.system.service import SystemService
from modules.system.models import TaskStatus

router = APIRouter(prefix="/system", tags=["系统管理"])


@router.get("/runtime-identity")
async def get_runtime_identity(current_user: dict = Depends(require_role("admin"))) -> dict:
    from core.runtime_identity import runtime_identity
    return runtime_identity()


@router.get("/info", response_model=SystemInfoResponse)
async def get_system_info(db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(require_role("admin"))) -> Any:
    return await SystemService.get_system_info(db)


@router.get("/config", response_model=list[SystemConfigResponse])
async def list_config(db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(require_role("admin"))) -> Any:
    configs = await SystemService.list_configs(db)
    return SystemService.serialize_configs(configs)


@router.get("/effective-config", response_model=None)
async def get_effective_config(db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(require_role("admin"))) -> dict:
    from .runtime_config import effective_config
    return await effective_config(db)


@router.get("/config/{key}", response_model=SystemConfigResponse)
async def get_config(key: str, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(require_role("admin"))) -> Any:
    config = await SystemService.get_config(db, key)
    if not config:
        raise HTTPException(status_code=404, detail="配置项不存在")
    return SystemService.serialize_config(config)


@router.post("/config", response_model=SystemConfigResponse)
async def create_config(data: SystemConfigCreate, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(require_role("admin"))) -> Any:
    existing = await SystemService.get_config(db, data.config_key)
    if existing:
        raise HTTPException(status_code=409, detail="配置项已存在")
    config = await SystemService.set_config(db, data.config_key, data.config_value, data.description, current_user["username"])
    detail = SystemService.build_config_audit_detail(data.config_key, data.description)
    db.add(AuditLog(
        user_id=current_user["user_id"],
        username=current_user["username"],
        module="system",
        action="create_config",
        resource_type="system_config",
        resource_id=data.config_key,
        detail=str(detail),
        result="success",
    ))
    await db.commit()
    return SystemService.serialize_config(config)


@router.put("/config/{key}", response_model=SystemConfigResponse)
async def update_config(key: str, data: SystemConfigUpdate, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(require_role("admin"))) -> Any:
    config = await SystemService.get_config(db, key)
    if not config:
        raise HTTPException(status_code=404, detail="配置项不存在")
    config = await SystemService.set_config(db, key, data.config_value, data.description, current_user["username"])
    detail = SystemService.build_config_audit_detail(key, data.description)
    db.add(AuditLog(
        user_id=current_user["user_id"],
        username=current_user["username"],
        module="system",
        action="update_config",
        resource_type="system_config",
        resource_id=key,
        detail=str(detail),
        result="success",
    ))
    await db.commit()
    return SystemService.serialize_config(config)


@router.delete("/config/{key}", response_model=None)
async def delete_config(key: str, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(require_role("admin"))) -> dict[str, Any]:
    deleted = await SystemService.delete_config(db, key)
    if not deleted:
        raise HTTPException(status_code=404, detail="配置项不存在")
    db.add(AuditLog(
        user_id=current_user["user_id"],
        username=current_user["username"],
        module="system",
        action="delete_config",
        resource_type="system_config",
        resource_id=key,
        detail=str(SystemService.build_config_audit_detail(key)),
        result="success",
    ))
    await db.commit()
    return {"message": "删除成功"}


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    module: str = Query(None),
    user_id: int = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_role("admin")),
) -> Any:
    return await SystemService.get_audit_logs(db, page, page_size, module, user_id)


@router.get("/logs", response_model=None)
async def list_log_files(current_user: dict = Depends(require_role("admin"))) -> Any:
    settings = get_settings()
    return await SystemService.get_log_files(settings.log_dir)


@router.get("/logs/{filename}", response_model=None)
async def read_log_file(filename: str, tail: int = Query(200, ge=1, le=5000), current_user: dict = Depends(require_role("admin"))) -> dict[str, Any]:
    settings = get_settings()
    try:
        content = await SystemService.read_log_file(settings.log_dir, filename, tail)
        return {"filename": filename, "content": content, "lines_returned": content.count("\n")}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tasks", response_model=BackgroundTaskListResponse)
async def list_tasks(
    status: TaskStatus = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    tasks = await SystemService.list_tasks(db, status)
    return {"items": tasks, "total": len(tasks)}


@router.get("/tasks/{task_id}", response_model=BackgroundTaskResponse)
async def get_task(task_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(require_role("admin"))) -> Any:
    from modules.system.models import BackgroundTask
    task = await db.get(BackgroundTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.post("/health", response_model=None)
async def health_detail(db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    """健康详情（含 LLM 真实探测）。

    A5：模型"测试连通性"动作要求可审计（设计 §8），因此这里写一条 llm_test 审计；
    detail 只记结论与模型名，**不落任何 api_key**。
    """
    from core.health import get_health_status

    status = await get_health_status(db)
    llm = ((status or {}).get("components") or {}).get("llm") or {}
    db.add(AuditLog(
        user_id=current_user["user_id"],
        username=current_user["username"],
        module="system",
        action="llm_test",
        resource_type="llm_config",
        resource_id=llm.get("model") or "",
        detail=str({
            "status": llm.get("status"),
            "model": llm.get("model"),
            "provider": llm.get("provider"),
            "config_source": llm.get("config_source"),
        }),
        result="success" if llm.get("status") == "healthy" else "failed",
    ))
    await db.commit()
    return status


@router.post("/llm-health", response_model=None)
async def llm_health_detail(db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(require_role("admin"))) -> dict:
    from datetime import datetime,timezone
    from core.health import _probe_llm
    from core.llm_provider import _LLM_HEALTH_TTL_SECONDS
    from modules.auth.service import AuditService
    llm=await _probe_llm(get_settings(),db)
    await AuditService.log(db,current_user['user_id'],current_user['username'],'system','llm_test',
                           resource_type='llm_config',resource_id=llm.get('model') or '',
                           detail={k:llm.get(k) for k in ('status','model','provider','config_source')},
                           result='success' if llm.get('status')=='healthy' else 'failed')
    await db.commit()
    return {'components':{'llm':llm},'generated_at':datetime.now(timezone.utc).isoformat(),'cache_window_seconds':_LLM_HEALTH_TTL_SECONDS,
            'scope':'仅模型主/备用链路健康检查，可能复用短时缓存；不是回答质量、视觉、检索或设备验收。'}
