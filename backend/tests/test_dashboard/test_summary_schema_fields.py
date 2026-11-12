"""回归测试：/dashboard/summary 的 A7 新字段必须真的出现在响应里。

背景：该端点用 `response_model=DashboardSummary`，FastAPI 会**裁掉**未在 Pydantic 模型里
声明的字段。A7 新增的 `alarms.trend` / `approvals` / `reports` 曾因此静默失效（service 里算好
了但到不了前端，趋势图永远显示"近 7 天没有产生告警"）。这组用例就是防止再次发生。
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from modules.deploy.models import ChangeLevel, DeployStatus, DeployTask
from modules.device.models import Device, DeviceStatus, DeviceType, DeviceVendor, Topology, TopologyType
from modules.monitor.models import Alarm, AlarmStatus, MonitorJob, MonitorJobStatus, MonitorJobType, MonitorTriggerMode
from modules.auth.models import User, UserRole


async def _seed_operator(db) -> User:
    user = User(username="schema-op", hashed_password="x", role=UserRole.ADMIN)
    db.add(user)
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_dashboard_summary_exposes_trend_approvals_and_reports(client, test_session_factory):
    async with test_session_factory() as db:
        await db.execute(update(Topology).values(status="inactive"))
        operator = await _seed_operator(db)
        topology = Topology(name="Schema Topo", topology_type=TopologyType.MAIN, status="active")
        db.add(topology)
        await db.flush()
        device = Device(
            hostname="schema-dev", mgmt_ip="198.51.100.201", device_type=DeviceType.ROUTER,
            vendor=DeviceVendor.HUAWEI, status=DeviceStatus.ONLINE, topology_id=topology.id,
        )
        db.add(device)
        await db.flush()

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # 待审批任务（高风险、等待确认）
        db.add(DeployTask(
            device_id=device.id, config_content="sysname X", status=DeployStatus.AWAITING_CONFIRMATION,
            change_level=ChangeLevel.HIGH_RISK, operator_id=operator.id,
        ))
        # 两条告警：一条在窗口内、一条 10 天前（不应计入 7 天趋势）
        db.add_all([
            Alarm(device_id=device.id, alarm_type="cpu_usage_high", severity="warning",
                  message="hot", metric_value=80, threshold=70, status=AlarmStatus.FIRED, fired_at=now),
            Alarm(device_id=device.id, alarm_type="cpu_usage_high", severity="warning",
                  message="old", metric_value=80, threshold=70, status=AlarmStatus.RESOLVED,
                  fired_at=now - timedelta(days=10)),
        ])
        # 一条巡检任务
        db.add(MonitorJob(
            topology_id=topology.id, job_type=MonitorJobType.INSPECTION,
            trigger_mode=MonitorTriggerMode.MANUAL, status=MonitorJobStatus.SUCCESS,
            device_count=3, success_count=3, failure_count=0,
            report_json='{"alarm_count": 1, "metric_types": ["cpu_usage"]}',
        ))
        await db.commit()

    token_user = await _login(client, test_session_factory)
    resp = await client.get("/api/v1/dashboard/summary", headers=token_user)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # 1) 趋势：7 个点、日期升序、只统计窗口内的告警
    trend = body["alarms"]["trend"]
    assert len(trend) == 7
    assert [p["count"] for p in trend][-1] == 1, trend
    assert sum(p["count"] for p in trend) == 1
    dates = [p["date"] for p in trend]
    assert dates == sorted(dates)

    # 2) 审批：待确认任务带设备名与高风险标记
    approvals = body["approvals"]
    assert any(item["high_risk"] and item["status"] == "awaiting_confirmation" for item in approvals), approvals

    # 3) 报告：巡检任务带统计与告警数
    reports = body["reports"]
    assert reports and reports[0]["job_type"] == "inspection"
    assert reports[0]["alarm_count"] == 1


async def _login(client, session_factory) -> dict:
    from core.security import create_access_token

    async with session_factory() as db:
        user = User(username="schema-viewer", hashed_password="x", role=UserRole.ADMIN)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        token = create_access_token(user.id, user.username, "admin")
    return {"Authorization": f"Bearer {token}"}
