"""MetricCollector解析方法测试"""
import pytest
from modules.monitor.service import MetricCollector


class TestParseCpu:
    def test_parse_cpu_standard_output(self):
        output = "CPU Usage: 45%"
        assert MetricCollector._parse_cpu(output) == 45.0

    def test_parse_cpu_with_whitespace(self):
        output = "CPU  Usage  :  72.5%"
        assert MetricCollector._parse_cpu(output) == 72.5

    def test_parse_cpu_max_format(self):
        output = "Max CPU Usage: 88%"
        assert MetricCollector._parse_cpu(output) == 88.0

    def test_parse_cpu_no_match(self):
        output = "No CPU info here"
        assert MetricCollector._parse_cpu(output) is None

    def test_parse_cpu_empty_string(self):
        assert MetricCollector._parse_cpu("") is None


class TestParseMemory:
    def test_parse_memory_percentage_format(self):
        output = "Memory Using Percentage: 65%"
        assert MetricCollector._parse_memory(output) == 65.0

    def test_parse_memory_used_total_format(self):
        output = "Used: 2048 MB\nTotal: 4096 MB"
        assert MetricCollector._parse_memory(output) == 50.0

    def test_parse_memory_used_total_rounding(self):
        output = "Used: 1024 MB\nTotal: 3072 MB"
        result = MetricCollector._parse_memory(output)
        assert result == round(1024 / 3072 * 100, 2)

    def test_parse_memory_no_match(self):
        output = "No memory info"
        assert MetricCollector._parse_memory(output) is None

    def test_parse_memory_zero_total(self):
        output = "Used: 0 MB\nTotal: 0 MB"
        assert MetricCollector._parse_memory(output) is None


class TestParseInterfaces:
    def test_parse_interfaces_mixed(self):
        output = "Interface          Status\nGE0/0/1            Up\nGE0/0/2            Down\nGE0/0/3            Up"
        stats = MetricCollector._parse_interfaces(output)
        assert stats["interface_up"]["value"] == 2
        assert stats["interface_down"]["value"] == 1

    def test_parse_interfaces_all_up(self):
        output = "GE0/0/1 Up\nGE0/0/2 Up"
        stats = MetricCollector._parse_interfaces(output)
        assert stats["interface_up"]["value"] == 2
        assert stats["interface_down"]["value"] == 0

    def test_parse_interfaces_empty(self):
        stats = MetricCollector._parse_interfaces("")
        assert stats == {}


class TestParseOspfNeighbors:
    def test_parse_ospf_full_neighbors(self):
        output = "Area Id  State\n0.0.0.0  Full\n0.0.0.0  Full\n0.0.0.0  2-Way"
        assert MetricCollector._parse_ospf_neighbors(output) == 3

    def test_parse_ospf_no_neighbors(self):
        output = "Area Id  State\n0.0.0.0  Init"
        assert MetricCollector._parse_ospf_neighbors(output) == 0

    def test_parse_ospf_empty(self):
        assert MetricCollector._parse_ospf_neighbors("") is None


class TestParseTemperature:
    """P2-10：temperature 指标此前没有任何写入点。"""

    def test_parse_single_board(self):
        output = (
            "<R1>display temperature\n"
            "Board 1:\n"
            "  Current temperature: 41.5 degrees Celsius\n"
            "  Highest temperature: 45.2 degrees Celsius\n"
            "  Lowest temperature:  38.0 degrees Celsius\n"
            "  Board temperature is OK\n"
        )
        assert MetricCollector._parse_temperature(output) == 41.5

    def test_parse_takes_hottest_board(self):
        output = (
            "Board 1:\n  Current temperature: 41.5 degrees Celsius\n"
            "Board 2:\n  Current temperature: 52.0 degrees Celsius\n"
        )
        assert MetricCollector._parse_temperature(output) == 52.0

    def test_unsupported_command_returns_none_instead_of_zero(self):
        """采集不到时必须返回 None（跳过该指标），不能写成 0 度。"""
        assert MetricCollector._parse_temperature("Error: Unrecognized command") is None
        assert MetricCollector._parse_temperature("") is None
        assert MetricCollector._parse_temperature(None) is None
