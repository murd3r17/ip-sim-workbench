"""B3：告警阈值扩充与可配置。

- 阈值覆盖 cpu/memory/interface_down/temperature/ospf_neighbor_count；
- 支持方向（high：越大越严重；low：越小越严重，如 OSPF 邻居数）；
- 系统配置键 `monitor.thresholds`（JSON）可覆盖默认阈值，非法配置回退默认。
"""

import json

import pytest
from sqlalchemy import delete

from modules.device.models import Device, DeviceStatus, DeviceType, DeviceVendor, Topology, TopologyType
from modules.monitor.models import Alarm, AlarmStatus
from modules.monitor.service import (
    THRESHOLDS,
    THRESHOLDS_CONFIG_KEY,
    AlarmService,
    _merge_thresholds,
    _severity_for,
    load_thresholds,
)
from modules.system.models import SystemConfig


async def _device(db, hostname: str = "thr-dev") -> Device:
    topology = Topology(name=f"topo-{hostname}", topology_type=TopologyType.LAB, status="active")
    db.add(topology)
    await db.flush()
    device = Device(
        hostname=hostname, mgmt_ip="198.51.100.111",
        device_type=DeviceType.ROUTER, vendor=DeviceVendor.HUAWEI,
        status=DeviceStatus.ONLINE, topology_id=topology.id,
    )
    db.add(device)
    await db.commit()
    return device


class TestThresholds:
    def test_defaults_cover_more_than_cpu_memory(self):
        assert {"cpu_usage", "memory_usage", "interface_down", "temperature", "ospf_neighbor_count"} <= set(THRESHOLDS)

    def test_severity_direction_high(self):
        cfg = {"direction": "high", "warning": 70, "critical": 95}
        assert _severity_for(60, cfg) is None
        assert _severity_for(70, cfg) == "warning"
        assert _severity_for(96, cfg) == "critical"

    def test_severity_direction_low(self):
        cfg = {"direction": "low", "warning": 1, "critical": 0}
        assert _severity_for(3, cfg) is None
        assert _severity_for(1, cfg) == "warning"
        assert _severity_for(0, cfg) == "critical"

    def test_merge_overrides_only_given_levels(self):
        merged = _merge_thresholds(
            {"cpu_usage": {"direction": "high", "warning": 70, "critical": 95}},
            {"cpu_usage": {"warning": 50}, "unknown_metric": {"warning": 1}},
        )
        assert merged["cpu_usage"]["warning"] == 50
        assert merged["cpu_usage"]["critical"] == 95  # 未给出的档位保持默认
        assert "unknown_metric" not in merged


class TestThresholdConfig:
    @pytest.mark.asyncio
    async def test_defaults_without_config_row(self, test_session_factory):
        async with test_session_factory() as db:
            await db.execute(delete(SystemConfig).where(SystemConfig.config_key == THRESHOLDS_CONFIG_KEY))
            await db.commit()
            thresholds = await load_thresholds(db)
        assert thresholds["cpu_usage"]["warning"] == THRESHOLDS["cpu_usage"]["warning"]

    @pytest.mark.asyncio
    async def test_system_config_overrides(self, test_session_factory):
        async with test_session_factory() as db:
            await db.execute(delete(SystemConfig).where(SystemConfig.config_key == THRESHOLDS_CONFIG_KEY))
            db.add(SystemConfig(
                config_key=THRESHOLDS_CONFIG_KEY,
                config_value=json.dumps({"cpu_usage": {"warning": 42}, "temperature": {"critical": 60}}),
            ))
            await db.commit()
            thresholds = await load_thresholds(db)
        assert thresholds["cpu_usage"]["warning"] == 42
        assert thresholds["temperature"]["critical"] == 60
        assert thresholds["memory_usage"]["warning"] == THRESHOLDS["memory_usage"]["warning"]

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back_to_defaults(self, test_session_factory):
        async with test_session_factory() as db:
            await db.execute(delete(SystemConfig).where(SystemConfig.config_key == THRESHOLDS_CONFIG_KEY))
            db.add(SystemConfig(config_key=THRESHOLDS_CONFIG_KEY, config_value="{不是合法 JSON"))
            await db.commit()
            thresholds = await load_thresholds(db)
        assert thresholds["cpu_usage"]["warning"] == THRESHOLDS["cpu_usage"]["warning"]


class TestEvaluateAndAlarm:
    @pytest.mark.asyncio
    async def test_temperature_fires_and_uses_celsius_unit(self, test_session_factory):
        async with test_session_factory() as db:
            device = await _device(db, "thr-temp")
            # 默认档位：warning 65 / minor 70 / major 75 / critical 85
            alarm = await AlarmService.evaluate_and_alarm(db, device, "temperature", 66.0)
            assert alarm is not None
            assert alarm.severity == "warning"
            assert alarm.alarm_type == "temperature_high"
            assert "°C" in alarm.message

            hotter = await AlarmService.evaluate_and_alarm(db, device, "temperature", 90.0)
            assert hotter.severity == "critical"

    @pytest.mark.asyncio
    async def test_interface_down_fires(self, test_session_factory):
        async with test_session_factory() as db:
            device = await _device(db, "thr-if")
            alarm = await AlarmService.evaluate_and_alarm(db, device, "interface_down", 1)
            assert alarm is not None and alarm.alarm_type == "interface_review" and alarm.severity == 'warning'

    @pytest.mark.asyncio
    async def test_ospf_zero_without_expectation_only_requests_review(self, test_session_factory):
        async with test_session_factory() as db:
            device = await _device(db, "thr-ospf")
            alarm = await AlarmService.evaluate_and_alarm(db, device, "ospf_neighbor_count", 0)
            assert alarm is not None
            assert alarm.alarm_type == "ospf_neighbor_count_review"
            assert alarm.severity == "warning"
            assert "未登记本设备" in alarm.message

            # 邻居恢复 → 自动恢复（方向为 low 的告警此前永远不会被 auto-resolve）
            await AlarmService.evaluate_and_alarm(db, device, "ospf_neighbor_count", 3)
            refreshed = await db.get(Alarm, alarm.id)
            assert refreshed.status == AlarmStatus.RESOLVED

    @pytest.mark.asyncio
    async def test_ospf_baseline_zero_and_positive_follow_device_expectation(self, test_session_factory):
        from modules.monitor.ports import PortPolicyWrite, load_policy
        from modules.monitor.port_service import save_port_policy
        from modules.auth.models import User, UserRole

        async with test_session_factory() as db:
            device = await _device(db, "thr-ospf-expected")
            admin = User(username="ospf-policy-admin", hashed_password="test", role=UserRole.ADMIN, is_active=True)
            db.add(admin)
            await db.commit()
            actor = {"user_id": admin.id, "username": admin.username}
            policy = await load_policy(db, device.id)
            policy = await save_port_policy(db, device.id, PortPolicyWrite(base_revision=policy["revision"], ospf_min_neighbors=0), actor)
            assert await AlarmService.evaluate_and_alarm(db, device, "ospf_neighbor_count", 0) is None
            policy = await save_port_policy(db, device.id, PortPolicyWrite(base_revision=policy["revision"], ospf_min_neighbors=2), actor)
            alarm = await AlarmService.evaluate_and_alarm(db, device, "ospf_neighbor_count", 1)
            assert alarm is not None and alarm.alarm_type == "ospf_neighbor_count_expected_low"
            assert alarm.threshold == 2 and alarm.severity == "major"
            await AlarmService.evaluate_and_alarm(db, device, "ospf_neighbor_count", 2)
            assert alarm.status == AlarmStatus.RESOLVED

    @pytest.mark.asyncio
    async def test_metric_without_threshold_is_ignored(self, test_session_factory):
        async with test_session_factory() as db:
            device = await _device(db, "thr-none")
            assert await AlarmService.evaluate_and_alarm(db, device, "interface_up", 3) is None
