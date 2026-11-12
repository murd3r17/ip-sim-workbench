"""配置回读差异比较测试。"""

from modules.deploy.config_verifier import ConfigVerifier


class TestNormalizeConfig:
    def test_basic_normalize(self):
        result = ConfigVerifier._normalize_config("sysname R1\ninterface GigabitEthernet0/0/1")
        assert result == {"sysname r1", "interface gigabitethernet0/0/1"}

    def test_skips_comments_empty_lines_and_watermarks(self):
        result = ConfigVerifier._normalize_config("# comment\n! comment\n# [SIM-ENV] tag\n\nsysname R1")
        assert result == {"sysname r1"}

    def test_normalizes_whitespace(self):
        assert ConfigVerifier._normalize_config("  sysname  R1  ") == {"sysname r1"}


class TestCompareConfig:
    def test_replaced_line_is_reported_as_changed(self):
        diff = ConfigVerifier.compare("sysname R1\ninterface GE0/0/1", "sysname R2\ninterface GE0/0/1")
        assert diff == {
            "added": [],
            "removed": [],
            "changed": ["sysname r1 -> sysname r2"],
        }

    def test_added_and_removed_lines_are_not_double_counted_as_changed(self):
        diff = ConfigVerifier.compare("sysname R1", "sysname R1\ninterface GE0/0/1\nospf 1")
        assert diff == {"added": ["interface ge0/0/1", "ospf 1"], "removed": [], "changed": []}

    def test_replace_block_with_uneven_sides_splits_leftovers(self):
        # 对齐后：首行相同；"b" 被替换为 "c"，右侧多出 "d"
        diff = ConfigVerifier.compare("a\nb", "a\nc\nd")
        assert diff["changed"] == ["b -> c"]
        assert diff["added"] == ["d"]
        assert diff["removed"] == []

    def test_sim_applied_marker_lines_are_ignored(self):
        """适配器写入的是 `#  [sim-applied]` 注释行，必须被当作无关行过滤。"""
        diff = ConfigVerifier.compare("sysname R1\n#  [sim-applied]\ninterface GE0/0/1", "sysname R1")
        assert diff == {"added": [], "removed": ["interface ge0/0/1"], "changed": []}

    def test_identical(self):
        assert ConfigVerifier._compare_config("SYSNAME R1", "sysname R1") is None

    def test_missing_lines(self):
        diff = ConfigVerifier._compare_config("sysname R1\ninterface GE0/0/1", "sysname R1")
        assert diff is not None and "缺失" in diff

    def test_extra_lines_are_not_a_failure(self):
        """提交的是增量片段，回读的是整机配置：整机多出的行不算差异。

        历史缺陷：旧实现做双向集合差（missing + extra），整机配置必然有大量 extra 行，
        于是"验证通过"分支永不可达，每次真实验证都会误判失败并触发回滚。
        """
        assert ConfigVerifier._compare_config("sysname R1", "sysname R1\nundo interface GE0/0/1") is None

    def test_fragment_missing_from_full_config_is_a_failure(self):
        diff = ConfigVerifier._compare_config(
            "sysname R1\nospf 1", "sysname R1\ninterface GE0/0/1"
        )
        assert diff is not None and "缺失" in diff


class TestConfigurationState:
    def test_same_address_on_another_interface_does_not_verify(self):
        expected = "interface GigabitEthernet0/0/1\nip address 192.0.2.1 255.255.255.0"
        actual = "interface GigabitEthernet0/0/1\n description spare\n#\ninterface GigabitEthernet0/0/2\n ip address 192.0.2.1 255.255.255.0"
        assert ConfigVerifier._compare_config(expected, actual) is not None

    def test_view_navigation_is_not_expected_in_running_config(self):
        expected = "system-view\ninterface GigabitEthernet0/0/1\n description uplink\nquit\nreturn"
        actual = "#\ninterface GigabitEthernet0/0/1\n description uplink\n#\nreturn"
        assert ConfigVerifier._compare_config(expected, actual) is None

    def test_repeated_commands_are_bound_to_their_ospf_area(self):
        expected = "ospf 1\n area 0.0.0.0\n  network 192.0.2.0 0.0.0.255"
        actual = "ospf 1\n area 0.0.0.0\n area 0.0.0.1\n  network 192.0.2.0 0.0.0.255"
        assert ConfigVerifier._compare_config(expected, actual) is not None

    def test_undo_shutdown_is_verified_by_absence_in_the_right_interface(self):
        expected = "interface GigabitEthernet0/0/1\nundo shutdown"
        assert ConfigVerifier._compare_config(expected, "interface GigabitEthernet0/0/1\n description uplink") is None
        assert ConfigVerifier._compare_config(expected, "interface GigabitEthernet0/0/1\n shutdown") is not None

    def test_description_operand_keeps_case(self):
        expected = "interface LoopBack1\n description RouterA"
        actual = "interface LoopBack1\n description routera"
        assert ConfigVerifier._compare_config(expected, actual) is not None

    def test_snapshot_restore_rejects_additional_configuration(self):
        target = "sysname R1\n#\ninterface LoopBack1\n description intended"
        actual = target + "\n#\ninterface LoopBack2\n description leftover"
        assert ConfigVerifier.verify_snapshot(target, actual) is not None

    def test_snapshot_equality_ignores_comments_and_view_navigation(self):
        target = "system-view\nsysname R1\ninterface LoopBack1\n description intended\nquit"
        actual = "# generated\nsysname R1\n#\ninterface LoopBack1\n description intended\n#\nreturn"
        assert ConfigVerifier.verify_snapshot(target, actual) is None

    def test_snapshot_unknown_undo_is_not_equivalent_to_absence(self):
        target = "interface GigabitEthernet0/0/1"
        actual = target + "\n undo portswitch"
        assert ConfigVerifier.verify_snapshot(target, actual) is not None
        assert ConfigVerifier.verify_snapshot(actual, target) is not None
        assert ConfigVerifier.verify_snapshot(actual, actual) is None

    def test_snapshot_explicit_interface_undo_shutdown_keeps_known_default_equivalence(self):
        target = "interface GigabitEthernet0/0/1"
        assert ConfigVerifier.verify_snapshot(target, target + "\n undo shutdown") is None
        assert ConfigVerifier.verify_snapshot(target + "\n undo shutdown", target) is None
        assert ConfigVerifier.verify_snapshot("undo shutdown", "") is not None

    def test_spaced_interface_identifiers_cannot_share_configuration(self):
        expected = "interface GigabitEthernet 0/0/1\n description intended"
        actual = "interface GigabitEthernet 0/0/1\n description spare\n#\ninterface GigabitEthernet 0/0/2\n description intended"
        assert ConfigVerifier._compare_config(expected, actual) is not None
        assert ConfigVerifier._compare_config(expected, expected) is None
