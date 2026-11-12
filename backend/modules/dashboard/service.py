"""首页运维指挥中心只读聚合服务。"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.time_utils import as_utc
from modules.auth.models import AuditLog
from modules.deploy.models import ChangeLevel, DeployStatus, DeployTask
from modules.device.models import Device, DeviceStatus, Topology, TopologyLink, TopologyType
from modules.device.service import TopologyService
from modules.monitor.models import Alarm, AlarmStatus, MonitorJob
from modules.system.models import BackgroundTask, TaskStatus
from modules.training.models import TrainingSession


def _value(value):
    return value.value if hasattr(value, "value") else value


class DashboardService:
    @staticmethod
    async def get_summary(db: AsyncSession, *, probe_services: bool = True) -> dict:
        settings = get_settings()

        devices = list((await db.execute(select(Device))).scalars().all())
        device_names = {device.id: device.hostname for device in devices}
        device_statuses = [_value(device.status) for device in devices]

        # 主拓扑优先选"有设备"的 active MAIN 拓扑（空拓扑会导致总览显示 0 设备/0 链路）
        main_topologies = list(
            (
                await db.execute(
                    select(Topology)
                    .where(
                        Topology.topology_type == TopologyType.MAIN,
                        Topology.status == "active",
                    )
                    .order_by(Topology.id)
                )
            )
            .scalars()
            .all()
        )
        device_topo_ids = {d.topology_id for d in devices}
        topology = next(
            (t for t in main_topologies if t.id in device_topo_ids),
            main_topologies[0] if main_topologies else None,
        )
        topology_summary = None
        if topology:
            topology_devices = [d for d in devices if d.topology_id == topology.id]
            links = list(
                (
                    await db.execute(
                        select(TopologyLink)
                        .where(TopologyLink.topology_id == topology.id)
                        .order_by(TopologyLink.id)
                    )
                ).scalars().all()
            )
            topology_summary = {
                "id": topology.id,
                "name": topology.name,
                "status": topology.status,
                "device_count": len(topology_devices),
                "link_count": len(links),
                "nodes": [
                    {
                        "id": d.id,
                        "hostname": d.hostname,
                        "status": _value(d.status),
                        "device_type": _value(d.device_type),
                        "network_role": d.network_role,
                    }
                    for d in topology_devices
                ],
                "links": [
                    {
                        "id": link.id,
                        "source_device_id": link.source_device_id,
                        "source_interface": link.source_interface,
                        "target_device_id": link.target_device_id,
                        "target_interface": link.target_interface,
                        "status": link.status,
                    }
                    for link in links
                ],
            }
            topology_summary["published_positions"] = (
                await TopologyService.get_layout(db, topology.id)
            )["published_positions"]

        deploy_tasks = list(
            (
                await db.execute(select(DeployTask).order_by(DeployTask.created_at.desc()))
            ).scalars().all()
        )
        background_tasks = list(
            (
                await db.execute(
                    select(BackgroundTask).order_by(BackgroundTask.created_at.desc())
                )
            ).scalars().all()
        )
        training_sessions = list(
            (
                await db.execute(
                    select(TrainingSession).order_by(TrainingSession.created_at.desc())
                )
            ).scalars().all()
        )

        deploy_progress = {
            "pending": 10,
            "validating": 30,
            "deploying": 60,
            "verifying": 80,
            "success": 100,
            "failed": 100,
            "rolled_back": 100,
            "cancelled": 100,
        }
        task_items = [
            {
                "id": task.id,
                "kind": "deploy",
                "name": f"配置下发 · {device_names.get(task.device_id, f'设备 {task.device_id}')}",
                "status": _value(task.status),
                "progress": deploy_progress.get(_value(task.status), 0),
                "device_name": device_names.get(task.device_id),
                "high_risk": task.change_level == ChangeLevel.HIGH_RISK,
                "has_diff": bool(task.verify_diff),
                "created_at": task.created_at,
            }
            for task in deploy_tasks
        ]
        task_items.extend(
            {
                "id": task.id,
                "kind": task.task_type or "background",
                "name": task.task_name,
                "status": _value(task.status),
                "progress": task.progress or 0,
                "created_at": task.created_at,
            }
            for task in background_tasks
        )
        task_items.extend(
            {
                "id": session.id,
                "kind": "training",
                "name": f"实训会话 #{session.id}",
                "status": session.status,
                "progress": 100 if session.status == "completed" else 50 if session.status == "in_progress" else 0,
                "created_at": session.created_at,
            }
            for session in training_sessions
        )
        task_items.sort(key=lambda item: as_utc(item["created_at"]) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        # 指挥中心先看"正在发生的事"：运行中/待确认的排前面，历史终态排后面。
        # 稳定排序保证组内仍是时间倒序（此前 5 条 cancelled 会把面板占满）。
        def _task_priority(item: dict) -> int:
            status = item["status"]
            if status in {"validating", "deploying", "verifying", "running", "in_progress"}:
                return 0
            if status in {"pending", "awaiting_confirmation", "confirmed"}:
                return 1
            return 2

        task_items.sort(key=_task_priority)
        # 终态任务最多留 3 条：否则历史 cancelled/failed 会把面板占满（实测被 5 条
        # e2e 遗留的 cancelled 刷屏），指挥中心应聚焦正在跑的事。
        live_items = [item for item in task_items if _task_priority(item) < 2]
        history_items = [item for item in task_items if _task_priority(item) >= 2][:3]
        task_items = (live_items + history_items)[:10]

        all_task_statuses = [
            *[_value(task.status) for task in deploy_tasks],
            *[_value(task.status) for task in background_tasks],
            *[session.status for session in training_sessions],
        ]
        active_statuses = {"validating", "deploying", "verifying", "running", "in_progress"}
        pending_statuses = {"pending"}
        failed_statuses = {"failed"}

        active_alarms = list(
            (
                await db.execute(
                    select(Alarm)
                    .where(Alarm.status.in_([AlarmStatus.FIRED, AlarmStatus.ACKNOWLEDGED]))
                    .order_by(Alarm.fired_at.desc())
                )
            ).scalars().all()
        )
        alarm_items = [
            {
                "id": alarm.id,
                "device_id": alarm.device_id,
                "device_name": device_names.get(alarm.device_id, f"设备 {alarm.device_id}"),
                "severity": alarm.severity,
                "message": alarm.message,
                "status": _value(alarm.status),
                "fired_at": alarm.fired_at,
            }
            for alarm in active_alarms[:8]
        ]

        # A7：首页"告警趋势"——最近 7 天每天的告警条数。按天计数后由 Python 补齐缺失日期，
        # 避免 SQLite/MySQL 的日期函数方言差异（两边 func.date 都返回 YYYY-MM-DD）。
        trend_start = datetime.now(timezone.utc).replace(
            tzinfo=None, hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=6)
        trend_rows = (
            await db.execute(
                select(func.date(Alarm.fired_at), func.count(Alarm.id))
                .where(Alarm.fired_at >= trend_start)
                .group_by(func.date(Alarm.fired_at))
            )
        ).all()
        count_by_day = {str(row[0]): int(row[1]) for row in trend_rows}
        alarm_trend = []
        for offset in range(7):
            day = (trend_start + timedelta(days=offset)).date().isoformat()
            alarm_trend.append({"date": day, "count": count_by_day.get(day, 0)})

        # A7：首页"报告"入口——最近巡检任务（含关键统计），报告详情走监控页
        recent_jobs = list(
            (
                await db.execute(
                    select(MonitorJob).order_by(MonitorJob.created_at.desc()).limit(5)
                )
            ).scalars().all()
        )
        report_items = []
        for job in recent_jobs:
            report_payload: dict = {}
            if job.report_json:
                try:
                    parsed = json.loads(job.report_json)
                    if isinstance(parsed, dict):
                        report_payload = parsed
                except (TypeError, ValueError):
                    report_payload = {}
            report_items.append({
                "id": job.id,
                "job_type": _value(job.job_type),
                "status": _value(job.status),
                "trigger_mode": _value(job.trigger_mode),
                "device_count": job.device_count,
                "success_count": job.success_count,
                "failure_count": job.failure_count,
                "alarm_count": report_payload.get("alarm_count"),
                "created_at": job.created_at,
            })

        # A7：首页"审批状态"——待确认/待执行的下发任务（高风险优先）
        approvals = [
            {
                "id": task.id,
                "device_name": device_names.get(task.device_id, f"设备 {task.device_id}"),
                "status": _value(task.status),
                "high_risk": task.change_level == ChangeLevel.HIGH_RISK,
                "change_level": _value(task.change_level),
                "created_at": task.created_at,
            }
            for task in deploy_tasks
            if _value(task.status) in {"pending", "awaiting_confirmation", "confirmed"}
        ]
        approvals.sort(key=lambda item: (not item["high_risk"], as_utc(item["created_at"]) or datetime.min.replace(tzinfo=timezone.utc)), reverse=False)
        approvals = approvals[:5]

        pending_approval = sum(
            task.change_level == ChangeLevel.HIGH_RISK
            and _value(task.status) in {"pending", "validating"}
            for task in deploy_tasks
        )
        offline_count = device_statuses.count(DeviceStatus.OFFLINE.value)
        critical_count = sum(alarm.severity == "critical" for alarm in active_alarms)
        risks = []
        if critical_count:
            risks.append({
                "level": "critical",
                "title": "严重告警待处理",
                "detail": f"当前有 {critical_count} 条严重告警",
                "recommendation": "优先进入告警中心确认影响范围并安排处置",
                "route": "/alarms",
            })
        if offline_count:
            risks.append({
                "level": "warning",
                "title": "设备离线",
                "detail": f"当前有 {offline_count} 台设备离线",
                "recommendation": "复核最近一次 SSH 健康检查和设备管理地址",
                "route": "/devices",
            })
        if pending_approval:
            risks.append({
                "level": "warning",
                "title": "高风险变更待审批",
                "detail": f"当前有 {pending_approval} 项高风险配置任务待确认",
                "recommendation": "完成审批并核对配置差异后再执行下发",
                "route": "/deploy?tab=tasks",
            })

        audit_logs = list(
            (
                await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(12))
            ).scalars().all()
        )
        llm_configured = bool(settings.llm_base_url and settings.llm_model)
        knowledge_provider = getattr(settings, "knowledge_provider", "") or None
        knowledge_configured = bool(
            (knowledge_provider or "").lower() == "local"
            or (
                getattr(settings, "knowledge_base_url", "")
                and (
                    getattr(settings, "knowledge_api_key", "")
                    or getattr(settings, "knowledge_dataset_id", "")
                    or getattr(settings, "knowledge_workspace_id", "")
                )
            )
            or getattr(settings, "rag_jwt_token", "")
            or getattr(settings, "rag_password", "")
        )

        db_status = "healthy"
        try:
            await db.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            db_status = "unhealthy"

        llm_status = "not_configured"
        llm_provider = settings.llm_provider
        llm_model = settings.llm_model
        llm_source = "env"
        try:
            from core.llm_provider import cached_llm_health_check, create_llm_provider
            from modules.system.service import SystemService
            runtime = await SystemService.get_llm_runtime_config(db)
            # 与 core/health.py 口径一致：只有 DB 里确实存在 llm.* 覆盖行才算 system_config，
            # 否则 runtime 的值其实来自 .env（此前这里硬编码 system_config，首页会显示错来源）
            llm_source = await SystemService.get_llm_config_source(db)
            llm_provider = runtime.get("llm_provider") or llm_provider
            llm_model = runtime.get("llm_model") or llm_model
            if runtime.get("llm_base_url") and llm_model and probe_services:
                provider = create_llm_provider(runtime)
                is_healthy = await cached_llm_health_check(provider)
                llm_status = "healthy" if is_healthy else "unavailable"
            elif llm_configured:
                llm_status = "configured"
        except Exception:  # noqa: BLE001
            llm_status = "unavailable" if llm_configured else "not_configured"

        knowledge_details: dict = {}
        if knowledge_configured and probe_services:
            try:
                # 走 core.health 的带缓存探测：直连 AnythingLLM 每次请求会让 summary 慢 2s+
                # （实测 P50≈2.1s，超过设计 §16 的首页 P95≤2s 底线）
                from core.health import get_knowledge_health_cached
                khealth = await get_knowledge_health_cached()
                knowledge_details = {
                    "available": khealth.get("status") == "healthy",
                    "document_count": khealth.get("document_count") or 0,
                    "workspace": khealth.get("workspace_slug") or "",
                }
            except Exception:  # noqa: BLE001
                knowledge_details = {"available": False, "document_count": 0, "error": True}

        knowledge_status = "not_configured"
        if knowledge_configured:
            knowledge_status = ("healthy" if knowledge_details.get("available") else "unavailable") if probe_services else "not_checked"

        return {
            "generated_at": datetime.now(timezone.utc),
            "environment_name": settings.app_name,
            "environment_status": "degraded" if offline_count or active_alarms else "operational",
            "devices": {
                "total": len(devices),
                "online": device_statuses.count(DeviceStatus.ONLINE.value),
                "ssh_reachable": device_statuses.count(DeviceStatus.ONLINE.value),
                "offline": offline_count,
                "maintenance": device_statuses.count(DeviceStatus.MAINTENANCE.value),
                "unknown": device_statuses.count(DeviceStatus.UNKNOWN.value),
            },
            "topology": topology_summary,
            "tasks": {
                "active": sum(status in active_statuses for status in all_task_statuses),
                "pending": sum(status in pending_statuses for status in all_task_statuses),
                "failed": sum(status in failed_statuses for status in all_task_statuses),
                "with_diff": sum(bool(task.verify_diff) for task in deploy_tasks),
                "items": task_items,
            },
            "alarms": {
                "active": len(active_alarms),
                "critical": critical_count,
                "items": alarm_items,
                "trend": alarm_trend,
            },
            "services": {
                "database": {"status": db_status},
                "llm": {
                    "status": llm_status,
                    "provider": llm_provider,
                    "model": llm_model,
                    "config_source": llm_source,
                },
                "knowledge": {
                    "status": knowledge_status,
                    "provider": knowledge_provider,
                    **knowledge_details,
                },
            },
            "risks": {"pending_approval": pending_approval, "items": risks},
            "approvals": approvals,
            "reports": report_items,
            "activity": [
                {
                    "id": log.id,
                    "module": log.module,
                    "action": log.action,
                    "result": log.result,
                    "created_at": log.created_at,
                }
                for log in audit_logs
            ],
            "monitor_scheduler_enabled": bool(settings.monitor_scheduler_enabled),
            "training": {
                "active": sum(session.status == "in_progress" for session in training_sessions),
                "total": len(training_sessions),
            },
        }
