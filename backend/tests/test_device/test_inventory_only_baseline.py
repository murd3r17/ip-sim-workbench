"""Inventory authorization can precede LLDP without inventing topology links."""
import json
import ast
from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from core.security import create_access_token
from modules.auth.models import AuditLog, User, UserRole
from modules.device.baseline_service import TopologyBaselineService
from modules.device.models import Device, DeviceType, Topology, TopologyLink, TopologyType, TopologyVersion
from modules.device.topology_import import TopologyExcelParser


def workbook(*, links=False, duplicate=False):
    book = Workbook()
    sheet = book.active
    sheet.title = "设备信息"
    sheet.append(["设备名称", "IP地址", "SSH端口"])
    for index in (1, 2, 3):
        sheet.append([f"R{index}", "192.0.2.100", 20121 if duplicate else 20120 + index])
    if links:
        book.create_sheet("设备互联图")["A1"] = "R1 GE0/0/1 ↔ R2 GE0/0/1"
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def test_empty_links_require_explicit_inventory_mode():
    assert not TopologyExcelParser.parse(workbook()).is_valid
    result = TopologyExcelParser.parse(workbook(), inventory_only=True)
    assert result.is_valid and result.inventory_only and result.links == []


@pytest.mark.parametrize("options,code", [({"links": True}, "inventory_links_not_allowed"),
                                          ({"duplicate": True}, "duplicate_management_ip")])
def test_inventory_mode_never_waives_real_validation(options, code):
    result = TopologyExcelParser.parse(workbook(**options), inventory_only=True)
    assert not result.is_valid and any(issue.code == code for issue in result.issues)


@pytest.mark.asyncio
async def test_inventory_api_creates_four_tuple_version_and_explicit_audit(client, test_session_factory):
    async with test_session_factory() as db:
        user = User(username="inventory-admin", hashed_password="!", role=UserRole.ADMIN)
        topology = Topology(name="Inventory without LLDP", topology_type=TopologyType.LAB, status="active")
        db.add_all([user, topology])
        await db.commit()
        user_id, topology_id = user.id, topology.id
    headers = {"Authorization": "Bearer " + create_access_token(user_id, "inventory-admin", "admin")}
    files = {"file": ("inventory.xlsx", workbook(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    prefix = f"/api/v1/topologies/{topology_id}/imports"
    preview = await client.post(prefix + "/validate?inventory_only=true", files=files, headers=headers)
    assert preview.status_code == 200 and preview.json()["is_valid"] and preview.json()["inventory_only"]
    assert (await client.post(prefix + "?inventory_only=true", files=files, headers=headers)).status_code == 409
    imported = await client.post(prefix + "?confirm=true&inventory_only=true", files=files, headers=headers)
    assert imported.status_code == 200 and imported.json()["source_type"] == "inventory_only"
    async with test_session_factory() as db:
        version = (await db.execute(select(TopologyVersion).where(TopologyVersion.topology_id == topology_id))).scalar_one()
        snapshot = json.loads(version.snapshot_json)
        assert version.source_type == "inventory_only" and snapshot["links"] == []
        assert {(item["hostname"], item["mgmt_ip"], item["ssh_port"]) for item in snapshot["devices"]} == {
            (f"R{i}", "192.0.2.100", 20120 + i) for i in (1, 2, 3)}
        assert all(item["id"] for item in snapshot["devices"])
        audit = (await db.execute(select(AuditLog).where(AuditLog.action == "topology_baseline_import"))).scalars().all()
        assert any(ast.literal_eval(row.detail).get("inventory_only") is True for row in audit)


@pytest.mark.asyncio
@pytest.mark.parametrize("historic", [False, True])
async def test_inventory_mode_refuses_existing_or_historical_links(client, test_session_factory, historic):
    async with test_session_factory() as db:
        topology = Topology(name="Existing links", topology_type=TopologyType.LAB, status="active")
        db.add(topology)
        await db.flush()
        devices = [Device(hostname=f"R{i}", mgmt_ip="192.0.2.100", ssh_port=20120 + i,
                          device_type=DeviceType.ROUTER, topology_id=topology.id) for i in (1, 2, 3)]
        db.add_all(devices)
        await db.flush()
        if historic:
            db.add(TopologyVersion(topology_id=topology.id, version=1, batch_id="fixture",
                                   source_name="baseline.xlsx", source_type="excel",
                                   snapshot_json=json.dumps({"devices": [], "links": [{"link_type": "physical"}]}),
                                   summary_json="{}"))
        else:
            db.add(TopologyLink(topology_id=topology.id, source_device_id=devices[0].id,
                                target_device_id=devices[1].id, source_interface="GE0/0/1",
                                target_interface="GE0/0/1", link_type="physical", source_type="discovered"))
        await db.commit()
        with pytest.raises(ValueError, match="链路"):
            await TopologyBaselineService.import_workbook(db, topology.id, workbook(), "inventory.xlsx", 1,
                                                         inventory_only=True)
