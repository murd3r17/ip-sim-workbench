"""Only the observed global-LLDP warning may be acknowledged after preflight."""
import asyncio
import re
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from engines import netmiko_exec as module
from engines.device_adapter import SSHDeviceAdapter

WARNING = "Warning: This command will delete the configurations of LLDP on all the ports. Continue? [Y/N]:"
VERSION = "Huawei VRP (R) software, Version 8.241 (NE40E-X16 V800R024)"
CONFIG = "sysname R3\n#\ninterface LoopBack0\n description probe\n#\nreturn"


def driver(monkeypatch, response):
    fake = object.__new__(module.SafeHuaweiVrpv8SSH)
    fake.base_prompt = "R3"
    fake.config_mode = Mock(return_value="[~R3]")
    fake._send_command_str = Mock(return_value="Y\n[*R3]")
    fake.exit_config_mode = Mock(return_value="<R3>")
    send = Mock(return_value=response)
    monkeypatch.setattr(module.HuaweiVrpv8SSH, "send_config_set", send)
    return fake, send


def test_exact_warning_requires_preflight_authorization_and_sends_one_y(monkeypatch):
    fake, send = driver(monkeypatch, "undo lldp enable\n" + WARNING)
    fake.send_config_set(["undo lldp enable"], allow_lldp_disable_confirmation=True)
    assert fake._send_command_str.call_args.args == ("Y",)
    assert fake._send_command_str.call_count == 1
    assert send.call_count == 1


@pytest.mark.parametrize("entry_output", [
    "[~R3]",
    "system-view\nWarning: The slave board is not in position. Exercise caution when performing this operation.\n"
    "Enter system view, return user view with return command.\n[~R3]",
])
def test_real_netmiko_command_loop_recognizes_warning_then_continues_in_order(entry_output):
    fake = object.__new__(module.SafeHuaweiVrpv8SSH)
    fake.base_prompt, fake.global_cmd_verify = "R3", None
    fake.fast_cli, fake._legacy_mode = False, False
    fake.select_delay_factor = lambda _: 0
    fake.config_mode = lambda: entry_output
    fake.normalize_cmd = lambda command: command + "\n"
    fake._sanitize_output = lambda value: value
    writes, reads = [], []
    fake.write_channel = lambda command: writes.append(command.strip())

    def read(**kwargs):
        pattern = kwargs["pattern"]
        reads.append(pattern)
        command = writes[-1]
        if pattern == re.escape(command):
            return command + "\n"
        output = WARNING if command == "undo lldp enable" else "[*R3-LoopBack0]"
        assert re.search(pattern, output, kwargs.get("re_flags", 0)), "Netmiko must stop at the observed warning"
        return output

    def acknowledge(command, **kwargs):
        writes.append(command)
        assert re.search(kwargs["expect_string"], "[*R3]")
        return "Y\n[*R3]"

    fake.read_until_pattern = read
    fake._send_command_str = acknowledge
    fake.send_config_set(["undo lldp enable", "interface loopback0", "undo description"],
                         allow_lldp_disable_confirmation=True, read_timeout=1)
    assert writes == ["undo lldp enable", "Y", "interface loopback0", "undo description"]


@pytest.mark.parametrize("reply", ["Continue? [Y/N]:", "Error: rejected\n[*R3]", "[*OTHER]"])
def test_confirmation_error_or_repeated_prompt_never_gets_second_y(monkeypatch, reply):
    fake, send = driver(monkeypatch, "undo lldp enable\n" + WARNING)
    fake._send_command_str.return_value = reply
    with pytest.raises(ValueError):
        fake.send_config_set(["undo lldp enable", "interface loopback0"], allow_lldp_disable_confirmation=True)
    assert fake._send_command_str.call_count == 1
    assert send.call_count == 1


@pytest.mark.parametrize("command,prompt,authorized", [
    ("undo lldp enable", WARNING, False),
    ("undo description", WARNING, True),
    ("undo lldp enable", "Warning: Delete all configuration? Continue? [Y/N]:", True),
    ("undo lldp enable", WARNING.replace("all the ports", "the device"), True),
])
def test_other_commands_or_prompts_never_get_an_automatic_answer(monkeypatch, command, prompt, authorized):
    fake, _ = driver(monkeypatch, command + "\n" + prompt)
    with pytest.raises(ValueError, match="confirmation"):
        fake.send_config_set([command], allow_lldp_disable_confirmation=authorized)
    fake._send_command_str.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("line", ["lldp enable", "undo lldp enable", "lldp tlv-enable basic-tlv port-description"])
async def test_interface_lldp_prevents_any_configuration_write(line):
    executor = module.NetmikoExecutor("192.0.2.1", "fixture", "", device_model="NE40E-X16")
    config = CONFIG.replace(" description probe", " description probe\n " + line)
    executor._device = SimpleNamespace(send_command=Mock(side_effect=[VERSION, config]), send_config_set=Mock(), commit=Mock())
    with pytest.raises(ValueError, match="interface.*LLDP"):
        await executor.send_config_set(["undo lldp enable", "interface loopback0", "undo description"])
    executor._device.send_config_set.assert_not_called()
    executor._device.commit.assert_not_called()


@pytest.mark.asyncio
async def test_cancellation_while_waiting_for_warning_never_answers_and_closes_after_settle(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    fake, send = driver(monkeypatch, "")

    def blocked(*args, **kwargs):
        entered.set()
        release.wait(2)
        return "undo lldp enable\n" + WARNING

    send.side_effect = blocked
    fake.send_command = Mock(side_effect=[VERSION, CONFIG])
    fake.disconnect = Mock()
    fake.commit = Mock()
    executor = module.NetmikoExecutor("192.0.2.83", "fixture", "", port=2283, device_model="NE40E-X16")
    executor._device = fake
    adapter = SSHDeviceAdapter("192.0.2.83", "fixture", "", port=2283)
    adapter._executor = executor

    async def run():
        try:
            await adapter.send_config(["undo lldp enable", "interface loopback0", "undo description"])
        finally:
            await adapter.close()

    task = asyncio.create_task(run())
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done()
        fake.disconnect.assert_not_called()
    finally:
        release.set()
        result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    fake._send_command_str.assert_not_called()
    fake.commit.assert_not_called()
    fake.disconnect.assert_called_once()
