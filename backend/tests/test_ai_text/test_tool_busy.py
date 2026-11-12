# -*- coding: utf-8 -*-
"""CA-T10：设备占用（busy）时工具返回可解释结果，不抛出、不冒充成功。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from engines.device_lock import DeviceBusyError
from modules.ai_text import agent_tools


class _BusyAdapter:
    async def run_command(self, command):
        raise DeviceBusyError("busy")

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_display_command_reports_busy(monkeypatch):
    device = SimpleNamespace(id=1, hostname="R1", mgmt_ip="192.0.2.1", ssh_port=22)
    monkeypatch.setattr(
        "modules.device.service.DeviceService.get_device",
        AsyncMock(return_value=device),
    )
    monkeypatch.setattr(
        "engines.device_adapter.get_device_adapter",
        AsyncMock(return_value=_BusyAdapter()),
    )
    out = await agent_tools._run_display_command(None, {"device_id": 1, "command": "display clock"}, None)
    assert "占用" in out
