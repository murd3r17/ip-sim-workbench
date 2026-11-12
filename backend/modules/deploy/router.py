from typing import Any
"""配置下发模块路由"""
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from core.database import get_async_session
from core.dependencies import get_current_user, require_role
from core.exceptions import parse_enum
from core.logger import get_logger
from core.rate_limiter import rate_limit
from core.redaction import redact_payload, redact_sensitive
from core.time_utils import iso_utc
from core.record_origin import declared_origin
from modules.deploy.service import DeployService
from modules.deploy.config_template_engine import ConfigTemplateEngine, TemplateRenderError
from modules.deploy.config_verifier import ConfigVerifier
from modules.deploy.models import DeployBatch, DeployTask, DeployStatus, ChangeLevel, ConfigTemplate, ConfigVersion
from modules.deploy.schemas import (
    DeployRequest, DeployResponse, TemplateCreate, TemplateResponse,
    ConfigVersionResponse, VerifyBatchRequest, TemplateRenderRequest,
    TemplateValidateRequest, ConfigValidateRequest, DeployConfirmRequest, DeployBatchCreateRequest, SnapshotCaptureRequest,
)
from modules.deploy.vrp_validator import VRPValidator
from modules.auth.service import AuditService
from modules.auth.models import AuditLog
from modules.device.models import Device
from core.exceptions import DeviceLockError
from modules.deploy.schemas import ExecuteResponse

logger = get_logger("deploy")
router = APIRouter(tags=["配置下发"])

# 下发/执行/回滚等写操作按 IP+路径限流（30 次/分）
_DEPLOY_RATE_LIMIT = rate_limit(max_requests=30, window_seconds=60)


@router.post("/deploy/batches", dependencies=[Depends(_DEPLOY_RATE_LIMIT)], response_model=None)
async def create_deploy_batch(
    data: DeployBatchCreateRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_role("admin", "user")),
) -> Any:
    """创建具名配置任务；每个设备配置为独立待确认执行项。"""
    try:
        return await DeployService.create_batch(
            db,
            name=data.name,
            description=data.description,
            source=data.source,
            planned_at=data.planned_at,
            items=data.items,
            engine=data.engine,
            operator_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _task_stage(task: DeployTask) -> str:
    if task.status == DeployStatus.SUCCESS:
        return "success"
    if task.status in {DeployStatus.FAILED, DeployStatus.ROLLED_BACK, DeployStatus.CANCELLED}:
        return "failed"
    if task.status == DeployStatus.DEPLOYING:
        return "deploying"
    if task.status == DeployStatus.VERIFYING:
        return "readback"
    if task.status == DeployStatus.CONFIRMED:
        return "waiting"
    return "pending"


@router.get("/deploy/batches", response_model=None)
async def list_deploy_batches(
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    query = select(DeployBatch).order_by(DeployBatch.created_at.desc())
    if current_user["role"] != "admin":
        # 非管理员只能看到自己创建的批次（含 config_content 原文）
        query = query.where(DeployBatch.operator_id == current_user["user_id"])
    batches = (await db.execute(query)).scalars().all()
    if not batches:
        return []
    batch_ids = [batch.id for batch in batches]
    tasks = (await db.execute(
        select(DeployTask).where(DeployTask.batch_id.in_(batch_ids))
    )).scalars().all()
    by_batch: dict[int, list[DeployTask]] = {}
    for task in tasks:
        by_batch.setdefault(task.batch_id, []).append(task)

    result = []
    for batch in batches:
        items = by_batch.get(batch.id, [])
        stages = [_task_stage(task) for task in items]
        result.append({
            "id": batch.id,
            "name": batch.name,
            "source": batch.source,
            "record_origin": declared_origin(batch.source),
            "planned_at": iso_utc(batch.planned_at),
            "created_at": batch.created_at,
            "operator_id": batch.operator_id,
            "items": [
                {
                    "id": task.id,
                    "device_id": task.device_id,
                    "config_content": task.config_content,
                    "status": task.status.value,
                    "stage": _task_stage(task),
                    "execution_mode": task.execution_mode,
                }
                for task in items
            ],
            "summary": {
                "total": len(items),
                "pending": sum(s == "pending" for s in stages),
                "running": sum(s in {"deploying", "readback"} for s in stages),
                "success": sum(s == "success" for s in stages),
                "failed": sum(s == "failed" for s in stages),
            },
        })
    return redact_payload(result)


@router.get("/deploy/batches/{batch_id}", response_model=None)
async def get_deploy_batch(
    batch_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    batch = await db.get(DeployBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="任务不存在")
    if current_user["role"] != "admin" and batch.operator_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="无权查看此任务（仅创建者或管理员）")
    tasks = (await db.execute(
        select(DeployTask).where(DeployTask.batch_id == batch.id).order_by(DeployTask.id)
    )).scalars().all()
    stages = [_task_stage(task) for task in tasks]
    from modules.device.models import Device as _Device
    device_rows = (await db.execute(select(_Device.id, _Device.hostname))).all()
    device_names = {row[0]: row[1] for row in device_rows}
    return redact_payload({
        "id": batch.id,
        "name": batch.name,
        "description": batch.description,
        "source": batch.source,
        "record_origin": declared_origin(batch.source),
        "planned_at": iso_utc(batch.planned_at),
        "created_at": batch.created_at,
        "summary": {
            "total": len(tasks), "pending": sum(stage == "pending" for stage in stages),
            "running": sum(stage in {"deploying", "readback"} for stage in stages),
            "success": sum(stage == "success" for stage in stages), "failed": sum(stage == "failed" for stage in stages),
        },
        "items": [
            {
                "id": task.id, "device_id": task.device_id, "config_content": task.config_content,
                # hostname/error_message：确认是不可逆授权，界面只写"设备 7"学员认不出是哪台；
                # 失败时也要能直接看到原因，而不是让他去猜任务项 ID（2026-10-05 UX 审计）
                "hostname": device_names.get(task.device_id, ""),
                "error_message": task.error_message,
                "status": task.status.value, "stage": _task_stage(task),
                "execution_mode": task.execution_mode,
                "links": {
                    "change_log": f"/config-versions?tab=logs&task_id={task.id}",
                    "snapshot": f"/config-versions?tab=snapshots&task_id={task.id}",
                    "compare": f"/config-versions?tab=compare&task_id={task.id}",
                },
            }
            for task in tasks
        ],
    })


@router.get("/deploy/change-logs", response_model=None)
async def list_deploy_change_logs(task_id: int | None = None, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> list[Any]:
    query = select(AuditLog).where(AuditLog.module == "deploy")
    if task_id:
        query = query.where(AuditLog.resource_id == str(task_id))
    if current_user["role"] != "admin":
        # 非管理员只能看到自己的下发审计
        query = query.where(AuditLog.user_id == current_user["user_id"])
    logs = (await db.execute(query.order_by(AuditLog.created_at.desc()))).scalars().all()
    return redact_payload([{"id": log.id, "task_id": log.resource_id, "action": log.action, "result": log.result, "created_at": iso_utc(log.created_at), "detail": log.detail} for log in logs])


@router.post("/deploy", response_model=DeployResponse, dependencies=[Depends(_DEPLOY_RATE_LIMIT)])
async def create_deploy(data: DeployRequest, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(require_role("admin", "user"))) -> Any:
    """创建配置下发任务"""
    try:
        change_level = ChangeLevel(data.change_level)
        result = await DeployService.create_pending_tasks(
            db, data.device_ids, data.config_content, data.template_id,
            change_level, data.engine, current_user["user_id"]
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/deploy/tasks/{task_id}/confirm", dependencies=[Depends(_DEPLOY_RATE_LIMIT)], response_model=None)
async def confirm_deploy_task(task_id: int, data: DeployConfirmRequest, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    try:
        task = await DeployService.confirm_task(db, task_id, current_user, data.risk_confirm)
        return {"task_id": task.id, "status": task.status.value}
    except DeviceLockError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/deploy/tasks/{task_id}/execute", response_model=ExecuteResponse, dependencies=[Depends(_DEPLOY_RATE_LIMIT)])
async def execute_deploy_task(
    task_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """执行已确认且持锁的任务；默认模拟执行。"""
    try:
        result = await DeployService.execute_task(db, task_id, current_user)
        return result
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        detail = str(exc)
        status = 409 if "锁" in detail or "状态" in detail else 422
        raise HTTPException(status_code=status, detail=detail)


@router.post("/deploy/tasks/{task_id}/cancel", response_model=None)
async def cancel_deploy_task(
    task_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """取消未终结的任务并释放设备写锁（设备被残留锁卡住时的人工恢复入口）。"""
    try:
        return await DeployService.cancel_task(db, task_id, current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/deploy/tasks", response_model=None)
async def list_deploy_tasks(status: str = None, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> list[Any]:
    """获取下发任务列表。

    `has_lock`：该任务当前是否持有设备写锁（审批页需要知道"确认后能否直接执行"）。
    一次查询取回全部锁的 (device_id, task_id)，避免逐任务查询。
    """
    query = select(DeployTask)
    if status:
        query = query.where(DeployTask.status == parse_enum(DeployStatus, status, "status"))
    if current_user["role"] != "admin":
        # 非管理员只能看到自己创建的任务
        query = query.where(DeployTask.operator_id == current_user["user_id"])
    result = await db.execute(query.order_by(DeployTask.created_at.desc()))
    tasks = list(result.scalars().all())

    batch_ids={t.batch_id for t in tasks if t.batch_id is not None}
    sources=dict((await db.execute(select(DeployBatch.id,DeployBatch.source).where(DeployBatch.id.in_(batch_ids)))).all()) if batch_ids else {}

    from modules.deploy.models import DeviceWriteLock
    lock_rows = (await db.execute(select(DeviceWriteLock.device_id, DeviceWriteLock.task_id))).all()
    locked_tasks = {row[1] for row in lock_rows}

    return [
        {
            "id": t.id,
            "transaction_id": t.transaction_id,
            "source": sources.get(t.batch_id),
            "record_origin": declared_origin(sources.get(t.batch_id)),
            "device_id": t.device_id,
            "status": t.status.value,
            "engine": t.engine,
            "change_level": t.change_level.value,
            "error_message": redact_sensitive(t.error_message),
            "has_lock": t.id in locked_tasks,
            "execution_mode": t.execution_mode,
            "created_at": iso_utc(t.created_at),
        }
        for t in tasks
    ]


@router.get("/deploy/tasks/{task_id}", response_model=None)
async def get_deploy_task(task_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """获取下发任务详情"""
    task = await db.get(DeployTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if current_user["role"] != "admin" and task.operator_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="无权查看此任务（仅创建者或管理员）")
    from modules.deploy.models import DeviceWriteLock as _Lock
    lock = await db.get(_Lock, task.device_id)
    batch = await db.get(DeployBatch,task.batch_id) if task.batch_id else None
    return redact_payload({
        "id": task.id, "transaction_id": task.transaction_id, "device_id": task.device_id,
        "batch_id": task.batch_id,
        "source": batch.source if batch else None,
        "record_origin": declared_origin(batch.source if batch else None),
        # change_level/has_lock：审批详情要显示风险级别与是否持锁（此前详情恒显 "-"，与列表标签矛盾）
        "change_level": task.change_level.value,
        "has_lock": bool(lock and lock.task_id == task.id),
        "status": task.status.value, "engine": task.engine, "config_content": task.config_content,
        "result_output": task.result_output, "error_message": task.error_message,
        "backup_config": task.backup_config, "verified": task.verified, "verify_diff": task.verify_diff,
        "rollback_output": task.rollback_output,
        "confirmed_by": task.confirmed_by, "confirmed_at": iso_utc(task.confirmed_at),
        "risk_confirmed_by": task.risk_confirmed_by, "risk_confirmed_at": iso_utc(task.risk_confirmed_at),
        "started_at": iso_utc(task.started_at), "completed_at": iso_utc(task.completed_at),
        "execution_mode": task.execution_mode,
        "created_at": iso_utc(task.created_at)
    })


@router.get("/config-versions", response_model=list[ConfigVersionResponse])
async def list_config_versions(device_id: int = None, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    """获取配置版本列表"""
    query = select(ConfigVersion)
    if device_id:
        query = query.where(ConfigVersion.device_id == device_id)
    result = await db.execute(query.order_by(ConfigVersion.created_at.desc()))
    return result.scalars().all()


@router.post("/config-versions/capture", dependencies=[Depends(_DEPLOY_RATE_LIMIT)], response_model=None)
async def capture_config_versions(data: SnapshotCaptureRequest, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(require_role("admin", "user"))) -> Any:
    try:
        return await DeployService.capture_snapshots(db, data.device_ids, current_user["user_id"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/config-templates", response_model=TemplateResponse, dependencies=[Depends(_DEPLOY_RATE_LIMIT)])
async def create_template(data: TemplateCreate, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    """创建配置模板"""
    errors = ConfigTemplateEngine().validate_variables(data.content, data.variables)
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    template = ConfigTemplate(name=data.name, description=data.description, content=data.content, variables=data.variables, category=data.category, created_by=current_user["user_id"])
    db.add(template)
    await db.commit()
    await db.refresh(template)
    detail = json.dumps({"template_name": template.name, "variable_names": sorted((data.variables or {}).keys())}, ensure_ascii=False)[:1000]
    await AuditService.log(db, current_user["user_id"], current_user.get("username", ""), "deploy", "template_created", "config_template", str(template.id), {"summary": detail})
    return template


@router.get("/config-templates", response_model=list[TemplateResponse])
async def list_templates(db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    """获取配置模板列表"""
    result = await db.execute(select(ConfigTemplate).order_by(ConfigTemplate.created_at.desc()))
    return result.scalars().all()


@router.post("/deploy/validate", dependencies=[Depends(_DEPLOY_RATE_LIMIT)], response_model=None)
async def validate_config(data: ConfigValidateRequest, current_user: dict = Depends(get_current_user)) -> Any:
    """校验配置内容"""
    return redact_payload(VRPValidator().assess(data.config_content, data.device_model))


@router.get("/config-versions/compare", response_model=None)
async def compare_versions(version1: int, version2: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """对比两个配置版本"""
    v1 = await db.get(ConfigVersion, version1)
    v2 = await db.get(ConfigVersion, version2)
    if not v1 or not v2:
        raise HTTPException(status_code=404, detail="版本不存在")
    snapshot1 = redact_sensitive(v1.config_snapshot or "")
    snapshot2 = redact_sensitive(v2.config_snapshot or "")
    return {
        "diff": ConfigVerifier.compare(snapshot1, snapshot2),
        "display_diff": ConfigVerifier.compare(snapshot1, snapshot2, preserve_case=True),
        "same_device": v1.device_id == v2.device_id,
        "version1": {
            "id": v1.id,
            "device_id": v1.device_id,
            "source": v1.source,
            "version_number": v1.version_number,
            "config_snapshot": snapshot1,
            "created_at": iso_utc(v1.created_at)
        },
        "version2": {
            "id": v2.id,
            "device_id": v2.device_id,
            "source": v2.source,
            "version_number": v2.version_number,
            "config_snapshot": snapshot2,
            "created_at": iso_utc(v2.created_at)
        }
    }


@router.post("/config-versions/{version_id}/rollback", dependencies=[Depends(_DEPLOY_RATE_LIMIT)], response_model=None)
async def rollback_version(version_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    """旧版本回滚入口已禁用（会绕过写锁与授权校验）。

    B2 起请使用 `POST /deploy/config-versions/{version_id}/rollback-task`：它只生成一个
    高风险回滚任务，仍需人工确认后才进入既有的受控执行/验证链路。
    """
    raise HTTPException(status_code=409, detail="请通过受控回滚任务执行：POST /deploy/config-versions/{id}/rollback-task")


@router.post("/deploy/config-versions/{version_id}/rollback-task", dependencies=[Depends(_DEPLOY_RATE_LIMIT)], response_model=None)
async def create_rollback_task(version_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    """由历史配置版本生成受控回滚任务（B2：阶段4.8 配置版本回滚）。"""
    try:
        return await DeployService.create_rollback_task(db, version_id, current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── P3-D2: 事务下发 + SSE + 验证 + 模板引擎 ──────────────────────────


@router.post("/deploy/transaction", response_model=DeployResponse, dependencies=[Depends(_DEPLOY_RATE_LIMIT)])
async def create_transaction_deploy(
    data: DeployRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_role("admin", "user")),
) -> Any:
    """旧事务下发入口在阶段4中禁用，避免绕过确认、写锁和服务端模拟开关。"""
    raise HTTPException(status_code=409, detail="请使用受控部署任务流程")


@router.post("/deploy/transaction/stream", dependencies=[Depends(_DEPLOY_RATE_LIMIT)], response_model=None)
async def stream_deploy_progress(
    data: DeployRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_role("admin", "user")),
) -> Any:
    """旧事务SSE入口同样禁用，防止以流式接口绕过受控部署链路。"""
    raise HTTPException(status_code=409, detail="请使用受控部署任务流程")


@router.post("/deploy/tasks/{task_id}/verify", dependencies=[Depends(_DEPLOY_RATE_LIMIT)], response_model=None)
async def verify_deploy_task(
    task_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """验证单个下发任务的配置一致性（双写验证）"""
    try:
        return redact_payload(await DeployService.verify_task(db, task_id, current_user))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        raise HTTPException(status_code=409 if "锁" in detail or "状态" in detail else 422, detail=detail)


@router.post("/deploy/tasks/verify-batch", dependencies=[Depends(_DEPLOY_RATE_LIMIT)], response_model=None)
async def verify_deploy_batch(
    data: VerifyBatchRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> list[Any]:
    """批量验证下发任务"""
    try:
        return redact_payload([await DeployService.verify_task(db, task_id, current_user) for task_id in data.task_ids])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        # 与单条接口保持一致的异常映射（此前状态不符/无锁会返回 500）
        detail = str(e)
        raise HTTPException(status_code=409 if "锁" in detail or "状态" in detail else 422, detail=detail)


@router.post("/config-templates/render", dependencies=[Depends(_DEPLOY_RATE_LIMIT)], response_model=None)
async def render_template(
    data: TemplateRenderRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """渲染配置模板"""
    engine = ConfigTemplateEngine()
    valid, errors = engine.validate_template(data.content)
    if not valid:
        raise HTTPException(status_code=422, detail=errors)

    errors = engine.validate_variables(data.content, data.declarations, data.variables)
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))

    try:
        rendered = engine.render(data.content, data.variables)
        detail = json.dumps({"variable_names": engine.extract_variables(data.content)}, ensure_ascii=False)[:1000]
        await AuditService.log(db, current_user["user_id"], current_user.get("username", ""), "deploy", "template_previewed", "config_template", None, {"summary": detail})
        return {"rendered": rendered, "variables_used": engine.extract_variables(data.content), "validation_errors": []}
    except TemplateRenderError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/config-templates/validate", dependencies=[Depends(_DEPLOY_RATE_LIMIT)], response_model=None)
async def validate_template(
    data: TemplateValidateRequest,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """校验模板语法"""
    engine = ConfigTemplateEngine()
    valid, errors = engine.validate_template(data.content)
    variables = engine.extract_variables(data.content) if valid else []
    return {"valid": valid, "errors": errors, "variables": variables}
