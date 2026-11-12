"""配置模板引擎 - Jin2渲染设备配置"""
from jinja2 import BaseLoader, StrictUndefined, TemplateError, TemplateNotFound, TemplateSyntaxError
from jinja2.exceptions import UndefinedError
from jinja2.sandbox import SandboxedEnvironment
from core.logger import get_logger

logger = get_logger("deploy.template")


class ConfigTemplateEngine:
    """基于Jinja2的配置模板引擎

    支持:
    - 变量替换: {{ hostname }}
    - 条件渲染: {% if ospf_enabled %}...{% endif %}
    - 循环渲染: {% for vlan in vlans %}...{% endfor %}
    - 自定义过滤器: ip_mask, interface_name, vrp_comments

    不支持 {% extends %}/{% include %}（loader 为 BaseLoader，无文件系统）。
    """

    def __init__(self):
        self._env = SandboxedEnvironment(
            loader=BaseLoader(),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._register_filters()

    def _register_filters(self) -> None:
        """注册自定义过滤器"""
        self._env.filters["ip_mask"] = self._filter_ip_mask
        self._env.filters["interface_name"] = self._filter_interface_name
        self._env.filters["vrp_comments"] = self._filter_vrp_comments

    @staticmethod
    def _filter_ip_mask(ip: str, mask) -> str:
        """IP地址+掩码格式化: ip_mask('192.168.1.1', 24) -> '192.168.1.1 255.255.255.0'

        mask 支持字符串或整数（模板里写 `{{ ip|ip_mask(24) }}` 很常见；
        此前 int 查不到映射会被原样拼出 `ip 24` 这种非法掩码）。
        """
        mask_map = {
            "8": "255.0.0.0",
            "16": "255.255.0.0",
            "24": "255.255.255.0",
            "30": "255.255.255.252",
            "32": "255.255.255.255",
        }
        key = str(mask).strip()
        subnet = mask_map.get(key)
        if subnet is None and key.isdigit():
            prefix = int(key)
            if 0 <= prefix <= 32:
                subnet = str(__import__("ipaddress").IPv4Network(f"0.0.0.0/{prefix}").netmask)
        if subnet is None:
            subnet = key  # 已经是点分掩码则原样使用
        return f"{ip} {subnet}"

    @staticmethod
    def _filter_interface_name(name: str) -> str:
        """接口名称标准化: 'gi0/0/1' -> 'GigabitEthernet0/0/1'

        必须幂等：已是全名（GigabitEthernet0/0/1）不能再被前缀匹配改写，
        此前会产出 `GigabitEthernetgabitEthernet0/0/1` 这种损坏值。
        """
        raw = (name or "").strip()
        if not raw:
            return raw
        abbrev_map = {
            "gi": "GigabitEthernet",
            "ge": "GigabitEthernet",
            "xge": "XGigabitEthernet",
            "eth": "Ethernet",
            "lo": "LoopBack",
            "vl": "Vlanif",
        }
        lowered = raw.lower()
        # 已是全名 → 原样返回
        for full in ("gigabitethernet", "xgigabitethernet", "ethernet", "loopback", "vlanif"):
            if lowered.startswith(full):
                return raw
        # 按缩写长度降序匹配，避免 "ge" 抢走 "xge"
        for abbrev in sorted(abbrev_map, key=len, reverse=True):
            if lowered.startswith(abbrev):
                suffix = raw[len(abbrev):]
                if suffix and (suffix[0].isdigit() or suffix[0] in " /"):
                    return f"{abbrev_map[abbrev]}{suffix}"
        return raw

    @staticmethod
    def _filter_vrp_comments(text: str) -> str:
        """为配置添加VRP注释格式"""
        lines = text.strip().splitlines()
        result = []
        for line in lines:
            result.append(f"# {line}")
        return "\n".join(result)

    def render(
        self, template_content: str, variables: dict | None = None
    ) -> str:
        """渲染配置模板

        Args:
            template_content: Jinja2模板字符串
            variables: 模板变量字典

        Returns:
            渲染后的配置文本

        Raises:
            TemplateRenderError: 渲染失败时抛出
        """
        try:
            template = self._env.from_string(template_content)
            return template.render(variables or {})
        except TemplateSyntaxError as e:
            raise TemplateRenderError(f"模板语法错误: {e.message} (行{e.lineno})")
        except UndefinedError as e:
            raise TemplateRenderError(f"模板变量缺失: {e.message}")
        except TemplateNotFound as e:
            # BaseLoader 不提供任何模板文件，{% extends %}/{% include %} 必然失败；
            # 此前会冒泡成 500，现在给出可读错误。
            raise TemplateRenderError(f"模板不存在: {e.name}（当前引擎不支持模板继承/包含）")
        except TemplateError as e:
            raise TemplateRenderError(f"模板渲染失败: {e}")

    def validate_template(
        self, template_content: str
    ) -> tuple[bool, list[str]]:
        """校验模板语法，返回 (是否合法, 错误列表)"""
        try:
            self._env.parse(template_content)
            return True, []
        except TemplateSyntaxError as e:
            return False, [f"语法错误: {e.message} (行{e.lineno})"]

    def extract_variables(self, template_content: str) -> list[str]:
        """提取模板中使用的变量名"""
        from jinja2.meta import find_undeclared_variables

        try:
            ast = self._env.parse(template_content)
            return sorted(find_undeclared_variables(ast))
        except TemplateSyntaxError:
            return []

    def validate_variables(self, template_content: str, declarations: dict | None, values: dict | None = None) -> list[str]:
        expected = self.extract_variables(template_content)
        if declarations is None:
            return []
        declared = sorted(declarations)
        if declared != expected:
            missing = sorted(set(expected) - set(declared))
            extra = sorted(set(declared) - set(expected))
            names = missing or extra
            return [f"变量声明与模板变量不一致: {', '.join(names)}"]
        if values is None:
            return []
        return [f"缺少必填变量: {name}" for name in expected if declarations[name].get("required") is True and (name not in values or values[name] is None or (isinstance(values[name], str) and not values[name].strip()))]


class TemplateRenderError(Exception):
    """模板渲染异常"""
