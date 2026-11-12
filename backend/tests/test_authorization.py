"""越权与自证类回归测试（2026-09-09 审计 P0-07/08/10/12/15 等）。

这些用例把"普通用户能干什么"固化为契约：任何一条失效都说明越权面回来了。
"""
import io

import pytest

from tests.test_api_full import _setup_admin_user, _setup_test_user, auth_header


async def _seed_topology_and_device(client, admin_token) -> tuple[int, int]:
    """建一个拓扑 + 一台设备，返回 (topology_id, device_id)。"""
    topo = await client.post("/api/v1/topologies", json={"name": "authz-test-topo"}, headers=auth_header(admin_token))
    assert topo.status_code in (200, 201), topo.text
    topology_id = topo.json()["id"]
    dev = await client.post(
        "/api/v1/devices",
        json={"hostname": "authz-dev", "mgmt_ip": "10.255.255.1", "ssh_port": 22,
              "topology_id": topology_id, "device_type": "router"},
        headers=auth_header(admin_token),
    )
    assert dev.status_code in (200, 201), dev.text
    return topology_id, dev.json()["id"]


class TestKnowledgeAuthorization:
    @pytest.mark.asyncio
    async def test_upload_requires_admin(self, client, test_session_factory):
        token = await _setup_test_user(test_session_factory)
        resp = await client.post(
            "/api/v1/ai/knowledge/upload",
            files={"file": ("authz.md", io.BytesIO(b"# hello"), "text/markdown")},
            headers=auth_header(token),
        )
        assert resp.status_code == 403, resp.text

    @pytest.mark.asyncio
    async def test_delete_requires_admin(self, client, test_session_factory):
        token = await _setup_test_user(test_session_factory)
        resp = await client.delete(
            "/api/v1/ai/knowledge/documents/authz.md", headers=auth_header(token)
        )
        assert resp.status_code == 403, resp.text


class TestTopologyLinkAuthorization:
    @pytest.mark.asyncio
    async def test_create_link_requires_admin(self, client, test_session_factory):
        admin = await _setup_admin_user(test_session_factory)
        user = await _setup_test_user(test_session_factory)
        topology_id, device_id = await _seed_topology_and_device(client, admin)
        resp = await client.post(
            f"/api/v1/topologies/{topology_id}/links",
            json={"source_device_id": device_id, "source_interface": "GE0/0/1",
                  "target_device_id": device_id, "target_interface": "GE0/0/2"},
            headers=auth_header(user),
        )
        assert resp.status_code == 403, resp.text


class TestDeployOwnershipFiltering:
    @pytest.mark.asyncio
    async def test_task_list_only_shows_own_tasks(self, client, test_session_factory):
        admin = await _setup_admin_user(test_session_factory)
        user = await _setup_test_user(test_session_factory)
        _, device_id = await _seed_topology_and_device(client, admin)
        online = await client.put(
            f"/api/v1/devices/{device_id}/status?status=online", headers=auth_header(admin)
        )
        assert online.status_code == 200, online.text
        # 管理员建一个批次（含 config_content 原文）
        created = await client.post(
            "/api/v1/deploy/batches",
            json={"name": "authz-batch",
                  "items": [{"device_id": device_id, "config_content": "sysname authz-owner"}]},
            headers=auth_header(admin),
        )
        assert created.status_code in (200, 201), created.text
        admin_batches = await client.get("/api/v1/deploy/batches", headers=auth_header(admin))
        assert admin_batches.status_code == 200
        assert admin_batches.json(), "管理员应能看到自己创建的批次"
        # 普通用户看不到他人批次与任务
        user_batches = await client.get("/api/v1/deploy/batches", headers=auth_header(user))
        assert user_batches.status_code == 200
        assert user_batches.json() == [], f"普通用户不应看到他人批次: {user_batches.text}"
        tasks = await client.get("/api/v1/deploy/tasks", headers=auth_header(user))
        assert tasks.status_code == 200
        assert tasks.json() == [], f"普通用户不应看到他人任务: {tasks.text}"


class TestTrainingFaultSelfCertification:
    @pytest.mark.asyncio
    async def test_trainee_cannot_mark_fault_resolved(self, client, test_session_factory):
        admin = await _setup_admin_user(test_session_factory)
        user = await _setup_test_user(test_session_factory)
        topology_id, device_id = await _seed_topology_and_device(client, admin)

        lab = await client.post(
            "/api/v1/training/labs",
            json={"title": "authz-lab", "topology_id": topology_id},
            headers=auth_header(admin),
        )
        assert lab.status_code in (200, 201), lab.text
        lab_id = lab.json()["id"]

        session = await client.post(
            "/api/v1/training/sessions", json={"lab_id": lab_id}, headers=auth_header(user)
        )
        assert session.status_code in (200, 201), session.text
        session_id = session.json()["id"]

        injected = await client.post(
            f"/api/v1/training/sessions/{session_id}/inject",
            json={"fault_scenario": [{"device_id": device_id, "fault_type": "interface_shutdown"}]},
            headers=auth_header(admin),
        )
        assert injected.status_code in (200, 201), injected.text
        faults = await client.get(f"/api/v1/training/sessions/{session_id}/faults", headers=auth_header(admin))
        assert faults.status_code == 200 and faults.json(), faults.text
        fault_id = faults.json()[0]["id"]

        # 学员自评"已解决"必须被拒（否则 fault_score 可自证）
        denied = await client.post(
            f"/api/v1/training/faults/{fault_id}/resolve?resolved_correctly=true",
            headers=auth_header(user),
        )
        assert denied.status_code == 403, denied.text

        # 学员标记"未解决"允许
        give_up = await client.post(
            f"/api/v1/training/faults/{fault_id}/resolve?resolved_correctly=false",
            headers=auth_header(user),
        )
        assert give_up.status_code == 200, give_up.text
