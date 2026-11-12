"""Cancellation must settle the SSH worker before close or lock release."""
import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from engines.device_adapter import SSHDeviceAdapter
from engines.device_lock import acquire_device_lock
from engines.netmiko_exec import NetmikoExecutor
from modules.monitor.service import MetricCollector


@pytest.mark.asyncio
async def test_cancelled_ssh_worker_settles_before_close_and_unlock():
    entered, release = threading.Event(), threading.Event()
    disconnected = Mock()

    def command(*args, **kwargs):
        entered.set()
        release.wait(2)
        return "finished"

    executor = NetmikoExecutor("192.0.2.80", "fixture", "", port=2280)
    executor._device = SimpleNamespace(send_command=command, disconnect=disconnected)
    adapter = SSHDeviceAdapter("192.0.2.80", "fixture", "", port=2280)
    adapter._executor = executor

    async def collect():
        try:
            await adapter.run_command("display version", timeout=1)
        finally:
            await adapter.close()

    acquired = asyncio.Event()

    async def competitor():
        async with acquire_device_lock("192.0.2.80", 2280):
            acquired.set()

    task = asyncio.create_task(collect())
    competitor_task = None
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        competitor_task = asyncio.create_task(competitor())
        await asyncio.sleep(0.02)
        assert not task.done()
        assert not acquired.is_set()
        disconnected.assert_not_called()
    finally:
        release.set()
        result = await asyncio.gather(task, return_exceptions=True)
        if competitor_task is not None:
            await competitor_task
    assert isinstance(result[0], asyncio.CancelledError)
    disconnected.assert_called_once()


@pytest.mark.asyncio
async def test_remaining_timeout_reaches_underlying_ssh_command():
    executor = NetmikoExecutor("192.0.2.80", "fixture", "")
    executor._device = SimpleNamespace(send_command=Mock(return_value="ok"))
    await executor.send_command("display version", timeout=0.25)
    assert executor._device.send_command.call_args.kwargs["read_timeout"] == 0.25


@pytest.mark.asyncio
async def test_collector_stops_starting_commands_after_overall_deadline(monkeypatch):
    collector = MetricCollector(None)
    collector.settings = collector.settings.model_copy(update={"monitor_device_timeout": 0.01})
    calls = []

    async def read(command, timeout=None):
        calls.append((command, timeout))
        await asyncio.sleep(0.025)
        return "CPU Usage: 20%"

    adapter = SimpleNamespace(run_command=AsyncMock(side_effect=read), close=AsyncMock())
    monkeypatch.setattr("engines.device_adapter.get_device_adapter", AsyncMock(return_value=adapter))
    device = SimpleNamespace(id=1, hostname="R1", device_type="router", model="NE40E-X16", network_role="core")
    with pytest.raises(TimeoutError):
        await collector._collect_via_ssh(device)
    assert len(calls) == 1 and 0 < calls[0][1] <= 0.010001
    adapter.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancellation_during_login_retains_connection_for_cleanup(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    disconnected = Mock()
    observed = {}

    def driver(**kwargs):
        observed.update(kwargs)
        entered.set()
        release.wait(2)
        return SimpleNamespace(disconnect=disconnected)

    monkeypatch.setattr("engines.netmiko_exec.SafeHuaweiSSH", driver)
    adapter = SSHDeviceAdapter("192.0.2.81", "fixture", "", port=2281)

    async def connect_and_close():
        try:
            await adapter.run_command("display version", timeout=1)
        finally:
            await adapter.close()

    task = asyncio.create_task(connect_and_close())
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.sleep(0.01)
        task.cancel()  # A second request/shutdown cancellation cannot abandon login.
        await asyncio.sleep(0.01)
        assert not task.done()
        disconnected.assert_not_called()
    finally:
        release.set()
        result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    disconnected.assert_called_once()
    assert not observed.get("read_timeout_override")
    assert observed["conn_timeout"] > 0 and observed["auth_timeout"] > 0


@pytest.mark.asyncio
async def test_deadline_exhausted_by_login_does_not_send_command():
    adapter = SSHDeviceAdapter("192.0.2.82", "fixture", "", port=2282)
    executor = SimpleNamespace(send_command=AsyncMock())

    async def slow_login():
        await asyncio.sleep(0.02)
        return executor

    adapter._ensure = slow_login
    with pytest.raises(TimeoutError, match="connection"):
        await adapter.run_command("display version", timeout=0.01)
    executor.send_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_temperature_deadline_is_not_a_successful_partial_collection(monkeypatch):
    collector = MetricCollector(None)
    collector._save_metrics = AsyncMock()
    adapter = SimpleNamespace(run_command=AsyncMock(side_effect=[
        "CPU Usage: 20%", "Memory Using Percentage: 30%", "GE0/0/1 up up", "Full", TimeoutError(),
    ]), close=AsyncMock())
    monkeypatch.setattr("engines.device_adapter.get_device_adapter", AsyncMock(return_value=adapter))
    device = SimpleNamespace(id=1, hostname="R1", device_type="router", model="NE40E-X16", network_role="core")
    assert await collector._collect_single_device(device) == "timeout"
    collector._save_metrics.assert_not_awaited()
    adapter.close.assert_awaited_once()
