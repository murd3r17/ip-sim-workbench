"""监控模块路由"""
import asyncio
import json
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from core.database import get_async_session
from core.dependencies import get_current_user, require_role
from core.exceptions import parse_enum
from core.logger import get_logger
from core.time_utils import iso_utc
from modules.monitor.service import MetricCollector, AlarmService, MonitorService
from modules.monitor.models import MetricRecord, Alarm, AlarmStatus, MonitorJobType, MonitorTriggerMode
from modules.device.models import Device, DeviceStatus

logger = get_logger("monitor")
router = APIRouter(tags=["监控告警"])

from modules.monitor.ports import PortPolicyWrite
from modules.monitor.port_service import get_port_state, save_port_policy


@router.get('/monitor/ports/{device_id}')
async def read_ports(device_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)):
    return await get_port_state(db, device_id)


@router.put('/monitor/ports/{device_id}/expectations')
async def update_port_expectations(device_id: int, body: PortPolicyWrite, db: AsyncSession = Depends(get_async_session),
                                   current_user: dict = Depends(require_role('admin'))):
    return await save_port_policy(db, device_id, body, current_user)


@router.get("/monitor/metrics/{device_id}", response_model=None)
async def get_device_metrics(device_id: int, metric_type: str = None, limit: int = Query(100, le=1000), db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> list[Any]:
    """获取设备指标"""
    query = select(MetricRecord).where(MetricRecord.device_id == device_id)
    if metric_type:
        query = query.where(MetricRecord.metric_type == metric_type)
    query = query.order_by(MetricRecord.collected_at.desc()).limit(limit)
    result = await db.execute(query)
    return [{"id": r.id, "metric_type": r.metric_type.value, "value": r.value, "unit": r.unit, "collected_at": iso_utc(r.collected_at)} for r in result.scalars().all()]


@router.post("/monitor/collect/{topology_id}", response_model=None)
async def trigger_collection(topology_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    """触发指标采集"""
    if current_user["role"] not in ["admin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return await MonitorService.run_collection(db, topology_id, current_user["user_id"], MonitorTriggerMode.MANUAL)


@router.post("/monitor/inspections/{topology_id}", response_model=None)
async def run_inspection(topology_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    """触发巡检任务"""
    if current_user["role"] not in ["admin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return await MonitorService.run_inspection(db, topology_id, current_user["user_id"], MonitorTriggerMode.MANUAL)


@router.get("/monitor/trends", response_model=None)
async def get_monitor_trends(
    topology_id: int | None = None,
    device_id: int | None = None,
    metric_type: str | None = None,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """获取监控趋势"""
    return await MonitorService.get_trend_series(db, topology_id=topology_id, device_id=device_id, metric_type=metric_type, limit=limit)


@router.get("/monitor/tasks", response_model=None)
async def list_monitor_tasks(
    topology_id: int | None = None,
    job_type: str | None = None,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """获取监控任务列表"""
    parsed_job_type = parse_enum(MonitorJobType, job_type, "job_type") if job_type else None
    return await MonitorService.list_jobs(db, topology_id=topology_id, job_type=parsed_job_type, limit=limit)


@router.get("/alarms", response_model=None)
async def list_alarms(status: str = None, device_id: int = None, limit: int = Query(100, le=1000), offset: int = Query(0, ge=0), db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> list[Any]:
    """获取告警列表"""
    query = select(Alarm, Device.hostname).join(Device, Device.id == Alarm.device_id)
    if status == "active":
        query = query.where(Alarm.status.in_([AlarmStatus.FIRED, AlarmStatus.ACKNOWLEDGED]))
    elif status:
        query = query.where(Alarm.status == parse_enum(AlarmStatus, status, "status"))
    if device_id:
        query = query.where(Alarm.device_id == device_id)
    query = query.order_by(Alarm.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    return [
        {
            "id": alarm.id,
            "device_id": alarm.device_id,
            "device_name": hostname,
            "alarm_type": alarm.alarm_type,
            "severity": alarm.severity,
            "message": alarm.message,
            "metric_value": alarm.metric_value,
            "threshold": alarm.threshold,
            "status": alarm.status.value,
            "fired_at": iso_utc(alarm.fired_at),
            "acknowledged_at": iso_utc(alarm.acknowledged_at),
            "resolved_at": iso_utc(alarm.resolved_at),
            "closed_at": iso_utc(alarm.closed_at),
        }
        for alarm, hostname in result.all()
    ]


@router.put("/alarms/{alarm_id}/acknowledge", response_model=None)
async def acknowledge_alarm(alarm_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """确认告警"""
    try:
        alarm = await AlarmService.acknowledge_alarm(db, alarm_id, current_user["user_id"])
        return {"id": alarm.id, "status": alarm.status.value}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/alarms/{alarm_id}/close", response_model=None)
async def close_alarm(alarm_id: int, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """关闭告警"""
    try:
        alarm = await AlarmService.close_alarm(db, alarm_id, current_user["user_id"])
        return {"id": alarm.id, "status": alarm.status.value}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/monitor/stats", response_model=None)
async def get_monitor_stats(db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """获取监控统计数据"""
    # 设备统计
    total_devices = await db.scalar(select(func.count()).select_from(Device))
    online_devices = await db.scalar(select(func.count()).select_from(Device).where(Device.status == DeviceStatus.ONLINE))

    # 告警统计：warningAlarms 只统计"活跃"的低级别告警（此前不过滤 status，
    # 把已 resolved/closed 的历史告警也算进来，与 activeAlarms 语义不一致）
    active_alarms = await db.scalar(select(func.count()).select_from(Alarm).where(
        Alarm.status.in_([AlarmStatus.FIRED, AlarmStatus.ACKNOWLEDGED])))
    warning_alarms = await db.scalar(
        select(func.count()).select_from(Alarm).where(
            Alarm.status.in_([AlarmStatus.FIRED, AlarmStatus.ACKNOWLEDGED]),
            Alarm.severity.in_(["warning", "minor"]),
        )
    )

    return {
        "totalDevices": total_devices or 0,
        "onlineDevices": online_devices or 0,
        "activeAlarms": active_alarms or 0,
        "warningAlarms": warning_alarms or 0
    }


@router.get("/monitor/stream", response_model=None)
async def monitor_stream(current_user: dict = Depends(get_current_user)) -> StreamingResponse:
    """SSE实时监控流：每 5s 推送 stats + 活跃告警 + 心跳。

    前端使用 fetch + Authorization 头连接（EventSource 无法携带 Bearer token）。
    """
    async def generate() -> Any:
        try:
            from core.database import get_session_factory
            session_factory = get_session_factory()
            while True:
                try:
                    if session_factory is not None:
                        async with session_factory() as db:
                            total_devices = await db.scalar(select(func.count()).select_from(Device))
                            online_devices = await db.scalar(
                                select(func.count()).select_from(Device).where(Device.status == DeviceStatus.ONLINE)
                            )
                            active_alarms = await db.scalar(
                                select(func.count()).select_from(Alarm).where(
                                    Alarm.status.in_([AlarmStatus.FIRED, AlarmStatus.ACKNOWLEDGED]))
                            )
                            warning_alarms = await db.scalar(
                                select(func.count()).select_from(Alarm).where(
                                    Alarm.status.in_([AlarmStatus.FIRED, AlarmStatus.ACKNOWLEDGED]),
                                    Alarm.severity.in_(["warning", "minor"]),
                                )
                            )
                            alarm_rows = (
                                await db.execute(
                                    select(Alarm, Device.hostname)
                                    .join(Device, Device.id == Alarm.device_id)
                                    .where(Alarm.status.in_([AlarmStatus.FIRED, AlarmStatus.ACKNOWLEDGED]))
                                    .order_by(Alarm.fired_at.desc())
                                    .limit(10)
                                )
                            ).all()
                        yield f"data: {json.dumps({'type': 'stats', 'data': {'totalDevices': total_devices or 0, 'onlineDevices': online_devices or 0, 'activeAlarms': active_alarms or 0, 'warningAlarms': warning_alarms or 0}})}\n\n"
                        alarms: list[dict[str, Any]] = [
                            {
                                "id": a.id,
                                "device_id": a.device_id,
                                "device_name": hostname,
                                "alarm_type": a.alarm_type,
                                "severity": a.severity,
                                "message": a.message,
                                "status": a.status.value,
                                "fired_at": iso_utc(a.fired_at),
                            }
                            for a, hostname in alarm_rows
                        ]
                        yield f"data: {json.dumps({'type': 'alarms', 'data': alarms})}\n\n"
                except Exception as exc:
                    logger.warning("sse_tick_failed", error=str(exc))
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            # 必须重新抛出：吞掉取消会让上层无法确认任务已终止
            logger.info("SSE connection closed", user=current_user.get("username"))
            raise

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
