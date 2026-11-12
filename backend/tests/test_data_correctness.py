"""数据正确性回归测试（2026-09-09 审计批次 3）。

覆盖：下发白名单真实校验、风险二次确认、回滚破坏性命令检查、接口状态解析、
采集失败计数、评分对 null 命令的健壮性。
这些用例此前要么没有，要么断言的是缺陷行为。
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.deploy.service import DeployService
from modules.deploy.vrp_validator import VRPValidator
from modules.monitor.service import MetricCollector, MonitorService
from modules.training.service import TrainingService


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDB:
    def __init__(self, baseline):
        self._baseline = baseline

    async def execute(self, *args, **kwargs):
        return _FakeResult(self._baseline)


def _settings(**overrides):
    base = dict(
        deploy_allowlist_device_ids="7,8,9",
        deploy_allowlist_mgmt_ips="192.0.2.10",
        deploy_allowlist_topology_id=3,
        deploy_allowlist_baseline_version=3,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _device(**overrides):
    base = dict(id=7, hostname="R1", mgmt_ip="192.0.2.10", ssh_port=20123, topology_id=3)
    base.update(overrides)
    return SimpleNamespace(**base)


def _baseline(hostnames=("R1", "R2", "R3")):
    """三台设备共用管理 IP、以不同 ssh_port 区分（真实 eNSP 端口映射形态）。"""
    import json
    ports = {"R1": 20123, "R2": 20124, "R3": 20125}
    devices = [
        {"id": {"R1": 7, "R2": 8, "R3": 9}.get(name, 99),
         "hostname": name, "mgmt_ip": "192.0.2.10", "ssh_port": ports.get(name, 20123)}
        for name in hostnames
    ]
    return SimpleNamespace(snapshot_json=json.dumps({"devices": devices, "links": []}))


class TestDeployAllowlist:
    """P0-27：白名单 baseline 分支此前两条路径都 return True（死逻辑）。"""

    @pytest.mark.asyncio
    async def test_allowlisted_device_in_baseline_passes(self, monkeypatch):
        from modules.deploy import service as deploy_service
        monkeypatch.setattr(deploy_service, "get_settings", lambda: _settings())
        assert await DeployService._is_authorized_stage4_target(_FakeDB(_baseline()), _device()) is True

    @pytest.mark.asyncio
    async def test_device_outside_allow_ids_is_rejected(self, monkeypatch):
        from modules.deploy import service as deploy_service
        monkeypatch.setattr(deploy_service, "get_settings", lambda: _settings())
        assert await DeployService._is_authorized_stage4_target(_FakeDB(_baseline()), _device(id=99)) is False

    @pytest.mark.asyncio
    async def test_device_in_wrong_topology_is_rejected(self, monkeypatch):
        from modules.deploy import service as deploy_service
        monkeypatch.setattr(deploy_service, "get_settings", lambda: _settings())
        assert await DeployService._is_authorized_stage4_target(_FakeDB(_baseline()), _device(topology_id=2)) is False

    @pytest.mark.asyncio
    async def test_device_absent_from_baseline_snapshot_is_rejected(self, monkeypatch):
        from modules.deploy import service as deploy_service
        monkeypatch.setattr(deploy_service, "get_settings", lambda: _settings())
        # 基线存在但不含 R1 → 必须拒绝（旧实现恒 True）
        assert await DeployService._is_authorized_stage4_target(
            _FakeDB(_baseline(hostnames=("R2", "R3"))), _device()
        ) is False

    @pytest.mark.asyncio
    async def test_missing_baseline_is_rejected(self, monkeypatch):
        from modules.deploy import service as deploy_service
        monkeypatch.setattr(deploy_service, "get_settings", lambda: _settings())
        assert await DeployService._is_authorized_stage4_target(_FakeDB(None), _device()) is False

    @pytest.mark.asyncio
    async def test_no_device_is_rejected(self, monkeypatch):
        from modules.deploy import service as deploy_service
        monkeypatch.setattr(deploy_service, "get_settings", lambda: _settings())
        assert await DeployService._is_authorized_stage4_target(_FakeDB(_baseline()), None) is False


class TestRiskConfirmation:
    """P0-28：requires_confirmation 此前硬编码 False，二次确认流程不可达。"""

    def test_ospf_command_requires_second_confirmation(self):
        report = VRPValidator().assess("ospf 1", "NE40E")
        assert report["valid"] is True
        assert report["requires_confirmation"] is True

    def test_plain_interface_config_needs_no_second_confirmation(self):
        report = VRPValidator().assess(
            "interface GigabitEthernet0/0/1\nip address 10.0.0.1 255.255.255.0", "NE40E"
        )
        assert report["valid"] is True
        assert report["requires_confirmation"] is False


class TestRollbackSafety:
    """P0-18：回滚整机重放前必须拦破坏性命令，但正常运行配置行不能被误拦。"""

    def test_destructive_commands_are_detected(self):
        assert VRPValidator.check_rollback_safe("sysname R1\nreset saved-configuration")
        assert VRPValidator.check_rollback_safe("format flash:")
        assert VRPValidator.check_rollback_safe("undo startup saved-configuration")

    def test_normal_running_config_passes(self):
        config = "\n".join([
            "sysname R1",
            "interface GigabitEthernet0/0/1",
            " shutdown",
            " undo shutdown",
            " ip address 10.0.0.1 255.255.255.0",
            "ospf 1",
            " area 0.0.0.0",
        ])
        assert VRPValidator.check_rollback_safe(config) == []


class TestInterfaceParsing:
    """P0-33：接口统计此前用子串匹配，描述里的 up 也会被计入。"""

    def test_vrp_table_counts_only_status_columns(self):
        output = "\n".join([
            "Interface                        PHY   Protocol  InUti OutUti   inErrors  outErrors",
            "GigabitEthernet0/0/0             up    up        0.01%  0.01%          0          0",
            "GigabitEthernet0/0/1             up    down      0.00%  0.00%          0          0",
            "GigabitEthernet0/0/2             down  down      0.00%  0.00%          0          0",
            "GigabitEthernet0/0/3             *down down      0.00%  0.00%          0          0",
            "Info: The max number of interfaces is 256",
        ])
        stats = MetricCollector._parse_interfaces(output)
        assert stats["interface_up"]["value"] == 1
        assert stats["interface_down"]["value"] == 3

    def test_description_containing_up_is_not_counted(self):
        output = "GigabitEthernet0/0/1 up up description linkup-to-core"
        stats = MetricCollector._parse_interfaces(output)
        assert stats["interface_up"]["value"] == 1

    def test_two_column_output_still_supported(self):
        stats = MetricCollector._parse_interfaces("GE0/0/1 Up\nGE0/0/2 Down")
        assert stats["interface_up"]["value"] == 1
        assert stats["interface_down"]["value"] == 1


class TestCollectorStatus:
    """P0-30：采集失败此前返回 False 并被计成 skipped，job 状态恒 SUCCESS。"""

    @pytest.mark.asyncio
    async def test_exception_reports_failed(self, monkeypatch):
        collector = MetricCollector(AsyncMock())

        async def boom(device):
            raise RuntimeError("ssh down")

        monkeypatch.setattr(collector, "_collect_via_ssh", boom)
        assert await collector._collect_single_device(_device()) == "failed"

    @pytest.mark.asyncio
    async def test_timeout_reports_timeout(self, monkeypatch):
        collector = MetricCollector(AsyncMock())
        collector.settings.monitor_device_timeout = 0.01

        async def slow(device):
            import asyncio
            await asyncio.sleep(0.5)

        monkeypatch.setattr(collector, "_collect_via_ssh", slow)
        assert await collector._collect_single_device(_device()) == "timeout"

    @pytest.mark.asyncio
    async def test_success_reports_success(self, monkeypatch):
        collector = MetricCollector(AsyncMock())

        async def ok(device):
            return {"cpu_usage": {"value": 10.0, "unit": "%"}}

        monkeypatch.setattr(collector, "_collect_via_ssh", ok)
        monkeypatch.setattr(collector, "_save_metrics", AsyncMock())
        assert await collector._collect_single_device(_device()) == "success"


class TestL2ProtocolMetric:
    """P0-33：L2 设备拿到的是 display stp brief，不应再产出 ospf_neighbor_count。"""

    def test_switch_l2_profile_uses_stp(self):
        profile = MonitorService.build_command_profile(
            SimpleNamespace(device_type=SimpleNamespace(value="switch_l2"))
        )
        assert "ospf" not in profile["protocol"]

    def test_router_profile_uses_ospf(self):
        profile = MonitorService.build_command_profile(
            SimpleNamespace(device_type=SimpleNamespace(value="router"))
        )
        assert "ospf" in profile["protocol"]


class _FakeCommandAdapter:
    def __init__(self, temperature_output):
        self._temperature_output = temperature_output
        self.closed = False

    async def run_command(self, command: str, timeout=None) -> str:
        if "temperature" in command:
            if isinstance(self._temperature_output, Exception):
                raise self._temperature_output
            return self._temperature_output
        if "cpu-usage" in command:
            return "CPU Usage: 30%"
        if "memory-usage" in command:
            return "Memory Using Percentage: 40%"
        if "interface brief" in command:
            return "GigabitEthernet0/0/0   up    up   0.01%  0.01%  0  0"
        return ""

    async def close(self) -> None:
        self.closed = True


class TestTemperatureMetric:
    """P2-10：temperature 指标此前没有任何写入点（枚举成员是死字段）。"""

    @staticmethod
    def _patch_adapter(monkeypatch, adapter):
        async def fake_get_adapter(device):
            return adapter

        monkeypatch.setattr("engines.device_adapter.get_device_adapter", fake_get_adapter)

    @pytest.mark.asyncio
    async def test_collect_emits_temperature_metric(self, monkeypatch):
        adapter = _FakeCommandAdapter(
            "Board 1:\n  Current temperature: 41.5 degrees Celsius\n"
        )
        self._patch_adapter(monkeypatch, adapter)
        collector = MetricCollector(AsyncMock())
        device = _device(device_type=SimpleNamespace(value="router"))

        metrics = await collector._collect_via_ssh(device)

        assert metrics["temperature"] == {"value": 41.5, "unit": "°C"}
        assert adapter.closed is True

    @pytest.mark.asyncio
    async def test_unsupported_temperature_does_not_break_other_metrics(self, monkeypatch):
        adapter = _FakeCommandAdapter(RuntimeError("Unrecognized command"))
        self._patch_adapter(monkeypatch, adapter)
        collector = MetricCollector(AsyncMock())
        device = _device(device_type=SimpleNamespace(value="router"))

        metrics = await collector._collect_via_ssh(device)

        assert "temperature" not in metrics
        assert metrics["cpu_usage"]["value"] == 30.0
        assert metrics["memory_usage"]["value"] == 40.0


class TestScoreRobustness:
    """P0-32：command 为 null 时 `.startswith` 抛 AttributeError → /score 500。"""

    def test_null_command_does_not_crash(self):
        import json
        log = "\n".join([
            json.dumps({"command": None, "action": "note"}),
            json.dumps({"command": "undo sysname", "action": "run"}),
            json.dumps({"command": "display version", "action": "run"}),
        ])
        score = TrainingService._analyze_command_quality(log)
        assert 0.0 <= score <= 100.0

    def test_repeated_commands_with_null_are_safe(self):
        import json
        commands = [{"command": None}, {"command": None}, {"command": "display version"}]
        assert TrainingService._find_repeated_commands(commands) == 0
