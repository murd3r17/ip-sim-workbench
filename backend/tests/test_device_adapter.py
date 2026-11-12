"""设备适配层（SSH/Sim）测试。"""
import pytest
from types import SimpleNamespace
from unittest.mock import patch

from engines.device_adapter import (
    SimDeviceAdapter, SSHDeviceAdapter, get_device_adapter, get_device_mode,
)


def _sim(hostname="R-1", neighbors=None) -> SimDeviceAdapter:
    return SimDeviceAdapter(hostname=hostname, neighbors=neighbors or ["R-2", "S-1"])


# ── Sim 回显与现有解析器兼容 ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_sim_cpu_output_parses():
    from modules.monitor.service import MetricCollector
    out = await _sim().run_command("display cpu-usage")
    value = MetricCollector._parse_cpu(out)
    assert value is not None and 0 < value <= 100


@pytest.mark.asyncio
async def test_sim_memory_output_parses():
    from modules.monitor.service import MetricCollector
    out = await _sim().run_command("display memory-usage")
    value = MetricCollector._parse_memory(out)
    assert value is not None and 0 < value <= 100


@pytest.mark.asyncio
async def test_sim_interface_output_parses():
    from modules.monitor.service import MetricCollector
    out = await _sim().run_command("display interface brief")
    stats = MetricCollector._parse_interfaces(out)
    assert stats["interface_up"]["value"] == 3
    assert stats["interface_down"]["value"] == 1


@pytest.mark.asyncio
async def test_sim_ospf_output_parses():
    from modules.monitor.service import MetricCollector
    out = await _sim().run_command("display ospf peer brief")
    assert MetricCollector._parse_ospf_neighbors(out) == 1


@pytest.mark.asyncio
async def test_sim_lldp_output_parses_and_uses_neighbor_context():
    from modules.device.lldp_parser import parse_lldp_neighbor_brief
    out = await _sim(neighbors=["R-2", "S-1"]).run_command("display lldp neighbor brief")
    neighbors = parse_lldp_neighbor_brief(out)
    assert [n["neighbor_device"] for n in neighbors] == ["R-2", "S-1"]


@pytest.mark.asyncio
async def test_sim_version_contains_hostname():
    out = await _sim("R-7").run_command("display version")
    assert "R-7" in out and "VRP" in out


@pytest.mark.asyncio
async def test_sim_current_config_contains_hostname_and_applied_config():
    adapter = _sim("R-1")
    base = await adapter.run_command("display current-configuration")
    assert "sysname R-1" in base
    await adapter.send_config(["interface GigabitEthernet0/0/5", "undo shutdown"])
    after = await adapter.run_command("display current-configuration")
    assert "GigabitEthernet0/0/5" in after


@pytest.mark.asyncio
async def test_sim_check_online_always_true():
    assert await _sim().check_online() is True


@pytest.mark.asyncio
async def test_sim_values_stable_per_hostname():
    a1, a2 = _sim("R-1"), _sim("R-1")
    out1, out2 = await a1.run_command("display cpu-usage"), await a2.run_command("display cpu-usage")
    assert out1 == out2


# ── 工厂与模式 ────────────────────────────────────────────────────────
def test_get_device_mode_defaults_to_ssh():
    with patch("engines.device_adapter.get_settings") as settings:
        settings.return_value.device_mode = ""
        assert get_device_mode() == "ssh"


@pytest.mark.asyncio
async def test_factory_returns_sim_in_sim_mode():
    with patch("engines.device_adapter.get_settings") as settings:
        settings.return_value.device_mode = "sim"
        adapter = await get_device_adapter(SimpleNamespace(hostname="R-1"))
        assert isinstance(adapter, SimDeviceAdapter)


@pytest.mark.asyncio
async def test_factory_returns_ssh_in_ssh_mode():
    device = SimpleNamespace(hostname="R-1", mgmt_ip="192.168.100.11", ssh_port=22)
    with patch("engines.device_adapter.get_settings") as settings, patch(
        "modules.device.service.DeviceService.get_device_credentials",
        return_value={"username": "u", "password": "p", "enable": ""},
    ):
        settings.return_value.device_mode = "ssh"
        settings.return_value.ssh_connect_timeout = 10
        adapter = await get_device_adapter(device)
        assert isinstance(adapter, SSHDeviceAdapter)
        assert adapter.host == "192.168.100.11"


# ── 健康检查 sim 分支：无凭据也视为在线 ───────────────────────────────
@pytest.mark.asyncio
async def test_check_device_health_sim_marks_online_without_credentials(test_session_factory):
    from modules.device.models import Device, DeviceStatus, DeviceType, Topology, TopologyType
    from modules.device.service import DeviceService

    async with test_session_factory() as db:
        topology = Topology(name="sim-topo", topology_type=TopologyType.LAB, status="active")
        db.add(topology)
        await db.flush()
        device = Device(
            hostname="sim-r1", mgmt_ip="192.168.100.11",
            device_type=DeviceType.ROUTER, status=DeviceStatus.UNKNOWN,
            topology_id=topology.id,
        )
        db.add(device)
        await db.commit()
        device_id = device.id

    async with test_session_factory() as db:
        with patch("engines.device_adapter.get_settings") as settings:
            settings.return_value.device_mode = "sim"
            result = await DeviceService.check_device_health(db, device_id)
        assert result["status"] == "online"


@pytest.mark.asyncio
async def test_device_lock_rejects_second_holder():
    from engines.device_lock import DeviceBusyError, acquire_device_lock
    async with acquire_device_lock("10.0.0.1", 22, timeout=0.2):
        with pytest.raises(DeviceBusyError, match="占用"):
            async with acquire_device_lock("10.0.0.1", 22, timeout=0.2):
                pass


@pytest.mark.asyncio
async def test_device_lock_allows_different_ports():
    from engines.device_lock import acquire_device_lock
    async with acquire_device_lock("10.0.0.1", 20123, timeout=0.2):
        async with acquire_device_lock("10.0.0.1", 20124, timeout=0.2):
            pass

# ── L2：完整命令归一，brief/detail 不互相遮蔽 ────────────────────────
@pytest.mark.asyncio
async def test_sim_ip_interface_brief_uses_address_output():
    out = await _sim().run_command("display ip interface brief")
    assert "IP Address" in out and "10.0.123.1/24" in out
    assert "PHY   Protocol  InUti" not in out


@pytest.mark.asyncio
async def test_sim_interface_brief_detail_kept_separate():
    out = await _sim().run_command("display interface brief")
    assert "InUti OutUti" in out


@pytest.mark.asyncio
async def test_sim_ospf_peer_full_vs_brief():
    full = await _sim().run_command("display ospf peer")
    brief = await _sim().run_command("display ospf peer brief")
    assert "State: Full" in full
    assert "display ospf peer brief" in brief


@pytest.mark.asyncio
async def test_sim_command_case_and_whitespace_normalized():
    out = await _sim().run_command("  DISPLAY   IP   INTERFACE   BRIEF ")
    assert "IP Address" in out
