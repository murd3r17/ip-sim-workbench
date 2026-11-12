"""C-07：`agent_tools.execute_tool` 此前零覆盖。

覆盖点：未知工具名、工具内部异常不外抛、真实分派（走真库）、
`run_display_command` 的只读白名单拒绝路径、结果截断与脱敏。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio

from modules.ai_text import agent_tools
from modules.ai_text.agent_tools import TOOL_RESULT_LIMIT, execute_tool
from modules.auth.models import User, UserRole


@pytest_asyncio.fixture
async def tool_user_id(test_session_factory):
    async with test_session_factory() as db:
        user = User(username=f"tool-{uuid4().hex}", hashed_password="unused", role=UserRole.USER)
        db.add(user)
        await db.commit()
        return user.id


def authenticated_db():
    account = SimpleNamespace(id=42, role=UserRole.USER, is_active=True, token_version=0)
    return SimpleNamespace(get=AsyncMock(return_value=account))


@pytest.mark.asyncio
async def test_unknown_tool_returns_message():
    assert await execute_tool(None, "no_such_tool", {}) == "未知工具: no_such_tool"


@pytest.mark.asyncio
async def test_tool_exception_is_swallowed(monkeypatch):
    """工具抛异常时返回文本而不是让整条 SSE 流崩掉。"""

    async def boom(db, args):
        raise RuntimeError("db exploded")

    monkeypatch.setitem(agent_tools.__dict__, "_query_devices", boom)
    result = await execute_tool(authenticated_db(), "query_devices", {}, user_id=42)
    assert result.startswith("工具执行失败: ")
    assert "db exploded" in result


@pytest.mark.asyncio
async def test_dispatch_query_devices_on_real_db(test_session_factory, tool_user_id):
    from modules.device.models import Device, DeviceStatus, DeviceType, DeviceVendor, Topology, TopologyType

    async with test_session_factory() as db:
        topology = Topology(name="tool-topo", topology_type=TopologyType.LAB, status="active")
        db.add(topology)
        await db.flush()
        db.add(
            Device(
                hostname="tool-r1", mgmt_ip="198.51.100.61", device_type=DeviceType.ROUTER,
                vendor=DeviceVendor.HUAWEI, status=DeviceStatus.ONLINE, topology_id=topology.id,
            )
        )
        await db.commit()

        result = await execute_tool(db, "query_devices", {}, user_id=tool_user_id)

    assert "tool-r1" in result


@pytest.mark.asyncio
async def test_dispatch_query_monitor_stats_on_real_db(test_session_factory, tool_user_id):
    async with test_session_factory() as db:
        result = await execute_tool(db, "query_monitor_stats", {}, user_id=tool_user_id)
    assert "设备总数=" in result


@pytest.mark.asyncio
async def test_run_display_command_rejects_non_readonly(test_session_factory, monkeypatch, tool_user_id):
    """只读白名单是 AI 侧唯一的命令闸门，必须真的拦下来。"""
    from modules.device.models import Device, DeviceStatus, DeviceType, DeviceVendor, Topology, TopologyType
    from modules.device.service import DeviceService

    async with test_session_factory() as db:
        topology = Topology(name="tool-topo-2", topology_type=TopologyType.LAB, status="active")
        db.add(topology)
        await db.flush()
        device = Device(
            hostname="tool-r2", mgmt_ip="198.51.100.62", device_type=DeviceType.ROUTER,
            vendor=DeviceVendor.HUAWEI, status=DeviceStatus.ONLINE, topology_id=topology.id,
        )
        db.add(device)
        await db.commit()

        async def fake_get_device(_db, device_id):
            return device

        monkeypatch.setattr(DeviceService, "get_device", fake_get_device)

        result = await execute_tool(
            db, "run_display_command",
            {"device_id": device.id, "command": "reset saved-configuration"},
            user_id=tool_user_id,
        )

    assert "拒绝执行" in result


@pytest.mark.asyncio
async def test_run_display_command_executes_readonly_and_redacts(test_session_factory, monkeypatch, tool_user_id):
    from modules.device.models import Device, DeviceStatus, DeviceType, DeviceVendor, Topology, TopologyType
    from modules.device.service import DeviceService

    class _Adapter:
        async def run_command(self, command):
            return "snmp-agent community read cipher %^%#secret%^%#\nsysname R3"

        async def close(self):
            return None

    async def fake_get_adapter(device):
        return _Adapter()

    async with test_session_factory() as db:
        topology = Topology(name="tool-topo-3", topology_type=TopologyType.LAB, status="active")
        db.add(topology)
        await db.flush()
        device = Device(
            hostname="tool-r3", mgmt_ip="198.51.100.63", device_type=DeviceType.ROUTER,
            vendor=DeviceVendor.HUAWEI, status=DeviceStatus.ONLINE, topology_id=topology.id,
        )
        db.add(device)
        await db.commit()

        async def fake_get_device(_db, device_id):
            return device

        monkeypatch.setattr(DeviceService, "get_device", fake_get_device)
        monkeypatch.setattr("engines.device_adapter.get_device_adapter", fake_get_adapter)

        result = await execute_tool(
            db, "run_display_command",
            {"device_id": device.id, "command": "display current-configuration"},
            user_id=tool_user_id,
        )

    assert "tool-r3" in result
    assert "secret" not in result  # 脱敏后不应出现 community 明文
    assert "sysname R3" in result


def test_limit_truncates_long_output():
    short = agent_tools._limit("abc")
    assert short == "abc"
    long_text = "x" * (TOOL_RESULT_LIMIT + 10)
    limited = agent_tools._limit(long_text)
    assert limited.startswith("x" * 10)
    assert "截断" in limited


def test_redact_output_masks_credentials():
    raw = "radius-server shared-key cipher MySharedKey\nlocal-user admin password irreversible-cipher abc"
    redacted = agent_tools._redact_output(raw)
    assert "MySharedKey" not in redacted


@pytest.mark.asyncio
async def test_audit_tool_is_best_effort(monkeypatch):
    """审计失败不能影响工具结果。"""

    class _BadDb:
        pass

    async def boom(*args, **kwargs):
        raise RuntimeError("audit down")

    monkeypatch.setattr("modules.auth.service.AuditService.log", boom)
    await agent_tools._audit_tool(_BadDb(), 1, "ai_display_command", {"device_id": 1})


@pytest.mark.asyncio
async def test_audit_tool_skips_without_user():
    assert await agent_tools._audit_tool(None, None, "x", {}) is None


@pytest.mark.asyncio
async def test_execute_tool_passes_user_id_to_display_command(monkeypatch):
    """user_id 必须传进设备命令工具，否则 AI 触发的命令不会留审计。"""
    captured = {}

    async def fake_display(db, args, user_id=None):
        captured["user_id"] = user_id
        return "ok"

    monkeypatch.setattr(agent_tools, "_run_display_command", fake_display)
    await execute_tool(authenticated_db(), "run_display_command", {}, user_id=42)
    assert captured["user_id"] == 42
