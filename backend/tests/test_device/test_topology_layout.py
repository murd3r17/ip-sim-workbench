import pytest
from sqlalchemy import select

from core.security import create_access_token
from modules.auth.models import User, UserRole
from modules.device.models import Device, DeviceStatus, DeviceType, DeviceVendor, Topology, TopologyType


async def _layout_token(session_factory) -> str:
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.username == "layout-admin"))).scalar_one_or_none()
        if user is None:
            user = User(
                username="layout-admin",
                hashed_password="not-used-by-this-test",
                display_name="Layout Admin",
                role=UserRole.ADMIN,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        return create_access_token(user.id, user.username, user.role.value)


async def _topology_with_device(session_factory, name: str) -> tuple[Topology, Device]:
    async with session_factory() as db:
        topology = Topology(name=name, topology_type=TopologyType.MAIN, status="active")
        db.add(topology)
        await db.flush()
        device = Device(
            hostname=f"{name}-device",
            mgmt_ip=f"10.0.0.{topology.id}",
            topology_id=topology.id,
            device_type=DeviceType.ROUTER,
            vendor=DeviceVendor.HUAWEI,
            status=DeviceStatus.UNKNOWN,
        )
        db.add(device)
        await db.commit()
        await db.refresh(topology)
        await db.refresh(device)
        return topology, device


@pytest.mark.asyncio
async def test_topology_layout_rejects_device_from_another_topology(client, test_session_factory):
    token = await _layout_token(test_session_factory)
    topology, _ = await _topology_with_device(test_session_factory, "layout-primary")
    _, foreign_device = await _topology_with_device(test_session_factory, "layout-foreign")

    response = await client.put(
        f"/api/v1/topologies/{topology.id}/layout/draft",
        json={"positions": {str(foreign_device.id): {"x": 0.25, "y": 0.5}}},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_topology_layout_keeps_draft_separate_until_publish(client, test_session_factory):
    token = await _layout_token(test_session_factory)
    topology, device = await _topology_with_device(test_session_factory, "layout-publish")
    positions = {str(device.id): {"x": 0.25, "y": 0.5}}

    saved = await client.put(
        f"/api/v1/topologies/{topology.id}/layout/draft",
        json={"positions": positions},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert saved.status_code == 200
    assert saved.json()["draft_positions"] == positions
    assert saved.json()["published_positions"] == {}

    published = await client.post(
        f"/api/v1/topologies/{topology.id}/layout/publish",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert published.status_code == 200
    assert published.json()["published_positions"] == positions
