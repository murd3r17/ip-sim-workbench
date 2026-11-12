"""All devices and database access in this suite are local fakes."""
import json
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from scripts import verify_live_readonly as probe


def targets():
    return [probe.ExpectedTarget(i, f"R{i}", "192.0.2.10", 2200 + i) for i in (1, 2, 3)]


def devices():
    return [SimpleNamespace(id=t.device_id, hostname=t.hostname, mgmt_ip=t.host,
                            ssh_port=t.port) for t in targets()]


def output(command, hostname):
    return {
        "display version": "Huawei Versatile Routing Platform\nVRP software, Version 8.241",
        "display current-configuration": f"sysname {hostname}\n#\ninterface LoopBack0\n description existing\n#\nreturn",
        "display interface brief": "Interface PHY Protocol InUti OutUti\nLoopBack0 up up(s) 0% 0%",
        "display lldp neighbor brief": "Local Intf Neighbor Dev Neighbor Intf Exptime(s)\nGE0/0/1 R2 GE0/0/2 100",
    }[command]


@pytest.mark.parametrize("url,mode", [("sqlite+aiosqlite:///:memory:", "ssh"),
                                     ("mysql+aiomysql://u:p@localhost/db", "sim"),
                                     ("mysql+aiomysql://u:p@localhost/db", "other")])
def test_real_runtime_guard(url, mode):
    with pytest.raises(probe.ProbeRefused):
        probe.validate_runtime(url, mode, exclusive_window=True)


def test_requires_quiet_window_and_exact_three_unique_endpoints():
    with pytest.raises(probe.ProbeRefused):
        probe.validate_runtime("mysql+aiomysql://u:p@localhost/db", "ssh", exclusive_window=False)
    for expected in [targets()[:2], [targets()[0]] * 3]:
        with pytest.raises(probe.ProbeRefused):
            probe.validate_targets(devices(), expected)


@pytest.mark.parametrize("field,value", [("id", 91), ("hostname", "R-1"),
                                        ("mgmt_ip", "192.0.2.99"), ("ssh_port", 2299)])
def test_inventory_mismatch_fails_before_any_adapter(field, value):
    inventory = devices()
    setattr(inventory[0], field, value)
    with pytest.raises(probe.ProbeRefused):
        probe.validate_targets(inventory, targets())


@pytest.mark.asyncio
async def test_serial_adapter_commands_and_close_without_writes():
    events = []

    class Adapter:
        name = "ssh"

        def __init__(self, device):
            self.device = device
            events.append((device.id, "open"))

        async def run_command(self, command):
            events.append((self.device.id, command))
            return output(command, self.device.hostname)

        async def close(self):
            events.append((self.device.id, "close"))

    async def actual_async_factory(device):
        return Adapter(device)

    result = await probe.probe_devices(devices(), targets(), actual_async_factory)
    assert result["ok"] and len(result["devices"]) == 3
    assert events == [(i, command) for i in (1, 2, 3)
                      for command in ("open", *probe.COMMANDS, "close")]
    assert all(d["adapter"] == "ssh" and d["closed"] for d in result["devices"])


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["exception", "cli_error", "wrong_identity", "sim"])
async def test_failed_probe_closes_and_stops_without_leaking(kind):
    marker = Fernet.generate_key().decode()
    opened, closed = [], []

    class Adapter:
        name = "sim" if kind == "sim" else "ssh"

        def __init__(self, device):
            self.device = device
            opened.append(device.id)

        async def run_command(self, command):
            if kind == "exception":
                raise RuntimeError(marker)
            if kind == "cli_error":
                return "Error: Unrecognized command " + marker
            return output(command, "WRONG" if kind == "wrong_identity" else self.device.hostname)

        async def close(self):
            closed.append(self.device.id)

    result = await probe.probe_devices(devices(), targets(), Adapter)
    assert not result["ok"]
    assert opened == closed == [1]
    assert marker not in json.dumps(result)


@pytest.mark.asyncio
async def test_write_lock_refused_before_adapter():
    async def locked(device_id):
        return True

    def must_not_open(device):
        pytest.fail("locked device must not connect")

    result = await probe.probe_devices(devices(), targets(), must_not_open, is_locked=locked)
    assert not result["ok"]
    assert result["devices"][0]["reason"] == "device_write_locked"


def test_prompt_and_truncated_outputs_are_not_success():
    for command in probe.COMMANDS:
        with pytest.raises(probe.ProbeRefused):
            probe.summarize_output(command, "<R1>", "R1")
    with pytest.raises(probe.ProbeRefused):
        probe.summarize_output("display current-configuration", "sysname R1\ninterface LoopBack0", "R1")


def test_redacted_hash_does_not_depend_on_secret_and_snapshot_is_encrypted(tmp_path):
    key = Fernet.generate_key()
    marker = Fernet.generate_key().decode()
    text = output("display current-configuration", "R1").replace("#\nreturn", f"local-user x password cipher {marker}\n#\nreturn")
    summary = probe.summarize_output("display current-configuration", text, "R1")
    other = probe.summarize_output("display current-configuration", text.replace(marker, "different"), "R1")
    assert summary["redacted_sha256"] == other["redacted_sha256"]
    path = probe.save_encrypted_snapshot(tmp_path, "run1", devices()[0], text, Fernet(key))
    assert marker not in path.read_text()
    payload = json.loads(Fernet(key).decrypt(path.read_bytes()))
    assert payload["configuration"] == text and payload["device_id"] == 1
    with pytest.raises(FileExistsError):
        probe.save_encrypted_snapshot(tmp_path, "run1", devices()[0], text, Fernet(key))


def test_lldp_zero_neighbor_header_is_valid_read_not_topology_acceptance():
    result = probe.summarize_output("display lldp neighbor brief", "Local Intf Neighbor Dev Neighbor Intf Exptime(s)", "R1")
    assert result["neighbor_count"] == 0


@pytest.mark.asyncio
async def test_lldp_disabled_collects_remaining_baselines_but_still_fails():
    visited = []

    class Adapter:
        name = "ssh"

        def __init__(self, device):
            self.device = device

        async def run_command(self, command):
            visited.append((self.device.id, command))
            if command == "display lldp neighbor brief":
                return "Error: Global LLDP is not enabled."
            return output(command, self.device.hostname)

        async def close(self):
            pass

    result = await probe.probe_devices(devices(), targets(), Adapter)
    assert not result["ok"] and result["core_readonly_ok"]
    assert len(result["devices"]) == 3 and len(visited) == 12
    assert all(item["reason"] == "lldp_disabled" and item["closed"] for item in result["devices"])
    assert all(item["commands"][-1]["ok"] is False for item in result["devices"])


@pytest.mark.asyncio
@pytest.mark.parametrize("equal", [True, False])
async def test_optional_saved_configuration_is_encrypted_and_compared(tmp_path, equal):
    cipher = Fernet(Fernet.generate_key())

    class Adapter:
        name = "ssh"

        def __init__(self, device):
            self.device = device

        async def run_command(self, command):
            if command == "display saved-configuration":
                text = output("display current-configuration", self.device.hostname)
                return text if equal else text.replace("description existing", "description older")
            return output(command, self.device.hostname)

        async def close(self):
            pass

    result = await probe.probe_devices(devices(), targets(), Adapter, capture_saved=True,
                                       snapshot_dir=tmp_path, cipher=cipher)
    assert result["ok"] is equal and result["running_saved_equivalent"] is equal
    assert len(result["devices"]) == 3
    for device in result["devices"]:
        payload = json.loads(cipher.decrypt((tmp_path / device["encrypted_saved_snapshot"]).read_bytes()))
        assert payload["configuration_type"] == "saved"
        assert "configuration" in payload
