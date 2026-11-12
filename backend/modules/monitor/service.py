"""监控模块服务 - SSH采集"""
import json
import asyncio
import re
import time
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from core.config import get_settings
from core.logger import get_logger
from core.time_utils import iso_utc
from modules.monitor.models import (
    MetricRecord, MetricType, Alarm, AlarmStatus, MetricAggregated, AggLevel,
    MonitorJob, MonitorJobStatus, MonitorJobType, MonitorTriggerMode,
)
from modules.device.models import Device, DeviceStatus, DeviceType

logger = get_logger("monitor")

THRESHOLDS = {
    # direction=high：值越大越严重（默认）；direction=low：值越小越严重
    "cpu_usage": {"direction": "high", "warning": 70, "minor": 80, "major": 90, "critical": 95},
    "memory_usage": {"direction": "high", "warning": 75, "minor": 85, "major": 92, "critical": 97},
    # Raw down is retained as a statistic; D06 uses purpose/expected-state alarms.
    "interface_down": {"direction": "high", "warning": 1},
    "temperature": {"direction": "high", "warning": 65, "minor": 70, "major": 75, "critical": 85},
    "ospf_neighbor_count": {"direction": "low", "warning": 1, "critical": 0},
}

# 阈值可在系统配置里覆盖（键 `monitor.thresholds`，JSON）；解析失败一律回退默认值
THRESHOLDS_CONFIG_KEY = "monitor.thresholds"


def _merge_thresholds(base: dict, override: dict) -> dict:
    """把系统配置里的阈值合并到默认阈值上（只覆盖显式给出的档位）。"""
    merged = {name: dict(cfg) for name, cfg in base.items()}
    for metric, cfg in (override or {}).items():
        if metric not in merged or not isinstance(cfg, dict):
            continue
        for level, limit in cfg.items():
            if level == "direction":
                if limit in ("high", "low"):
                    merged[metric]["direction"] = limit
                continue
            if isinstance(limit, (int, float)):
                merged[metric][level] = limit
    return merged


async def load_thresholds(db: AsyncSession) -> dict:
    """读取生效阈值（默认值 + 系统配置覆盖）。"""
    try:
        from modules.system.models import SystemConfig
        row = (
            await db.execute(select(SystemConfig).where(SystemConfig.config_key == THRESHOLDS_CONFIG_KEY))
        ).scalars().first()
        if not row or not (row.config_value or "").strip():
            return {name: dict(cfg) for name, cfg in THRESHOLDS.items()}
        parsed = json.loads(row.config_value)
        if not isinstance(parsed, dict):
            raise ValueError("阈值配置必须是 JSON 对象")
        return _merge_thresholds(THRESHOLDS, parsed)
    except json.JSONDecodeError as exc:
        logger.warning("monitor_threshold_config_invalid_json", error=str(exc))
    except Exception as exc:  # noqa: BLE001 - 配置读取失败不能影响采集
        logger.warning("monitor_threshold_config_failed", error=type(exc).__name__)
    return {name: dict(cfg) for name, cfg in THRESHOLDS.items()}


def _severity_for(value: float, thresholds: dict) -> str | None:
    """按方向判定告警级别。high：值 >= 阈值；low：值 <= 阈值。"""
    if thresholds.get("direction") == "low":
        for level in ("critical", "major", "minor", "warning"):
            limit = thresholds.get(level)
            if limit is not None and value <= limit:
                return level
        return None
    for level in ("critical", "major", "minor", "warning"):
        limit = thresholds.get(level)
        if limit is not None and value >= limit:
            return level
    return None


def _to_iso(value):
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        # naive DB 值按 UTC 解释，出参带偏移，避免前端再按本地时间解析
        return iso_utc(value)
    return str(value)


async def _audit_alarm(db: AsyncSession, user_id: int, action: str, alarm: Alarm) -> None:
    """告警操作留痕（此前 acknowledge_alarm/close_alarm 丢弃了 user_id，无操作人记录）。"""
    try:
        from modules.auth.service import AuditService
        severity = alarm.severity.value if hasattr(alarm.severity, "value") else alarm.severity
        await AuditService.log(
            db, user_id, "", "monitor", action, "alarm", str(alarm.id),
            {"device_id": alarm.device_id, "severity": severity, "alarm_type": alarm.alarm_type},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("alarm_audit_failed", action=action, error=str(exc))


class MonitorService:
    @staticmethod
    def build_command_profile(device: Device) -> dict[str, str]:
        device_type = getattr(device.device_type, "value", device.device_type)
        protocol_command = "display lldp neighbor brief"
        if device_type in (DeviceType.ROUTER.value, DeviceType.SWITCH_L3.value):
            protocol_command = "display ospf peer brief"
        elif device_type == DeviceType.SWITCH_L2.value:
            protocol_command = "display stp brief"

        return {
            "cpu": "display cpu-usage",
            "memory": "display memory-usage",
            "interface": "display interface brief",
            "protocol": protocol_command,
            "temperature": "display temperature",
        }

    @staticmethod
    async def get_trend_series(
        db: AsyncSession,
        topology_id: int | None = None,
        device_id: int | None = None,
        metric_type: str | None = None,
        limit: int = 50,
    ) -> dict:
        metric_query = select(MetricRecord, Device.hostname).join(Device)
        if topology_id is not None:
            metric_query = metric_query.where(Device.topology_id == topology_id)
        if device_id is not None:
            metric_query = metric_query.where(MetricRecord.device_id == device_id)
        if metric_type:
            try:
                metric_query = metric_query.where(MetricRecord.metric_type == MetricType(metric_type))
            except ValueError:
                metric_query = metric_query.where(False)

        # 取"最近 N*20 条"再反转为时间正序。此前用 asc().limit()，取到的是最旧的一段，
        # 长期运行的设备永远看不到新数据。
        metric_query = metric_query.order_by(MetricRecord.collected_at.desc()).limit(limit * 20)
        metric_rows = list((await db.execute(metric_query)).all())
        metric_rows.reverse()

        metric_series: dict[str, list[dict]] = {}
        for row, device_name in metric_rows:
            key = row.metric_type.value if hasattr(row.metric_type, "value") else str(row.metric_type)
            metric_series.setdefault(key, []).append({
                "time": _to_iso(row.collected_at),
                "value": row.value,
                "device_id": row.device_id,
                "device_name": device_name,
                "unit": row.unit,
            })

        alarm_query = select(Alarm).join(Device)
        if topology_id is not None:
            alarm_query = alarm_query.where(Device.topology_id == topology_id)
        if device_id is not None:
            alarm_query = alarm_query.where(Alarm.device_id == device_id)
        alarm_query = alarm_query.order_by(Alarm.fired_at.desc()).limit(limit)
        alarm_rows = list((await db.execute(alarm_query)).scalars().all())
        alarm_rows.reverse()
        alarm_series = [
            {
                "time": _to_iso(alarm.fired_at),
                "device_id": alarm.device_id,
                "alarm_type": alarm.alarm_type,
                "severity": alarm.severity,
                "status": alarm.status.value if hasattr(alarm.status, "value") else alarm.status,
            }
            for alarm in alarm_rows
        ]

        return {
            "metrics": metric_series,
            "alarms": alarm_series,
            "summary": {
                "metric_points": sum(len(points) for points in metric_series.values()),
                "alarm_points": len(alarm_series),
            },
        }

    @staticmethod
    def _job_to_dict(job: MonitorJob) -> dict:
        return {
            "id": job.id,
            "topology_id": job.topology_id,
            "job_type": job.job_type.value if hasattr(job.job_type, "value") else job.job_type,
            "trigger_mode": job.trigger_mode.value if hasattr(job.trigger_mode, "value") else job.trigger_mode,
            "status": job.status.value if hasattr(job.status, "value") else job.status,
            "triggered_by": job.triggered_by,
            "device_count": job.device_count,
            "success_count": job.success_count,
            "failure_count": job.failure_count,
            "error_message": job.error_message,
            "summary": json.loads(job.summary_json) if job.summary_json else None,
            "report": json.loads(job.report_json) if job.report_json else None,
            "started_at": _to_iso(job.started_at),
            "finished_at": _to_iso(job.finished_at),
            "created_at": _to_iso(job.created_at),
        }

    @staticmethod
    async def _run_job(
        db: AsyncSession,
        topology_id: int,
        job_type: MonitorJobType,
        triggered_by: int | None,
        trigger_mode: MonitorTriggerMode,
    ) -> dict:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        job = MonitorJob(
            topology_id=topology_id,
            job_type=job_type,
            trigger_mode=trigger_mode,
            status=MonitorJobStatus.PENDING,
            triggered_by=triggered_by,
            started_at=now,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        job.status = MonitorJobStatus.RUNNING
        await db.commit()
        job_id = job.id

        collector = MetricCollector(db)
        try:
            summary = await collector.collect_all_devices(topology_id)
            job.device_count = summary["expected"]
            job.success_count = summary["success"]
            job.failure_count = summary["failed"]
            job.summary_json = json.dumps(summary, ensure_ascii=False, default=str)
            job.error_message = "; ".join(summary["errors"][:3]) if summary["errors"] else None
            complete = summary["success"] > 0 and not summary["failed"] and not summary["skipped"]
            job.status = MonitorJobStatus.SUCCESS if complete else MonitorJobStatus.FAILED

            report = None
            if job_type == MonitorJobType.INSPECTION:
                evidence = [item for item in summary["devices"] if item["status"] == "success"]
                metrics = [point for item in evidence for point in item["metrics"]]
                alarms = [alarm for item in evidence for alarm in item["alarms"]]
                report = {
                    "job_id": job.id,
                    "topology_id": topology_id,
                    "started_at": _to_iso(job.started_at),
                    "evidence_scope": "current_job",
                    "devices": evidence,
                    "metric_types": sorted({point["metric_type"] for point in metrics}),
                    "alarm_count": len(alarms),
                    "alarm_severities": sorted({item["severity"] for item in alarms}),
                    "summary": {"metric_points": len(metrics), "alarm_points": len(alarms)},
                    "collection": summary,
                }
                job.report_json = json.dumps(report, ensure_ascii=False, default=str)

            job.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.commit()
            await db.refresh(job)
            result = {"task": MonitorService._job_to_dict(job), "summary": summary}
            if report is not None:
                result["report"] = report
            return result
        except Exception as exc:
            # A failed flush/commit invalidates the transaction. Roll back before
            # recording the job failure, using the persisted ID rather than an expired ORM attribute.
            await db.rollback()
            job = await db.get(MonitorJob, job_id)
            if job is None:
                raise
            job.status = MonitorJobStatus.FAILED
            job.error_message = type(exc).__name__
            job.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.commit()
            await db.refresh(job)
            raise

    @staticmethod
    async def run_collection(
        db: AsyncSession,
        topology_id: int,
        triggered_by: int | None = None,
        trigger_mode: MonitorTriggerMode = MonitorTriggerMode.MANUAL,
    ) -> dict:
        return await MonitorService._run_job(db, topology_id, MonitorJobType.COLLECTION, triggered_by, trigger_mode)

    @staticmethod
    async def run_inspection(
        db: AsyncSession,
        topology_id: int,
        triggered_by: int | None = None,
        trigger_mode: MonitorTriggerMode = MonitorTriggerMode.MANUAL,
    ) -> dict:
        return await MonitorService._run_job(db, topology_id, MonitorJobType.INSPECTION, triggered_by, trigger_mode)

    @staticmethod
    async def list_jobs(
        db: AsyncSession,
        topology_id: int | None = None,
        job_type: MonitorJobType | None = None,
        limit: int = 50,
    ) -> list[dict]:
        query = select(MonitorJob)
        if topology_id is not None:
            query = query.where(MonitorJob.topology_id == topology_id)
        if job_type is not None:
            query = query.where(MonitorJob.job_type == job_type)
        query = query.order_by(MonitorJob.created_at.desc()).limit(limit)
        rows = (await db.execute(query)).scalars().all()
        return [MonitorService._job_to_dict(job) for job in rows]


class MetricCollector:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()
        # 采集并发上限（重试交给上层任务/调度器统一处理：
        # 此前每个 collector 建了 RetryEngine 却从未使用）
        self._semaphore = asyncio.Semaphore(self.settings.monitor_batch_size)
        # AsyncSession 不支持并发使用：采集（网络/模拟）可并发，但 DB 写入必须串行。
        # 否则 evaluate_and_alarm 的 SELECT 会在半程触发 autoflush，
        # 批量 INSERT 拿到重复自增 id（Duplicate entry ... PRIMARY）。
        self._db_lock = asyncio.Lock()
        self._evidence: dict[int, dict] = {}
        self._port_samples: dict[int, dict] = {}

    async def collect_all_devices(self, topology_id: int) -> dict:
        from modules.device.service import DeviceService

        all_devices = await DeviceService.get_devices_by_topology(self.db, topology_id)
        devices = [device for device in all_devices if device.status == DeviceStatus.ONLINE]
        results = {"expected": len(all_devices), "attempted": len(devices),
                   "success": 0, "failed": 0, "skipped": len(all_devices) - len(devices),
                   "errors": [], "devices": []}
        for device in all_devices:
            if device.status != DeviceStatus.ONLINE:
                reason = f"设备状态为 {getattr(device.status, 'value', device.status)}，本轮未采集"
                results["devices"].append({"device_id": device.id, "hostname": device.hostname,
                                           "status": "skipped", "reason": reason})
                results["errors"].append(f"{device.hostname}: {reason}")
        if not all_devices:
            results["errors"].append("拓扑中没有可采集设备")

        batch_size = self.settings.monitor_batch_size
        for i in range(0, len(devices), batch_size):
            batch = devices[i:i + batch_size]
            tasks = [self._collect_single_device(device) for device in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for device, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    results["failed"] += 1
                    results["errors"].append(f"{device.hostname}: {type(result).__name__}")
                elif result == "success":
                    results["success"] += 1
                    results["devices"].append(self._evidence[device.id])
                else:
                    # 超时/异常此前都落进 skipped，导致 failed 恒为 0、
                    # job.status 恒为 SUCCESS（全设备采集失败也显示成功）。
                    results["failed"] += 1
                    results["errors"].append(f"{device.hostname}: {result}")
                if result != "success":
                    results["devices"].append({"device_id": device.id, "hostname": device.hostname,
                                               "status": "failed", "reason": type(result).__name__ if isinstance(result, Exception) else result})

            if i + batch_size < len(devices):
                await asyncio.sleep(self.settings.monitor_batch_interval)

        # Commit failures must fail the job, never return a successful summary.
        await self.db.commit()

        logger.info("metric_collection_complete", topology_id=topology_id,
                    **{key: value for key, value in results.items() if key != "devices"})
        return results

    async def _collect_single_device(self, device: Device) -> str:
        """返回 success | timeout | failed（不再用布尔值，否则失败会被当成 skipped）。"""
        async with self._semaphore:
            try:
                metrics = await asyncio.wait_for(
                    self._collect_via_ssh(device), timeout=self.settings.monitor_device_timeout
                )
                if not metrics:
                    return "no_metrics"
                evidence = await self._save_metrics(device, metrics)
                self._evidence[device.id] = evidence
                return "success"
            except asyncio.TimeoutError:
                logger.warning("collect_timeout", device=device.hostname)
                return "timeout"
            except Exception as e:
                logger.error("collect_failed", device=device.hostname, error=str(e))
                return "failed"

    async def _collect_via_ssh(self, device: Device) -> dict:
        from engines.device_adapter import get_device_adapter
        deadline = time.monotonic() + self.settings.monitor_device_timeout
        command_profile = MonitorService.build_command_profile(device)
        adapter = await get_device_adapter(device)

        async def read(command: str) -> str:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("monitor device deadline expired")
            return await adapter.run_command(command, timeout=remaining)

        metrics = {}
        try:
            cpu_output = await read(command_profile["cpu"])
            cpu_value = self._parse_cpu(cpu_output)
            if cpu_value is not None:
                metrics["cpu_usage"] = {"value": cpu_value, "unit": "%"}

            mem_output = await read(command_profile["memory"])
            mem_value = self._parse_memory(mem_output)
            if mem_value is not None:
                metrics["memory_usage"] = {"value": mem_value, "unit": "%"}

            intf_output = await read(command_profile["interface"])
            intf_stats = self._parse_interfaces(intf_output)
            metrics.update(intf_stats)
            from modules.monitor.ports import parse_ports
            from engines.device_adapter import get_device_mode
            self._port_samples[device.id] = parse_ports(intf_output) | {
                'observed_at': datetime.now(timezone.utc).isoformat(),
                'mode': getattr(adapter, 'name', None) or get_device_mode(),
            }

            protocol_output = await read(command_profile["protocol"])
            # 只有 OSPF 命令才产出邻居数；L2 设备拿到的是 display stp brief，
            # 此前仍按 OSPF 解析器统计，指标名与语义不符。
            if "ospf" in command_profile["protocol"]:
                neighbor_count = self._parse_ospf_neighbors(protocol_output)
                if neighbor_count is not None:
                    metrics["ospf_neighbor_count"] = {"value": neighbor_count, "unit": "count"}

            # 温度是可选指标（P2-10）：部分型号/单板不支持该命令，失败不能影响其它指标，
            # 也不写 0 —— 解析不到就干脆不产生该指标。
            try:
                temp_output = await read(command_profile["temperature"])
                temp_value = self._parse_temperature(temp_output)
                if temp_value is not None:
                    metrics["temperature"] = {"value": temp_value, "unit": "°C"}
            except asyncio.TimeoutError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "temperature_collect_skipped", device=device.hostname, error=str(exc)
                )

        finally:
            await adapter.close()

        return metrics

    async def _save_metrics(self, device: Device, metrics: dict) -> dict:
        async with self._db_lock:
            # A bad device record must not poison later devices in this batch.
            async with self.db.begin_nested():
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                for metric_type, data in metrics.items():
                    record = MetricRecord(
                        device_id=device.id, metric_type=metric_type,
                        metric_name=data.get("name", ""), value=data["value"],
                        unit=data.get("unit", ""), collected_at=now
                    )
                    self.db.add(record)

                from modules.monitor.ports import assess_ports, load_policy, VERSION
                from modules.monitor.port_service import evaluate_port_alarms
                policy = await load_policy(self.db, device.id)
                sample = self._port_samples.pop(device.id, None)
                port_snapshot = None
                alarms = []
                if sample:
                    port_snapshot = assess_ports(sample, policy) | {
                        'observed_at': sample['observed_at'], 'mode': sample['mode'], 'version': VERSION}
                    alarms.extend(await evaluate_port_alarms(self.db, device, port_snapshot))
                for metric_type, data in metrics.items():
                    if metric_type == 'interface_down' and port_snapshot is not None:
                        continue  # raw count remains a metric; policy-aware alarms are distinct
                    alarm = await AlarmService.evaluate_and_alarm(self.db, device, metric_type, data["value"], commit=False)
                    if alarm is not None:
                        alarms.append(alarm)
                await self.db.flush()
                return {
                    "device_id": device.id, "hostname": device.hostname, "status": "success",
                    "collected_at": now.isoformat() + "Z",
                    "port_observation": port_snapshot,
                    "metrics": [{"metric_type": name, "value": data["value"], "unit": data.get("unit", "")}
                                for name, data in metrics.items()],
                    "alarms": [{"id": alarm.id, "alarm_type": alarm.alarm_type,
                                "severity": alarm.severity, "metric_value": alarm.metric_value,
                                "threshold": alarm.threshold} for alarm in alarms],
                }

    @staticmethod
    def _parse_cpu(output: str) -> float | None:
        match = re.search(r'CPU\s*Usage[:\s]*(\d+(?:\.\d+)?)\s*%', output, re.IGNORECASE)
        if match:
            return float(match.group(1))
        match = re.search(r'Max\s*CPU.*?(\d+(?:\.\d+)?)\s*%', output, re.IGNORECASE)
        if match:
            return float(match.group(1))
        return None

    @staticmethod
    def _parse_memory(output: str) -> float | None:
        match = re.search(r'Memory\s*Using\s*Percentage.*?(\d+(?:\.\d+)?)\s*%', output, re.IGNORECASE)
        if match:
            return float(match.group(1))
        used_match = re.search(r'Used[:\s]*(\d+)\s*MB', output, re.IGNORECASE)
        total_match = re.search(r'Total[:\s]*(\d+)\s*MB', output, re.IGNORECASE)
        if used_match and total_match:
            used = int(used_match.group(1))
            total = int(total_match.group(1))
            if total > 0:
                return round(used / total * 100, 2)
        return None

    _TEMPERATURE_RE = re.compile(r"Current temperature:\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)

    @staticmethod
    def _parse_temperature(output: str) -> float | None:
        """取各板卡"当前温度"的最高值（`display temperature`）。

        只解析 VRP 的 `Current temperature: 41.5 degrees Celsius` 形式；解析不到就返回
        None，让调用方直接跳过该指标 —— 不写 0，避免把"没采到"伪装成"温度 0 度"。
        """
        values = [float(raw) for raw in MetricCollector._TEMPERATURE_RE.findall(output or "")]
        return max(values) if values else None

    # 接口状态取值（VRP brief 输出里带 * 前缀表示管理/协议异常）
    _IFACE_STATUS_TOKENS = frozenset({"up", "down", "dormant", "off", "absent", "admindown"})
    _IFACE_ROW_RE = re.compile(r"^(?P<name>[A-Za-z][\w./\-]*)\s+(?P<rest>.+)$")

    @staticmethod
    def _parse_interfaces(output: str) -> dict:
        """按"接口名 + PHY + Protocol 状态列"解析 up/down。

        此前用 `"up" in line` 子串匹配：接口描述里含 up、或 "Info: ... backup ..." 之类
        说明行都会被计入，且 `up/down`（物理 up、协议 down）只会算一次 down。
        现在只认状态列：两个状态列都 up 才算 up，否则算 down。
        """
        up = down = 0
        for line in (output or "").splitlines():
            match = MetricCollector._IFACE_ROW_RE.match(line.strip())
            if not match:
                continue
            tokens = [token.lstrip("*").lower() for token in match.group("rest").split()]
            status_tokens = [token for token in tokens if token in MetricCollector._IFACE_STATUS_TOKENS]
            if not status_tokens:
                continue  # 表头或说明行
            phy = status_tokens[0]
            proto = status_tokens[1] if len(status_tokens) > 1 else status_tokens[0]
            if phy == "up" and proto == "up":
                up += 1
            else:
                down += 1
        if not up and not down:
            return {}
        return {"interface_up": {"value": up, "unit": "count"}, "interface_down": {"value": down, "unit": "count"}}

    @staticmethod
    def _parse_ospf_neighbors(output: str) -> int | None:
        if not output.strip() or re.search(r"Error:|Unrecognized command|Incomplete command", output, re.I):
            return None
        count = 0
        for line in output.strip().splitlines():
            if "Full" in line or "2-Way" in line:
                count += 1
        return count


class AlarmService:
    @classmethod
    async def evaluate_and_alarm(cls, db: AsyncSession, device: Device, metric_type: str, value: float, *, commit: bool = True) -> Alarm | None:
        if metric_type == 'interface_down':
            # Legacy callers without a parsed port snapshot have no business-impact evidence.
            # Do not mutate/auto-resolve historic aggregate-count alarms under a new rule.
            if value <= 0:
                return None
            from modules.monitor.port_service import evaluate_port_alarms
            from modules.monitor.ports import VERSION
            alarms = await evaluate_port_alarms(db, device, {
                'version': VERSION, 'ports': [], 'complete': False, 'expected_down': 0,
                'review_count': int(value), 'missing_expected_ports': [], 'policy_revision': 'unknown',
                'observed_at': datetime.now(timezone.utc).isoformat()})
            if commit:
                await db.commit()
                await db.refresh(alarms[0])
            return alarms[0]
        thresholds_all = await load_thresholds(db)
        thresholds = thresholds_all.get(metric_type)
        if not thresholds:
            return None

        severity = _severity_for(value, thresholds)
        # 方向决定告警类型后缀：接口 down / OSPF 邻居减少是"低于阈值"，与 CPU 超限区分开
        suffix = "low" if thresholds.get("direction") == "low" else "high"
        alarm_type = f"{metric_type}_{suffix}"

        if severity is None:
            await cls._auto_resolve(db, device, metric_type, commit=commit)
            return None

        existing = await db.execute(
            select(Alarm).where(
                Alarm.device_id == device.id,
                Alarm.alarm_type == alarm_type,
                Alarm.status.in_([AlarmStatus.FIRED, AlarmStatus.ACKNOWLEDGED])
            )
        )
        existing_alarm = existing.scalar_one_or_none()

        unit = "°C" if metric_type == "temperature" else ""
        detail = f"{device.hostname} {metric_type} = {value}{unit}，触发{severity}阈值"

        if existing_alarm:
            existing_alarm.severity = severity
            existing_alarm.metric_value = value
            existing_alarm.threshold = thresholds[severity]
            existing_alarm.message = detail
            if commit:
                await db.commit()
            return existing_alarm

        alarm = Alarm(
            device_id=device.id, alarm_type=alarm_type, severity=severity,
            message=detail,
            metric_value=value, threshold=thresholds[severity], status=AlarmStatus.FIRED
        )
        db.add(alarm)
        if commit:
            await db.commit()
            await db.refresh(alarm)

        logger.warning("alarm_fired", device=device.hostname, type=metric_type, value=value, severity=severity)
        return alarm

    @classmethod
    async def _auto_resolve(cls, db: AsyncSession, device: Device, metric_type: str, *, commit: bool = True):
        # B3：阈值有方向（high/low），自动恢复要覆盖两个方向，否则 low 类告警（接口 down、
        # OSPF 邻居恢复）永远停留在 FIRED。
        result = await db.execute(
            select(Alarm).where(
                Alarm.device_id == device.id,
                Alarm.alarm_type.like(f"{metric_type}\\_%", escape="\\"),
                Alarm.status.in_([AlarmStatus.FIRED, AlarmStatus.ACKNOWLEDGED])
            )
        )
        alarms = result.scalars().all()
        for alarm in alarms:
            alarm.status = AlarmStatus.RESOLVED
            alarm.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if alarms and commit:
            await db.commit()

    @staticmethod
    async def acknowledge_alarm(db: AsyncSession, alarm_id: int, user_id: int) -> Alarm:
        alarm = await db.get(Alarm, alarm_id)
        if not alarm:
            raise ValueError("告警不存在")
        if alarm.status != AlarmStatus.FIRED:
            raise ValueError("当前状态不允许确认")
        alarm.status = AlarmStatus.ACKNOWLEDGED
        alarm.acknowledged_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.commit()
        await _audit_alarm(db, user_id, "alarm_acknowledged", alarm)
        return alarm

    @staticmethod
    async def close_alarm(db: AsyncSession, alarm_id: int, user_id: int) -> Alarm:
        alarm = await db.get(Alarm, alarm_id)
        if not alarm:
            raise ValueError("告警不存在")
        if alarm.status not in (AlarmStatus.RESOLVED, AlarmStatus.ACKNOWLEDGED):
            raise ValueError("当前状态不允许关闭")
        alarm.status = AlarmStatus.CLOSED
        alarm.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.commit()
        await _audit_alarm(db, user_id, "alarm_closed", alarm)
        return alarm


class MetricAggregator:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    async def aggregate_hourly(self, target_hour: datetime | None = None) -> int:
        if target_hour is None:
            target_hour = datetime.now(timezone.utc).replace(tzinfo=None).replace(minute=0, second=0, microsecond=0)
        period_start = target_hour
        period_end = target_hour.replace(minute=59, second=59)

        result = await self.db.execute(
            select(
                MetricRecord.device_id,
                MetricRecord.metric_type,
                func.min(MetricRecord.value).label("min_v"),
                func.max(MetricRecord.value).label("max_v"),
                func.avg(MetricRecord.value).label("avg_v"),
                func.count(MetricRecord.id).label("cnt"),
            ).where(
                MetricRecord.collected_at >= period_start,
                MetricRecord.collected_at <= period_end,
            ).group_by(MetricRecord.device_id, MetricRecord.metric_type)
        )
        rows = result.all()
        created = 0
        # 幂等：同一小时重复聚合时先清掉旧行，避免重复累计
        await self.db.execute(delete(MetricAggregated).where(
            MetricAggregated.agg_level == AggLevel.HOURLY,
            MetricAggregated.period_start == period_start,
        ))
        for row in rows:
            agg = MetricAggregated(
                device_id=row.device_id,
                metric_type=row.metric_type,
                agg_level=AggLevel.HOURLY,
                period_start=period_start,
                period_end=period_end,
                min_value=round(row.min_v, 2),
                max_value=round(row.max_v, 2),
                avg_value=round(float(row.avg_v), 2),
                sample_count=row.cnt,
            )
            self.db.add(agg)
            created += 1
        if created:
            await self.db.commit()
        logger.info("hourly_aggregation_complete", period=period_start.isoformat(), records=created)
        return created

    async def aggregate_daily(self, target_date: datetime | None = None) -> int:
        if target_date is None:
            target_date = datetime.now(timezone.utc).replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
        period_start = target_date
        period_end = target_date.replace(hour=23, minute=59, second=59)

        result = await self.db.execute(
            select(
                MetricAggregated.device_id,
                MetricAggregated.metric_type,
                func.min(MetricAggregated.min_value).label("min_v"),
                func.max(MetricAggregated.max_value).label("max_v"),
                func.avg(MetricAggregated.avg_value).label("avg_v"),
                func.sum(MetricAggregated.sample_count).label("cnt"),
            ).where(
                MetricAggregated.agg_level == AggLevel.HOURLY,
                MetricAggregated.period_start >= period_start,
                MetricAggregated.period_start <= period_end,
            ).group_by(MetricAggregated.device_id, MetricAggregated.metric_type)
        )
        rows = result.all()
        created = 0
        # 幂等：同一天重复聚合时先清掉旧行
        await self.db.execute(delete(MetricAggregated).where(
            MetricAggregated.agg_level == AggLevel.DAILY,
            MetricAggregated.period_start == period_start,
        ))
        for row in rows:
            agg = MetricAggregated(
                device_id=row.device_id,
                metric_type=row.metric_type,
                agg_level=AggLevel.DAILY,
                period_start=period_start,
                period_end=period_end,
                min_value=round(row.min_v, 2),
                max_value=round(row.max_v, 2),
                avg_value=round(float(row.avg_v), 2),
                sample_count=row.cnt,
            )
            self.db.add(agg)
            created += 1
        if created:
            await self.db.commit()
        logger.info("daily_aggregation_complete", period=period_start.isoformat(), records=created)
        return created

    async def cleanup_old_records(self) -> dict:
        retention_days = self.settings.monitor_retention_days
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        raw_cutoff = now - timedelta(days=retention_days)
        agg_cutoff = now - timedelta(days=retention_days * 2)

        raw_result = await self.db.execute(
            delete(MetricRecord).where(MetricRecord.collected_at < raw_cutoff)
        )
        raw_deleted = raw_result.rowcount

        agg_result = await self.db.execute(
            delete(MetricAggregated).where(MetricAggregated.created_at < agg_cutoff)
        )
        agg_deleted = agg_result.rowcount

        await self.db.commit()
        logger.info(
            "data_cleanup_complete",
            raw_deleted=raw_deleted,
            agg_deleted=agg_deleted,
            raw_cutoff=raw_cutoff.isoformat(),
            agg_cutoff=agg_cutoff.isoformat(),
        )
        return {"raw_deleted": raw_deleted, "agg_deleted": agg_deleted}
