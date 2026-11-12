"""agent_tools 只读白名单 + 脱敏的回归测试。

背景（2026-09-09 审计）：`is_readonly_command` 此前不拦换行，实测
`is_readonly_command("display version\\nreset saved-configuration")` 返回 True，
经 `adapter.run_command` → netmiko `send_command` 原样下发，等于让 AI 对真实设备
执行任意 VRP 命令。本文件把该缺陷固化为回归用例（此前该模块 0 覆盖）。
"""
import pytest

from modules.ai_text.agent_tools import is_readonly_command
from modules.ai_text.llm_service import redact_sensitive


class TestReadonlyCommandWhitelist:
    @pytest.mark.parametrize(
        "cmd",
        [
            # 换行/回车/制表符注入（历史缺陷）
            "display version\nreset saved-configuration",
            "display version\r\nundo sysname R1",
            "display version\treboot",
            # 命令分隔与 shell 元字符
            "display version; reboot",
            "display version | include x",
            "display version && reboot",
            "display version `reboot`",
            "display version > flash:/x.txt",
            "display version < input",
            # 前缀混淆
            "display versionX",
            # 非白名单命令
            "reboot",
            "system-view",
            "reset saved-configuration",
            # 空与超长
            "",
            "display version " + "x" * 300,
        ],
    )
    def test_rejects_injection_and_non_whitelisted(self, cmd: str) -> None:
        assert is_readonly_command(cmd) is False

    @pytest.mark.parametrize(
        "cmd",
        [
            "display version",
            "DISPLAY VERSION",
            "display clock",
            "display interface brief",
            "display interface brief GigabitEthernet0/0/1",
            "display ospf peer brief",
            "display ospf peer",
            "display current-configuration configuration ospf",
            "display  version",  # 多重空白归一化后仍合法
            "  display version  ",
        ],
    )
    def test_allows_whitelisted_commands(self, cmd: str) -> None:
        assert is_readonly_command(cmd) is True


class TestRedactSensitive:
    @pytest.mark.parametrize(
        ("text", "leak"),
        [
            ("local-user admin password irreversible-cipher %^%#abc%^%#", "%^%#abc%^%#"),
            ("snmp-agent community read cipher %^%#xyz%^%#", "%^%#xyz%^%#"),
            ("snmp-agent community read public", "public"),
            ("radius-server shared-key cipher Huawei@123", "Huawei@123"),
            ("ike peer p1 pre-shared-key Huawei@123", "Huawei@123"),
            ("peer 1.1.1.1 password simple Passw0rd", "Passw0rd"),
            ("password: secret123", "secret123"),
        ],
    )
    def test_secrets_are_masked(self, text: str, leak: str) -> None:
        out = redact_sensitive(text)
        assert "******" in out, out
        assert leak not in out, out

    @pytest.mark.parametrize(
        "text",
        [
            "ospf 1 area 0.0.0.0",
            "public-key local create rsa",  # 不应把 public-key 里的 key 当密钥关键字
            "interface GigabitEthernet0/0/1",
            "ip route-static 0.0.0.0 0.0.0.0 192.168.1.1",
        ],
    )
    def test_non_secret_lines_untouched(self, text: str) -> None:
        assert redact_sensitive(text) == text
