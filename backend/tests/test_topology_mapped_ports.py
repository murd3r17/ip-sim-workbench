from io import BytesIO
import json

from openpyxl import Workbook
import pytest
from sqlalchemy import select

from modules.auth.models import User, UserRole
from modules.device.baseline_service import TopologyBaselineService
from modules.device.models import Device, DeviceType, DeviceVendor, Topology, TopologyType, TopologyVersion
from modules.device.topology_import import TopologyExcelParser


def workbook(ports):
    book = Workbook()
    sheet = book.active
    sheet.title = "设备信息"
    sheet.append(["设备名称", "IP地址", "SSH端口"])
    for index, port in enumerate(ports, 1):
        sheet.append([f"R{index}", "192.0.2.1", port])
    links = book.create_sheet("设备互联图")
    for index in range(1, len(ports)):
        links.append([f"R{index} GE0/0/1 ↔ R{index + 1} GE0/0/2"])
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def test_three_mapped_ports_are_distinct_but_same_endpoint_is_rejected():
    parsed = TopologyExcelParser.parse(workbook([20123, 20124, 20125]))
    assert parsed.is_valid
    assert [device.ssh_port for device in parsed.devices] == [20123, 20124, 20125]
    assert not TopologyExcelParser.parse(workbook([20123, 20123])).is_valid


@pytest.mark.parametrize("port", [0, 65536, -1, 22.5, "bad", True])
def test_invalid_port_cannot_enter_inventory(port):
    parsed = TopologyExcelParser.parse(workbook([port]))
    assert not parsed.is_valid
    assert any(issue.code == "invalid_ssh_port" for issue in parsed.issues)


@pytest.mark.asyncio
async def test_mapped_import_preserves_ids_and_creates_exact_endpoint_baseline(test_session_factory):
    async with test_session_factory() as db:
        user = User(username="mapped-admin", hashed_password="placeholder", role=UserRole.ADMIN)
        topology = Topology(name="Mapped", topology_type=TopologyType.MAIN)
        db.add_all([user, topology])
        await db.flush()
        devices = [Device(hostname=f"R{i+1}", mgmt_ip="192.0.2.1", ssh_port=port,
                          device_type=DeviceType.ROUTER, vendor=DeviceVendor.HUAWEI, topology_id=topology.id)
                   for i, port in enumerate([20123, 20124, 20125])]
        db.add_all(devices)
        await db.commit()
        original_ids = [device.id for device in devices]
        preview = await TopologyBaselineService.preview(db, topology.id, workbook([20123, 20124, 20125]))
        assert preview.is_valid
        result = await TopologyBaselineService.import_workbook(db, topology.id, workbook([20123, 20124, 20125]), "inventory-only.xlsx", user.id)
        await db.commit()
        version = (await db.execute(select(TopologyVersion).where(TopologyVersion.topology_id == topology.id,
                                                                  TopologyVersion.version == result["version"]))).scalar_one()
        saved = json.loads(version.snapshot_json)["devices"]
        assert [item["id"] for item in saved] == original_ids
        assert [item["ssh_port"] for item in saved] == [20123, 20124, 20125]
        # Old sheets omit the port. A one-device update must retain that device's endpoint.
        await TopologyBaselineService.import_workbook(db, topology.id, workbook([None, 20124]), "legacy-sheet.xlsx", user.id)
        await db.flush()
        assert devices[0].ssh_port == 20123


@pytest.mark.asyncio
async def test_existing_endpoint_in_another_topology_is_rejected(test_session_factory):
    async with test_session_factory() as db:
        first, second = Topology(name="one"), Topology(name="two")
        db.add_all([first, second])
        await db.flush()
        db.add(Device(hostname="R1", mgmt_ip="192.0.2.1", ssh_port=20123, topology_id=first.id,
                      device_type=DeviceType.ROUTER, vendor=DeviceVendor.HUAWEI))
        await db.commit()
        preview = await TopologyBaselineService.preview(db, second.id, workbook([20123]))
        assert not preview.is_valid
        assert any(issue.code == "database_ip_conflict" for issue in preview.issues)
