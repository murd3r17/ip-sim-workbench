"""Security regression checks for the reviewed workflow."""
import asyncio
from datetime import timedelta
from secrets import token_urlsafe
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from core.browser_session import cookie_name
from core.database import Base
from core.security import create_access_token, hash_password
from modules.auth.models import LoginAttemptWindow, TerminalGrant, User, UserRole
from modules.auth.login_limits import reserve_login_attempt
from modules.device.models import Device, DeviceType, Topology


ORIGIN = "http://127.0.0.1:8000"


async def account(factory, username, role=UserRole.USER):
    password = "A7a-" + token_urlsafe(20)
    async with factory() as db:
        user = User(username=username, hashed_password=hash_password(password), role=role)
        db.add(user)
        await db.commit()
        return user.id, password


@pytest.mark.asyncio
async def test_browser_cookie_and_csrf_logout(client, test_session_factory):
    user_id, password = await account(test_session_factory, "review-cookie")
    data = {"username": "review-cookie", "password": password}
    route = f"{ORIGIN}/api/v1/auth/session"
    assert (await client.post(route, json=data, headers={"Origin": "https://foreign.invalid", "X-Workbench-Login": "1"})).status_code == 403
    assert (await client.post(route, json=data, headers={"Origin": ORIGIN})).status_code == 403
    login = await client.post(route, json=data, headers={"Origin": ORIGIN, "X-Workbench-Login": "1"})
    assert login.status_code == 200
    assert "httponly" in login.headers["set-cookie"].lower()
    assert "samesite=strict" in login.headers["set-cookie"].lower()
    assert login.headers["cache-control"] == "no-store"
    body = login.json()
    assert body["user"]["id"] == user_id
    assert "access_token" not in body
    assert (await client.get(route)).json()["session_id"] == body["session_id"]
    assert (await client.delete(route, headers={"Origin": ORIGIN})).status_code == 403
    assert (await client.get(route, headers={"X-Workbench-Session": "stale-tab"})).status_code == 401
    headers = {"Origin": ORIGIN, "X-Workbench-CSRF": body["csrf_token"]}
    assert (await client.delete(route, headers={**headers, "Origin": "https://foreign.invalid"})).status_code == 403
    assert (await client.delete(route, headers=headers)).status_code == 204
    assert (await client.get(route, headers={"Cookie": f"{cookie_name()}={login.cookies[cookie_name()]}"})).status_code == 401


@pytest.mark.asyncio
async def test_cookie_token_version_closes_http_and_sse(client, test_session_factory, monkeypatch):
    from core import auth_stream
    user_id, password = await account(test_session_factory, "review-stream")
    start = await client.post(f"{ORIGIN}/api/v1/auth/session", headers={"Origin": ORIGIN, "X-Workbench-Login": "1"},
                              json={"username": "review-stream", "password": password})
    assert start.status_code == 200
    from core.browser_session import authenticate_browser_session, credential_digest
    async with test_session_factory() as db:
        actor = await authenticate_browser_session(credential_digest(start.cookies[cookie_name()]), db)
    stop = asyncio.Event()

    async def events():
        try:
            yield "first"
            await asyncio.Event().wait()
        finally:
            stop.set()

    monkeypatch.setattr(auth_stream, "LEASE_INTERVAL", 0.02)
    stream = auth_stream.require_live_session(events(), actor)
    assert await anext(stream) == "first"
    async with test_session_factory() as db:
        user = await db.get(User, user_id)
        user.token_version += 1
        await db.commit()
    assert "auth_expired" in await asyncio.wait_for(anext(stream), timeout=2)
    await stream.aclose()
    assert stop.is_set()
    assert (await client.get(f"{ORIGIN}/api/v1/auth/session")).status_code == 401


@pytest.mark.asyncio
async def test_terminal_grant_checks_account_and_device_before_any_connection(client, test_session_factory, monkeypatch):
    import json
    from modules.auth.terminal_grants import check_terminal_grant, TerminalPermissionError, _now
    from modules.webssh.router import webssh_websocket
    learner, _ = await account(test_session_factory, "review-learner")
    admin, _ = await account(test_session_factory, "review-admin", UserRole.ADMIN)
    async with test_session_factory() as db:
        topology = Topology(name="grant-fixture")
        db.add(topology)
        await db.flush()
        first = Device(hostname="fixture-one", mgmt_ip="192.0.2.10", device_type=DeviceType.ROUTER, topology_id=topology.id)
        second = Device(hostname="fixture-two", mgmt_ip="192.0.2.11", device_type=DeviceType.ROUTER, topology_id=topology.id)
        db.add_all([first, second])
        await db.commit()
    monkeypatch.setattr("engines.device_adapter.get_device_mode", lambda: "ssh")
    credentials = AsyncMock(side_effect=AssertionError("must not read credentials"))
    monkeypatch.setattr("modules.webssh.router.DeviceService.get_device_credentials", credentials)
    user_token = create_access_token(learner, "review-learner", "user")
    admin_token = create_access_token(admin, "review-admin", "admin")
    headers = {"Authorization": f"Bearer {admin_token}"}
    target = f"/api/v1/auth/users/{learner}/terminal-grants/{first.id}"
    websocket = SimpleNamespace(headers={"authorization": f"Bearer {user_token}"}, cookies={}, query_params={},
                                accept=AsyncMock(), send_text=AsyncMock(), close=AsyncMock())
    await webssh_websocket(websocket, first.id)
    assert websocket.close.call_args.kwargs["code"] == 4003
    assert "只读观察" in json.loads(websocket.send_text.call_args.args[0])["message"]
    credentials.assert_not_called()
    assert (await client.put(target, headers={"Authorization": f"Bearer {user_token}"}, json={"minutes": 5})).status_code == 403
    grant = await client.put(target, headers=headers, json={"minutes": 5})
    assert grant.status_code == 200
    grant_id = grant.json()["grant_id"]
    actor = {"user_id": learner, "role": "user"}
    async with test_session_factory() as db:
        assert await check_terminal_grant(db, actor, first, mode="ssh") == grant_id
        assert await check_terminal_grant(db, actor, second, mode="sim") is None
        with pytest.raises(TerminalPermissionError):
            await check_terminal_grant(db, actor, second, mode="ssh")
    assert (await client.delete(target, headers=headers, params={"grant_id": grant_id})).status_code == 204
    async with test_session_factory() as db:
        with pytest.raises(TerminalPermissionError):
            await check_terminal_grant(db, actor, first, mode="ssh", expected=grant_id)
    renewed = await client.put(target, headers=headers, json={"minutes": 5})
    assert renewed.status_code == 200 and renewed.json()["grant_id"] != grant_id
    async with test_session_factory() as db:
        with pytest.raises(TerminalPermissionError):
            await check_terminal_grant(db, actor, first, mode="ssh", expected=grant_id)
        row = await db.get(TerminalGrant, (learner, first.id))
        row.expires_at = _now() - timedelta(seconds=1)
        await db.commit()
        with pytest.raises(TerminalPermissionError):
            await check_terminal_grant(db, actor, first, mode="ssh")


@pytest.mark.asyncio
async def test_revoked_terminal_grant_closes_idle_shell_and_releases_lock(client, test_session_factory, monkeypatch):
    import json
    from fastapi import WebSocketDisconnect
    from modules.deploy.models import DeviceWriteLock
    from modules.webssh.router import webssh_websocket

    learner, _ = await account(test_session_factory, "idle-learner")
    admin, _ = await account(test_session_factory, "idle-admin", UserRole.ADMIN)
    async with test_session_factory() as db:
        topology = Topology(name="idle-grant-fixture")
        db.add(topology)
        await db.flush()
        device = Device(hostname="idle-fixture", mgmt_ip="192.0.2.25", device_type=DeviceType.ROUTER, topology_id=topology.id)
        db.add(device)
        await db.commit()

    admin_token = create_access_token(admin, "idle-admin", "admin")
    learner_token = create_access_token(learner, "idle-learner", "user")
    headers = {"Authorization": f"Bearer {admin_token}"}
    target = f"/api/v1/auth/users/{learner}/terminal-grants/{device.id}"
    grant = await client.put(target, headers=headers, json={"minutes": 5})
    assert grant.status_code == 200

    connected, ended = asyncio.Event(), asyncio.Event()
    closed_codes = []
    channel = SimpleNamespace(closed=False, setblocking=lambda _: None, recv_ready=lambda: False)
    channel.close = lambda: setattr(channel, "closed", True)
    ssh = SimpleNamespace(invoke_shell=lambda **_: channel, get_transport=lambda: None, close=lambda: None)

    async def send_text(value):
        if json.loads(value).get("type") == "connected":
            connected.set()

    async def close(*, code=1000, reason=""):
        closed_codes.append(code)
        ended.set()

    async def receive_text():
        await ended.wait()
        raise WebSocketDisconnect()

    monkeypatch.setattr("engines.device_adapter.get_device_mode", lambda: "ssh")
    monkeypatch.setattr("engines.netmiko_exec.new_ssh_client", lambda: ssh)
    monkeypatch.setattr("modules.webssh.proxy.connect_with_device_password", lambda *_: None)
    monkeypatch.setattr("modules.webssh.proxy.SSHProxySession._skip_password_change_prompt", AsyncMock())
    monkeypatch.setattr("modules.webssh.router.DeviceService.get_device_credentials", AsyncMock(return_value={
        "username": "fixture", "password": "",
    }))
    ws = SimpleNamespace(headers={"authorization": f"Bearer {learner_token}"}, cookies={}, query_params={},
                         accept=AsyncMock(), send_text=send_text, receive_text=receive_text, close=close)
    task = asyncio.create_task(webssh_websocket(ws, device.id))
    try:
        await asyncio.wait_for(connected.wait(), 3)
        async with test_session_factory() as db:
            current_lock = await db.get(DeviceWriteLock, device.id)
            assert current_lock is not None and current_lock.owner_id == learner
        result = await client.delete(target, headers=headers, params={"grant_id": grant.json()["grant_id"]})
        assert result.status_code == 204
        await asyncio.wait_for(ended.wait(), 6)
        assert closed_codes[0] == 4003
        await asyncio.wait_for(task, 2)
        assert channel.closed
        for _ in range(40):
            async with test_session_factory() as db:
                if not await db.get(DeviceWriteLock, device.id):
                    break
            await asyncio.sleep(.05)
        else:
            pytest.fail("revoked terminal retained its write lock")
    finally:
        ended.set()
        await asyncio.wait_for(task, 3)


@pytest.mark.asyncio
async def test_shared_budget_and_trusted_proxy(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'attempts.db').as_posix()}"
    engine_a, engine_b = create_async_engine(url), create_async_engine(url)
    try:
        async with engine_a.begin() as connection:
            await connection.run_sync(LoginAttemptWindow.__table__.create)
        factories = [async_sessionmaker(engine_a), async_sessionmaker(engine_b)]
        results = []

        async def attempt(scope, _receive, _send):
            async with factories[len(results) % 2]() as db:
                try:
                    await reserve_login_attempt(db, Request(scope), "same-account")
                except HTTPException as error:
                    results.append((error.status_code, error.headers.get("Retry-After")))
                else:
                    results.append((200, None))

        for number in range(6):
            await ProxyHeadersMiddleware(attempt, trusted_hosts="192.0.2.33")(
                {"type": "http", "scheme": "http", "client": ("192.0.2.10", 12345),
                 "headers": [(b"x-forwarded-for", f"198.51.100.{number}".encode())]}, None, None,
            )
        assert [code for code, _ in results] == [200] * 5 + [429]
        assert int(results[-1][1]) > 0
        await ProxyHeadersMiddleware(attempt, trusted_hosts="192.0.2.33")(
            {"type": "http", "scheme": "https", "client": ("192.0.2.33", 12345),
             "headers": [(b"x-forwarded-for", b"2001:db8::123")]}, None, None,
        )
        assert results[-1] == (200, None)
    finally:
        await engine_a.dispose()
        await engine_b.dispose()
