"""监控调度器"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from core.config import get_settings
from core.database import get_session_factory
from core.logger import get_logger
from modules.device.models import Topology

logger = get_logger("scheduler")
_scheduler: AsyncIOScheduler | None = None


async def _run_monitor_cycle():
    from modules.monitor.models import MonitorTriggerMode
    from modules.monitor.service import MonitorService

    session_factory = get_session_factory()
    if session_factory is None:
        logger.warning("monitor_scheduler_skipped", reason="session_factory_unavailable")
        return

    async with session_factory() as db:
        result = await db.execute(select(Topology.id).where(Topology.status == "active"))
        topology_ids = [row[0] for row in result.all()]

    # 每个拓扑独立会话：某个拓扑失败后会话可能处于失败事务状态，
    # 复用同一会话会让后续拓扑连带失败。
    for topology_id in topology_ids:
        try:
            async with session_factory() as db:
                await MonitorService.run_collection(db, topology_id, trigger_mode=MonitorTriggerMode.SCHEDULED)
        except Exception as exc:  # pragma: no cover - scheduler best effort
            logger.warning("monitor_scheduler_cycle_failed", topology_id=topology_id, error=type(exc).__name__)


async def _run_aggregation_cycle():
    """小时/天聚合与保留期清理。

    此前 MetricAggregator 只被测试引用、调度器没注册它 —— 聚合与清理永不执行。
    """
    from modules.monitor.service import MetricAggregator

    session_factory = get_session_factory()
    if session_factory is None:
        return
    async with session_factory() as db:
        aggregator = MetricAggregator(db)
        for name, coro in (
            ("hourly", aggregator.aggregate_hourly()),
            ("daily", aggregator.aggregate_daily()),
            ("cleanup", aggregator.cleanup_old_records()),
        ):
            try:
                await coro
            except Exception as exc:  # pragma: no cover - scheduler best effort
                logger.warning("monitor_aggregation_failed", step=name, error=type(exc).__name__)


async def _run_lock_expiry_cycle():
    """释放过期的设备写锁（设计 §15.3）。

    与监控采集无关（不碰设备，只清理数据库里过期且未进入执行的锁），因此**不随
    `monitor_scheduler_enabled` 关闭** —— 否则"超时锁自动释放"在默认配置下永不生效。
    """
    from modules.deploy.service import DeployService

    session_factory = get_session_factory()
    if session_factory is None:
        return
    async with session_factory() as db:
        try:
            await DeployService.release_expired_locks(db)
        except Exception as exc:  # pragma: no cover - scheduler best effort
            logger.warning("lock_expiry_cycle_failed", error=type(exc).__name__)


def register_jobs(scheduler, settings) -> list[str]:
    """注册调度任务，返回已注册的 job id 列表（抽出便于单测，不必真正启动调度器）。"""
    ids: list[str] = []
    # 写锁过期清理：始终注册
    scheduler.add_job(
        _run_lock_expiry_cycle,
        "interval",
        seconds=settings.deploy_lock_expire_check_seconds,
        id="deploy_lock_expiry_cycle",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    ids.append("deploy_lock_expiry_cycle")
    if settings.monitor_scheduler_enabled:
        scheduler.add_job(
            _run_monitor_cycle,
            "interval",
            seconds=settings.monitor_collect_interval,
            id="monitor_collect_cycle",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.add_job(
            _run_aggregation_cycle,
            "interval",
            seconds=3600,
            id="monitor_aggregation_cycle",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        ids.extend(["monitor_collect_cycle", "monitor_aggregation_cycle"])
    return ids


def start_monitor_scheduler() -> None:
    global _scheduler
    settings = get_settings()
    if _scheduler and _scheduler.running:
        return

    _scheduler = AsyncIOScheduler()
    registered = register_jobs(_scheduler, settings)
    if settings.monitor_scheduler_enabled:
        logger.info(
            "monitor_scheduler_started",
            interval=settings.monitor_collect_interval,
            jobs=registered,
        )
    else:
        logger.info("monitor_scheduler_disabled", jobs=registered)
    _scheduler.start()


def shutdown_monitor_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("monitor_scheduler_stopped")
    _scheduler = None
