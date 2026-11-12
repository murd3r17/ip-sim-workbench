"""Candidate configuration tests use a fake transport only."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from engines import netmiko_exec

VERSION = "Huawei VRP (R) software, Version 8.241 (NE40E-X16 V800R024C10SPC200B131)"


def executor():
    result = netmiko_exec.NetmikoExecutor("192.0.2.1", "fixture", "", device_model="NE40E-X16")
    result._device = Mock(send_command=Mock(return_value=VERSION),
                          send_config_set=Mock(return_value="[*R1-LoopBack0]"),
                          commit=Mock(return_value="[~R1]\n<R1>"),
                          save_config=Mock(return_value="Info: Save the configuration successfully."))
    return result


@pytest.mark.asyncio
async def test_actual_version_then_candidate_commit_and_separate_save():
    instance = executor()
    await instance.send_config_set(["system-view", "interface LoopBack0", "description probe", "quit", "return"])
    instance._device.send_command.assert_called_once_with("display version", read_timeout=instance.read_timeout)
    args = instance._device.send_config_set.call_args
    assert "system-view" not in args.args[0] and "return" not in args.args[0]
    assert args.kwargs["exit_config_mode"] is False
    instance._device.commit.assert_called_once()
    instance._device.save_config.assert_not_called()
    await instance.save_config()
    instance._device.save_config.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["", "Huawei VRP Version 5.170 (NE40E)", "Huawei VRP Version 8.241 (CE12800)"])
async def test_db_metadata_never_substitutes_for_actual_write_capability(version):
    instance = executor()
    instance._device.send_command.return_value = version
    with pytest.raises(ValueError, match="capability"):
        await instance.send_config_set(["lldp enable"])
    instance._device.send_config_set.assert_not_called()
    instance._device.commit.assert_not_called()
    instance._device.save_config.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["send", "commit", "save"])
async def test_each_write_stage_failure_is_explicit(failure):
    instance = executor()
    getattr(instance._device, {"send": "send_config_set", "commit": "commit", "save": "save_config"}[failure]).return_value = "Error: synthetic rejection"
    with pytest.raises(ValueError):
        await instance.send_config_set(["lldp enable"])
        await instance.save_config()
    if failure == "send":
        instance._device.commit.assert_not_called()
    if failure != "save":
        instance._device.save_config.assert_not_called()


@pytest.mark.asyncio
async def test_save_without_successful_commit_is_refused():
    instance = executor()
    with pytest.raises(ValueError):
        await instance.save_config()
    instance._device.save_config.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["commit", "save", "commit trial 60"])
async def test_payload_cannot_take_over_commit_or_save(command):
    instance = executor()
    with pytest.raises(ValueError):
        await instance.send_config_set([command])
    instance._device.send_config_set.assert_not_called()


def test_dirty_or_failed_commit_never_exits_candidate_view():
    driver = getattr(netmiko_exec, "SafeHuaweiVrpv8SSH", None)
    assert driver is not None
    for output in ["Error: rejected\n[*R1]", "[*R1]", "Failed to generate committed config\n[~R1]"]:
        fake = SimpleNamespace(config_mode=Mock(return_value="[*R1]"),
                               _send_command_str=Mock(return_value=output), exit_config_mode=Mock())
        with pytest.raises(ValueError):
            driver.commit(fake)
        fake.exit_config_mode.assert_not_called()


def test_vrp8_disconnect_never_sends_cli_cleanup_into_uncommitted_prompt():
    driver = getattr(netmiko_exec, "SafeHuaweiVrpv8SSH", None)
    assert driver is not None
    fake = SimpleNamespace(check_config_mode=Mock(), exit_config_mode=Mock(), write_channel=Mock())
    driver.cleanup(fake)
    fake.exit_config_mode.assert_not_called()
    fake.write_channel.assert_not_called()
