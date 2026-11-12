"""No network: security prompts and target evidence use local fakes only."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from netmiko.huawei.huawei import HuaweiSSH

from engines import netmiko_exec
from modules.deploy.service import DeployService


@pytest.mark.parametrize("after_password", [False, True])
def test_security_repair_prompt_never_accepted(after_password):
    risky = "There are security risks in the configuration file. Save now? [y/n]"
    fake = SimpleNamespace(prompt_or_password_change=HuaweiSSH.prompt_or_password_change,
                           password_change_prompt=HuaweiSSH.password_change_prompt,
                           prompt_pattern=HuaweiSSH.prompt_pattern, RETURN="\n",
                           read_until_pattern=Mock(side_effect=["Change now", risky] if after_password else [risky]),
                           write_channel=Mock(), send_command=Mock(), remote_conn=Mock(), remote_conn_pre=Mock())
    driver = getattr(netmiko_exec, "SafeHuaweiSSH", HuaweiSSH)
    with pytest.raises(RuntimeError, match="manual.*configuration|configuration.*manual"):
        driver.special_login_handler(fake)
    fake.send_command.assert_not_called()
    assert all(call.args == ("N\n",) for call in fake.write_channel.call_args_list)
    fake.remote_conn.close.assert_called_once_with()
    fake.remote_conn_pre.close.assert_called_once_with()


def test_password_change_is_declined_and_normal_prompt_is_read():
    fake = SimpleNamespace(prompt_or_password_change=HuaweiSSH.prompt_or_password_change,
                           password_change_prompt=HuaweiSSH.password_change_prompt,
                           prompt_pattern=HuaweiSSH.prompt_pattern, RETURN="\n",
                           read_until_pattern=Mock(side_effect=["Change now", "<R1>"]),
                           write_channel=Mock(), send_command=Mock())
    driver = getattr(netmiko_exec, "SafeHuaweiSSH", HuaweiSSH)
    driver.special_login_handler(fake)
    fake.write_channel.assert_called_once_with("N\n")
    fake.send_command.assert_not_called()


def device():
    return SimpleNamespace(id=7, hostname="R1", mgmt_ip="192.0.2.1", ssh_port=20123, topology_id=3)


def entry():
    return {"id": 7, "hostname": "R1", "mgmt_ip": "192.0.2.1", "ssh_port": 20123}


@pytest.mark.parametrize("snapshot", ["broken", "[]", "null", '{"devices": [null]}',
                                      json.dumps({"devices": [{"hostname": "R1"}]}),
                                      json.dumps({"devices": [{**entry(), "id": 8}]}),
                                      json.dumps({"devices": [{**entry(), "mgmt_ip": "192.0.2.2"}]}),
                                      json.dumps({"devices": [{**entry(), "ssh_port": 20124}]}),
                                      json.dumps({"devices": [{**entry(), "hostname": "R2"}]}),
                                      json.dumps({"devices": [{**entry(), "ssh_port": "bad"}]})])
def test_snapshot_requires_exact_complete_identity(snapshot):
    assert DeployService._device_in_snapshot(snapshot, device()) is False


def test_exact_snapshot_is_accepted():
    assert DeployService._device_in_snapshot(json.dumps({"devices": [entry()]}), device()) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("topology,version,baseline", [(3, 3, None), (0, 3, None), (3, 0, None)])
async def test_missing_baseline_or_baseline_selector_fails_closed(monkeypatch, topology, version, baseline):
    settings = SimpleNamespace(deploy_allowlist_device_ids="7", deploy_allowlist_mgmt_ips="192.0.2.1",
                               deploy_allowlist_topology_id=topology, deploy_allowlist_baseline_version=version)
    monkeypatch.setattr("modules.deploy.service.get_settings", lambda: settings)
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: baseline)))
    assert await DeployService._is_authorized_stage4_target(db, device()) is False


@pytest.mark.asyncio
async def test_executor_uses_safe_driver(monkeypatch):
    fake = Mock()
    driver = Mock(return_value=fake)
    monkeypatch.setattr(netmiko_exec, "SafeHuaweiSSH", driver)
    executor = netmiko_exec.NetmikoExecutor("192.0.2.1", "fixture-user", "", port=2201)
    await executor.connect()
    assert executor._device is fake
    assert driver.call_args.kwargs["host"] == "192.0.2.1"
    await executor.disconnect()
    fake.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_new_baseline_captures_execution_identity():
    from modules.device.baseline_service import TopologyBaselineService

    target = device()
    for key, value in {"device_type": SimpleNamespace(value="router"), "vendor": SimpleNamespace(value="huawei"),
                       "network_role": "core", "notes": None}.items():
        setattr(target, key, value)
    db = SimpleNamespace(execute=AsyncMock(side_effect=[
        SimpleNamespace(scalars=lambda: [target]), SimpleNamespace(scalars=lambda: [])]))
    snapshot = await TopologyBaselineService._snapshot(db, 3)
    assert snapshot["devices"][0]["id"] == target.id
    assert DeployService._device_in_snapshot(json.dumps(snapshot), target)
