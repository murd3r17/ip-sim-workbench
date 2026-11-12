# -*- coding: utf-8 -*-
"""V7-B 可信基础：环境 preflight、只读证据、OSPF 规则、能力目录、实训工作区。"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from modules.auth.models import User, UserRole
from modules.deploy.models import ChangeLevel, DeployBatch, DeployStatus, DeployTask, DeviceWriteLock
from modules.device.models import Device, DeviceStatus, DeviceType, Topology, TopologyType
from modules.trust.models import ReadOnlyObservation
from tests.test_training.test_v7a_state_and_reports import _admin_token, _lab, _session, auth_header


async def _device(factory, *, status=DeviceStatus.ONLINE, hostname="B-R1"):
    async with factory() as db:
        topo = Topology(name=f"b-topo-{hostname}", topology_type=TopologyType.LAB, status="active")
        db.add(topo)
        await db.flush()
        device = Device(hostname=hostname, mgmt_ip="192.0.2.10", device_type=DeviceType.ROUTER,
                        status=status, topology_id=topo.id)
        db.add(device)
        await db.commit()
        return device.id


async def _environment(client, token, device_id, *, protections=True, status="ready"):
    created = await client.post("/api/v1/trust/environments", json={
        "name": f"B 环境 {device_id}", "version": "v1", "site": "lab",
        "devices": [{"device_id": device_id, "role": "R1", "mgmt_ip": "192.0.2.10",
                     "interfaces": [{"name": "GigabitEthernet3/0/3", "address": "10.0.123.1/24"}]}],
        "protections": [{"kind": "mgmt_port", "target": "GigabitEthernet3/0/3"}] if protections else [],
    }, headers=auth_header(token))
    assert created.status_code == 200, created.text
    env_id = created.json()["id"]
    updated = await client.put(f"/api/v1/trust/environments/{env_id}", json={"status": status}, headers=auth_header(token))
    assert updated.status_code == 200
    return env_id


@pytest.mark.asyncio
async def test_environment_preflight_reports_ready_and_mismatch(client, test_session_factory, monkeypatch):
    token = await _admin_token(test_session_factory)
    device_id = await _device(test_session_factory)
    env_id = await _environment(client, token, device_id)

    class Adapter:
        async def run_command(self, command):
            return "GigabitEthernet3/0/3  up  up  10.0.123.1/24"

        async def close(self):
            return None

    monkeypatch.setattr("engines.device_adapter.get_device_adapter", AsyncMock(return_value=Adapter()))
    monkeypatch.setattr("engines.device_adapter.get_device_mode", lambda: "sim")
    ready = await client.post(f"/api/v1/trust/environments/{env_id}/preflight", json={}, headers=auth_header(token))
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["version"] == "v1"

    missing = await client.post("/api/v1/trust/environments", json={
        "name": "缺映射", "version": "v1", "devices": [{"device_id": 99999, "role": "R9", "interfaces": []}],
        "protections": [],
    }, headers=auth_header(token))
    env2 = missing.json()["id"]
    result = await client.post(f"/api/v1/trust/environments/{env2}/preflight", json={}, headers=auth_header(token))
    assert result.json()["status"] == "mismatch"
    assert any(check["status"] == "mismatch" for check in result.json()["checks"])


@pytest.mark.asyncio
async def test_environment_preflight_offline_is_unreachable(client, test_session_factory, monkeypatch):
    token = await _admin_token(test_session_factory)
    device_id = await _device(test_session_factory, status=DeviceStatus.OFFLINE, hostname="B-OFF")
    env_id = await _environment(client, token, device_id)
    async def unreachable(_device):
        raise OSError("deterministic unreachable transport")
    monkeypatch.setattr("engines.device_adapter.get_device_adapter", unreachable)
    monkeypatch.setattr("engines.device_adapter.get_device_mode", lambda: "ssh")
    result = await client.post(f"/api/v1/trust/environments/{env_id}/preflight", json={}, headers=auth_header(token))
    assert result.json()["status"] == "unreachable"


@pytest.mark.asyncio
async def test_environment_write_requires_admin(client, test_session_factory):
    token = await _admin_token(test_session_factory)
    device_id = await _device(test_session_factory, hostname="B-ADMIN")
    env_id = await _environment(client, token, device_id)
    async with test_session_factory() as db:
        user = User(username="b-normal", hashed_password="x", role=UserRole.USER)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    from core.security import create_access_token
    normal = create_access_token(user.id, user.username, "user")
    denied = await client.post("/api/v1/trust/environments", json={"name": "x"}, headers=auth_header(normal))
    assert denied.status_code == 403
    assert (await client.get(f"/api/v1/trust/environments/{env_id}", headers=auth_header(normal))).status_code == 200


@pytest.mark.asyncio
async def test_readonly_observation_action_whitelist_and_parsing(client, test_session_factory, monkeypatch):
    token = await _admin_token(test_session_factory)
    device_id = await _device(test_session_factory, hostname="B-OBS")
    env_id = await _environment(client, token, device_id)

    class Adapter:
        async def run_command(self, command):
            assert command in {"display ip interface brief", "display ospf peer"}
            if "interface" in command:
                return "GigabitEthernet3/0/3  up  up  10.0.123.1/24\nLoopBack0  up  up  10.0.0.1/24"
            return "10.0.123.2  1  Full/ -  00:00:12"

        async def close(self):
            return None

    monkeypatch.setattr("engines.device_adapter.get_device_adapter", AsyncMock(return_value=Adapter()))
    response = await client.post("/api/v1/trust/observations", json={
        "device_id": device_id, "action_id": "interface_brief", "environment_id": env_id,
    }, headers=auth_header(token))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["source"] == "server_observed" and data["mode"] in {"sim", "real"}
    assert data["completeness"] == "complete"
    assert data["facts"]["interfaces"][0]["address"] == "10.0.123.1/24"

    bad = await client.post("/api/v1/trust/observations", json={
        "device_id": device_id, "action_id": "display version\nquit", "environment_id": env_id,
    }, headers=auth_header(token))
    assert bad.status_code == 400
    unmanaged = await client.post("/api/v1/trust/observations", json={
        "device_id": device_id, "action_id": "ospf_peer", "environment_id": 99999,
    }, headers=auth_header(token))
    assert unmanaged.status_code == 400


@pytest.mark.asyncio
async def test_ospf_rule_requires_exact_expected_objects_and_fresh_evidence(client, test_session_factory, monkeypatch):
    token = await _admin_token(test_session_factory)
    monkeypatch.setattr("engines.device_adapter.get_device_mode", lambda: "ssh")
    device_id = await _device(test_session_factory, hostname="B-RULE")
    env_id = await _environment(client, token, device_id)

    class Adapter:
        def __init__(self, output):
            self.output = output

        async def run_command(self, command):
            return self.output

        async def close(self):
            return None

    monkeypatch.setattr("engines.device_adapter.get_device_adapter", AsyncMock(return_value=Adapter("10.0.123.2  1  Full/ -  00:00:12")))
    observed = await client.post("/api/v1/trust/observations", json={
        "device_id": device_id, "action_id": "ospf_peer", "environment_id": env_id,
    }, headers=auth_header(token))
    obs_id = observed.json()["id"]

    satisfied = await client.post("/api/v1/trust/rules/ospf/evaluate", json={
        "observation_ids": [obs_id], "expected_neighbors": ["10.0.123.2"], "expected_routes": [],
    }, headers=auth_header(token))
    assert satisfied.status_code == 200
    assert satisfied.json()["status"] == "satisfied"

    wrong = await client.post("/api/v1/trust/rules/ospf/evaluate", json={
        "observation_ids": [obs_id], "expected_neighbors": ["10.0.123.9"], "expected_routes": [],
    }, headers=auth_header(token))
    assert wrong.json()["status"] == "not_matched"
    assert wrong.json()["missing"] == ["10.0.123.9"]

    async with test_session_factory() as db:
        row = await db.get(ReadOnlyObservation, obs_id)
        row.collected_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db.commit()
    stale = await client.post("/api/v1/trust/rules/ospf/evaluate", json={
        "observation_ids": [obs_id], "expected_neighbors": ["10.0.123.2"], "max_age_seconds": 60,
    }, headers=auth_header(token))
    assert stale.json()["status"] == "stale"


@pytest.mark.asyncio
async def test_evidence_is_owner_scoped_for_non_admin(client, test_session_factory, monkeypatch):
    token = await _admin_token(test_session_factory)
    device_id = await _device(test_session_factory, hostname="B-OWN")
    env_id = await _environment(client, token, device_id)

    class Adapter:
        async def run_command(self, command):
            return "10.0.123.2  1  Full/ -  00:00:12"

        async def close(self):
            return None

    monkeypatch.setattr("engines.device_adapter.get_device_adapter", AsyncMock(return_value=Adapter()))
    observed = await client.post("/api/v1/trust/observations", json={
        "device_id": device_id, "action_id": "ospf_peer", "environment_id": env_id,
    }, headers=auth_header(token))
    obs_id = observed.json()["id"]

    async with test_session_factory() as db:
        user = User(username="b-other", hashed_password="x", role=UserRole.USER)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    from core.security import create_access_token
    other = create_access_token(user.id, user.username, "user")
    assert (await client.get(f"/api/v1/trust/observations/{obs_id}", headers=auth_header(other))).status_code == 404
    listing = await client.get("/api/v1/trust/observations", headers=auth_header(other))
    assert listing.json() == []
    rule = await client.post("/api/v1/trust/rules/ospf/evaluate", json={
        "observation_ids": [obs_id], "expected_neighbors": ["10.0.123.2"],
    }, headers=auth_header(other))
    assert rule.status_code == 403


@pytest.mark.asyncio
async def test_training_workspace_persists_and_conflicts(client, test_session_factory):
    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token)
    sid = await _session(client, token, lab_id)
    empty = await client.get(f"/api/v1/training/sessions/{sid}/workspace", headers=auth_header(token))
    assert empty.status_code == 200
    assert empty.json()["revision"] == 0 and empty.json()["read_only"] is False
    saved = await client.put(f"/api/v1/training/sessions/{sid}/workspace", json={
        "notes": "第一步：核对接口", "steps": [{"id": 1, "status": "done"}], "revision": 0,
    }, headers=auth_header(token))
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    conflict = await client.put(f"/api/v1/training/sessions/{sid}/workspace", json={
        "notes": "另一个页面", "steps": [], "revision": 0,
    }, headers=auth_header(token))
    assert conflict.status_code == 409
    reloaded = await client.get(f"/api/v1/training/sessions/{sid}/workspace", headers=auth_header(token))
    assert reloaded.json()["notes"] == "第一步：核对接口"


@pytest.mark.asyncio
async def test_device_lock_status_exposes_recovery_and_preflight_busy(client, test_session_factory):
    token = await _admin_token(test_session_factory)
    device_id = await _device(test_session_factory, hostname="B-LOCK")
    env_id = await _environment(client, token, device_id)
    async with test_session_factory() as db:
        from modules.auth.models import User
        admin = (await db.execute(select(User).where(User.role == UserRole.ADMIN))).scalars().first()
        batch = DeployBatch(name="B lock batch", source="manual", operator_id=admin.id)
        db.add(batch)
        await db.flush()
        task = DeployTask(batch_id=batch.id, device_id=device_id, config_content="sysname X",
                          status=DeployStatus.SUCCESS, engine="netmiko", change_level=ChangeLevel.DAILY,
                          operator_id=admin.id)
        db.add(task)
        await db.flush()
        db.add(DeviceWriteLock(device_id=device_id, task_id=task.id, lock_type="deploy"))
        await db.commit()
    busy = await client.post(f"/api/v1/trust/environments/{env_id}/preflight", json={}, headers=auth_header(token))
    assert busy.json()["status"] == "busy"
    locks = await client.get("/api/v1/trust/locks", headers=auth_header(token))
    assert locks.status_code == 200
    row = next(item for item in locks.json() if item["device_id"] == device_id)
    assert row["recovery_required"] is True
    assert row["writable"] is False


@pytest.mark.asyncio
async def test_capability_catalog_hides_admin_actions_from_user(client, test_session_factory):
    token = await _admin_token(test_session_factory)
    admin_pages = await client.get("/api/v1/trust/pages", headers=auth_header(token))
    assert admin_pages.status_code == 200
    assert any(item["page_id"] == "system_config" for item in admin_pages.json())
    async with test_session_factory() as db:
        user = User(username="b-cat", hashed_password="x", role=UserRole.USER)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    from core.security import create_access_token
    normal = create_access_token(user.id, user.username, "user")
    user_pages = await client.get("/api/v1/trust/pages", headers=auth_header(normal))
    assert not any(item["page_id"] == "system_config" for item in user_pages.json())
    actions = await client.get("/api/v1/trust/actions", headers=auth_header(normal))
    assert all(item["risk"] != "system_write" for item in actions.json())


@pytest.mark.asyncio
async def test_terminal_release_removes_own_lock(client, test_session_factory):
    """BF4-01：正常释放必须删除本实例锁，而不是被 NameError 吞掉。"""
    import importlib
    from datetime import datetime, timedelta, timezone
    from modules.deploy.models import DeviceWriteLock
    token = await _admin_token(test_session_factory)
    did = await _device(test_session_factory, hostname="B-RELEASE")
    async with test_session_factory() as db:
        db.add(DeviceWriteLock(device_id=did, task_id=None, lock_type="terminal", owner_type="terminal",
                               owner_id=1, owner_token="release-token", state="active",
                               last_seen_at=datetime.now(timezone.utc),
                               expire_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        await db.commit()
    router = importlib.import_module("modules.webssh.router")
    await router._release_terminal_lock(test_session_factory, did, 1, "release-token")
    locks = (await client.get("/api/v1/trust/locks", headers=auth_header(token))).json()
    assert not locks

@pytest.mark.asyncio
async def test_workspace_invalid_revision_is_normalized_and_writable(client, test_session_factory):
    """BF9：迁移遗留的负/非法 revision 不能把会话锁死（GET 报 0、PUT 必须能写）。"""
    from modules.training.models import TrainingSession
    token = await _admin_token(test_session_factory)
    lab = await _lab(client, token)
    sid = await _session(client, token, lab)
    async with test_session_factory() as db:
        row = await db.get(TrainingSession, sid)
        row.workspace = {"revision": -3, "notes": "bad revision"}
        row.workspace_revision = -5
        await db.commit()
    got = await client.get(f"/api/v1/training/sessions/{sid}/workspace", headers=auth_header(token))
    assert got.status_code == 200
    assert got.json()["revision"] == 0
    put = await client.put(f"/api/v1/training/sessions/{sid}/workspace", headers=auth_header(token),
                           json={"notes": "healed", "steps": [], "revision": 0})
    assert put.status_code == 200, put.text
    assert put.json()["revision"] == 1
    reopened = await client.get(f"/api/v1/training/sessions/{sid}/workspace", headers=auth_header(token))
    assert reopened.json()["revision"] == 1 and reopened.json()["notes"] == "healed"
