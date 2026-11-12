"""Resilience checks must rebind the server and release mocked sockets on failure."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from scripts import verify_live_resilience as probe


@pytest.fixture
def rig(monkeypatch):
    stamp = dict(schema=1, database_fingerprint='db', root_fingerprint='root', source_fingerprint='source',
                 device_mode='ssh', deploy_simulate_only=False, knowledge_provider='anythingllm', captured_at='2026-10-11T12:00:00Z')
    targets = [dict(id=n, hostname=f'R{n}', mgmt_ip=f'192.0.2.{n}', ssh_port=22) for n in (1, 2, 3)]
    identity = {**stamp, 'pid': 55, 'launch_id': 'owned-fixture'}
    state = SimpleNamespace(identity_calls=0, changed=False, wrong_target=False, clients=[])
    async def handle(request):
        if request.url.path.endswith('/auth/login'):
            return httpx.Response(200, json={'access_token': 'fixture-token'})
        if request.url.path.endswith('/runtime-identity'):
            if request.headers.get('Authorization') != 'Bearer fixture-token':
                return httpx.Response(401, json={'detail': 'unauthenticated'})
            state.identity_calls += 1
            return httpx.Response(200, json={**identity, 'pid': 99 if state.changed and state.identity_calls > 1 else 55})
        if request.url.path.endswith('/devices'):
            rows = deepcopy(targets)
            if state.wrong_target:
                rows[0]['ssh_port'] = 23
            return httpx.Response(200, json=rows)
        pytest.fail('unexpected external request')
    real_client = httpx.AsyncClient
    def client(**kwargs):
        instance = real_client(**kwargs, transport=httpx.MockTransport(handle))
        state.clients.append(instance)
        return instance
    monkeypatch.setattr(httpx, 'AsyncClient', client)
    monkeypatch.setattr(probe, 'get_settings', lambda: SimpleNamespace(device_mode='ssh', db_backend='mysql', knowledge_provider='anythingllm', admin_username='fixture', admin_password='fixture'))
    monkeypatch.setattr(probe, 'capture_binding', lambda _: deepcopy(stamp))
    monkeypatch.setattr(probe, 'db_facts', AsyncMock(return_value={'devices': targets, 'llm': {'model': 'fixture'}}))
    monkeypatch.setattr(probe, 'load_run', AsyncMock(return_value={}))
    monkeypatch.setattr(probe, 'load_report', lambda *a: ({'endpoints': [{'errors': 0}]}, True))
    state.contention = AsyncMock(return_value={'ok': True})
    monkeypatch.setattr(probe, 'check_contention', state.contention)
    state.args = SimpleNamespace(api_url='http://isolated.invalid', expected_endpoints='192.0.2.1:22,192.0.2.2:22,192.0.2.3:22', users=30, duration=60, exclusive_window=True)
    return state


@pytest.mark.asyncio
async def test_server_and_targets_are_rechecked_before_terminal_and_at_finish(rig):
    result = await probe.verify(rig.args)
    assert result['ok'] is True and rig.identity_calls == 3
    assert rig.contention.await_count == 1 and all(c.is_closed for c in rig.clients)


@pytest.mark.asyncio
async def test_replaced_server_cannot_receive_terminal_commands(rig):
    rig.changed = True
    result = await probe.verify(rig.args)
    assert result['ok'] is False and rig.contention.await_count == 0
    assert all(c.is_closed for c in rig.clients)


@pytest.mark.asyncio
async def test_wrong_api_endpoint_is_rejected_before_load_or_terminal(rig):
    rig.wrong_target = True
    result = await probe.verify(rig.args)
    assert result['ok'] is False and rig.contention.await_count == 0
    assert probe.load_run.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('cancelled', [False, True])
async def test_failed_or_cancelled_contention_closes_both_owned_sockets(monkeypatch, cancelled):
    import websockets.asyncio.client
    closed = []
    class Socket:
        def __init__(self, number): self.number = number
        async def __aenter__(self): return self
        async def __aexit__(self, *args): closed.append(self.number)
        async def recv(self):
            if cancelled: raise asyncio.CancelledError()
            raise RuntimeError('fixture transport closed')
    count = 0
    def connect(*args, **kwargs):
        nonlocal count
        count += 1
        return Socket(count)
    monkeypatch.setattr(websockets.asyncio.client, 'connect', connect)
    monkeypatch.setattr(probe, 'check_webssh', AsyncMock(return_value={'ok': True}))
    with pytest.raises(asyncio.CancelledError if cancelled else ValueError):
        await probe.check_contention('http://isolated.invalid/api/v1', 'fixture', {'id': 1, 'hostname': 'R1'})
    assert closed == [2, 1] and count == 2
