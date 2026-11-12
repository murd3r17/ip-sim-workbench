"""监控模块阶段5工作流测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestMonitorCommandProfile:
    def test_router_profile_includes_protocol_state_command(self):
        from modules.device.models import DeviceType
        from modules.monitor.service import MonitorService

        device = MagicMock()
        device.device_type = DeviceType.ROUTER
        device.vendor = "huawei"
        device.model = "NE40E"

        profile = MonitorService.build_command_profile(device)

        assert profile["cpu"] == "display cpu-usage"
        assert profile["memory"] == "display memory-usage"
        assert profile["interface"] == "display interface brief"
        assert profile["protocol"] == "display ospf peer brief"

    def test_switch_profile_uses_switch_protocol_command(self):
        from modules.device.models import DeviceType
        from modules.monitor.service import MonitorService

        device = MagicMock()
        device.device_type = DeviceType.SWITCH_L2
        device.vendor = "huawei"
        device.model = "S5700"

        profile = MonitorService.build_command_profile(device)

        assert profile["protocol"] == "display stp brief"


class TestMonitorTrendsService:
    @pytest.mark.asyncio
    async def test_get_monitor_trends_returns_real_series(self):
        from modules.monitor.service import MonitorService

        db = MagicMock()
        db.execute = AsyncMock()

        metric_row = MagicMock()
        metric_row.metric_type = "cpu_usage"
        metric_row.collected_at = "2026-07-17T00:00:00+00:00"
        metric_row.value = 66.0
        metric_row.device_id = 1
        metric_result = MagicMock()
        metric_result.all.return_value = [(metric_row,'R-A')]

        alarm_row = MagicMock()
        alarm_row.fired_at = "2026-07-17T00:00:00+00:00"
        alarm_row.severity = "warning"
        alarm_result = MagicMock()
        alarm_result.scalars.return_value.all.return_value = [alarm_row]

        db.execute.side_effect = [metric_result, alarm_result]

        data = await MonitorService.get_trend_series(db, topology_id=1, device_id=1)

        assert "metrics" in data
        assert "alarms" in data
        assert data["metrics"]["cpu_usage"][0]["value"] == 66.0
        assert data["metrics"]["cpu_usage"][0]["device_name"] == 'R-A'
        assert data["alarms"][0]["severity"] == "warning"


class TestMonitorInspectionService:
    @pytest.mark.asyncio
    async def test_run_inspection_returns_task_and_report(self):
        from modules.monitor.service import MonitorService

        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock()

        metric_row = MagicMock()
        metric_row.metric_type = "cpu_usage"
        metric_row.collected_at = MagicMock(isoformat=lambda: "2026-07-17T00:00:00+00:00")
        metric_row.value = 66.0
        metric_result = MagicMock()
        metric_result.scalars.return_value.all.return_value = [metric_row]

        alarm_row = MagicMock()
        alarm_row.fired_at = MagicMock(isoformat=lambda: "2026-07-17T00:05:00+00:00")
        alarm_row.severity = "warning"
        alarm_result = MagicMock()
        alarm_result.scalars.return_value.all.return_value = [alarm_row]

        db.execute.side_effect = [metric_result, alarm_result]

        from modules.monitor.service import MetricCollector
        original_collect = MetricCollector.collect_all_devices
        MetricCollector.collect_all_devices = AsyncMock(return_value={
            "expected": 1, "attempted": 1, "success": 1, "failed": 0, "skipped": 0, "errors": [],
            "devices": [{"device_id": 1, "status": "success", "collected_at": "2026-07-17T00:00:00Z",
                         "metrics": [{"metric_type": "cpu_usage", "value": 66.0}],
                         "alarms": [{"severity": "warning"}]}],
        })
        try:
            data = await MonitorService.run_inspection(db, topology_id=1, triggered_by=7, trigger_mode="manual")
        finally:
            MetricCollector.collect_all_devices = original_collect

        assert data["task"]["job_type"] == "inspection"
        assert data["task"]["status"] == "success"
        assert data["report"]["alarm_count"] == 1
        assert data["report"]["metric_types"] == ["cpu_usage"]
