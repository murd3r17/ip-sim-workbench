"""设备管理模块路由"""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Any
from core.database import get_async_session
from core.dependencies import get_current_user
from modules.device.service import DeviceService, TopologyService
from modules.device.schemas import (
    DeviceCreate,
    DeviceUpdate,
    DeviceResponse,
    RuntimeCheckResponse,
    RuntimeBaselineConfirmationResult,
    SnapshotDiffResponse,
    TopologyCreate,
    TopologyImportPreview,
    TopologyImportResult,
    TopologyResponse,
    TopologyRollbackResult,
    TopologyVersionResponse,
    TopologyLinkResponse,
    TopologyLinkCreate,
    TopologyLayoutResponse,
    TopologyLayoutUpdate,
)
from modules.device.models import DeviceStatus
from modules.device.baseline_service import TopologyBaselineService
from modules.auth.service import AuditService
from core.exceptions import AppException, parse_enum
from core.rate_limiter import rate_limit

router = APIRouter(tags=["设备管理"])

# 批量 SSH 健康检查是"放大"动作（一次请求探测全部设备），单独限流
_HEALTH_RATE_LIMIT = rate_limit(max_requests=6, window_seconds=60)


@router.get("/devices", response_model=list[DeviceResponse])
async def list_devices(topology_id: Optional[int] = Query(None), status: Optional[str] = Query(None), db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    if topology_id:
        device_status = parse_enum(DeviceStatus, status, "status") if status else None
        devices = await DeviceService.get_devices_by_topology(db, topology_id, device_status)
    else:
        from sqlalchemy import select
        from modules.device.models import Device
        query = select(Device)
        if status:
            query = query.where(Device.status == parse_enum(DeviceStatus, status, "status"))
        result = await db.execute(query)
        devices = list(result.scalars().all())
    return devices


@router.post("/devices", response_model=DeviceResponse)
async def create_device(data: DeviceCreate, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    if current_user["role"] not in ["admin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    try:
        device = await DeviceService.create_device(db, data.model_dump())
        return device
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/devices/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    try:
        return await DeviceService.get_device(db, device_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/devices/{device_id}", response_model=DeviceResponse)
async def update_device(device_id: int, data: DeviceUpdate, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    if current_user["role"] not in ["admin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    try:
        return await DeviceService.update_device(db, device_id, data.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/devices/{device_id}", response_model=None)
async def delete_device(device_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    if current_user["role"] not in ["admin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    try:
        await DeviceService.delete_device(db, device_id)
        return {"message": "设备已删除"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/devices/{device_id}/status", response_model=None)
async def update_device_status(device_id: int, status: str, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    try:
        return await DeviceService.update_device_status(db, device_id, parse_enum(DeviceStatus, status, "status"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/topologies", response_model=list[TopologyResponse])
async def list_topologies(db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    return await TopologyService.list_topologies(db)


@router.post("/topologies", response_model=TopologyResponse)
async def create_topology(data: TopologyCreate, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    if current_user["role"] not in ["admin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    payload = data.model_dump()
    payload["owner_id"] = current_user["user_id"]
    return await TopologyService.create_topology(db, payload)


@router.get("/topologies/{topology_id}", response_model=TopologyResponse)
async def get_topology(topology_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    try:
        return await TopologyService.get_topology(db, topology_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/topologies/{topology_id}/layout", response_model=TopologyLayoutResponse)
async def get_topology_layout(topology_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    try:
        return await TopologyService.get_layout(db, topology_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/topologies/{topology_id}/layout/draft", response_model=TopologyLayoutResponse)
async def save_topology_layout_draft(topology_id: int, data: TopologyLayoutUpdate, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    if current_user["role"] not in ["admin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    try:
        layout = await TopologyService.save_layout_draft(
            db, topology_id, data.positions, current_user["username"]
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await AuditService.log(
        db, current_user["user_id"], current_user["username"], "device", "save_layout_draft",
        "topology", str(topology_id), {"position_count": len(data.positions)},
    )
    return layout


@router.post("/topologies/{topology_id}/layout/publish", response_model=TopologyLayoutResponse)
async def publish_topology_layout(topology_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    if current_user["role"] not in ["admin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    try:
        layout = await TopologyService.publish_layout(db, topology_id, current_user["username"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await AuditService.log(
        db, current_user["user_id"], current_user["username"], "device", "publish_layout",
        "topology", str(topology_id), {"position_count": len(layout["published_positions"])},
    )
    return layout


@router.post("/devices/health-check", dependencies=[Depends(_HEALTH_RATE_LIMIT)], response_model=None)
async def check_all_devices_health(
    topology_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
) -> dict[str, Any]:
    """批量检查所有设备SSH健康状态并更新（从配置获取凭证，不暴露密码）。

    这是会对全部设备发起 SSH 探测的"放大"动作，因此加限流 + 审计留痕。
    """
    results = await DeviceService.check_all_devices_health(db, topology_id)
    await AuditService.log(
        db, current_user["user_id"], current_user.get("username", ""), "device",
        "device_health_check", "topology", str(topology_id or ""),
        {"total": len(results)},
    )
    return {"total": len(results), "results": results}


@router.get("/topologies/{topology_id}/links", response_model=list[TopologyLinkResponse])
async def get_topology_links(topology_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    return await TopologyService.get_links(db, topology_id)


async def _read_excel(file: UploadFile) -> bytes:
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="仅支持.xlsx文件")
    content = await file.read()
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Excel文件不能为空且不能超过10MB")
    return content


@router.post("/topologies/{topology_id}/imports/validate", response_model=TopologyImportPreview)
async def validate_topology_import(
    topology_id: int,
    inventory_only: bool = Query(False),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    try:
        preview = await TopologyBaselineService.preview(db, topology_id, await _read_excel(file), inventory_only=inventory_only)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return preview


@router.post("/topologies/{topology_id}/imports", response_model=TopologyImportResult)
async def import_topology_baseline(
    topology_id: int,
    confirm: bool = Query(False),
    inventory_only: bool = Query(False),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    if not confirm:
        raise HTTPException(status_code=409, detail="导入前必须确认")
    try:
        result = await TopologyBaselineService.import_workbook(
            db,
            topology_id,
            await _read_excel(file),
            file.filename or "baseline.xlsx",
            current_user["user_id"],
            inventory_only=inventory_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await AuditService.log(
        db,
        current_user["user_id"],
        current_user["username"],
        "device",
        "topology_baseline_import",
        "topology",
        str(topology_id),
        {"version": result["version"], "device_count": result["device_count"], "link_count": result["link_count"],
         "inventory_only": inventory_only, "source_type": result["source_type"]},
    )
    return result


@router.post(
    "/topologies/{topology_id}/runtime-checks/{runtime_check_id}/confirm-baseline",
    response_model=RuntimeBaselineConfirmationResult,
)
async def confirm_runtime_topology_baseline(
    topology_id: int,
    runtime_check_id: int,
    confirm: bool = Query(False),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    if not confirm:
        raise HTTPException(status_code=409, detail="固化基线前必须确认")
    try:
        result = await TopologyBaselineService.confirm_runtime_baseline(
            db, topology_id, runtime_check_id, current_user["user_id"]
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await AuditService.log(
        db,
        current_user["user_id"],
        current_user["username"],
        "device",
        "topology_runtime_baseline_confirmed",
        "topology",
        str(topology_id),
        {"version": result["version"], "runtime_check_id": runtime_check_id, "link_count": result["link_count"]},
    )
    return result


@router.get("/topologies/{topology_id}/versions", response_model=list[TopologyVersionResponse])
async def list_topology_versions(
    topology_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    return await TopologyBaselineService.list_versions(db, topology_id)


@router.get("/topologies/{topology_id}/versions/{version}/diff", response_model=SnapshotDiffResponse)
async def diff_topology_version(
    topology_id: int,
    version: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    try:
        return await TopologyBaselineService.diff_version(db, topology_id, version)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/topologies/{topology_id}/versions/{version}/rollback", response_model=TopologyRollbackResult)
async def rollback_topology_version(
    topology_id: int,
    version: int,
    confirm: bool = Query(False),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    if not confirm:
        raise HTTPException(status_code=409, detail="回滚前必须确认")
    try:
        result = await TopologyBaselineService.rollback(
            db, topology_id, version, current_user["user_id"]
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await AuditService.log(
        db,
        current_user["user_id"],
        current_user["username"],
        "device",
        "topology_baseline_rollback",
        "topology",
        str(topology_id),
        {"version": result["version"], "rollback_of_version": version},
    )
    return result


@router.post("/topologies/{topology_id}/discover", response_model=RuntimeCheckResponse)
async def discover_topology_links(topology_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    """LLDP自动发现拓扑链路 - SSH连接所有设备执行display lldp neighbor brief，解析结果更新拓扑"""
    if current_user["role"] not in ["admin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    try:
        result = await TopologyService.discover_via_lldp(db, topology_id)
        return result
    except AppException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLDP发现失败: {str(e)}")


@router.get("/topologies/{topology_id}/runtime-checks/latest", response_model=RuntimeCheckResponse | None)
async def get_latest_topology_runtime_check(
    topology_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    return await TopologyService.get_latest_runtime_check(db, topology_id)


@router.post("/topologies/{topology_id}/links", response_model=None)
async def create_topology_link(topology_id: int, data: TopologyLinkCreate, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """创建拓扑链路（仅管理员；基线变更仍以 Excel 导入/运行态固化为主入口）。"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    from sqlalchemy import select as _select
    from modules.device.models import Device as _Device
    ids = {data.source_device_id, data.target_device_id}
    rows = (await db.execute(_select(_Device.id, _Device.topology_id).where(_Device.id.in_(ids)))).all()
    found = {row[0]: row[1] for row in rows}
    missing = ids - set(found)
    if missing:
        raise HTTPException(status_code=404, detail=f"设备不存在: {sorted(missing)}")
    wrong = sorted(device_id for device_id, topo in found.items() if topo != topology_id)
    if wrong:
        raise HTTPException(status_code=422, detail=f"设备不属于拓扑 {topology_id}: {wrong}")
    try:
        link = await TopologyService.add_link(
            db, topology_id,
            data.source_device_id, data.source_interface,
            data.target_device_id, data.target_interface,
            data.discovery_source
        )
        await AuditService.log(
            db, current_user["user_id"], current_user.get("username", ""), "device",
            "topology_link_created", "topology", str(topology_id),
            {"link_id": link.id, "source_device_id": data.source_device_id,
             "target_device_id": data.target_device_id},
        )
        return {
            "id": link.id,
            "source_device_id": link.source_device_id,
            "source_interface": link.source_interface,
            "target_device_id": link.target_device_id,
            "target_interface": link.target_interface,
            "link_type": link.link_type,
            "status": link.status
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/topologies/{topology_id}/links/bulk-import", response_model=None)
async def bulk_import_topology_links(topology_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    """Deprecated: static link data is no longer an accepted baseline source."""
    raise HTTPException(status_code=410, detail="请使用Excel拓扑基线导入接口")


@router.delete("/topologies/{topology_id}/links", response_model=None)
async def delete_all_topology_links(topology_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """清空拓扑所有链路"""
    if current_user["role"] not in ["admin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    from sqlalchemy import delete
    from modules.device.models import TopologyLink
    await DeviceService.lock_topology(db, topology_id)
    result = await db.execute(delete(TopologyLink).where(TopologyLink.topology_id == topology_id))
    await db.commit()
    return {"deleted": result.rowcount}


@router.post("/topologies/{topology_id}/links/lldp-import", response_model=None)
async def lldp_import_links(topology_id: int, links: list[dict], db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    """Deprecated: LLDP is runtime evidence and must not write the baseline."""
    raise HTTPException(status_code=410, detail="LLDP结果仅用于运行态差异校验")
