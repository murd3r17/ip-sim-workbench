"""首页运维指挥中心只读聚合服务。"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.time_utils import as_utc
from modules.auth.models import AuditLog
from modules.deploy.models import ChangeLevel, DeployBatch, DeployTask
from modules.device.models import Device, DeviceStatus, Topology, TopologyLink, TopologyType
from modules.device.service import TopologyService
from modules.monitor.models import Alarm, AlarmStatus, MonitorJob
from modules.system.models import BackgroundTask
from modules.training.models import LabStatus, TrainingLab, TrainingSession


def _value(value):
    return value.value if hasattr(value, "value") else value


class DashboardService:
    @staticmethod
    async def get_summary(db: AsyncSession, *, actor: dict | None = None, probe_services: bool = True) -> dict:
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

        # Match the visibility of each destination list. The actor-free form is
        # used by internal checks. HTTP and assistant calls pass the authenticated actor.
        full_scope = actor is None or actor["role"] == "admin"
        deploy_query = select(DeployTask, DeployBatch.name).outerjoin(
            DeployBatch,
            and_(DeployTask.batch_id == DeployBatch.id, DeployTask.operator_id == DeployBatch.operator_id),
        ).order_by(DeployTask.created_at.desc())
        batch_count_query = select(func.count(DeployBatch.id))
        training_query = select(TrainingSession, TrainingLab.title).outerjoin(
            TrainingLab, TrainingSession.lab_id == TrainingLab.id,
        ).order_by(TrainingSession.created_at.desc())
        if not full_scope:
            user_id = actor["user_id"]
            deploy_query = deploy_query.where(DeployTask.operator_id == user_id)
            batch_count_query = batch_count_query.where(DeployBatch.operator_id == user_id)
            training_query = training_query.where(TrainingSession.trainee_id == user_id)
        deploy_rows = (await db.execute(deploy_query)).all()
        deploy_tasks = [task for task, _ in deploy_rows]
        deploy_batches = (await db.execute(batch_count_query)).scalar_one()
        training_rows = (await db.execute(training_query)).all()
        training_sessions = [session for session, _ in training_rows]
        intro_lab_id = None
        if (settings.device_mode or "").strip().lower() == "sim" and device_topo_ids:
            published = await db.execute(
                select(TrainingLab.id, TrainingLab.environment_spec)
                .where(TrainingLab.status == LabStatus.READY, TrainingLab.topology_id.in_(device_topo_ids))
                .order_by(TrainingLab.id)
            )
            intro_lab_id = next(
                (lab_id for lab_id, spec in published if isinstance(spec, dict) and spec.get("kind") == "workflow_demo"),
                None,
            )
        background_tasks = []
        if full_scope:
            background_tasks = (await db.scalars(
                select(BackgroundTask).order_by(BackgroundTask.created_at.desc())
            )).all()

        deploy_names = {
            task.id: name or f"配置任务 #{task.id}" for task, name in deploy_rows
        }

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
                "name": deploy_names[task.id],
                "batch_id": task.batch_id if name else None,
                "status": _value(task.status),
                "progress": deploy_progress.get(_value(task.status), 0),
                "device_name": device_names.get(task.device_id),
                "high_risk": task.change_level == ChangeLevel.HIGH_RISK,
                "has_diff": bool(task.verify_diff),
                "created_at": task.created_at,
            }
            for task, name in deploy_rows
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
                "name": title or f"实训会话 #{session.id}",
                "status": session.status,
                "progress": 100 if session.status == "completed" else 50 if session.status == "in_progress" else 0,
                "created_at": session.created_at,
            }
            for session, title in training_rows
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
                "alarm_type": alarm.alarm_type,
                "severity": alarm.severity,
                "message": alarm.message,
                "metric_value": alarm.metric_value,
                "threshold": alarm.threshold,
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
        def saved_count(raw, key):
            try:
                data = json.loads(raw) if raw else None
            except (TypeError, ValueError):
                return None
            value = data.get(key) if isinstance(data, dict) else None
            return value if type(value) is int and value >= 0 else None

        report_items = []
        for job in recent_jobs:
            report_items.append({
                "id": job.id,
                "topology_id": job.topology_id,
                "job_type": _value(job.job_type),
                "status": _value(job.status),
                "trigger_mode": _value(job.trigger_mode),
                "device_count": job.device_count,
                "success_count": job.success_count,
                "failure_count": job.failure_count,
                "skipped_count": saved_count(job.summary_json, "skipped"),
                "alarm_count": saved_count(job.report_json, "alarm_count") if job.success_count else None,
                "created_at": job.created_at,
            })

        awaiting_statuses = {"pending", "awaiting_confirmation"}
        approvals = [
            {
                "id": task.id,
                "name": deploy_names[task.id],
                "device_name": device_names.get(task.device_id, f"设备 {task.device_id}"),
                "status": _value(task.status),
                "high_risk": task.change_level == ChangeLevel.HIGH_RISK,
                "change_level": _value(task.change_level),
                "created_at": task.created_at,
            }
            for task in deploy_tasks
            if _value(task.status) in awaiting_statuses or _value(task.status) == "confirmed"
        ]
        approvals.sort(key=lambda item: (not item["high_risk"], as_utc(item["created_at"]) or datetime.min.replace(tzinfo=timezone.utc)), reverse=False)
        approvals = approvals[:5]

        awaiting_approval = [task for task in deploy_tasks if _value(task.status) in awaiting_statuses]
        high_risk_pending = sum(task.change_level == ChangeLevel.HIGH_RISK for task in awaiting_approval)
        offline_count = device_statuses.count(DeviceStatus.OFFLINE.value)
        critical_count = sum(alarm.severity == "critical" for alarm in active_alarms)
        risks = []
        if critical_count:
            risks.append({
                "level": "critical",
                "title": "严重告警待处理",
                "detail": f"当前有 {critical_count} 条严重告警",
                "recommendation": "优先进入告警中心确认影响范围并安排处置",
                "route": "/alarms?status=active",
            })
        if offline_count:
            risks.append({
                "level": "warning",
                "title": "设备离线",
                "detail": f"当前有 {offline_count} 台设备离线",
                "recommendation": "复核最近一次 SSH 健康检查和设备管理地址",
                "route": "/devices?status=offline",
            })
        if high_risk_pending:
            risks.append({
                "level": "warning",
                "title": "高风险变更待审批",
                "detail": f"当前有 {high_risk_pending} 项高风险配置任务待确认",
                "recommendation": "完成审批并核对配置差异后再执行下发",
                "route": "/approvals?status=awaiting_review",
            })

        audit_logs = []
        if full_scope:
            audit_logs = (await db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(12))).all()
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
                "deploy_batches": deploy_batches,
                "items": task_items,
            },
            "alarms": {
                "active": len(active_alarms),
                "critical": critical_count,
                "items": alarm_items,
                "trend": alarm_trend,
            },
            "services": await DashboardService.get_services(db, probe_services=probe_services),
            "risks": {"pending_approval": len(awaiting_approval), "items": risks},
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
                "intro_lab_id": intro_lab_id,
            },
        }

    @staticmethod
    async def get_services(db: AsyncSession, *, probe_services: bool = True) -> dict:
        settings = get_settings()
        from core.health import llm_is_configured
        llm_configured = llm_is_configured(settings)
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

        llm_status = "disabled"
        llm_provider = settings.llm_provider
        llm_model = settings.llm_model
        llm_source = "env"
        llm_checked_at = None
        try:
            from core.llm_provider import cached_llm_health_check, create_llm_provider, llm_health_checked_at
            from modules.system.service import SystemService
            runtime = await SystemService.get_llm_runtime_config(db)
            # 与 core/health.py 口径一致：只有 DB 里确实存在 llm.* 覆盖行才算 system_config，
            # 否则 runtime 的值其实来自 .env（此前这里硬编码 system_config，首页会显示错来源）
            llm_source = await SystemService.get_llm_config_source(db)
            llm_provider = runtime.get("llm_provider") or llm_provider
            llm_model = runtime.get("llm_model") or llm_model
            llm_configured = llm_is_configured(settings, runtime)
            if llm_configured and probe_services:
                provider = create_llm_provider(runtime)
                is_healthy = await cached_llm_health_check(provider)
                llm_checked_at = llm_health_checked_at(provider)
                llm_status = "healthy" if is_healthy else "unavailable"
            elif llm_configured:
                llm_status = "configured"
        except Exception:  # noqa: BLE001
            llm_status = "unavailable" if llm_configured else "disabled"

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
            "database": {"status": db_status, "backend": db.get_bind().dialect.name},
            "llm": {
                "status": llm_status,
                "provider": llm_provider,
                "model": llm_model,
                "config_source": llm_source,
                "checked_at": llm_checked_at,
            },
            "knowledge": {
                "status": knowledge_status,
                "provider": knowledge_provider,
                **knowledge_details,
            },
        }
