"""监控路由单测"""
from unittest.mock import AsyncMock, patch

import pytest

from modules.monitor.router import get_monitor_trends, run_inspection, list_monitor_tasks


class TestMonitorRouter:
    @pytest.mark.asyncio
    @patch("modules.monitor.router.MonitorService.get_trend_series", new_callable=AsyncMock)
    async def test_get_monitor_trends_routes_to_service(self, mock_get_trend):
        db = AsyncMock()
        current_user = {"user_id": 1, "role": "admin"}
        mock_get_trend.return_value = {"metrics": {"cpu_usage": [{"value": 66.0}]}, "alarms": [], "summary": {}}

        result = await get_monitor_trends(topology_id=1, device_id=2, metric_type="cpu_usage", limit=20, db=db, current_user=current_user)

        assert result["metrics"]["cpu_usage"][0]["value"] == 66.0
        mock_get_trend.assert_awaited_once_with(db, topology_id=1, device_id=2, metric_type="cpu_usage", limit=20)

    @pytest.mark.asyncio
    @patch("modules.monitor.router.MonitorService.run_inspection", new_callable=AsyncMock)
    async def test_run_inspection_routes_to_service(self, mock_run_inspection):
        db = AsyncMock()
        current_user = {"user_id": 7, "role": "admin"}
        mock_run_inspection.return_value = {
            "task": {"id": 1, "job_type": "inspection", "status": "success"},
            "summary": {"success": 1, "failed": 0, "skipped": 0, "errors": []},
            "report": {"alarm_count": 0, "metric_types": ["cpu_usage"]},
        }

        result = await run_inspection(topology_id=1, db=db, current_user=current_user)

        assert result["task"]["job_type"] == "inspection"
        mock_run_inspection.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("modules.monitor.router.MonitorService.list_jobs", new_callable=AsyncMock)
    async def test_list_monitor_tasks_routes_to_service(self, mock_list_jobs):
        db = AsyncMock()
        current_user = {"user_id": 1, "role": "admin"}
        mock_list_jobs.return_value = [{"id": 1, "job_type": "inspection"}]

        result = await list_monitor_tasks(topology_id=1, job_type="inspection", limit=5, db=db, current_user=current_user)

        assert result[0]["job_type"] == "inspection"
        mock_list_jobs.assert_awaited_once()
