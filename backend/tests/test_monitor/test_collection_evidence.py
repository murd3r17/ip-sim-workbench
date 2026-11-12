from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from modules.device.models import Device, DeviceStatus, DeviceType, Topology
from modules.monitor.models import Alarm, AlarmStatus, MetricRecord, MetricType
from modules.monitor.service import MetricCollector, MonitorService
from modules.monitor.router import get_monitor_stats, list_alarms


async def make_devices(db, statuses):
    topology = Topology(name="Isolated evidence", device_count=len(statuses))
    db.add(topology)
    await db.flush()
    devices = [Device(hostname=f"E{i}", mgmt_ip=f"192.0.2.{i + 1}", device_type=DeviceType.ROUTER,
                      topology_id=topology.id, status=status) for i, status in enumerate(statuses)]
    db.add_all(devices)
    await db.commit()
    return topology, devices


@pytest.mark.asyncio
async def test_all_offline_is_explicitly_skipped_not_success(client, test_session_factory):
    async with test_session_factory() as db:
        topology, _ = await make_devices(db, [DeviceStatus.OFFLINE, DeviceStatus.UNKNOWN])
        result = await MonitorService.run_inspection(db, topology.id)
        assert result["task"]["status"] == "failed"
        assert result["summary"]["expected"] == 2
        assert result["summary"]["attempted"] == 0
        assert result["summary"]["skipped"] == 2
        assert result["report"]["summary"]["metric_points"] == 0


@pytest.mark.asyncio
async def test_report_contains_only_current_successful_device_evidence(client, test_session_factory, monkeypatch):
    async with test_session_factory() as db:
        topology, devices = await make_devices(db, [DeviceStatus.ONLINE, DeviceStatus.ONLINE])
        db.add(MetricRecord(device_id=devices[1].id, metric_type=MetricType.CPU_USAGE, value=99,
                            collected_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)))
        db.add(Alarm(device_id=devices[1].id, alarm_type="old", severity="critical", message="old",
                     status=AlarmStatus.CLOSED))
        await db.commit()

        async def collect(self, device):
            if device.id == devices[1].id:
                raise TimeoutError("isolated failure")
            return {"cpu_usage": {"value": 20, "unit": "%"}}

        monkeypatch.setattr(MetricCollector, "_collect_via_ssh", collect)
        result = await MonitorService.run_inspection(db, topology.id)
        assert result["task"]["status"] == "failed"
        assert result["summary"]["success"] == 1
        assert result["summary"]["failed"] == 1
        assert result["report"]["summary"]["metric_points"] == 1
        assert result["report"]["alarm_count"] == 0
        assert result["report"]["job_id"] == result["task"]["id"]
        evidence = result["report"]["devices"]
        assert len(evidence) == 1 and evidence[0]["device_id"] == devices[0].id
        assert evidence[0]["metrics"][0]["value"] == 20
        assert evidence[0]["collected_at"]


@pytest.mark.asyncio
async def test_empty_metric_response_is_not_collection_success(client, test_session_factory, monkeypatch):
    async def empty(self, device):
        return {}
    monkeypatch.setattr(MetricCollector, "_collect_via_ssh", empty)
    async with test_session_factory() as db:
        topology, _ = await make_devices(db, [DeviceStatus.ONLINE])
        result = await MonitorService.run_collection(db, topology.id)
        assert result["summary"]["failed"] == 1
        assert result["task"]["status"] == "failed"


def test_empty_or_unsupported_commands_do_not_create_zero_metrics():
    assert MetricCollector._parse_interfaces("") == {}
    assert MetricCollector._parse_ospf_neighbors("Error: Unrecognized command") is None


@pytest.mark.asyncio
async def test_bad_device_data_does_not_poison_later_device_transaction(client, test_session_factory, monkeypatch):
    async def collect(self, device):
        return {"cpu_usage": {"value": None if device.hostname == "E0" else 25, "unit": "%"}}
    monkeypatch.setattr(MetricCollector, "_collect_via_ssh", collect)
    async with test_session_factory() as db:
        topology, devices = await make_devices(db, [DeviceStatus.ONLINE, DeviceStatus.ONLINE])
        result = await MonitorService.run_collection(db, topology.id)
        assert result["summary"]["failed"] == 1
        assert result["summary"]["success"] == 1
        records = list((await db.execute(select(MetricRecord))).scalars())
        assert len(records) == 1 and records[0].device_id == devices[1].id


@pytest.mark.asyncio
async def test_stats_and_active_filter_include_acknowledged_but_not_resolved(client, test_session_factory):
    async with test_session_factory() as db:
        _, devices = await make_devices(db, [DeviceStatus.ONLINE])
        for status in AlarmStatus:
            db.add(Alarm(device_id=devices[0].id, alarm_type=status.value, severity="warning", message="isolated", status=status))
        await db.commit()
        stats = await get_monitor_stats(db=db, current_user={})
        rows = await list_alarms(status="active", device_id=None, limit=100, offset=0, db=db, current_user={})
        assert stats["activeAlarms"] == stats["warningAlarms"] == len(rows) == 2
        assert {row["status"] for row in rows} == {"fired", "acknowledged"}
