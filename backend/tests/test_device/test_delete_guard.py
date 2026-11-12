import pytest

from core.security import create_access_token
from modules.auth.models import User, UserRole
from modules.device.models import Device, DeviceType, Topology, TopologyLink


@pytest.mark.asyncio
async def test_delete_referenced_device_returns_conflict_and_preserves_history(client, test_session_factory):
    async with test_session_factory() as db:
        admin = User(username="delete-guard", hashed_password="x", role=UserRole.ADMIN)
        topology = Topology(name="Delete guard", device_count=2)
        db.add_all([admin, topology])
        await db.flush()
        devices = [Device(hostname=name, mgmt_ip="192.0.2.1", device_type=DeviceType.ROUTER,
                          topology_id=topology.id) for name in ("A", "B")]
        db.add_all(devices)
        await db.flush()
        link = TopologyLink(topology_id=topology.id, source_device_id=devices[0].id,
                            target_device_id=devices[1].id, source_interface="GE0/0/1", target_interface="GE0/0/1")
        db.add(link)
        await db.commit()
        token = create_access_token(admin.id, admin.username, "admin")
        device_id, link_id = devices[0].id, link.id
    response = await client.delete(f"/api/v1/devices/{device_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 409
    assert response.json()["detail"]["dependencies"]["topology_link"] == 1
    async with test_session_factory() as db:
        assert await db.get(Device, device_id) is not None
        assert await db.get(TopologyLink, link_id) is not None


@pytest.mark.asyncio
async def test_delete_unreferenced_device_updates_topology_count(client, test_session_factory):
    async with test_session_factory() as db:
        admin = User(username="delete-empty", hashed_password="x", role=UserRole.ADMIN)
        topology = Topology(name="Delete empty", device_count=1)
        db.add_all([admin, topology])
        await db.flush()
        device = Device(hostname="Unused", mgmt_ip="192.0.2.2", device_type=DeviceType.ROUTER, topology_id=topology.id)
        db.add(device)
        await db.commit()
        token = create_access_token(admin.id, admin.username, "admin")
        device_id, topology_id = device.id, topology.id
    response = await client.delete(f"/api/v1/devices/{device_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    async with test_session_factory() as db:
        assert await db.get(Device, device_id) is None
        assert (await db.get(Topology, topology_id)).device_count == 0
