"""VRP四层校验引擎测试"""
import pytest
from modules.deploy.vrp_validator import VRPValidator, HIGH_RISK_COMMANDS, normalize_device_model


class TestNormalizeDeviceModel:
    def test_unspecified_defaults_to_ne40e(self):
        assert normalize_device_model(None) == "NE40E"
        assert normalize_device_model("") == "NE40E"
        assert normalize_device_model("unknown") == "NE40E"
        assert normalize_device_model("通用") == "NE40E"

    def test_family_prefix(self):
        assert normalize_device_model("NE40E-X16") == "NE40E"
        assert normalize_device_model("AR2240") == "AR6000"
        assert normalize_device_model("S6720") == "S6700"

    def test_unknown_model_kept(self):
        assert normalize_device_model("unknown_model") == "unknown_model"


class TestVRPValidator:
    """VRP四层校验测试"""

    def setup_method(self):
        self.validator = VRPValidator()

    # === L1: 命令存在性校验 ===

    def test_l1_registered_command_passes(self):
        results = self.validator.validate("sysname Router01", "NE40E")
        l1 = [r for r in results if r["level"] == "L1"]
        assert l1[0]["passed"] is True

    def test_l1_unregistered_command_is_not_blocked_in_simulator(self):
        results = self.validator.validate("unknown_cmd foo bar", "NE40E")
        l1 = [r for r in results if r["level"] == "L1"]
        assert l1[0]["passed"] is True

    def test_l1_blank_lines_skipped(self):
        results = self.validator.validate("", "NE40E")
        assert results == []

    def test_l1_comments_skipped(self):
        results = self.validator.validate("# comment\n! another", "NE40E")
        assert results == []

    # === L2: 视图匹配校验 ===

    def test_l2_system_view_command_passes(self):
        results = self.validator.validate("sysname R1", "NE40E")
        l2 = [r for r in results if r["level"] == "L2"]
        assert l2[0]["passed"] is True

    def test_l2_explicit_view_transition(self):
        # 使用 -view 后缀显式切换视图
        config = "interface-view\nip address 192.168.1.1 255.255.255.0"
        results = self.validator.validate(config, "NE40E")
        l2 = [r for r in results if r["level"] == "L2"]
        assert all(r["passed"] for r in l2)

    def test_l2_wrong_view_fails(self):
        # ip address requires interface view, but we're in system view
        results = self.validator.validate("ip address 192.168.1.1 255.255.255.0", "NE40E")
        l2 = [r for r in results if r["level"] == "L2"]
        assert any(not r["passed"] for r in l2)

    def test_l2_view_transition_quit(self):
        config = "interface-view\nquit\nsysname R1"
        results = self.validator.validate(config, "NE40E")
        l2 = [r for r in results if r["level"] == "L2"]
        assert all(r["passed"] for r in l2)

    # === L3: 参数格式校验 ===

    def test_l3_valid_params_passes(self):
        results = self.validator.validate("sysname Router01", "NE40E")
        l3 = [r for r in results if r["level"] == "L3"]
        assert l3[0]["passed"] is True

    def test_l3_invalid_hostname_fails(self):
        results = self.validator.validate("sysname " + "A" * 100, "NE40E")
        l3 = [r for r in results if r["level"] == "L3"]
        assert l3[0]["passed"] is False

    def test_l3_valid_ip_passes(self):
        config = "interface-view\nip address 10.0.0.1 255.255.255.0"
        results = self.validator.validate(config, "NE40E")
        l3 = [r for r in results if r["level"] == "L3"]
        assert all(r["passed"] for r in l3)

    def test_l3_ip_regex_rejects_out_of_range_octets(self):
        # BF-06：已支持地址语法必须拒绝越界八位组，而不是只匹配 \d{1,3}。
        config = "interface-view\nip address 999.999.999.999 255.255.255.0"
        results = self.validator.validate(config, "NE40E")
        l3 = [r for r in results if r["level"] == "L3"]
        assert any(not r["passed"] and "不合法" in r["message"] for r in l3)

    def test_l3_missing_param_fails(self):
        # 使用显式视图切换确保L2通过，L3检测到缺少参数
        config = "interface-view\nip address"
        results = self.validator.validate(config, "NE40E")
        l3 = [r for r in results if r["level"] == "L3"]
        assert any(not r["passed"] for r in l3)

    def test_l3_ospf_valid_process_id(self):
        results = self.validator.validate("ospf 1", "NE40E")
        l3 = [r for r in results if r["level"] == "L3"]
        assert l3[0]["passed"] is True

    def test_l3_ospf_invalid_process_id(self):
        results = self.validator.validate("ospf abc", "NE40E")
        l3 = [r for r in results if r["level"] == "L3"]
        assert l3[0]["passed"] is False

    # === L4: 设备型号兼容性校验 ===

    def test_l4_universal_command_passes(self):
        results = self.validator.validate("sysname R1", "NE40E")
        l4 = [r for r in results if r["level"] == "L4"]
        assert l4[0]["passed"] is True

    def test_l4_ospf_on_ne40e_passes(self):
        results = self.validator.validate("ospf 1", "NE40E")
        l4 = [r for r in results if r["level"] == "L4"]
        assert l4[0]["passed"] is True

    def test_l4_bgp_on_unsupported_model_fails(self):
        results = self.validator.validate("bgp 65001", "S6700")
        l4 = [r for r in results if r["level"] == "L4"]
        assert l4[0]["passed"] is False

    def test_l4_ospf_on_unknown_model_fails(self):
        results = self.validator.validate("ospf 1", "unknown_model")
        l4 = [r for r in results if r["level"] == "L4"]
        # NE40E, AR6000, S6700 only - 真正未知型号仍失败
        assert l4[0]["passed"] is False

    def test_l4_ospf_unspecified_unknown_defaults_to_ne40e(self):
        results = self.validator.validate("ospf 1", "unknown")
        l4 = [r for r in results if r["level"] == "L4"]
        assert l4[0]["passed"] is True

    def test_l4_ospf_on_ne40e_x16_passes(self):
        results = self.validator.validate("ospf 1 router-id 10.0.1.1", "NE40E-X16")
        l4 = [r for r in results if r["level"] == "L4"]
        assert l4[0]["passed"] is True

    def test_assess_ospf_draft_without_model(self):
        config = (
            "system-view\n"
            "ospf 1 router-id 10.0.1.1\n"
            "area 0.0.0.0\n"
            "network 10.0.123.0 0.0.0.255\n"
            "network 10.0.1.1 0.0.0.0\n"
            "quit\n"
            "quit\n"
        )
        report = self.validator.assess(config, "unknown")
        assert report["valid"] is True
        assert report["deploy_allowed"] is True

    # === 高危命令检测 ===

    def test_high_risk_reset_detected(self):
        detected = VRPValidator.check_high_risk_commands("reset ip routing-table")
        assert len(detected) == 1

    def test_high_risk_delete_detected(self):
        detected = VRPValidator.check_high_risk_commands("delete flash:/config.cfg")
        assert len(detected) == 1

    def test_high_risk_reboot_detected(self):
        detected = VRPValidator.check_high_risk_commands("reboot")
        assert len(detected) == 1

    def test_high_risk_shutdown_detected(self):
        detected = VRPValidator.check_high_risk_commands("shutdown")
        assert len(detected) == 1

    def test_high_risk_undo_sysname_detected(self):
        detected = VRPValidator.check_high_risk_commands("undo sysname")
        assert len(detected) == 1

    def test_high_risk_clear_config_detected(self):
        detected = VRPValidator.check_high_risk_commands("clear configuration")
        assert len(detected) == 1

    def test_no_high_risk_in_safe_config(self):
        config = "sysname Router01\ninterface-view\nip address 10.0.0.1 255.255.255.0"
        detected = VRPValidator.check_high_risk_commands(config)
        assert detected == []

    def test_high_risk_case_insensitive(self):
        detected = VRPValidator.check_high_risk_commands("RESET ip routing-table")
        assert len(detected) == 1

    # === 综合场景 ===

    def test_multi_command_config(self):
        # 使用显式视图切换确保所有命令在正确视图中执行
        config = (
            "sysname CoreRouter\n"
            "interface-view\n"
            "ip address 10.0.0.1 255.255.255.0\n"
            "quit\n"
            "ospf 1\n"
            "quit"
        )
        results = self.validator.validate(config, "NE40E")
        failures = [r for r in results if not r["passed"]]
        assert failures == []

    def test_unregistered_command_still_has_a_precheck_result(self):
        results = self.validator.validate("foobar baz", "NE40E")
        levels = [r["level"] for r in results]
        assert "L1" in levels
        assert all(result["passed"] for result in results)

    def test_validate_returns_list_of_dicts(self):
        results = self.validator.validate("sysname R1", "NE40E")
        assert isinstance(results, list)
        for r in results:
            assert "level" in r
            assert "command" in r
            assert "passed" in r
            assert "message" in r

    # === 阶段4A：视图状态与风险分级 ===

    def test_interface_command_enters_interface_view(self):
        results = self.validator.validate(
            "interface LoopBack0\nip address 10.0.0.1 255.255.255.255",
            "NE40E",
        )
        assert all(result["passed"] for result in results)

    def test_display_command_is_blocked_from_config_payload(self):
        report = self.validator.assess("display current-configuration", "NE40E")
        assert report["deploy_allowed"] is False
        assert report["details"][0]["risk_level"] == "blocked"

    def test_simulator_allows_aaa_and_local_user_config(self):
        report = self.validator.assess(
            "aaa\nlocal-user demo password irreversible-cipher placeholder",
            "unknown",
        )
        assert report["valid"] is True
        assert not any("命令未注册" in error for error in report["errors"])

    def test_forbidden_command_is_blocked(self):
        report = self.validator.assess("reboot", "NE40E")
        assert report["deploy_allowed"] is False
        assert report["details"][0]["risk_level"] == "blocked"

    def test_valid_configuration_is_allowed_without_risk_classification(self):
        report = self.validator.assess(
            "interface LoopBack0\nip address 10.0.0.1 255.255.255.255",
            "NE40E",
        )
        assert report["valid"] is True
        assert report["requires_confirmation"] is False
        assert report["deploy_allowed"] is True
