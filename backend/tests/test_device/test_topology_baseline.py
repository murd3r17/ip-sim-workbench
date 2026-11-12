from tests.test_device._runtime_fixture import with_coverage, complete_coverage
"""V6.0 stage 3 topology baseline tests."""
import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from core.security import create_access_token
from modules.auth.models import AuditLog, User, UserRole
from modules.auth.service import AuditService
from modules.device.baseline_service import TopologyBaselineService, snapshot_diff
from modules.device.models import (
    Device,
    DeviceStatus,
    DeviceType,
    DeviceVendor,
    Topology,
    TopologyLink,
    TopologyRuntimeCheck,
    TopologyType,
    TopologyVersion,
)
from modules.device.service import DeviceService, TopologyService
from modules.device.topology_import import TopologyExcelParser, compare_topology_links
from modules.device.lldp_parser import parse_lldp_neighbor_brief
from modules.device.readonly_commands import get_readonly_commands


def _workbook_bytes(
    *,
    duplicate_ip: bool = False,
    changed: bool = False,
    include_third: bool = False,
    malformed_link: bool = False,
) -> bytes:
    workbook = Workbook()
    devices = workbook.active
    devices.title = "设备信息"
    devices.append(["设备名称", "IP地址", "账号", "密码", "串口密码", "备注"])
    devices.append(["R-1", "192.0.2.1", None, None, None, "core"])
    devices.append(["R-2", "192.0.2.1" if duplicate_ip else "192.0.2.2", None, None, None, "edge"])
    if include_third:
        devices.append(["R-3", "192.0.2.3", None, None, None, "edge"])

    links = workbook.create_sheet("设备互联图")
    target_interface = "GE0/0/2" if changed else "GE0/0/1"
    links["B10"] = f"1. R-1 GE0/0/1 ↔ R-2 {target_interface}"
    if include_third:
        links["B10"] = "1. R-1 GE0/0/1 ↔ R-3 GE0/0/1"
    if malformed_link:
        links["B11"] = "2. R-1 ↔ R-2 GE0/0/2"

    addresses = workbook.create_sheet("Sheet1")
    target_ip = "10.0.0.6/30" if changed else "10.0.0.2/30"
    addresses["D20"] = (
        f"1 R-1 GE0/0/1 10.0.0.1/30 R-2 {target_interface} {target_ip}"
    )
    if include_third:
        addresses["D20"] = "1 R-1 GE0/0/1 10.0.0.1/30 R-3 GE0/0/1 10.0.0.2/30"

    content = BytesIO()
    workbook.save(content)
    return content.getvalue()


def test_excel_parser_ignores_credentials_and_parses_links_and_addresses():
    parsed = TopologyExcelParser.parse(_workbook_bytes())

    assert parsed.is_valid is True
    assert [device.hostname for device in parsed.devices] == ["R-1", "R-2"]
    assert parsed.devices[0].model_dump() == {
        "hostname": "R-1",
        "mgmt_ip": "192.0.2.1",
        "ssh_port": None,
        "notes": "core",
    }
    assert parsed.ignored_sensitive_columns == ["账号", "密码", "串口密码"]
    assert len(parsed.links) == 1
    assert parsed.links[0].source_ip == "10.0.0.1/30"
    assert parsed.links[0].target_ip == "10.0.0.2/30"


def test_excel_parser_rejects_duplicate_ip():
    parsed = TopologyExcelParser.parse(_workbook_bytes(duplicate_ip=True))

    assert parsed.is_valid is False
    assert any(issue.code == "duplicate_management_ip" for issue in parsed.issues)


def test_excel_parser_reports_malformed_link_row():
    parsed = TopologyExcelParser.parse(_workbook_bytes(malformed_link=True))

    assert parsed.is_valid is False
    assert any(issue.code == "missing_interface" and issue.row == 11 for issue in parsed.issues)


def test_snapshot_diff_preserves_parallel_links():
    first = {
        "devices": [],
        "links": [
            {"source_device": "R-1", "source_interface": "GE0/0/1", "target_device": "R-2", "target_interface": "GE0/0/1"},
            {"source_device": "R-1", "source_interface": "GE0/0/2", "target_device": "R-2", "target_interface": "GE0/0/2"},
        ],
    }
    second = {"devices": [], "links": [first["links"][0]]}

    assert snapshot_diff(first, second)["removed_links"] == 1


@pytest.mark.asyncio
async def test_latest_runtime_check_normalizes_legacy_object_errors():
    check = SimpleNamespace(
        id=3,
        status="different",
        ssh_success=21,
        ssh_failed=0,
        observed_links_json="[]",
        diff_json=json.dumps({"missing": [], "unexpected": []}),
        errors_json=json.dumps({"policy": "exclude_inactive_unassigned_physical_links"}),
        version_id=None,
        confirmed_version_id=None,
        baseline_fingerprint=None,
        created_at=None,
    )

    class Result:
        def scalar_one_or_none(self):
            return check

    class Session:
        calls = 0
        async def execute(self, statement):
            self.calls += 1
            return Result() if self.calls == 1 else SimpleNamespace(scalar_one_or_none=lambda: None)

    result = await TopologyService.get_latest_runtime_check(Session(), 1)

    assert result is not None
    assert result["errors"] == ['{"policy": "exclude_inactive_unassigned_physical_links"}']


@pytest.mark.asyncio
async def test_import_versions_diff_and_rollback(client, test_session_factory):
    async with test_session_factory() as db:
        user = User(
            username="stage3-admin",
            hashed_password="!",
            display_name="Stage 3 Admin",
            role=UserRole.ADMIN,
        )
        topology = Topology(
            name="Stage 3 Topology",
            topology_type=TopologyType.LAB,
            status="active",
        )
        db.add_all([user, topology])
        await db.commit()
        await db.refresh(user)
        await db.refresh(topology)
        user_id = user.id
        topology_id = topology.id

    headers = {
        "Authorization": f"Bearer {create_access_token(user_id, 'stage3-admin', 'admin')}"
    }
    first = _workbook_bytes()
    preview = await client.post(
        f"/api/v1/topologies/{topology_id}/imports/validate",
        files={"file": ("baseline.xlsx", first, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    assert preview.status_code == 200
    assert preview.json()["is_valid"] is True
    assert preview.json()["device_count"] == 2
    assert preview.json()["link_count"] == 1

    imported = await client.post(
        f"/api/v1/topologies/{topology_id}/imports?confirm=true",
        files={"file": ("baseline.xlsx", first, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    assert imported.status_code == 200
    assert imported.json()["version"] == 1

    changed = await client.post(
        f"/api/v1/topologies/{topology_id}/imports?confirm=true",
        files={"file": ("baseline-v2.xlsx", _workbook_bytes(changed=True), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    assert changed.status_code == 200
    assert changed.json()["version"] == 2
    assert changed.json()["diff"]["changed_links"] == 1

    versions = await client.get(
        f"/api/v1/topologies/{topology_id}/versions", headers=headers
    )
    assert [item["version"] for item in versions.json()][:2] == [2, 1]

    rollback = await client.post(
        f"/api/v1/topologies/{topology_id}/versions/1/rollback?confirm=true",
        headers=headers,
    )
    assert rollback.status_code == 200
    assert rollback.json()["version"] == 3
    assert rollback.json()["rollback_of_version"] == 1

    async with test_session_factory() as db:
        links = list((await db.execute(
            select(TopologyLink).where(TopologyLink.topology_id == topology_id)
        )).scalars())
        devices = list((await db.execute(
            select(Device).where(Device.topology_id == topology_id)
        )).scalars())
        stored_versions = list((await db.execute(
            select(TopologyVersion).where(TopologyVersion.topology_id == topology_id)
        )).scalars())

    assert len(devices) == 2
    assert len(links) == 1
    assert links[0].target_interface == "GE0/0/1"
    assert links[0].source_type == "baseline"
    assert links[0].discovery_source == "excel"
    assert len(stored_versions) == 3
    assert all("password" not in version.snapshot_json.lower() for version in stored_versions)


@pytest.mark.asyncio
async def test_first_import_versions_existing_baseline_before_replacement(client, test_session_factory):
    async with test_session_factory() as db:
        user = User(username="pre-import-admin", hashed_password="!", role=UserRole.ADMIN)
        topology = Topology(name="Existing Baseline", topology_type=TopologyType.LAB, status="active")
        db.add_all([user, topology])
        await db.flush()
        first = Device(
            hostname="R-1", mgmt_ip="192.0.2.1", device_type=DeviceType.ROUTER,
            vendor=DeviceVendor.HUAWEI, status=DeviceStatus.UNKNOWN, topology_id=topology.id,
        )
        second = Device(
            hostname="R-2", mgmt_ip="192.0.2.2", device_type=DeviceType.ROUTER,
            vendor=DeviceVendor.HUAWEI, status=DeviceStatus.UNKNOWN, topology_id=topology.id,
        )
        db.add_all([first, second])
        await db.flush()
        db.add(TopologyLink(
            topology_id=topology.id,
            source_device_id=first.id,
            source_interface="GE0/0/9",
            target_device_id=second.id,
            target_interface="GE0/0/9",
            source_type="baseline",
            discovery_source="manual",
        ))
        await db.commit()
        user_id, topology_id = user.id, topology.id

    headers = {"Authorization": f"Bearer {create_access_token(user_id, 'pre-import-admin', 'admin')}"}
    preview = await client.post(
        f"/api/v1/topologies/{topology_id}/imports/validate",
        files={"file": ("baseline.xlsx", _workbook_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    assert preview.status_code == 200
    assert preview.json()["current_device_count"] == 2
    assert preview.json()["current_link_count"] == 1
    assert preview.json()["replaced_link_count"] == 1

    imported = await client.post(
        f"/api/v1/topologies/{topology_id}/imports?confirm=true",
        files={"file": ("baseline.xlsx", _workbook_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    assert imported.status_code == 200
    assert imported.json()["version"] == 2

    rollback = await client.post(
        f"/api/v1/topologies/{topology_id}/versions/1/rollback?confirm=true",
        headers=headers,
    )
    assert rollback.status_code == 200
    async with test_session_factory() as db:
        restored = list((await db.execute(
            select(TopologyLink).where(TopologyLink.topology_id == topology_id)
        )).scalars())
    assert len(restored) == 1
    assert restored[0].source_interface == "GE0/0/9"


@pytest.mark.asyncio
async def test_rollback_removes_devices_added_after_target_version(client, test_session_factory):
    async with test_session_factory() as db:
        user = User(username="device-rollback-admin", hashed_password="!", role=UserRole.ADMIN)
        topology = Topology(name="Device Rollback", topology_type=TopologyType.LAB, status="active")
        db.add_all([user, topology])
        await db.commit()
        user_id, topology_id = user.id, topology.id
    headers = {"Authorization": f"Bearer {create_access_token(user_id, 'device-rollback-admin', 'admin')}"}

    for content in (_workbook_bytes(), _workbook_bytes(include_third=True)):
        response = await client.post(
            f"/api/v1/topologies/{topology_id}/imports?confirm=true",
            files={"file": ("baseline.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=headers,
        )
        assert response.status_code == 200

    rollback = await client.post(
        f"/api/v1/topologies/{topology_id}/versions/1/rollback?confirm=true",
        headers=headers,
    )
    assert rollback.status_code == 200
    async with test_session_factory() as db:
        names = list((await db.execute(
            select(Device.hostname).where(Device.topology_id == topology_id)
        )).scalars())
    assert sorted(names) == ["R-1", "R-2"]


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_import(client, test_session_factory, monkeypatch):
    async with test_session_factory() as db:
        user = User(username="audit-failure-admin", hashed_password="!", role=UserRole.ADMIN)
        topology = Topology(name="Audit Failure", topology_type=TopologyType.LAB, status="active")
        db.add_all([user, topology])
        await db.commit()
        user_id, topology_id = user.id, topology.id

    async def fail_audit(*_args, **_kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(AuditService, "log", fail_audit)
    headers = {"Authorization": f"Bearer {create_access_token(user_id, 'audit-failure-admin', 'admin')}"}
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await client.post(
            f"/api/v1/topologies/{topology_id}/imports?confirm=true",
            files={"file": ("baseline.xlsx", _workbook_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=headers,
        )

    async with test_session_factory() as db:
        assert not list((await db.execute(
            select(TopologyVersion).where(TopologyVersion.topology_id == topology_id)
        )).scalars())
        assert not list((await db.execute(
            select(Device).where(Device.topology_id == topology_id)
        )).scalars())
        assert not list((await db.execute(select(AuditLog).where(
            AuditLog.username == "audit-failure-admin",
            AuditLog.action == "topology_baseline_import",
        ))).scalars())


def test_runtime_diff_and_readonly_commands_do_not_mutate_baseline():
    baseline = [
        {
            "source_device": "R-1",
            "source_interface": "GE0/0/1",
            "target_device": "R-2",
            "target_interface": "GE0/0/1",
        }
    ]
    observed = [
        {
            "source_device": "R-1",
            "source_interface": "GE0/0/1",
            "target_device": "R-3",
            "target_interface": "GE0/0/1",
        }
    ]

    diff = compare_topology_links(baseline, observed)

    assert len(diff.missing) == 1
    assert len(diff.unexpected) == 1
    assert baseline[0]["target_device"] == "R-2"
    commands = get_readonly_commands("switch_l2", "S5700")
    assert "display lldp neighbor brief" in commands
    assert "display interface brief" in commands
    assert all(not command.startswith(("system-view", "undo", "delete")) for command in commands)


def test_lldp_parser_ignores_prompt_and_footer_text():
    output = """
Local Intf    Neighbor Dev    Neighbor Intf    Neighbor TTL
GE3/0/0       R-2             GE3/0/1          120
Info: The max number of neighbors is 256
<R-1>
"""

    assert parse_lldp_neighbor_brief(output) == [{
        "local_interface": "GE3/0/0",
        "neighbor_device": "R-2",
        "remote_interface": "GE3/0/1",
    }]


def test_runtime_diff_normalizes_interface_aliases():
    baseline = [{
        "source_device": "R-1",
        "source_interface": "GigabitEthernet3/0/0",
        "target_device": "R-2",
        "target_interface": "GigabitEthernet3/0/1",
    }]
    observed = [{
        "source_device": "R-1",
        "source_interface": "GE3/0/0",
        "target_device": "R-2",
        "target_interface": "GE3/0/1",
    }]

    diff = compare_topology_links(baseline, observed)

    assert diff.has_differences is False


@pytest.mark.asyncio
async def test_lldp_collection_uses_netmiko_and_filters_unknown_devices(monkeypatch):
    # This is an SSH executor test, independent of the developer's sim default.
    monkeypatch.setattr('engines.device_adapter.get_device_mode', lambda: 'ssh')
    class UnexpectedParamiko:
        def __init__(self):
            raise AssertionError("LLDP collection must use the existing Netmiko executor")

    class FakeExecutor:
        def __init__(self, **kwargs):
            self.host = kwargs["host"]

        async def connect(self):
            return None

        async def send_command(self, command):
            assert command == "display lldp neighbor brief"
            neighbor = "R-2" if self.host.endswith(".1") else "R-1"
            return f"""
Local Intf    Neighbor Dev    Neighbor Intf    Neighbor TTL
GE3/0/0       {neighbor}      GE3/0/0          120
GE3/0/1       110             GE1/0/1          120
Info: The max number of neighbors is 256
"""

        async def disconnect(self):
            return None

    async def fake_credentials(_device):
        return {"username": None, "password": None}

    monkeypatch.setattr("engines.netmiko_exec.NetmikoExecutor", FakeExecutor)
    monkeypatch.setattr("paramiko.SSHClient", UnexpectedParamiko)
    monkeypatch.setattr(DeviceService, "get_device_credentials", fake_credentials)
    devices = [
        SimpleNamespace(
            id=index, hostname=f"R-{index}",
            mgmt_ip=f"192.0.2.{index}",
            ssh_port=22,
            device_type=DeviceType.ROUTER,
            model="NE40E",
        )
        for index in (1, 2)
    ]

    result = await TopologyService._collect_lldp_observations(devices)

    assert result["ssh_success"] == 2
    assert result["ssh_failed"] == 0
    assert len(result["errors"]) == 2
    assert all("1 条 LLDP 邻居无法归属当前拓扑库存" in error for error in result["errors"])
    assert all("GE3/0/1 → 110/GE1/0/1" in error for error in result["errors"])
    assert len(result["observed_links"]) == 1
    assert result["observed_links"][0]["target_device"] == "R-2"


@pytest.mark.asyncio
async def test_lldp_runtime_check_records_diff_without_overwriting_baseline(
    test_session_factory, monkeypatch
):
    async with test_session_factory() as db:
        topology = Topology(
            name="Runtime Check Topology",
            topology_type=TopologyType.LAB,
            status="active",
        )
        db.add(topology)
        await db.flush()
        first = Device(
            hostname="runtime-r1",
            mgmt_ip="198.51.100.1",
            device_type=DeviceType.ROUTER,
            vendor=DeviceVendor.HUAWEI,
            status=DeviceStatus.ONLINE,
            topology_id=topology.id,
        )
        second = Device(
            hostname="runtime-r2",
            mgmt_ip="198.51.100.2",
            device_type=DeviceType.ROUTER,
            vendor=DeviceVendor.HUAWEI,
            status=DeviceStatus.ONLINE,
            topology_id=topology.id,
        )
        db.add_all([first, second])
        await db.flush()
        baseline = TopologyLink(
            topology_id=topology.id,
            source_device_id=first.id,
            source_interface="GE0/0/1",
            target_device_id=second.id,
            target_interface="GE0/0/1",
            discovery_source="excel",
            source_type="baseline",
        )
        db.add(baseline)
        await db.commit()
        topology_id = topology.id
        baseline_id = baseline.id

        async def fake_collect(devices):
            return {
                "observed_links": [],
                "ssh_success": 2,
                "ssh_failed": 0,
                "errors": [],
            }

        monkeypatch.setattr(TopologyService, "_collect_lldp_observations", with_coverage(fake_collect))
        result = await TopologyService.discover_via_lldp(db, topology_id)

        stored_link = await db.get(TopologyLink, baseline_id)
        checks = list((await db.execute(
            select(TopologyRuntimeCheck).where(TopologyRuntimeCheck.topology_id == topology_id)
        )).scalars())

    assert stored_link is not None
    assert stored_link.discovery_source == "excel"
    assert result["imported"] == 0
    assert len(result["diff"]["missing"]) == 1
    assert len(checks) == 1
    assert checks[0].status == "different"


@pytest.mark.asyncio
async def test_lldp_runtime_check_compares_management_links_in_same_scope(
    test_session_factory, monkeypatch
):
    async with test_session_factory() as db:
        topology = Topology(name="Management Link", topology_type=TopologyType.LAB, status="active")
        db.add(topology)
        await db.flush()
        first = Device(
            hostname="MGMT-1", mgmt_ip="198.51.100.11", device_type=DeviceType.ROUTER,
            vendor=DeviceVendor.HUAWEI, status=DeviceStatus.ONLINE, topology_id=topology.id,
        )
        second = Device(
            hostname="MGMT-2", mgmt_ip="198.51.100.12", device_type=DeviceType.ROUTER,
            vendor=DeviceVendor.HUAWEI, status=DeviceStatus.ONLINE, topology_id=topology.id,
        )
        db.add_all([first, second])
        await db.flush()
        db.add(TopologyLink(
            topology_id=topology.id,
            source_device_id=first.id,
            source_interface="GE0/0/0",
            target_device_id=second.id,
            target_interface="GE0/0/0",
            link_type="management",
            discovery_source="excel",
            source_type="baseline",
        ))
        await db.commit()

        async def fake_collect(_devices):
            return {
                "observed_links": [{
                    "source_device": "MGMT-1", "source_interface": "GE0/0/0",
                    "target_device": "MGMT-2", "target_interface": "GE0/0/0",
                    "source_ip": None, "target_ip": None, "link_type": "management",
                }],
                "ssh_success": 2,
                "ssh_failed": 0,
                "errors": [],
            }

        monkeypatch.setattr(TopologyService, "_collect_lldp_observations", with_coverage(fake_collect))
        result = await TopologyService.discover_via_lldp(db, topology.id)

    assert result["status"] == "matched"
    assert result["diff"] == {"missing": [], "unexpected": []}


@pytest.mark.asyncio
async def test_confirm_runtime_baseline_replaces_all_old_baseline_links_and_versions_snapshot(
    test_session_factory,
):
    async with test_session_factory() as db:
        # 需要一个真实用户：打开 SQLite 外键后 topology_version.created_by=1 会违反外键
        from modules.auth.models import User, UserRole

        admin = User(username="baseline-admin", hashed_password="x", role=UserRole.ADMIN)
        db.add(admin)
        await db.flush()
        topology = Topology(name="Confirmed Runtime", topology_type=TopologyType.LAB, status="active")
        db.add(topology)
        await db.flush()
        first = Device(
            hostname="runtime-r1", mgmt_ip="198.51.100.21", device_type=DeviceType.ROUTER,
            vendor=DeviceVendor.HUAWEI, status=DeviceStatus.ONLINE, topology_id=topology.id,
        )
        second = Device(
            hostname="runtime-r2", mgmt_ip="198.51.100.22", device_type=DeviceType.ROUTER,
            vendor=DeviceVendor.HUAWEI, status=DeviceStatus.ONLINE, topology_id=topology.id,
        )
        db.add_all([first, second])
        await db.flush()
        db.add_all([
            TopologyLink(
                topology_id=topology.id, source_device_id=first.id, source_interface="GE0/0/0",
                target_device_id=second.id, target_interface="GE0/0/0", link_type="management",
                discovery_source="excel", source_type="baseline",
            ),
            TopologyLink(
                topology_id=topology.id, source_device_id=first.id, source_interface="GE0/0/1",
                target_device_id=second.id, target_interface="GE0/0/1", link_type="physical",
                discovery_source="excel", source_type="baseline",
            ),
        ])
        check = TopologyRuntimeCheck(
            topology_id=topology.id,
            status="different",
            baseline_fingerprint=await TopologyBaselineService.fingerprint(db, topology.id),
            ssh_success=2,
            ssh_failed=0,
            observed_links_json=json.dumps([{
                "source_device": "runtime-r1", "source_interface": "GE0/0/2",
                "target_device": "runtime-r2", "target_interface": "GE0/0/2",
                "source_ip": None, "target_ip": None, "link_type": "physical",
            }]),
            diff_json=json.dumps({"missing": [], "unexpected": [], "_coverage": complete_coverage([first, second])}),
            errors_json="[]",
        )
        db.add(check)
        await db.commit()

        result = await TopologyBaselineService.confirm_runtime_baseline(
            db, topology.id, check.id, user_id=admin.id,
        )
        await db.commit()

        links = list((await db.execute(
            select(TopologyLink).where(TopologyLink.topology_id == topology.id)
        )).scalars())
        versions = list((await db.execute(
            select(TopologyVersion)
            .where(TopologyVersion.topology_id == topology.id)
            .order_by(TopologyVersion.version)
        )).scalars())
        confirmed_check = await db.get(TopologyRuntimeCheck, check.id)

    assert result["link_count"] == 1
    assert [(link.source_interface, link.link_type, link.discovery_source) for link in links] == [
        ("GE0/0/2", "physical", "lldp"),
    ]
    assert [(version.version, version.source_type) for version in versions] == [
        (1, "pre_runtime_confirmation"), (2, "lldp")
    ]
    assert confirmed_check.version_id is None
    assert confirmed_check.confirmed_version_id == versions[-1].id


@pytest.mark.asyncio
async def test_confirm_runtime_baseline_rejects_partial_runtime_check(test_session_factory):
    async with test_session_factory() as db:
        topology = Topology(name="Partial Runtime", topology_type=TopologyType.LAB, status="active")
        db.add(topology)
        await db.flush()
        check = TopologyRuntimeCheck(
            topology_id=topology.id,
            status="partial",
            ssh_success=1,
            ssh_failed=1,
            observed_links_json="[]",
            diff_json=json.dumps({"missing": [], "unexpected": []}),
            errors_json="[]",
        )
        db.add(check)
        await db.commit()

        with pytest.raises(ValueError, match="SSH"):
            await TopologyBaselineService.confirm_runtime_baseline(db, topology.id, check.id, user_id=1)


@pytest.mark.asyncio
async def test_import_discover_confirm_can_repeat_and_old_check_is_stale(client, test_session_factory, monkeypatch):
    async def observed(_devices):
        return {
            "observed_links": [{"source_device": "R-1", "source_interface": "GE0/0/1",
                                "target_device": "R-2", "target_interface": "GE0/0/1",
                                "source_ip": None, "target_ip": None}],
            "ssh_success": 2, "ssh_failed": 0, "errors": [],
        }

    monkeypatch.setattr(TopologyService, "_collect_lldp_observations", with_coverage(observed))
    async with test_session_factory() as db:
        admin = User(username="version-flow-admin", hashed_password="x", role=UserRole.ADMIN)
        topology = Topology(name="Version flow", topology_type=TopologyType.LAB, status="active")
        db.add_all([admin, topology])
        await db.commit()
        await TopologyBaselineService.import_workbook(db, topology.id, _workbook_bytes(), "baseline.xlsx", admin.id)
        await db.commit()
        for expected_version in (2, 3):
            check = await TopologyService.discover_via_lldp(db, topology.id)
            result = await TopologyBaselineService.confirm_runtime_baseline(db, topology.id, check["check_id"], admin.id)
            await db.commit()
            assert result["version"] == expected_version
            latest = await TopologyService.get_latest_runtime_check(db, topology.id)
            assert latest["is_stale"] is True
            assert latest["confirmed_version_id"] == latest["current_version_id"]
            assert latest["compared_version_id"] != latest["confirmed_version_id"]
            with pytest.raises(ValueError, match="已固化"):
                await TopologyBaselineService.confirm_runtime_baseline(db, topology.id, check["check_id"], admin.id)


@pytest.mark.asyncio
async def test_new_baseline_rejects_older_runtime_evidence(client, test_session_factory, monkeypatch):
    async def observed(_devices):
        return {"observed_links": [{"source_device": "R-1", "source_interface": "GE0/0/1",
                                    "target_device": "R-2", "target_interface": "GE0/0/1"}],
                "ssh_success": 2, "ssh_failed": 0, "errors": []}

    monkeypatch.setattr(TopologyService, "_collect_lldp_observations", with_coverage(observed))
    async with test_session_factory() as db:
        admin = User(username="stale-check-admin", hashed_password="x", role=UserRole.ADMIN)
        topology = Topology(name="Stale check", topology_type=TopologyType.LAB, status="active")
        db.add_all([admin, topology])
        await db.commit()
        await TopologyBaselineService.import_workbook(db, topology.id, _workbook_bytes(), "first.xlsx", admin.id)
        await db.commit()
        check = await TopologyService.discover_via_lldp(db, topology.id)
        await TopologyBaselineService.import_workbook(db, topology.id, _workbook_bytes(changed=True), "second.xlsx", admin.id)
        await db.commit()
        latest = await TopologyService.get_latest_runtime_check(db, topology.id)
        assert latest["is_stale"] is True
        with pytest.raises(ValueError, match="基线已变更"):
            await TopologyBaselineService.confirm_runtime_baseline(db, topology.id, check["check_id"], admin.id)


@pytest.mark.asyncio
async def test_empty_topology_check_has_readable_error(client, test_session_factory):
    from core.exceptions import AppException
    async with test_session_factory() as db:
        topology = Topology(name="Empty check")
        db.add(topology)
        await db.commit()
        with pytest.raises(AppException) as error:
            await TopologyService.discover_via_lldp(db, topology.id)
        assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_lldp_adapter_setup_failure_does_not_abort_other_devices(monkeypatch):
    class Adapter:
        async def run_command(self, command):
            return "Local Intf Neighbor Dev Neighbor Intf Exptime(s)\nTotal Neighbors : 0"
        async def close(self):
            pass
    async def adapter(device, **kwargs):
        if device.hostname == "A":
            raise ValueError("isolated missing credentials")
        return Adapter()
    monkeypatch.setattr("engines.device_adapter.get_device_adapter", adapter)
    devices = [SimpleNamespace(id=i, hostname=name, device_type=DeviceType.ROUTER, model=None) for i, name in enumerate(("A", "B"), 1)]
    result = await TopologyService._collect_lldp_observations(devices)
    assert result["ssh_success"] == 1
    assert result["ssh_failed"] == 1
    assert len(result["errors"]) == 1


@pytest.mark.asyncio
async def test_unversioned_device_edit_invalidates_runtime_evidence(client, test_session_factory, monkeypatch):
    async def observed(_devices):
        return {"observed_links": [{"source_device": "R-1", "source_interface": "GE0/0/1",
                                    "target_device": "R-2", "target_interface": "GE0/0/1"}],
                "ssh_success": 2, "ssh_failed": 0, "errors": []}
    monkeypatch.setattr(TopologyService, "_collect_lldp_observations", with_coverage(observed))
    async with test_session_factory() as db:
        admin = User(username="fingerprint-admin", hashed_password="x", role=UserRole.ADMIN)
        topology = Topology(name="Same version new facts", topology_type=TopologyType.LAB)
        db.add_all([admin, topology])
        await db.commit()
        await TopologyBaselineService.import_workbook(db, topology.id, _workbook_bytes(), "baseline.xlsx", admin.id)
        await db.commit()
        check = await TopologyService.discover_via_lldp(db, topology.id)
        device = (await db.execute(select(Device).where(Device.topology_id == topology.id).limit(1))).scalar_one()
        await DeviceService.update_device(db, device.id, {"mgmt_ip": "192.0.2.99"})
        latest = await TopologyService.get_latest_runtime_check(db, topology.id)
        assert latest["is_stale"] is True
        assert latest["compared_version_id"] == latest["current_version_id"]
        with pytest.raises(ValueError, match="基线已变更"):
            await TopologyBaselineService.confirm_runtime_baseline(db, topology.id, check["check_id"], admin.id)


@pytest.mark.asyncio
async def test_runtime_change_during_collection_is_immediately_stale(client, test_session_factory, monkeypatch):
    async with test_session_factory() as db:
        admin = User(username="during-check-admin", hashed_password="x", role=UserRole.ADMIN)
        topology = Topology(name="Changed during collection", topology_type=TopologyType.LAB)
        db.add_all([admin, topology])
        await db.commit()
        await TopologyBaselineService.import_workbook(db, topology.id, _workbook_bytes(), "baseline.xlsx", admin.id)
        await db.commit()

        async def observed(devices):
            # Fake the await boundary; no real network or second database involved.
            await DeviceService.update_device(db, devices[0].id, {"mgmt_ip": "192.0.2.88"})
            return {"observed_links": [], "ssh_success": 2, "ssh_failed": 0, "errors": []}

        monkeypatch.setattr(TopologyService, "_collect_lldp_observations", with_coverage(observed))
        result = await TopologyService.discover_via_lldp(db, topology.id)
        assert result["is_stale"] is True
        with pytest.raises(ValueError, match="基线已变更"):
            await TopologyBaselineService.confirm_runtime_baseline(db, topology.id, result["check_id"], admin.id)


@pytest.mark.asyncio
async def test_legacy_check_without_snapshot_requires_recheck(client, test_session_factory):
    async with test_session_factory() as db:
        topology = Topology(name="Unknown historical baseline", topology_type=TopologyType.LAB)
        db.add(topology)
        await db.flush()
        check = TopologyRuntimeCheck(topology_id=topology.id, status="matched", ssh_success=2, ssh_failed=0,
                                     observed_links_json="[]", diff_json="{}", errors_json="[]")
        db.add(check)
        await db.commit()
        assert (await TopologyService.get_latest_runtime_check(db, topology.id))["is_stale"] is True
        with pytest.raises(ValueError, match="缺少基线快照"):
            await TopologyBaselineService.confirm_runtime_baseline(db, topology.id, check.id, 1)


@pytest.mark.asyncio
async def test_restore_retains_training_only_dependency_and_actual_inventory_count(client, test_session_factory):
    from modules.training.models import TrainingLab, TrainingSession, FaultInjection, FaultType

    async with test_session_factory() as db:
        admin = User(username="retained-training-admin", hashed_password="x", role=UserRole.ADMIN)
        topology = Topology(name="Historical device", topology_type=TopologyType.LAB)
        db.add_all([admin, topology])
        await db.commit()
        for content in (_workbook_bytes(), _workbook_bytes(include_third=True)):
            await TopologyBaselineService.import_workbook(db, topology.id, content, "baseline.xlsx", admin.id)
            await db.commit()
        target = (await db.execute(select(TopologyVersion).where(
            TopologyVersion.topology_id == topology.id, TopologyVersion.version == 1))).scalar_one()
        third = (await db.execute(select(Device).where(
            Device.topology_id == topology.id, Device.hostname == "R-3"))).scalar_one()
        lab = TrainingLab(title="Historical lab", topology_id=topology.id, instructor_id=admin.id)
        db.add(lab)
        await db.flush()
        session = TrainingSession(lab_id=lab.id, trainee_id=admin.id)
        db.add(session)
        await db.flush()
        fault = FaultInjection(session_id=session.id, device_id=third.id, fault_type=FaultType.INTERFACE_SHUTDOWN)
        db.add(fault)
        await db.commit()

        await TopologyBaselineService._restore_snapshot(db, topology.id, json.loads(target.snapshot_json))
        await db.commit()
        assert await db.get(FaultInjection, fault.id) is not None
        assert (await db.get(Device, third.id)).status == DeviceStatus.OFFLINE
        assert (await db.get(Topology, topology.id)).device_count == 3
        # A retained extra device is not an exact version restore. Preserve the
        # existing rejection contract rather than calling a partial rollback success.
        with pytest.raises(ValueError, match="回滚结果与目标版本不一致"):
            await TopologyBaselineService.rollback(db, topology.id, 1, admin.id)
        await db.rollback()
