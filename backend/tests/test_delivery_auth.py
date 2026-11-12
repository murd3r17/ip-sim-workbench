"""Current account state and AI tools must preserve the HTTP permission boundary."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.security import create_access_token, hash_password
from modules.auth.models import User, UserRole, AuditLog
from modules.ai_text.agent_tools import execute_tool
from tests.test_api_full import _setup_admin_user, _setup_test_user, auth_header


@pytest.mark.asyncio
async def test_disabled_account_cannot_reuse_http_token(client, test_session_factory):
    token = await _setup_admin_user(test_session_factory)
    from core.security import decode_access_token
    async with test_session_factory() as db:
        user = await db.get(User, int(decode_access_token(token)["sub"]))
        user.is_active = False
        await db.commit()
    assert (await client.get('/api/v1/devices', headers=auth_header(token))).status_code == 401


@pytest.mark.asyncio
async def test_demoted_account_cannot_reuse_admin_claim(client, test_session_factory):
    token = await _setup_admin_user(test_session_factory)
    from core.security import decode_access_token
    async with test_session_factory() as db:
        user = await db.get(User, int(decode_access_token(token)["sub"]))
        user.role = UserRole.USER
        await db.commit()
    result = await client.get('/api/v1/system/audit-logs', headers=auth_header(token))
    assert result.status_code in (401, 403)


@pytest.mark.asyncio
async def test_password_change_revokes_old_token(client, test_session_factory):
    old = 'A1' + uuid.uuid4().hex
    new = 'B2' + uuid.uuid4().hex
    async with test_session_factory() as db:
        user = User(username='password-revocation', hashed_password=hash_password(old), role=UserRole.USER)
        db.add(user)
        await db.commit()
        token = create_access_token(user.id, user.username, 'user')
    response = await client.put('/api/v1/auth/password', headers=auth_header(token),
                                json={'old_password':old, 'new_password':new})
    assert response.status_code == 200
    assert (await client.get('/api/v1/devices', headers=auth_header(token))).status_code == 401
    login = await client.post('/api/v1/auth/login', json={'username':'password-revocation','password':new})
    assert login.status_code == 200
    assert (await client.get('/api/v1/devices', headers=auth_header(login.json()['access_token']))).status_code == 200


@pytest.mark.asyncio
async def test_validly_signed_token_for_missing_account_is_rejected(client):
    token = create_access_token(987654, 'missing', 'admin')
    assert (await client.get('/api/v1/devices', headers=auth_header(token))).status_code == 401


@pytest.mark.asyncio
async def test_audit_tool_does_not_bypass_admin_permission(client, test_session_factory):
    from core.security import decode_access_token
    admin = await _setup_admin_user(test_session_factory)
    user = await _setup_test_user(test_session_factory)
    admin_id = int(decode_access_token(admin)['sub'])
    user_id = int(decode_access_token(user)['sub'])
    async with test_session_factory() as db:
        db.add(AuditLog(user_id=admin_id, username='private-owner', module='system', action='private-action'))
        await db.commit()
        ordinary = await execute_tool(db, 'query_audit_logs', {}, user_id)
        allowed = await execute_tool(db, 'query_audit_logs', {}, admin_id)
    assert 'private-action' not in ordinary
    assert '无权' in ordinary
    assert 'private-action' in allowed


@pytest.mark.asyncio
async def test_tool_dispatch_requires_active_actor_and_filters_task_owner(client, test_session_factory):
    from core.security import decode_access_token
    from modules.device.models import Device, DeviceType, Topology
    from modules.deploy.models import DeployTask, DeployStatus, ChangeLevel
    admin = await _setup_admin_user(test_session_factory)
    user = await _setup_test_user(test_session_factory)
    admin_id = int(decode_access_token(admin)['sub'])
    user_id = int(decode_access_token(user)['sub'])
    async with test_session_factory() as db:
        topology = Topology(name='tool-owner-scope')
        db.add(topology)
        await db.flush()
        device = Device(hostname='owner-scope', mgmt_ip='192.0.2.27', device_type=DeviceType.ROUTER,
                        topology_id=topology.id)
        db.add(device)
        await db.flush()
        task = DeployTask(device_id=device.id, operator_id=admin_id, config_content='sysname example',
                          status=DeployStatus.SUCCESS, change_level=ChangeLevel.DAILY, engine='netmiko')
        db.add(task)
        await db.commit()
        ordinary = await execute_tool(db, 'query_deploy_tasks', {}, user_id)
        allowed = await execute_tool(db, 'query_deploy_tasks', {}, admin_id)
        account = await db.get(User, user_id)
        account.is_active = False
        await db.commit()
        disabled = await execute_tool(db, 'query_devices', {}, user_id)
    assert f'task#{task.id}' not in ordinary
    assert f'task#{task.id}' in allowed
    assert 'owner-scope' not in disabled


@pytest.mark.asyncio
async def test_webssh_rejects_disabled_account_before_device_connect(client, test_session_factory, monkeypatch):
    from modules.webssh.router import webssh_websocket
    from core.security import decode_access_token
    token = await _setup_test_user(test_session_factory)
    async with test_session_factory() as db:
        user = await db.get(User, int(decode_access_token(token)['sub']))
        user.is_active = False
        await db.commit()
    websocket = SimpleNamespace(headers={}, accept=AsyncMock(), close=AsyncMock(), send_text=AsyncMock())
    get_device = AsyncMock(side_effect=AssertionError('device lookup must not happen'))
    monkeypatch.setattr('modules.webssh.router.DeviceService.get_device', get_device)
    await webssh_websocket(websocket, 1, token)
    get_device.assert_not_called()
    assert websocket.close.call_args.kwargs['code'] == 4001


@pytest.mark.asyncio
async def test_open_webssh_rechecks_account_before_forwarding_input():
    import json
    from unittest.mock import MagicMock
    from fastapi import WebSocketDisconnect
    from modules.webssh.proxy import SSHProxySession
    websocket = SimpleNamespace(
        receive_text=AsyncMock(side_effect=[json.dumps({'type': 'input', 'data': 'sysname changed\r'}), WebSocketDisconnect()]),
        send_text=AsyncMock(), close=AsyncMock(),
    )
    proxy = SSHProxySession(websocket, '192.0.2.44', 22, 'unused', '', authorize=AsyncMock(return_value=False))
    proxy._channel = MagicMock()
    proxy._running = True
    await proxy._ws_to_ssh()
    proxy._channel.send.assert_not_called()
    assert websocket.close.call_args.kwargs['code'] == 4001
    assert not proxy._running


@pytest.mark.asyncio
async def test_webssh_revalidation_uses_current_database_state(client, test_session_factory):
    from core.security import decode_access_token
    from modules.webssh.router import _session_authorized
    token = await _setup_test_user(test_session_factory)
    assert await _session_authorized(test_session_factory, token)
    async with test_session_factory() as db:
        user = await db.get(User, int(decode_access_token(token)['sub']))
        user.token_version += 1
        await db.commit()
    assert not await _session_authorized(test_session_factory, token)
