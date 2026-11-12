"""配置模板引擎测试 - Jinja2渲染"""
import pytest
from modules.deploy.config_template_engine import (
    ConfigTemplateEngine,
    TemplateRenderError,
)


class TestConfigTemplateEngine:
    """模板引擎核心测试"""

    def setup_method(self):
        self.engine = ConfigTemplateEngine()

    # === 基础渲染 ===

    def test_simple_variable(self):
        template = "sysname {{ hostname }}"
        result = self.engine.render(template, {"hostname": "Router01"})
        assert result == "sysname Router01"

    def test_multiple_variables(self):
        template = "interface {{ interface }}\nip address {{ ip }} {{ mask }}"
        result = self.engine.render(
            template, {"interface": "Gi0/0/1", "ip": "10.0.0.1", "mask": "24"}
        )
        assert "Gi0/0/1" in result
        assert "10.0.0.1" in result

    def test_render_empty_variables(self):
        template = "sysname Router01"
        result = self.engine.render(template, {})
        assert result == "sysname Router01"

    def test_render_none_variables(self):
        template = "sysname Router01"
        result = self.engine.render(template, None)
        assert result == "sysname Router01"

    # === 条件渲染 ===

    def test_if_condition_true(self):
        template = "{% if ospf_enabled %}ospf 1{% endif %}"
        result = self.engine.render(template, {"ospf_enabled": True})
        assert result == "ospf 1"

    def test_if_condition_false(self):
        template = "{% if ospf_enabled %}ospf 1{% endif %}"
        result = self.engine.render(template, {"ospf_enabled": False})
        assert result == ""

    def test_if_else(self):
        template = "{% if use_dhcp %}dhcp select interface{% else %}ip address {{ ip }} {{ mask }}{% endif %}"
        result = self.engine.render(template, {"use_dhcp": False, "ip": "10.0.0.1", "mask": "24"})
        assert "ip address 10.0.0.1 24" in result

    # === 循环渲染 ===

    def test_for_loop(self):
        template = "{% for vlan in vlans %}vlan {{ vlan }}\n{% endfor %}"
        result = self.engine.render(template, {"vlans": [10, 20, 30]})
        assert "vlan 10" in result
        assert "vlan 20" in result
        assert "vlan 30" in result

    def test_for_loop_with_interface(self):
        template = (
            "{% for port in ports %}"
            "interface {{ port.name }}\n"
            "port link-type access\n"
            "port default vlan {{ port.vlan }}\n"
            "{% endfor %}"
        )
        result = self.engine.render(template, {
            "ports": [
                {"name": "GigabitEthernet0/0/1", "vlan": 10},
                {"name": "GigabitEthernet0/0/2", "vlan": 20},
            ]
        })
        assert "GigabitEthernet0/0/1" in result
        assert "vlan 10" in result
        assert "GigabitEthernet0/0/2" in result
        assert "vlan 20" in result

    # === 自定义过滤器 ===

    def test_ip_mask_filter(self):
        template = "ip address {{ ip | ip_mask('24') }}"
        result = self.engine.render(template, {"ip": "192.168.1.1"})
        assert result == "ip address 192.168.1.1 255.255.255.0"

    def test_ip_mask_filter_30(self):
        template = "ip address {{ ip | ip_mask('30') }}"
        result = self.engine.render(template, {"ip": "10.0.0.1"})
        assert result == "ip address 10.0.0.1 255.255.255.252"

    def test_interface_name_filter(self):
        template = "{{ name | interface_name }}"
        result = self.engine.render(template, {"name": "gi0/0/1"})
        assert result == "GigabitEthernet0/0/1"

    def test_interface_name_filter_lo(self):
        template = "{{ name | interface_name }}"
        result = self.engine.render(template, {"name": "lo0"})
        assert result == "LoopBack0"

    def test_vrp_comments_filter(self):
        template = "{{ text | vrp_comments }}"
        result = self.engine.render(template, {"text": "line1\nline2"})
        assert "# line1" in result
        assert "# line2" in result

    # === 语法校验 ===

    def test_validate_valid_template(self):
        valid, errors = self.engine.validate_template("sysname {{ hostname }}")
        assert valid is True
        assert errors == []

    def test_validate_invalid_template(self):
        valid, errors = self.engine.validate_template("sysname {{ hostname")
        assert valid is False
        assert len(errors) > 0

    def test_validate_empty_template(self):
        valid, errors = self.engine.validate_template("")
        assert valid is True

    # === 变量提取 ===

    def test_extract_variables(self):
        template = "sysname {{ hostname }}\ninterface {{ interface }}\nip address {{ ip }}"
        variables = self.engine.extract_variables(template)
        assert "hostname" in variables
        assert "interface" in variables
        assert "ip" in variables

    def test_extract_variables_empty(self):
        variables = self.engine.extract_variables("sysname Router01")
        assert variables == []

    def test_rejects_declarations_that_do_not_match_template_variables(self):
        errors = self.engine.validate_variables(
            "sysname {{ hostname }}", {"ip": {"required": True}}
        )
        assert errors == ["变量声明与模板变量不一致: hostname"]

    def test_requires_non_blank_required_variable(self):
        errors = self.engine.validate_variables(
            "sysname {{ hostname }}",
            {"hostname": {"required": True}},
            {"hostname": " "},
        )
        assert errors == ["缺少必填变量: hostname"]

    # === 错误处理 ===

    def test_render_missing_variable_raises(self):
        template = "sysname {{ hostname }}"
        with pytest.raises(TemplateRenderError, match="变量缺失"):
            self.engine.render(template, {})

    def test_render_syntax_error_raises(self):
        template = "sysname {{ hostname"
        with pytest.raises(TemplateRenderError, match="语法错误"):
            self.engine.render(template, {})

    # === 综合场景 ===

    def test_full_vrp_config_template(self):
        template = """# {{ description }}
sysname {{ hostname }}
{% if ospf_enabled %}
ospf 1
 area 0.0.0.0
  network {{ network }} {{ wildcard }}
{% endif %}
{% for vlan in vlans %}
vlan {{ vlan.id }}
 description {{ vlan.name }}
{% endfor %}
interface {{ mgmt_interface | interface_name }}
 ip address {{ mgmt_ip | ip_mask(mgmt_mask) }}
"""
        result = self.engine.render(template, {
            "description": "Core Router Config",
            "hostname": "CoreR01",
            "ospf_enabled": True,
            "network": "10.0.0.0",
            "wildcard": "0.0.255.255",
            "vlans": [
                {"id": 10, "name": "Management"},
                {"id": 20, "name": "Server"},
            ],
            "mgmt_interface": "gi0/0/0",
            "mgmt_ip": "192.168.1.1",
            "mgmt_mask": "24",
        })
        assert "CoreR01" in result
        assert "ospf 1" in result
        assert "vlan 10" in result
        assert "GigabitEthernet0/0/0" in result
        assert "192.168.1.1 255.255.255.0" in result
