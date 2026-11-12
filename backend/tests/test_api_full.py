"""全量API集成测试 - 覆盖所有模块的路由端点"""
import pytest
import pytest_asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from core.security import create_access_token
from core.database import Base


ADMIN_PASSWORD_HASH = "$2b$12$L8lZdovA8eLRSN0WkKZ7lOaKp3RxaeQ/1TdHuGo3C4N3GgwSHfkeu"
TEST_USER_PASSWORD_HASH = "$2b$12$3D7xXD/FzWluDz3Kzu/FluCx/PJKeN/rjtRH6.venzYUM5PHqoYam"


@pytest.fixture
def mock_ssh_device_mode(monkeypatch):
    """Executor mocks must exercise SSH regardless of the developer's default mode."""
    from core.config import get_settings

    monkeypatch.setenv("DEVICE_MODE", "ssh")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _setup_admin_user(session_factory):
    """在数据库中创建admin用户"""
    from modules.auth.models import User, UserRole
    from sqlalchemy import select

    async with session_factory() as db:
        result = await db.execute(select(User).where(User.username == "admin"))
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                username="admin",
                hashed_password=ADMIN_PASSWORD_HASH,
                display_name="系统管理员",
                role=UserRole.ADMIN,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        return create_access_token(user.id, user.username, user.role.value, user.token_version)


async def _setup_test_user(session_factory):
    """在数据库中创建测试用户"""
    from modules.auth.models import User, UserRole
    from sqlalchemy import select

    async with session_factory() as db:
        result = await db.execute(select(User).where(User.username == "testuser"))
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                username="testuser",
                hashed_password=TEST_USER_PASSWORD_HASH,
                display_name="测试用户",
                role=UserRole.USER,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        return create_access_token(user.id, user.username, user.role.value, user.token_version)


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════════
# 1. 认证模块 (Auth)
# ═══════════════════════════════════════════════════════════════════

class TestAuth:
    @pytest.mark.asyncio
    async def test_login_success(self, client, test_session_factory):
        """登录成功"""
        await _setup_admin_user(test_session_factory)
        resp = await client.post("/api/v1/auth/login", json={
            "username": "admin", "password": "admin123"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["username"] == "admin"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client, test_session_factory):
        """登录失败 - 错误密码"""
        await _setup_admin_user(test_session_factory)
        resp = await client.post("/api/v1/auth/login", json={
            "username": "admin", "password": "wrongpassword"
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client):
        """登录失败 - 用户不存在"""
        resp = await client.post("/api/v1/auth/login", json={
            "username": "nonexistent", "password": "any"
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_me(self, client, test_session_factory):
        """获取当前用户信息"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/auth/me", headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "admin"
        assert data["role"] == "admin"

    @pytest.mark.asyncio
    async def test_get_me_no_token(self, client):
        """未认证访问：必须 401（此前用 in [401,403] 容忍 HTTPBearer 的 403 语义）"""
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_create_user(self, client, test_session_factory):
        """管理员创建用户"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.post("/api/v1/auth/users", json={
            "username": "newuser", "password": "Pass1234", "display_name": "新用户"
        }, headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "newuser"
        assert data["role"] == "user"

    @pytest.mark.asyncio
    async def test_create_user_duplicate(self, client, test_session_factory):
        """创建重复用户"""
        token = await _setup_admin_user(test_session_factory)
        await client.post("/api/v1/auth/users", json={
            "username": "dupuser", "password": "Pass1234"
        }, headers=auth_header(token))
        resp = await client.post("/api/v1/auth/users", json={
            "username": "dupuser", "password": "Pass4567"
        }, headers=auth_header(token))
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_user_non_admin(self, client, test_session_factory):
        """非管理员创建用户"""
        token = await _setup_test_user(test_session_factory)
        resp = await client.post("/api/v1/auth/users", json={
            "username": "hacker", "password": "Pass1234"
        }, headers=auth_header(token))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_change_password(self, client, test_session_factory):
        """修改密码"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.put("/api/v1/auth/password", json={
            "old_password": "admin123", "new_password": "Newpass456"
        }, headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["message"] == "密码修改成功"

    @pytest.mark.asyncio
    async def test_change_password_wrong_old(self, client, test_session_factory):
        """修改密码 - 旧密码错误"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.put("/api/v1/auth/password", json={
            "old_password": "wrongold", "new_password": "Newpass456"
        }, headers=auth_header(token))
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════
# 2. 设备管理模块 (Device)
# ═══════════════════════════════════════════════════════════════════

class TestDevice:
    @pytest_asyncio.fixture
    async def topology_id(self, client, test_session_factory):
        """创建测试拓扑"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.post("/api/v1/topologies", json={
            "name": "测试拓扑", "description": "集成测试用拓扑"
        }, headers=auth_header(token))
        assert resp.status_code == 200
        return resp.json()["id"], token

    @pytest.mark.asyncio
    async def test_create_device(self, client, test_session_factory):
        """创建设备"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "设备测试拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        resp = await client.post("/api/v1/devices", json={
            "hostname": "Router01",
            "mgmt_ip": "192.168.100.1",
            "device_type": "router",
            "vendor": "huawei",
            "topology_id": topo_id,
        }, headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["hostname"] == "Router01"
        assert data["mgmt_ip"] == "192.168.100.1"

    @pytest.mark.asyncio
    async def test_list_devices(self, client, test_session_factory):
        """获取设备列表"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "列表拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        await client.post("/api/v1/devices", json={
            "hostname": "Switch01", "mgmt_ip": "192.168.100.2",
            "device_type": "switch_l2", "topology_id": topo_id,
        }, headers=auth_header(token))
        resp = await client.get("/api/v1/devices", headers=auth_header(token))
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    @pytest.mark.asyncio
    async def test_get_device(self, client, test_session_factory):
        """获取单个设备"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "详情拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        create_resp = await client.post("/api/v1/devices", json={
            "hostname": "FW01", "mgmt_ip": "192.168.100.3",
            "device_type": "firewall", "topology_id": topo_id,
        }, headers=auth_header(token))
        device_id = create_resp.json()["id"]
        resp = await client.get(f"/api/v1/devices/{device_id}", headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["hostname"] == "FW01"

    @pytest.mark.asyncio
    async def test_get_device_not_found(self, client, test_session_factory):
        """获取不存在的设备"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/devices/99999", headers=auth_header(token))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_device(self, client, test_session_factory):
        """更新设备"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "更新拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        create_resp = await client.post("/api/v1/devices", json={
            "hostname": "UpdateMe", "mgmt_ip": "192.168.100.4",
            "device_type": "router", "topology_id": topo_id,
        }, headers=auth_header(token))
        device_id = create_resp.json()["id"]
        resp = await client.put(f"/api/v1/devices/{device_id}", json={
            "hostname": "UpdatedRouter",
        }, headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["hostname"] == "UpdatedRouter"

    @pytest.mark.asyncio
    async def test_delete_device(self, client, test_session_factory):
        """删除设备"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "删除拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        create_resp = await client.post("/api/v1/devices", json={
            "hostname": "DeleteMe", "mgmt_ip": "192.168.100.5",
            "device_type": "server", "topology_id": topo_id,
        }, headers=auth_header(token))
        device_id = create_resp.json()["id"]
        resp = await client.delete(f"/api/v1/devices/{device_id}", headers=auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_device_status(self, client, test_session_factory):
        """更新设备状态"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "状态拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        create_resp = await client.post("/api/v1/devices", json={
            "hostname": "StatusDevice", "mgmt_ip": "192.168.100.6",
            "device_type": "router", "topology_id": topo_id,
        }, headers=auth_header(token))
        device_id = create_resp.json()["id"]
        resp = await client.put(f"/api/v1/devices/{device_id}/status",
                                params={"status": "online"},
                                headers=auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_filter_devices_by_topology(self, client, test_session_factory):
        """按拓扑过滤设备"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "过滤拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        await client.post("/api/v1/devices", json={
            "hostname": "FilteredDevice", "mgmt_ip": "192.168.100.7",
            "device_type": "router", "topology_id": topo_id,
        }, headers=auth_header(token))
        resp = await client.get("/api/v1/devices",
                                params={"topology_id": topo_id},
                                headers=auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_filter_devices_by_status(self, client, test_session_factory):
        """按状态过滤设备"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "状态过滤拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        await client.post("/api/v1/devices", json={
            "hostname": "StatusFilter", "mgmt_ip": "192.168.100.8",
            "device_type": "router", "topology_id": topo_id,
        }, headers=auth_header(token))
        resp = await client.get("/api/v1/devices",
                                params={"status": "unknown"},
                                headers=auth_header(token))
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════
# 3. 拓扑管理模块 (Topology)
# ═══════════════════════════════════════════════════════════════════

class TestTopology:
    @pytest.mark.asyncio
    async def test_create_topology(self, client, test_session_factory):
        """创建拓扑"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.post("/api/v1/topologies", json={
            "name": "核心拓扑", "description": "核心网络拓扑"
        }, headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "核心拓扑"

    @pytest.mark.asyncio
    async def test_list_topologies(self, client, test_session_factory):
        """获取拓扑列表"""
        token = await _setup_admin_user(test_session_factory)
        await client.post("/api/v1/topologies", json={
            "name": "列表测试拓扑"
        }, headers=auth_header(token))
        resp = await client.get("/api/v1/topologies", headers=auth_header(token))
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    @pytest.mark.asyncio
    async def test_get_topology(self, client, test_session_factory):
        """获取单个拓扑"""
        token = await _setup_admin_user(test_session_factory)
        create_resp = await client.post("/api/v1/topologies", json={
            "name": "详情拓扑"
        }, headers=auth_header(token))
        topo_id = create_resp.json()["id"]
        resp = await client.get(f"/api/v1/topologies/{topo_id}", headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["name"] == "详情拓扑"

    @pytest.mark.asyncio
    async def test_get_topology_not_found(self, client, test_session_factory):
        """获取不存在的拓扑"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/topologies/99999", headers=auth_header(token))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_topology_link(self, client, test_session_factory):
        """创建拓扑链路"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "链路测试拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]

        dev1_resp = await client.post("/api/v1/devices", json={
            "hostname": "LinkDev1", "mgmt_ip": "192.168.200.1",
            "device_type": "router", "topology_id": topo_id,
        }, headers=auth_header(token))
        dev2_resp = await client.post("/api/v1/devices", json={
            "hostname": "LinkDev2", "mgmt_ip": "192.168.200.2",
            "device_type": "switch_l2", "topology_id": topo_id,
        }, headers=auth_header(token))

        resp = await client.post(f"/api/v1/topologies/{topo_id}/links", json={
            "source_device_id": dev1_resp.json()["id"],
            "source_interface": "GigabitEthernet0/0/1",
            "target_device_id": dev2_resp.json()["id"],
            "target_interface": "GigabitEthernet0/0/24",
        }, headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_interface"] == "GigabitEthernet0/0/1"

    @pytest.mark.asyncio
    async def test_get_topology_links(self, client, test_session_factory):
        """获取拓扑链路"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "链路列表拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        resp = await client.get(f"/api/v1/topologies/{topo_id}/links",
                                headers=auth_header(token))
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════
# 4. 配置下发模块 (Deploy)
# ═══════════════════════════════════════════════════════════════════

class TestDeploy:
    async def _create_pending_task(self, client, test_session_factory, config_content, change_level="daily"):
        from uuid import uuid4
        token = await _setup_admin_user(test_session_factory)
        suffix = uuid4().hex[:8]
        topology = await client.post("/api/v1/topologies", json={"name": f"确认拓扑{suffix}"}, headers=auth_header(token))
        device = await client.post("/api/v1/devices", json={
            "hostname": f"ConfirmRouter{suffix}", "mgmt_ip": f"10.9.{int(suffix[:2], 16)}.{int(suffix[2:4], 16)}",
            "device_type": "router", "topology_id": topology.json()["id"],
        }, headers=auth_header(token))
        device_id = device.json()["id"]
        await client.put(f"/api/v1/devices/{device_id}/status", params={"status": "online"}, headers=auth_header(token))
        created = await client.post("/api/v1/deploy", json={"device_ids": [device_id], "config_content": config_content, "change_level": change_level}, headers=auth_header(token))
        return token, created.json()["details"][0]["task_id"]

    @pytest.mark.asyncio
    async def test_engine_ansible_rejected(self, client, test_session_factory):
        token = await _setup_admin_user(test_session_factory)
        topo = await client.post("/api/v1/topologies", json={"name": "ansible禁拓扑"}, headers=auth_header(token))
        device = await client.post(
            "/api/v1/devices",
            json={"hostname": "NoAnsible", "mgmt_ip": "10.9.9.9", "device_type": "router", "topology_id": topo.json()["id"]},
            headers=auth_header(token),
        )
        resp = await client.post(
            "/api/v1/deploy",
            json={"device_ids": [device.json()["id"]], "config_content": "sysname x", "engine": "ansible"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_named_batch_creates_one_item_per_device(self, client, test_session_factory):
        """具名任务将不同设备脚本保存为独立执行项。"""
        from uuid import uuid4

        token = await _setup_admin_user(test_session_factory)
        suffix = uuid4().hex[:8]
        topology = await client.post(
            "/api/v1/topologies", json={"name": f"批任务拓扑{suffix}"}, headers=auth_header(token)
        )
        device_ids = []
        for index in (1, 2):
            device = await client.post(
                "/api/v1/devices",
                json={
                    "hostname": f"BatchRouter{index}{suffix}",
                    "mgmt_ip": f"10.8.{int(suffix[:2], 16)}.{index}",
                    "device_type": "router",
                    "topology_id": topology.json()["id"],
                },
                headers=auth_header(token),
            )
            device_id = device.json()["id"]
            device_ids.append(device_id)
            await client.put(
                f"/api/v1/devices/{device_id}/status", params={"status": "online"}, headers=auth_header(token)
            )

        response = await client.post(
            "/api/v1/deploy/batches",
            headers=auth_header(token),
            json={
                "name": "ISIS lab",
                "source": "manual",
                "items": [
                    {"device_id": device_ids[0], "config_content": "isis 1"},
                    {"device_id": device_ids[1], "config_content": "isis 2"},
                ],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "ISIS lab"
        assert {item["device_id"] for item in body["items"]} == set(device_ids)
        assert {item["config_content"] for item in body["items"]} == {"isis 1", "isis 2"}

    @pytest.mark.asyncio
    async def test_batch_detail_aggregates_item_status_and_links(self, client, test_session_factory):
        """任务管理可按父任务查看子项状态和追溯链接。"""
        from sqlalchemy import select
        token = await _setup_admin_user(test_session_factory)
        from modules.auth.models import User
        from modules.deploy.models import DeployBatch, DeployStatus, DeployTask
        from modules.device.models import Device, DeviceType
        topology = await client.post(
            "/api/v1/topologies", json={"name": "任务详情拓扑"}, headers=auth_header(token)
        )

        async with test_session_factory() as db:
            user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
            device = Device(
                hostname="DetailRouter", mgmt_ip="10.7.1.1", device_type=DeviceType.ROUTER,
                topology_id=topology.json()["id"],
            )
            db.add(device)
            await db.flush()
            batch = DeployBatch(name="Detail batch", source="manual", operator_id=user.id)
            db.add(batch)
            await db.flush()
            task = DeployTask(
                batch_id=batch.id, device_id=device.id, config_content="sysname Detail",
                status=DeployStatus.SUCCESS, operator_id=user.id,
            )
            db.add(task)
            await db.commit()
            batch_id = batch.id

        response = await client.get(f"/api/v1/deploy/batches/{batch_id}", headers=auth_header(token))
        assert response.status_code == 200
        body = response.json()
        assert body["summary"] == {"total": 1, "pending": 0, "running": 0, "success": 1, "failed": 0}
        assert body["items"][0]["stage"] == "success"
        assert body["items"][0]["links"]["change_log"].endswith(f"task_id={body['items'][0]['id']}")

    @pytest.mark.asyncio
    async def test_high_risk_change_level_requires_explicit_second_confirmation(self, client, test_session_factory):
        token, task_id = await self._create_pending_task(
            client, test_session_factory, "sysname ConfirmRouter", change_level="high_risk"
        )
        confirmed = await client.post(
            f"/api/v1/deploy/tasks/{task_id}/confirm", json={"risk_confirm": False}, headers=auth_header(token)
        )
        assert confirmed.status_code == 422
        assert confirmed.json()["detail"] == "高风险任务需要二次确认"
        confirmed = await client.post(
            f"/api/v1/deploy/tasks/{task_id}/confirm", json={"risk_confirm": True}, headers=auth_header(token)
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_second_task_for_locked_device_returns_409(self, client, test_session_factory):
        from modules.deploy.models import DeployTask
        token, first_task = await self._create_pending_task(client, test_session_factory, "sysname LockRouter")
        # 低风险配置一次确认即进入 confirmed 并持锁；无需二次 risk_confirm
        first_confirm = await client.post(
            f"/api/v1/deploy/tasks/{first_task}/confirm", json={}, headers=auth_header(token)
        )
        assert first_confirm.status_code == 200
        assert first_confirm.json()["status"] == "confirmed"
        async with test_session_factory() as db:
            device_id = (await db.get(DeployTask, first_task)).device_id
        created = await client.post("/api/v1/deploy", json={"device_ids": [device_id], "config_content": "sysname LockRouter2"}, headers=auth_header(token))
        second_task = created.json()["details"][0]["task_id"]
        conflict = await client.post(
            f"/api/v1/deploy/tasks/{second_task}/confirm", json={}, headers=auth_header(token)
        )
        assert conflict.status_code == 409

    @pytest.mark.asyncio
    async def test_confirmation_audit_excludes_config_content(self, client, test_session_factory):
        from sqlalchemy import select
        from modules.auth.models import AuditLog
        config = "sysname SecretRouter"
        token, task_id = await self._create_pending_task(client, test_session_factory, config)
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={}, headers=auth_header(token))
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={"risk_confirm": True}, headers=auth_header(token))
        async with test_session_factory() as db:
            audit = (await db.execute(select(AuditLog).where(AuditLog.action == "deploy_task_confirmed").order_by(AuditLog.id.desc()))).scalars().first()
        assert audit is not None
        assert str(task_id) in audit.detail
        assert config not in audit.detail

    @pytest.mark.asyncio
    async def test_create_pending_deploy_task(self, client, test_session_factory):
        """创建配置下发任务"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "部署测试拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        dev_resp = await client.post("/api/v1/devices", json={
            "hostname": "DeployRouter", "mgmt_ip": "192.168.100.10",
            "device_type": "router", "topology_id": topo_id,
        }, headers=auth_header(token))
        device_id = dev_resp.json()["id"]
        # 设置设备状态为online
        await client.put(f"/api/v1/devices/{device_id}/status",
                         params={"status": "online"}, headers=auth_header(token))
        resp = await client.post("/api/v1/deploy", json={
            "device_ids": [device_id],
            "config_content": "sysname TestRouter",
            "change_level": "daily",
            "engine": "netmiko",
        }, headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "transaction_id" in data
        assert data["details"][0]["status"] == "awaiting_confirmation"

    @pytest.mark.asyncio
    async def test_list_deploy_tasks(self, client, test_session_factory):
        """获取下发任务列表"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "任务列表拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        dev_resp = await client.post("/api/v1/devices", json={
            "hostname": "ListRouter", "mgmt_ip": "192.168.100.11",
            "device_type": "router", "topology_id": topo_id,
        }, headers=auth_header(token))
        device_id = dev_resp.json()["id"]
        await client.put(f"/api/v1/devices/{device_id}/status",
                         params={"status": "online"}, headers=auth_header(token))
        await client.post("/api/v1/deploy", json={
            "device_ids": [device_id],
            "config_content": "sysname ListTest",
            "change_level": "daily",
            "engine": "netmiko",
        }, headers=auth_header(token))
        resp = await client.get("/api/v1/deploy/tasks", headers=auth_header(token))
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    @pytest.mark.asyncio
    async def test_validate_config(self, client, test_session_factory):
        """VRP配置校验"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.post("/api/v1/deploy/validate", json={
            "config_content": "interface GigabitEthernet0/0/1\nip address 192.168.1.1 255.255.255.0",
            "device_model": "AR2240",
        }, headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "valid" in data
        assert "errors" in data
        assert "details" in data
        assert data["requires_confirmation"] is False
        assert data["deploy_allowed"] is True
        assert data["config_preview"] == "interface GigabitEthernet0/0/1\nip address 192.168.1.1 255.255.255.0"

    @pytest.mark.asyncio
    async def test_validate_ospf_draft_without_device_model(self, client, test_session_factory):
        """未传型号时按 NE40E 校验，OSPF 草稿应通过。"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.post("/api/v1/deploy/validate", json={
            "config_content": (
                "system-view\n"
                "ospf 1 router-id 10.0.1.1\n"
                "area 0.0.0.0\n"
                "network 10.0.123.0 0.0.0.255\n"
                "network 10.0.1.1 0.0.0.0\n"
                "quit\n"
                "quit\n"
            ),
        }, headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["deploy_allowed"] is True
        assert data["errors"] == []

    @pytest.mark.asyncio
    async def test_create_template(self, client, test_session_factory):
        """创建配置模板"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.post("/api/v1/config-templates", json={
            "name": "接口配置模板",
            "description": "配置接口IP地址",
            "content": "interface {{interface_name}}\nip address {{ip_address}} {{subnet_mask}}",
            "variables": {"interface_name": {"required": True}, "ip_address": {"required": True}, "subnet_mask": {"required": True}},
            "category": "interface",
        }, headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "接口配置模板"

    @pytest.mark.asyncio
    async def test_list_templates(self, client, test_session_factory):
        """获取模板列表"""
        token = await _setup_admin_user(test_session_factory)
        await client.post("/api/v1/config-templates", json={
            "name": "列表模板", "content": "sysname {{hostname}}",
        }, headers=auth_header(token))
        resp = await client.get("/api/v1/config-templates", headers=auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_render_template(self, client, test_session_factory):
        """渲染配置模板"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.post("/api/v1/config-templates/render", json={
            "content": "sysname {{hostname}}",
            "variables": {"hostname": "CoreRouter"},
        }, headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "CoreRouter" in data["rendered"]

    @pytest.mark.asyncio
    async def test_template_variable_contract_rejects_mismatch(self, client, test_session_factory):
        token = await _setup_admin_user(test_session_factory)
        resp = await client.post("/api/v1/config-templates", json={
            "name": "变量不一致模板", "content": "sysname {{ hostname }}",
            "variables": {"ip": {"required": True}},
        }, headers=auth_header(token))
        assert resp.status_code == 422
        assert "变量声明与模板变量不一致" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_render_template_rejects_missing_required_variable(self, client, test_session_factory):
        token = await _setup_admin_user(test_session_factory)
        resp = await client.post("/api/v1/config-templates/render", json={
            "content": "sysname {{ hostname }}",
            "declarations": {"hostname": {"required": True}},
            "variables": {},
        }, headers=auth_header(token))
        assert resp.status_code == 422
        assert "缺少必填变量: hostname" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_template_preview_audit_excludes_variable_values(self, client, test_session_factory):
        from sqlalchemy import select
        from modules.auth.models import AuditLog

        token = await _setup_admin_user(test_session_factory)
        secret_value = "Router01"
        resp = await client.post("/api/v1/config-templates/render", json={
            "content": "sysname {{ hostname }}",
            "declarations": {"hostname": {"required": True}},
            "variables": {"hostname": secret_value},
        }, headers=auth_header(token))
        assert resp.status_code == 200

        async with test_session_factory() as db:
            result = await db.execute(
                select(AuditLog).where(AuditLog.action == "template_previewed").order_by(AuditLog.id.desc())
            )
            audit = result.scalars().first()
        assert audit is not None
        assert "hostname" in audit.detail
        assert secret_value not in audit.detail

    @pytest.mark.asyncio
    async def test_validate_template(self, client, test_session_factory):
        """校验模板语法"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.post("/api/v1/config-templates/validate", json={
            "content": "interface {{ intf }}\nip address {{ ip }} {{ mask }}",
        }, headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert len(data["variables"]) == 3

    @pytest.mark.asyncio
    async def test_validate_template_invalid(self, client, test_session_factory):
        """校验无效模板"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.post("/api/v1/config-templates/validate", json={
            "content": "{% if %}{% endif %}",
        }, headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False

    @pytest.mark.asyncio
    async def test_list_config_versions(self, client, test_session_factory):
        """获取配置版本列表"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/config-versions", headers=auth_header(token))
        assert resp.status_code == 200

    # ── 4D: 受控下发与回读 ─────────────────────────────

    @pytest.mark.asyncio
    async def test_execute_rejects_non_confirmed_task(self, client, test_session_factory):
        """非 confirmed 任务返回409"""
        token, task_id = await self._create_pending_task(client, test_session_factory, "sysname R1")
        resp = await client.post(f"/api/v1/deploy/tasks/{task_id}/execute", headers=auth_header(token))
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_legacy_transaction_route_is_blocked_by_controlled_pipeline(self, client, test_session_factory):
        """旧事务入口不能绕过4C-4E的确认、锁和服务端模拟边界。"""
        token = await _setup_admin_user(test_session_factory)
        response = await client.post("/api/v1/deploy/transaction", json={
            "device_ids": [1],
            "config_content": "sysname BypassAttempt",
            "change_level": "daily",
            "engine": "netmiko",
        }, headers=auth_header(token))
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_legacy_version_rollback_route_is_blocked_by_controlled_pipeline(self, client, test_session_factory):
        """旧版本回滚入口不得绕过当前任务锁、白名单和受控回滚。"""
        token = await _setup_admin_user(test_session_factory)
        response = await client.post("/api/v1/config-versions/999/rollback", headers=auth_header(token))
        assert response.status_code == 409

    async def _lock_owned_by_other_task(self, client, token, task_id, test_session_factory) -> None:
        """把设备写锁改成"属于同一设备上的另一个真实任务"。

        注意：必须指向真实存在的任务 —— 打开 SQLite 外键约束后，
        随意写 task_id + 1 会触发 FOREIGN KEY constraint failed。
        """
        from modules.deploy.models import DeployTask, DeviceWriteLock

        async with test_session_factory() as db:
            device_id = (await db.get(DeployTask, task_id)).device_id
        other = await client.post(
            "/api/v1/deploy",
            json={"device_ids": [device_id], "config_content": "sysname OtherOwner"},
            headers=auth_header(token),
        )
        other_task_id = other.json()["details"][0]["task_id"]
        async with test_session_factory() as db:
            lock = await db.get(DeviceWriteLock, device_id)
            lock.task_id = other_task_id
            await db.commit()

    @pytest.mark.asyncio
    async def test_execute_rejects_lock_owned_by_another_task(self, client, test_session_factory):
        """同设备的锁不属于当前任务时返回409。"""
        token, task_id = await self._create_pending_task(client, test_session_factory, "sysname LockOwner")
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={}, headers=auth_header(token))
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={"risk_confirm": True}, headers=auth_header(token))
        await self._lock_owned_by_other_task(client, token, task_id, test_session_factory)

        response = await client.post(f"/api/v1/deploy/tasks/{task_id}/execute", headers=auth_header(token))
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_verify_rejects_lock_owned_by_another_task(self, client, test_session_factory):
        """验证阶段也必须拒绝不属于当前任务的设备写锁。"""
        token, task_id = await self._create_pending_task(client, test_session_factory, "sysname VerifyLockOwner")
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={}, headers=auth_header(token))
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={"risk_confirm": True}, headers=auth_header(token))
        await client.post(f"/api/v1/deploy/tasks/{task_id}/execute", headers=auth_header(token))
        await self._lock_owned_by_other_task(client, token, task_id, test_session_factory)

        response = await client.post(f"/api/v1/deploy/tasks/{task_id}/verify", headers=auth_header(token))
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_simulate_override_does_not_change_default(self, client, test_session_factory):
        """请求体 simulate:false 不改变服务端默认模拟"""
        token, task_id = await self._create_pending_task(client, test_session_factory, "sysname R1")
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={}, headers=auth_header(token))
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={"risk_confirm": True}, headers=auth_header(token))
        resp = await client.post(f"/api/v1/deploy/tasks/{task_id}/execute", json={"simulate": False}, headers=auth_header(token))
        # 服务端忽略客户端参数，仍返回 simulated
        assert resp.status_code == 200
        assert resp.json()["mode"] == "simulated"

    @pytest.mark.asyncio
    async def test_simulate_execution_does_not_call_credentials_or_netmiko(self, client, test_session_factory, monkeypatch):
        """模拟路径不调用凭据、RetryEngine、NetmikoExecutor"""
        from modules.device.service import DeviceService
        monkeypatch.setattr(DeviceService, "get_device_credentials", AsyncMock(side_effect=AssertionError("must not read credentials")))
        from core.retry_engine import RetryEngine
        monkeypatch.setattr(RetryEngine, "execute", AsyncMock(side_effect=AssertionError("must not retry")))
        from engines.netmiko_exec import NetmikoExecutor
        monkeypatch.setattr(NetmikoExecutor, "connect", AsyncMock(side_effect=AssertionError("must not connect")))
        token, task_id = await self._create_pending_task(client, test_session_factory, "sysname MockGuard")
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={}, headers=auth_header(token))
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={"risk_confirm": True}, headers=auth_header(token))
        resp = await client.post(f"/api/v1/deploy/tasks/{task_id}/execute", headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["mode"] == "simulated"
        report = await client.post(f"/api/v1/deploy/tasks/{task_id}/verify", headers=auth_header(token))
        assert report.status_code == 200
        assert report.json()["mode"] == "simulated"
        assert report.json()["verification"] == "not_performed"
        async with test_session_factory() as db:
            from modules.deploy.models import DeployTask, DeviceWriteLock
            from modules.auth.models import AuditLog
            from sqlalchemy import select
            task = await db.get(DeployTask, task_id)
            # 模拟验证后任务置为成功（旧行为残留 deploying 会永久卡锁，已修复为结束即释放）
            assert task.status.value == "success"
            assert await db.get(DeviceWriteLock, task.device_id) is None
            audit = (await db.execute(select(AuditLog).where(AuditLog.action == "deploy_task_verified").order_by(AuditLog.id.desc()))).scalars().first()
        assert audit is not None
        assert "MockGuard" not in audit.detail
        assert "no_readback" in audit.detail

    @pytest.mark.asyncio
    async def test_execute_simulated_audit_excludes_config(self, client, test_session_factory):
        """审计 detail 不含配置正文或凭据"""
        from sqlalchemy import select
        from modules.auth.models import AuditLog
        config = "sysname SecretExec"
        token, task_id = await self._create_pending_task(client, test_session_factory, config)
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={}, headers=auth_header(token))
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={"risk_confirm": True}, headers=auth_header(token))
        await client.post(f"/api/v1/deploy/tasks/{task_id}/execute", headers=auth_header(token))
        async with test_session_factory() as db:
            audit = (await db.execute(select(AuditLog).where(AuditLog.action == "deploy_task_executed").order_by(AuditLog.id.desc()))).scalars().first()
        assert audit is not None
        assert config not in audit.detail
        assert "task_id" in audit.detail

    @pytest.mark.asyncio
    async def test_controlled_real_execution_uses_mock_executor_only(self, client, test_session_factory, monkeypatch, mock_ssh_device_mode):
        """关闭服务端模拟时，只通过mock验证下发、保存、回读顺序。"""
        from types import SimpleNamespace
        from modules.deploy import service as deploy_service
        from modules.device.service import DeviceService

        calls = []

        class FakeExecutor:
            def __init__(self, *args, **kwargs):
                calls.append("init")

            async def connect(self):
                calls.append("connect")

            async def send_config_set(self, commands):
                calls.append("send_config_set")
                return "configured"

            async def save_config(self):
                calls.append("save_config")
                return "saved"

            async def send_command(self, command):
                assert command in {"display current-configuration", "display saved-configuration"}
                calls.append("read_saved" if command == "display saved-configuration" else "readback")
                return "sysname MockOnly" if "send_config_set" in calls else "sysname Before"

            async def disconnect(self):
                calls.append("disconnect")

        monkeypatch.setattr(deploy_service, "get_settings", lambda: SimpleNamespace(deploy_simulate_only=False, ssh_connect_timeout=10))
        monkeypatch.setattr(deploy_service.DeployService, "_is_authorized_stage4_target", AsyncMock(return_value=True))
        monkeypatch.setattr(DeviceService, "get_device_credentials", AsyncMock(return_value={"username": "test", "password": "not-a-real-credential"}))
        monkeypatch.setattr("engines.netmiko_exec.NetmikoExecutor", FakeExecutor)
        token, task_id = await self._create_pending_task(client, test_session_factory, "sysname MockOnly")
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={}, headers=auth_header(token))
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={"risk_confirm": True}, headers=auth_header(token))

        response = await client.post(f"/api/v1/deploy/tasks/{task_id}/execute", headers=auth_header(token))

        assert response.status_code == 200
        assert response.json()["mode"] == "real"
        assert calls == ["init", "connect", "readback", "read_saved", "send_config_set", "save_config", "readback", "read_saved", "disconnect"]
        from sqlalchemy import select
        from modules.auth.models import AuditLog
        from modules.deploy.models import DeployTask
        async with test_session_factory() as db:
            task = await db.get(DeployTask, task_id)
            audit = (await db.execute(select(AuditLog).where(AuditLog.action == "deploy_task_executed").order_by(AuditLog.id.desc()))).scalars().first()
        assert task.status.value == "deploying"
        assert task.backup_config is not None
        assert task.result_output == "sysname MockOnly"
        assert "sysname MockOnly" not in audit.detail

        verified = await client.post(f"/api/v1/deploy/tasks/{task_id}/verify", headers=auth_header(token))
        assert verified.status_code == 200
        assert verified.json()["verification"] == "passed"
        assert verified.json()["result"] == "success"
        async with test_session_factory() as db:
            task = await db.get(DeployTask, task_id)
            from modules.deploy.models import DeviceWriteLock
            lock = await db.get(DeviceWriteLock, task.device_id)
            from sqlalchemy import select
            from modules.deploy.models import ConfigVersion
            version = (await db.execute(select(ConfigVersion).where(ConfigVersion.deploy_task_id == task_id))).scalar_one()
        assert task.status.value == "success"
        assert lock is None
        assert version.config_snapshot == "sysname MockOnly"
        async with test_session_factory() as db:
            verified_audit = (await db.execute(select(AuditLog).where(AuditLog.action == "deploy_task_verified").order_by(AuditLog.id.desc()))).scalars().first()
        assert "sysname MockOnly" not in verified_audit.detail

    @pytest.mark.asyncio
    async def test_verify_mismatch_rolls_back_only_through_authorized_mock_executor(self, client, test_session_factory, monkeypatch, mock_ssh_device_mode):
        """真实回读差异仅在当前任务锁、备份和授权都满足时才经mock回滚。"""
        from types import SimpleNamespace
        from sqlalchemy import select
        from modules.auth.models import AuditLog
        from modules.deploy import service as deploy_service
        from modules.deploy.models import DeployTask, DeviceWriteLock
        from modules.device.service import DeviceService

        calls = []

        class FakeExecutor:
            def __init__(self, *args, **kwargs):
                calls.append("init")

            async def connect(self):
                calls.append("connect")

            async def send_config_set(self, commands):
                calls.append("restore")

            async def save_config(self):
                calls.append("save")

            async def send_command(self, command):
                assert command in {"display current-configuration", "display saved-configuration"}
                calls.append("read_saved" if command == "display saved-configuration" else "readback")
                return "sysname BackupRouter" if "restore" in calls else "sysname UnexpectedRouter"

            async def disconnect(self):
                calls.append("disconnect")

        expected = "sysname ExpectedRouter"
        actual = "sysname UnexpectedRouter"
        token, task_id = await self._create_pending_task(client, test_session_factory, expected)
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={}, headers=auth_header(token))
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={"risk_confirm": True}, headers=auth_header(token))
        async with test_session_factory() as db:
            task = await db.get(DeployTask, task_id)
            task.status = deploy_service.DeployStatus.DEPLOYING
            task.backup_config = "sysname BackupRouter"
            task.result_output = actual
            await db.commit()

        monkeypatch.setattr(deploy_service, "get_settings", lambda: SimpleNamespace(deploy_simulate_only=False, ssh_connect_timeout=10))
        monkeypatch.setattr(deploy_service.DeployService, "_is_authorized_stage4_target", AsyncMock(return_value=True))
        monkeypatch.setattr(DeviceService, "get_device_credentials", AsyncMock(return_value={"username": "test", "password": "not-a-real-credential"}))
        monkeypatch.setattr("engines.netmiko_exec.NetmikoExecutor", FakeExecutor)

        response = await client.post(f"/api/v1/deploy/tasks/{task_id}/verify", headers=auth_header(token))

        assert response.status_code == 200
        assert response.json()["rollback"] == "rolled_back"
        assert calls == ["init", "connect", "readback", "read_saved", "restore", "save", "readback", "read_saved", "disconnect"]
        async with test_session_factory() as db:
            task = await db.get(DeployTask, task_id)
            lock = await db.get(DeviceWriteLock, task.device_id)
            audit = (await db.execute(select(AuditLog).where(AuditLog.action == "deploy_task_rollback").order_by(AuditLog.id.desc()))).scalars().first()
        assert task.status.value == "rolled_back"
        assert lock is None
        assert expected not in audit.detail
        assert actual not in audit.detail

    @pytest.mark.asyncio
    async def test_verify_mismatch_releases_lock_when_authorized_rollback_fails(self, client, test_session_factory, monkeypatch, mock_ssh_device_mode):
        """受控回滚失败也必须释放当前任务写锁。"""
        from types import SimpleNamespace
        from modules.deploy import service as deploy_service
        from modules.deploy.models import DeployTask, DeviceWriteLock
        from modules.device.service import DeviceService

        class FailingExecutor:
            async def connect(self):
                pass

            async def send_config_set(self, commands):
                raise RuntimeError("rollback failed")

            async def send_command(self, command):
                return "sysname UnexpectedRouter"

            async def disconnect(self):
                pass

        token, task_id = await self._create_pending_task(client, test_session_factory, "sysname ExpectedRouter")
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={}, headers=auth_header(token))
        await client.post(f"/api/v1/deploy/tasks/{task_id}/confirm", json={"risk_confirm": True}, headers=auth_header(token))
        async with test_session_factory() as db:
            task = await db.get(DeployTask, task_id)
            task.status = deploy_service.DeployStatus.DEPLOYING
            task.backup_config = "sysname BackupRouter"
            task.result_output = "sysname UnexpectedRouter"
            await db.commit()

        monkeypatch.setattr(deploy_service, "get_settings", lambda: SimpleNamespace(deploy_simulate_only=False, ssh_connect_timeout=10))
        monkeypatch.setattr(deploy_service.DeployService, "_is_authorized_stage4_target", AsyncMock(return_value=True))
        monkeypatch.setattr(DeviceService, "get_device_credentials", AsyncMock(return_value={"username": "test", "password": "not-a-real-credential"}))
        monkeypatch.setattr("engines.netmiko_exec.NetmikoExecutor", lambda *args, **kwargs: FailingExecutor())

        response = await client.post(f"/api/v1/deploy/tasks/{task_id}/verify", headers=auth_header(token))

        assert response.status_code == 200
        assert response.json()["rollback"] == "rollback_failed"
        async with test_session_factory() as db:
            task = await db.get(DeployTask, task_id)
            lock = await db.get(DeviceWriteLock, task.device_id)
            from sqlalchemy import select
            from modules.auth.models import AuditLog
            lock_release = (await db.execute(select(AuditLog).where(AuditLog.action == "device_write_lock_released"))).scalars().first()
        assert task.status.value == "failed"
        assert lock is None
        assert lock_release is not None


# ═══════════════════════════════════════════════════════════════════
# 5. 监控告警模块 (Monitor)
# ═══════════════════════════════════════════════════════════════════

class TestMonitor:
    @pytest.mark.asyncio
    async def test_get_monitor_stats(self, client, test_session_factory):
        """获取监控统计数据"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/monitor/stats", headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "totalDevices" in data
        assert "onlineDevices" in data
        assert "activeAlarms" in data

    @pytest.mark.asyncio
    async def test_list_alarms(self, client, test_session_factory):
        """获取告警列表"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/alarms", headers=auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_device_metrics(self, client, test_session_factory):
        """获取设备指标"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/monitor/metrics/1", headers=auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_monitor_trends(self, client, test_session_factory):
        """获取监控趋势"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/monitor/trends", headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "metrics" in data
        assert "alarms" in data

    @pytest.mark.asyncio
    @patch("modules.monitor.router.MonitorService.run_inspection", new_callable=AsyncMock)
    async def test_create_monitor_inspection(self, mock_run_inspection, client, test_session_factory):
        """触发巡检任务"""
        token = await _setup_admin_user(test_session_factory)
        mock_run_inspection.return_value = {
            "task": {
                "id": 1,
                "topology_id": 1,
                "job_type": "inspection",
                "trigger_mode": "manual",
                "status": "success",
                "triggered_by": 1,
                "device_count": 1,
                "success_count": 1,
                "failure_count": 0,
                "error_message": None,
                "summary": {"success": 1, "failed": 0, "skipped": 0, "errors": []},
                "report": {"alarm_count": 0, "metric_types": ["cpu_usage"]},
                "started_at": "2026-07-17T00:00:00+00:00",
                "finished_at": "2026-07-17T00:01:00+00:00",
                "created_at": "2026-07-17T00:00:00+00:00",
            },
            "summary": {"success": 1, "failed": 0, "skipped": 0, "errors": []},
            "report": {"alarm_count": 0, "metric_types": ["cpu_usage"]},
        }

        resp = await client.post("/api/v1/monitor/inspections/1", headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["task"]["job_type"] == "inspection"
        assert data["report"]["alarm_count"] == 0


# ═══════════════════════════════════════════════════════════════════
# 6. 实训考核模块 (Training)
# ═══════════════════════════════════════════════════════════════════

class TestTraining:
    @pytest.mark.asyncio
    async def test_create_lab(self, client, test_session_factory):
        """创建实训Lab"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "实训拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        resp = await client.post("/api/v1/training/labs", json={
            "title": "OSPF基础配置",
            "description": "学习OSPF路由协议基础配置",
            "topology_id": topo_id,
            "objectives": ["完成OSPF区域配置"],
            "time_limit_minutes": 60,
        }, headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "OSPF基础配置"
        assert data["status"] == "ready"

    @pytest.mark.asyncio
    async def test_list_labs(self, client, test_session_factory):
        """获取Lab列表"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "列表实训拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        await client.post("/api/v1/training/labs", json={
            "title": "列表测试Lab", "topology_id": topo_id,
        }, headers=auth_header(token))
        resp = await client.get("/api/v1/training/labs", headers=auth_header(token))
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    @pytest.mark.asyncio
    async def test_get_lab(self, client, test_session_factory):
        """获取Lab详情"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "详情实训拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        create_resp = await client.post("/api/v1/training/labs", json={
            "title": "详情测试Lab", "topology_id": topo_id,
        }, headers=auth_header(token))
        lab_id = create_resp.json()["id"]
        resp = await client.get(f"/api/v1/training/labs/{lab_id}",
                                headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["title"] == "详情测试Lab"

    @pytest.mark.asyncio
    async def test_update_lab(self, client, test_session_factory):
        """更新Lab"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "更新实训拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        create_resp = await client.post("/api/v1/training/labs", json={
            "title": "更新前Lab", "topology_id": topo_id,
        }, headers=auth_header(token))
        lab_id = create_resp.json()["id"]
        resp = await client.put(f"/api/v1/training/labs/{lab_id}", json={
            "title": "更新后Lab",
        }, headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["title"] == "更新后Lab"

    @pytest.mark.asyncio
    async def test_delete_lab(self, client, test_session_factory):
        """删除Lab"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "删除实训拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        create_resp = await client.post("/api/v1/training/labs", json={
            "title": "删除测试Lab", "topology_id": topo_id,
        }, headers=auth_header(token))
        lab_id = create_resp.json()["id"]
        resp = await client.delete(f"/api/v1/training/labs/{lab_id}",
                                   headers=auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_start_session(self, client, test_session_factory):
        """开始实训会话"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "会话实训拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        lab_resp = await client.post("/api/v1/training/labs", json={
            "title": "会话测试Lab", "topology_id": topo_id,
        }, headers=auth_header(token))
        lab_id = lab_resp.json()["id"]
        # 更新Lab状态为ready
        await client.put(f"/api/v1/training/labs/{lab_id}", json={
            "status": "ready",
        }, headers=auth_header(token))
        resp = await client.post("/api/v1/training/sessions", json={
            "lab_id": lab_id,
        }, headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_get_session(self, client, test_session_factory):
        """获取会话详情"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "会话详情拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        lab_resp = await client.post("/api/v1/training/labs", json={
            "title": "会话详情Lab", "topology_id": topo_id,
        }, headers=auth_header(token))
        lab_id = lab_resp.json()["id"]
        await client.put(f"/api/v1/training/labs/{lab_id}", json={"status": "ready"}, headers=auth_header(token))
        sess_resp = await client.post("/api/v1/training/sessions", json={
            "lab_id": lab_id,
        }, headers=auth_header(token))
        session_id = sess_resp.json()["id"]
        resp = await client.get(f"/api/v1/training/sessions/{session_id}",
                                headers=auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_sessions(self, client, test_session_factory):
        """关闭弹窗后可通过会话列表重新进入"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "会话列表拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        lab_resp = await client.post("/api/v1/training/labs", json={
            "title": "会话列表Lab", "topology_id": topo_id,
        }, headers=auth_header(token))
        lab_id = lab_resp.json()["id"]
        sess_resp = await client.post("/api/v1/training/sessions", json={
            "lab_id": lab_id,
        }, headers=auth_header(token))
        session_id = sess_resp.json()["id"]
        resp = await client.get("/api/v1/training/sessions", headers=auth_header(token))
        assert resp.status_code == 200
        rows = resp.json()
        assert isinstance(rows, list)
        assert any(row["id"] == session_id and row["lab_title"] == "会话列表Lab" for row in rows)
        assert any(row["status"] == "in_progress" for row in rows)

    @pytest.mark.asyncio
    async def test_inject_fault(self, client, test_session_factory):
        """故障注入"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "故障注入拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        dev_resp = await client.post("/api/v1/devices", json={
            "hostname": "FaultDev", "mgmt_ip": "192.168.100.30",
            "device_type": "router", "topology_id": topo_id,
        }, headers=auth_header(token))
        device_id = dev_resp.json()["id"]
        lab_resp = await client.post("/api/v1/training/labs", json={
            "title": "故障注入Lab", "topology_id": topo_id,
        }, headers=auth_header(token))
        lab_id = lab_resp.json()["id"]
        await client.put(f"/api/v1/training/labs/{lab_id}", json={"status": "ready"}, headers=auth_header(token))
        sess_resp = await client.post("/api/v1/training/sessions", json={
            "lab_id": lab_id,
        }, headers=auth_header(token))
        session_id = sess_resp.json()["id"]
        resp = await client.post(f"/api/v1/training/sessions/{session_id}/inject", json={
            "fault_scenario": [{
                "device_id": device_id,
                "fault_type": "interface_shutdown",
                "config": {"interface": "GigabitEthernet0/0/1"},
            }],
        }, headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["injected"] == 1

    @pytest.mark.asyncio
    async def test_score_session(self, client, test_session_factory):
        """评分"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "评分实训拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        lab_resp = await client.post("/api/v1/training/labs", json={
            "title": "评分测试Lab", "topology_id": topo_id,
            "scoring_rules": {"correct_config": 50, "no_errors": 30, "speed": 20},
        }, headers=auth_header(token))
        lab_id = lab_resp.json()["id"]
        await client.put(f"/api/v1/training/labs/{lab_id}", json={"status": "ready"}, headers=auth_header(token))
        sess_resp = await client.post("/api/v1/training/sessions", json={
            "lab_id": lab_id,
        }, headers=auth_header(token))
        session_id = sess_resp.json()["id"]
        resp = await client.post(f"/api/v1/training/sessions/{session_id}/score",
                                 headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "score" in data

    @pytest.mark.asyncio
    async def test_start_sandbox(self, client, test_session_factory):
        """沙箱模式 - 仅测试会话创建，不测试故障注入"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "沙箱实训拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        lab_resp = await client.post("/api/v1/training/labs", json={
            "title": "沙箱测试Lab", "topology_id": topo_id,
            "is_sandbox": True,
        }, headers=auth_header(token))
        lab_id = lab_resp.json()["id"]
        await client.put(f"/api/v1/training/labs/{lab_id}", json={"status": "ready"}, headers=auth_header(token))
        resp = await client.post("/api/v1/training/sandbox/start", json={
            "lab_id": lab_id,
        }, headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "in_progress"


# ═══════════════════════════════════════════════════════════════════
# 7. AI服务模块 (AI)
# ═══════════════════════════════════════════════════════════════════

class TestAI:
    @pytest.mark.asyncio
    async def test_get_ai_logs(self, client, test_session_factory):
        """获取AI交互日志"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/ai/logs", headers=auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_ai_logs_with_type(self, client, test_session_factory):
        """按类型过滤AI日志"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/ai/logs",
                                params={"request_type": "generate_cli"},
                                headers=auth_header(token))
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════
# 8. 系统管理模块 (System)
# ═══════════════════════════════════════════════════════════════════

class TestSystem:
    @pytest.mark.asyncio
    async def test_system_info(self, client, test_session_factory):
        """获取系统信息"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/system/info", headers=auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_system_config(self, client, test_session_factory):
        """获取系统配置"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/system/config", headers=auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_system_config(self, client, test_session_factory):
        """创建系统配置"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.post("/api/v1/system/config", json={
            "config_key": "test_config_key",
            "config_value": "test_config_value",
            "description": "测试配置",
        }, headers=auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_audit_logs(self, client, test_session_factory):
        """获取审计日志"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/system/audit-logs", headers=auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_log_files(self, client, test_session_factory):
        """获取日志文件列表"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/system/logs", headers=auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_background_tasks(self, client, test_session_factory):
        """获取后台任务列表"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/system/tasks", headers=auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """健康检查"""
        resp = await client.get("/api/v1/health")
        assert resp.status_code in [200, 503]


# ═══════════════════════════════════════════════════════════════════
# 9. 事务性配置下发 (Deploy Transaction)
# ═══════════════════════════════════════════════════════════════════

class TestDeployTransaction:
    @pytest.mark.asyncio
    async def test_transaction_deploy(self, client, test_session_factory):
        """事务性配置下发"""
        token = await _setup_admin_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "事务部署拓扑"
        }, headers=auth_header(token))
        topo_id = topo_resp.json()["id"]
        dev_resp = await client.post("/api/v1/devices", json={
            "hostname": "TxRouter", "mgmt_ip": "192.168.100.20",
            "device_type": "router", "topology_id": topo_id,
        }, headers=auth_header(token))
        device_id = dev_resp.json()["id"]

        resp = await client.post("/api/v1/deploy/transaction", json={
            "device_ids": [device_id],
            "config_content": "sysname TxRouter",
            "change_level": "daily",
            "engine": "netmiko",
        }, headers=auth_header(token))
        assert resp.status_code == 409


# ═══════════════════════════════════════════════════════════════════
# 10. 权限测试 (Authorization)
# ═══════════════════════════════════════════════════════════════════

class TestAuthorization:
    @pytest.mark.asyncio
    async def test_user_cannot_create_device(self, client, test_session_factory):
        """普通用户不能创建设备"""
        admin_token = await _setup_admin_user(test_session_factory)
        user_token = await _setup_test_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "权限测试拓扑"
        }, headers=auth_header(admin_token))
        topo_id = topo_resp.json()["id"]
        resp = await client.post("/api/v1/devices", json={
            "hostname": "NoPerm", "mgmt_ip": "192.168.100.99",
            "device_type": "router", "topology_id": topo_id,
        }, headers=auth_header(user_token))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_user_cannot_delete_device(self, client, test_session_factory):
        """普通用户不能删除设备"""
        admin_token = await _setup_admin_user(test_session_factory)
        user_token = await _setup_test_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "删除权限拓扑"
        }, headers=auth_header(admin_token))
        topo_id = topo_resp.json()["id"]
        dev_resp = await client.post("/api/v1/devices", json={
            "hostname": "ProtectMe", "mgmt_ip": "192.168.100.98",
            "device_type": "router", "topology_id": topo_id,
        }, headers=auth_header(admin_token))
        device_id = dev_resp.json()["id"]
        resp = await client.delete(f"/api/v1/devices/{device_id}",
                                   headers=auth_header(user_token))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_user_cannot_get_draft_lab(self, client, test_session_factory):
        """普通用户不能读取草稿 Lab 详情"""
        admin_token = await _setup_admin_user(test_session_factory)
        user_token = await _setup_test_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "草稿Lab拓扑"
        }, headers=auth_header(admin_token))
        topo_id = topo_resp.json()["id"]
        create_resp = await client.post("/api/v1/training/labs", json={
            "title": "草稿Lab", "topology_id": topo_id,
        }, headers=auth_header(admin_token))
        lab_id = create_resp.json()["id"]
        await client.put(
            f"/api/v1/training/labs/{lab_id}",
            json={"status": "draft"},
            headers=auth_header(admin_token),
        )
        resp = await client.get(f"/api/v1/training/labs/{lab_id}", headers=auth_header(user_token))
        assert resp.status_code == 404
        admin_resp = await client.get(f"/api/v1/training/labs/{lab_id}", headers=auth_header(admin_token))
        assert admin_resp.status_code == 200

    @pytest.mark.asyncio
    async def test_user_cannot_save_topology_layout(self, client, test_session_factory):
        """普通用户不能保存拓扑布局"""
        admin_token = await _setup_admin_user(test_session_factory)
        user_token = await _setup_test_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "布局权限拓扑"
        }, headers=auth_header(admin_token))
        topo_id = topo_resp.json()["id"]
        resp = await client.put(
            f"/api/v1/topologies/{topo_id}/layout/draft",
            json={"positions": {}},
            headers=auth_header(user_token),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_user_cannot_execute_others_deploy_task(self, client, test_session_factory):
        """普通用户不能执行他人下发任务"""
        admin_token = await _setup_admin_user(test_session_factory)
        user_token = await _setup_test_user(test_session_factory)
        topo_resp = await client.post("/api/v1/topologies", json={
            "name": "执行权限拓扑"
        }, headers=auth_header(admin_token))
        topo_id = topo_resp.json()["id"]
        dev_resp = await client.post("/api/v1/devices", json={
            "hostname": "ExecLock", "mgmt_ip": "192.168.100.97",
            "device_type": "router", "topology_id": topo_id,
        }, headers=auth_header(admin_token))
        device_id = dev_resp.json()["id"]
        await client.put(f"/api/v1/devices/{device_id}/status",
                         params={"status": "online"}, headers=auth_header(admin_token))
        created = await client.post("/api/v1/deploy", json={
            "device_ids": [device_id], "config_content": "sysname ExecLock",
        }, headers=auth_header(admin_token))
        assert created.status_code == 200
        task_id = created.json()["details"][0]["task_id"]
        resp = await client.post(
            f"/api/v1/deploy/tasks/{task_id}/execute",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_unauthenticated_access(self, client):
        """未认证访问：必须 401（缺凭证 ≠ 权限不足）"""
        resp = await client.get("/api/v1/devices")
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════
# 11. 边界条件测试 (Edge Cases)
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_deploy_invalid_change_level(self, client, test_session_factory):
        """无效的变更级别"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.post("/api/v1/deploy", json={
            "device_ids": [1],
            "config_content": "test",
            "change_level": "invalid_level",
            "engine": "netmiko",
        }, headers=auth_header(token))
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_get_nonexistent_deploy_task(self, client, test_session_factory):
        """获取不存在的部署任务"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/deploy/tasks/99999",
                                headers=auth_header(token))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_render_invalid_template(self, client, test_session_factory):
        """渲染无效模板"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.post("/api/v1/config-templates/render", json={
            "content": "{% if %}{% endif %}",
            "variables": {},
        }, headers=auth_header(token))
        assert resp.status_code == 422


@pytest_asyncio.fixture
async def webssh_engine(tmp_path):
    """Independent connections for concurrent heartbeat/auth/release sessions.

    TestClient also runs its own loop. A StaticPool memory DB shares one driver
    connection across those sessions and loops; cancellation can strand its
    graceful-close task while the portal waits forever at shutdown.
    """
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'webssh.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def webssh_session_factory(webssh_engine):
    factory = async_sessionmaker(webssh_engine, class_=AsyncSession, expire_on_commit=False)
    await _setup_admin_user(factory)
    return factory


class TestWebSSH:
    """WebSSH测试使用独立临时文件库；并发会话不共享driver连接。"""

    @pytest.mark.asyncio
    async def test_sim_terminal_reads_and_disconnects_with_concurrent_heartbeat(self, client, webssh_session_factory, monkeypatch):
        """Keep the original failing sim/heartbeat path, not just the SSH mock."""
        from modules.device.models import Device, DeviceType, Topology, TopologyType
        from main import app
        monkeypatch.setattr('engines.device_adapter.get_device_mode', lambda: 'sim')
        async with webssh_session_factory() as db:
            topology = Topology(name='sim-disconnect', topology_type=TopologyType.LAB)
            db.add(topology); await db.flush()
            device = Device(hostname='SIM-DISCONNECT', mgmt_ip='192.0.2.204',
                            device_type=DeviceType.ROUTER, topology_id=topology.id)
            db.add(device); await db.commit(); await db.refresh(device)
        token = create_access_token(1, 'admin', 'admin')
        with TestClient(app) as ws_client:
            with patch('modules.webssh.router.get_session_factory', return_value=webssh_session_factory):
                with patch('modules.webssh.proxy.paramiko.SSHClient', side_effect=AssertionError('sim must not use SSH')):
                    with ws_client.websocket_connect(f'/api/v1/ws/ssh/{device.id}?token={token}') as ws:
                        connected = json.loads(ws.receive_text())
                        assert connected['type'] == 'connected' and '模拟终端' in connected['message']
                        assert json.loads(ws.receive_text())['type'] == 'output'  # prompt
                        ws.send_text(json.dumps({'type': 'input', 'data': 'display version\n'}))
                        output = json.loads(ws.receive_text())
                        assert output['type'] == 'output' and 'VRP' in output['data']

    @pytest.mark.asyncio
    async def test_websocket_rejects_device_with_write_lock(self, client, webssh_session_factory):
        from sqlalchemy import select
        from modules.device.models import Topology, TopologyType, Device, DeviceType, DeviceStatus
        from modules.deploy.models import DeployTask, DeployStatus, ChangeLevel, DeviceWriteLock
        from modules.auth.models import User
        async with webssh_session_factory() as db:
            user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one_or_none()
            if not user:
                user = User(username="admin", hashed_password=ADMIN_PASSWORD_HASH, role="admin")
                db.add(user)
                await db.flush()
            topo = Topology(name="锁测试拓扑", topology_type=TopologyType.LAB)
            db.add(topo); await db.flush()
            device = Device(hostname="LockedWebSSH", mgmt_ip="10.10.10.10", device_type=DeviceType.ROUTER, topology_id=topo.id, status=DeviceStatus.ONLINE)
            db.add(device); await db.flush()
            task = DeployTask(device_id=device.id, config_content="sysname x", status=DeployStatus.CONFIRMED, change_level=ChangeLevel.DAILY, operator_id=user.id)
            db.add(task); await db.flush()
            db.add(DeviceWriteLock(device_id=device.id, task_id=task.id)); await db.commit()
            token = create_access_token(user.id, user.username, "admin")
        from main import app
        with TestClient(app) as ws_client:
            with patch("modules.webssh.router.get_session_factory", return_value=webssh_session_factory):
                with ws_client.websocket_connect(f"/api/v1/ws/ssh/{device.id}?token={token}") as ws:
                    assert "占用" in json.loads(ws.receive_text())["message"]

    def test_websocket_auth_failure_invalid_token(self, client, test_session_factory):
        """WebSocket连接 - 无效token认证失败。

        A3：拒绝路径改为"先 accept 再 close"，否则浏览器只能看到 1006 空原因
        （自定义 close code/reason 传不出去）。因此握手会成功，失败体现在随后的关闭帧上。
        """
        from main import app
        with TestClient(app) as ws_client:
            with ws_client.websocket_connect("/api/v1/ws/ssh/1?token=invalid_token") as ws:
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    ws.receive_text()
        assert exc_info.value.code == 4001
        assert "认证失败" in exc_info.value.reason

    def test_websocket_auth_failure_no_token(self, client, test_session_factory):
        """WebSocket连接 - 无token认证失败（同上：接受握手后用关闭帧告知原因）"""
        from main import app
        with TestClient(app) as ws_client:
            with ws_client.websocket_connect("/api/v1/ws/ssh/1") as ws:
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    ws.receive_text()
        assert exc_info.value.code == 4001
        assert "缺少认证token" in exc_info.value.reason

    def test_websocket_reject_echoes_subprotocol(self, client, test_session_factory):
        """A3：拒绝时必须回显子协议。

        前端用 `new WebSocket(url, [token])` 传 token；按规范服务端若不回显子协议，
        浏览器会直接判定握手失败并只报 1006（实测），用户看不到原因。
        """
        from main import app
        with TestClient(app) as ws_client:
            with ws_client.websocket_connect(
                "/api/v1/ws/ssh/1", subprotocols=["invalid_token"]
            ) as ws:
                assert ws.accepted_subprotocol == "invalid_token"
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    ws.receive_text()
        assert exc_info.value.code == 4001

    def test_websocket_device_not_found(self, client, webssh_session_factory):
        """WebSocket连接 - 设备不存在"""
        token = create_access_token(1, "admin", "admin")
        from main import app
        with TestClient(app) as ws_client:
            with patch("modules.webssh.router.get_session_factory", return_value=webssh_session_factory):
                with ws_client.websocket_connect(f"/api/v1/ws/ssh/99999?token={token}") as ws:
                    data = ws.receive_text()
                    msg = json.loads(data)
                    assert msg["type"] == "error"
                    assert "设备不存在" in msg["message"]

    @pytest.mark.asyncio
    async def test_websocket_connected_success(self, client, webssh_session_factory, mock_ssh_device_mode):
        """WebSocket连接 - 成功连接设备（mock SSH）"""
        token = create_access_token(1, "admin", "admin")

        async def setup_device():
            from modules.device.models import Device, DeviceStatus, DeviceType, Topology, TopologyType
            async with webssh_session_factory() as db:
                topo = Topology(name="webssh_test_topo", topology_type=TopologyType.LAB)
                db.add(topo)
                await db.commit()
                await db.refresh(topo)
                device = Device(
                    hostname="test-router",
                    mgmt_ip="192.168.100.1",
                    ssh_port=22,
                    device_type=DeviceType.ROUTER,
                    topology_id=topo.id,
                    status=DeviceStatus.ONLINE,
                )
                db.add(device)
                await db.commit()
                await db.refresh(device)
                return device.id

        device_id = await setup_device()

        mock_ssh_client = MagicMock()
        mock_channel = MagicMock()
        mock_channel.recv_ready.return_value = False
        mock_ssh_client.invoke_shell.return_value = mock_channel

        from main import app
        with TestClient(app) as ws_client:
            with patch("modules.webssh.router.get_session_factory", return_value=webssh_session_factory):
                with patch("modules.webssh.proxy.paramiko.SSHClient", return_value=mock_ssh_client):
                    with ws_client.websocket_connect(f"/api/v1/ws/ssh/{device_id}?token={token}") as ws:
                        data = ws.receive_text()
                        msg = json.loads(data)
                        assert msg["type"] == "connected"
                        assert "已连接到" in msg["message"]
        mock_ssh_client.connect.assert_called_once()
        mock_ssh_client.invoke_shell.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_input_message(self, client, webssh_session_factory):
        """WebSocket输入消息处理"""
        import threading
        import uuid
        token = create_access_token(1, "admin", "admin")

        async def setup_device():
            from modules.device.models import Device, DeviceStatus, DeviceType, Topology, TopologyType
            async with webssh_session_factory() as db:
                topo = Topology(name=f"webssh_input_topo_{uuid.uuid4().hex[:8]}", topology_type=TopologyType.LAB)
                db.add(topo)
                await db.commit()
                await db.refresh(topo)
                device = Device(
                    hostname="test-input-router",
                    mgmt_ip=f"192.168.100.{hash(uuid.uuid4()) % 200 + 10}",
                    ssh_port=22,
                    device_type=DeviceType.ROUTER,
                    topology_id=topo.id,
                    status=DeviceStatus.ONLINE,
                )
                db.add(device)
                await db.commit()
                await db.refresh(device)
                return device.id

        device_id = await setup_device()

        mock_ssh_client = MagicMock()
        mock_channel = MagicMock()
        mock_channel.recv_ready.return_value = False
        mock_ssh_client.invoke_shell.return_value = mock_channel
        sent = threading.Event()
        mock_channel.send.side_effect = lambda *args, **kwargs: sent.set()

        from main import app
        with TestClient(app) as ws_client:
            with patch("modules.webssh.router.get_session_factory", return_value=webssh_session_factory):
                with patch("engines.device_adapter.get_device_mode", return_value="ssh"):
                    with patch("modules.webssh.proxy.paramiko.SSHClient", return_value=mock_ssh_client):
                        with ws_client.websocket_connect(f"/api/v1/ws/ssh/{device_id}?token={token}") as ws:
                            ws.receive_text()  # connected message
                            ws.send_text(json.dumps({"type": "input", "data": "ls\n"}))
                            assert sent.wait(2), "input was not delivered to the SSH channel"

    @pytest.mark.asyncio
    async def test_websocket_resize_message(self, client, webssh_session_factory):
        """WebSocket窗口大小调整消息"""
        import threading
        import uuid
        token = create_access_token(1, "admin", "admin")

        async def setup_device():
            from modules.device.models import Device, DeviceStatus, DeviceType, Topology, TopologyType
            async with webssh_session_factory() as db:
                topo = Topology(name=f"webssh_resize_topo_{uuid.uuid4().hex[:8]}", topology_type=TopologyType.LAB)
                db.add(topo)
                await db.commit()
                await db.refresh(topo)
                device = Device(
                    hostname="test-resize-router",
                    mgmt_ip=f"192.168.100.{hash(uuid.uuid4()) % 200 + 10}",
                    ssh_port=22,
                    device_type=DeviceType.ROUTER,
                    topology_id=topo.id,
                    status=DeviceStatus.ONLINE,
                )
                db.add(device)
                await db.commit()
                await db.refresh(device)
                return device.id

        device_id = await setup_device()

        mock_ssh_client = MagicMock()
        mock_channel = MagicMock()
        mock_channel.recv_ready.return_value = False
        mock_ssh_client.invoke_shell.return_value = mock_channel
        resized = threading.Event()
        mock_channel.resize_pty.side_effect = lambda *args, **kwargs: resized.set()

        from main import app
        with TestClient(app) as ws_client:
            with patch("modules.webssh.router.get_session_factory", return_value=webssh_session_factory):
                with patch("engines.device_adapter.get_device_mode", return_value="ssh"):
                    with patch("modules.webssh.proxy.paramiko.SSHClient", return_value=mock_ssh_client):
                        with ws_client.websocket_connect(f"/api/v1/ws/ssh/{device_id}?token={token}") as ws:
                            ws.receive_text()  # connected message
                            ws.send_text(json.dumps({"type": "resize", "cols": 120, "rows": 40}))
                            assert resized.wait(2), "resize was not delivered to the SSH channel"
