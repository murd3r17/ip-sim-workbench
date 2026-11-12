"""Unknown LLDP identities must stay visible without inventing inventory links."""
import json

import pytest
from sqlalchemy import select

from modules.auth.models import User, UserRole
from modules.device.baseline_service import TopologyBaselineService
from modules.device.models import Device, DeviceType, Topology, TopologyLink, TopologyRuntimeCheck, TopologyType, TopologyVersion
from modules.device.service import TopologyService


# The shared client fixture also clears the in-memory database after each case.
pytestmark = pytest.mark.usefixtures("client")


HEADER = "Local Intf                     Neighbor Dev         Neighbor Intf        Exptime (sec)\n" + "-" * 86
# Port/name-only reproduction of the observed VRP tables; no connection details.
UNKNOWN_TABLES = {
    "R1": HEADER + "\nGigabitEthernet0/0/0 HUAWEI GE1/0/10 96\nGigabitEthernet3/0/3 HUAWEI GE1/0/1 99",
    "R2": HEADER + "\nGigabitEthernet0/0/0 HUAWEI GE1/0/9 119\nGigabitEthernet3/0/4 HUAWEI GE1/0/2 120",
    "R3": HEADER + "\nGigabitEthernet0/0/0 HUAWEI GE1/0/2 112\nGigabitEthernet3/0/4 HUAWEI GE1/0/3 106",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["unknown", "mixed", "known", "empty"])
async def test_lldp_inventory_resolution_is_persisted_and_never_false_matched(
    scenario, test_session_factory, monkeypatch,
):
    tables = {"R1": HEADER, "R2": HEADER, "R3": HEADER}
    if scenario == "unknown":
        tables = UNKNOWN_TABLES
    elif scenario in {"mixed", "known"}:
        tables["R1"] += "\nGigabitEthernet3/0/0 R2 GE3/0/0 120"
        tables["R2"] += "\nGigabitEthernet3/0/0 R1 GE3/0/0 120"
        if scenario == "mixed":
            tables["R1"] += "\nGigabitEthernet3/0/3 HUAWEI GE1/0/1 99"
    tables = {host: text + '\nTotal Neighbors : 0' if text == HEADER else text for host, text in tables.items()}
    closed = []

    class Adapter:
        def __init__(self, hostname):
            self.hostname = hostname

        async def run_command(self, command):
            assert command == "display lldp neighbor brief"
            return tables[self.hostname]

        async def close(self):
            closed.append(self.hostname)

    async def fake_adapter(device, **_kwargs):
        return Adapter(device.hostname)

    monkeypatch.setattr("engines.device_adapter.get_device_adapter", fake_adapter)
    async with test_session_factory() as db:
        topology = Topology(name=f"LLDP {scenario}", topology_type=TopologyType.LAB)
        db.add(topology)
        await db.flush()
        devices = [Device(hostname=f"R{i}", mgmt_ip=f"192.0.2.{i}", device_type=DeviceType.ROUTER,
                          topology_id=topology.id) for i in (1, 2, 3)]
        db.add_all(devices)
        await db.flush()
        if scenario in {"mixed", "known"}:
            db.add(TopologyLink(topology_id=topology.id, source_device_id=devices[0].id,
                                target_device_id=devices[1].id, source_interface="GE3/0/0",
                                target_interface="GE3/0/0", source_type="baseline"))
        await db.commit()
        result = await TopologyService.discover_via_lldp(db, topology.id)
        latest = await TopologyService.get_latest_runtime_check(db, topology.id)
        assert sorted(closed) == ["R1", "R2", "R3"]
        assert result["ssh_success"] == 3 and result["ssh_failed"] == 0
        assert result["imported"] == 0
        assert result["discovered"] == (1 if scenario in {"mixed", "known"} else 0)
        assert latest["links"] == result["links"]
        assert latest["errors"] == result["errors"]
        assert result["status"] == latest["status"] == ("partial" if scenario in {"unknown", "mixed"} else "no_baseline" if scenario == 'empty' else "matched")
        if scenario in {"unknown", "mixed"}:
            assert len(result["errors"]) == (3 if scenario == "unknown" else 1)
            assert all("HUAWEI" in error and "库存" in error for error in result["errors"])
            assert all(f"{2 if scenario == 'unknown' else 1} 条" in error for error in result["errors"])
            with pytest.raises(ValueError, match="不完整"):
                await TopologyBaselineService.confirm_runtime_baseline(db, topology.id, result["check_id"], user_id=1)
            assert not list((await db.execute(select(TopologyVersion).where(TopologyVersion.topology_id == topology.id))).scalars())
        else:
            assert result["errors"] == []
        links = list((await db.execute(select(TopologyLink).where(TopologyLink.topology_id == topology.id))).scalars())
        assert len(links) == (1 if scenario in {"mixed", "known"} else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,errors", [("partial", []), ("matched", ["库存外邻居未归属"])])
async def test_confirm_rejects_incomplete_evidence_even_with_all_ssh_success(status, errors, test_session_factory):
    async with test_session_factory() as db:
        topology = Topology(name="Incomplete evidence", topology_type=TopologyType.LAB)
        db.add(topology)
        await db.flush()
        admin = User(username=f"incomplete-{status}", hashed_password="x", role=UserRole.ADMIN)
        db.add(admin)
        db.add_all([Device(hostname=f"R{i}", mgmt_ip=f"192.0.2.{i}", device_type=DeviceType.ROUTER,
                           topology_id=topology.id) for i in (1, 2)])
        await db.flush()
        check = TopologyRuntimeCheck(
            topology_id=topology.id, status=status, ssh_success=2, ssh_failed=0,
            baseline_fingerprint=await TopologyBaselineService.fingerprint(db, topology.id),
            observed_links_json=json.dumps([{"source_device": "R1", "source_interface": "GE3/0/0",
                                             "target_device": "R2", "target_interface": "GE3/0/0"}]),
            diff_json="{}", errors_json=json.dumps(errors),
        )
        db.add(check)
        await db.commit()
        with pytest.raises(ValueError, match="不完整"):
            await TopologyBaselineService.confirm_runtime_baseline(db, topology.id, check.id, user_id=admin.id)
        assert not list((await db.execute(select(TopologyVersion).where(TopologyVersion.topology_id == topology.id))).scalars())
