"""Bounded restoration refuses changes without a known inverse before writing."""
import pytest

from modules.deploy.config_verifier import ConfigVerifier


def test_restore_replaces_sysname_and_removes_an_added_loopback():
    current = "sysname AFTER\n#\ninterface LoopBack9\n description temporary\n ip address 192.0.2.9 255.255.255.255"
    commands = ConfigVerifier.build_restore_commands(current, "sysname BEFORE")
    assert "sysname BEFORE" in commands
    assert "undo interface loopback9" in commands
    assert "description temporary" not in commands


def test_restore_removes_old_address_before_applying_target_address():
    current = "interface GigabitEthernet0/0/1\n ip address 192.0.2.2 255.255.255.0\n description temporary"
    target = "interface GigabitEthernet0/0/1\n ip address 192.0.2.1 255.255.255.0"
    commands = ConfigVerifier.build_restore_commands(current, target)
    assert commands.index("undo ip address 192.0.2.2 255.255.255.0") < commands.index("ip address 192.0.2.1 255.255.255.0")
    assert "undo description" in commands


def test_unknown_unchanged_configuration_is_not_replayed():
    shared = "#\nssh server cipher aes256_ctr\n#\ninterface GigabitEthernet0/0/1\n mtu 9000"
    assert ConfigVerifier.build_restore_commands("sysname AFTER\n" + shared, "sysname BEFORE\n" + shared) == ["sysname BEFORE"]


@pytest.mark.parametrize(("current", "target"), [
    ("ssh server cipher aes256_ctr", "ssh server cipher aes128_ctr"),
    ("interface GigabitEthernet0/0/1\n mtu 9000", "interface GigabitEthernet0/0/1\n mtu 1500"),
    ("interface GigabitEthernet0/0/1", ""),
    ("ospf 1\n area 0.0.0.0\n network 192.0.2.0 0.0.0.255", "ospf 1"),
    ("interface GigabitEthernet0/0/1\n undo portswitch", "interface GigabitEthernet0/0/1"),
    ("interface GigabitEthernet0/0/1", "interface GigabitEthernet0/0/1\n undo portswitch"),
])
def test_unknown_or_destructive_inverse_is_refused(current, target):
    with pytest.raises(ValueError, match="暂不支持自动恢复"):
        ConfigVerifier.build_restore_commands(current, target)


def test_identical_snapshot_needs_no_commands():
    assert ConfigVerifier.build_restore_commands("sysname R1", "sysname R1") == []
