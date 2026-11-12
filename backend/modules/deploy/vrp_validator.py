"""VRP四层校验引擎"""
import ipaddress
import re
from typing import Optional
from core.logger import get_logger

logger = get_logger("deploy")


class RiskLevel:
    """配置风险等级（P2-26：此前这些字符串散落在 service.py 与 vrp_validator.py 里）。

    顺序即严重程度，`DeployService._highest_risk` 依赖它排序。
    """

    SAFE = "safe"
    WARNING = "warning"
    DANGEROUS = "dangerous"
    BLOCKED = "blocked"

    ORDER = {SAFE: 0, WARNING: 1, DANGEROUS: 2, BLOCKED: 3}


# VRP命令知识库
VRP_COMMAND_REGISTRY = {
    "sysname": {"view": "system", "params": [{"name": "hostname", "pattern": r"^\S{1,64}$"}], "models": ["*"]},
    "interface": {"view": "system", "params": [{"name": "interface_type", "pattern": r"^(GigabitEthernet|Ethernet|LoopBack|Vlanif)\S*$"}], "models": ["*"]},
    "ip address": {"view": "interface", "params": [{"name": "ip", "pattern": r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"}, {"name": "mask", "pattern": r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$|^\d{1,2}$"}], "models": ["*"]},
    "ospf": {"view": "system", "params": [{"name": "process_id", "pattern": r"^\d{1,5}$"}], "models": ["NE40E", "AR6000", "S6700"]},
    "bgp": {"view": "system", "params": [{"name": "as_number", "pattern": r"^\d{1,10}$"}], "models": ["NE40E", "AR6000"]},
}

HIGH_RISK_COMMANDS = [
    r"^reset\s+", r"^delete\s+", r"^format\s+", r"^reboot\b", r"^save\b",
    r"^shutdown\b", r"^clear\s+configuration", r"^undo\s+(sysname|interface|ip\s+address|route|ospf|bgp)\b",
]

# 回滚会把"备份的运行配置"整机重放，因此不能套用上面的 HIGH_RISK_COMMANDS
# （running-config 里本来就有 shutdown / undo 等正常行）。这里只拦"绝不可能出现在
# 设备 running-config 里"的破坏性命令，防止被污染的备份把设备刷成砖。
ROLLBACK_FORBIDDEN_COMMANDS = [
    r"^reset\s+saved-configuration",
    r"^reset\s+recycle-bin",
    r"^format\s+",
    r"^delete\s+/unreserved",
    r"^reboot\b",
    r"^startup\s+saved-configuration",
    r"^undo\s+startup",
    r"^reset\s+factory",
]

# 工作台现网是 NE40E-X16。未选设备 / 库里没填型号 / 前端漏传时按此家族校验。
_DEFAULT_MODEL_FAMILY = "NE40E"
_UNSPECIFIED_MODELS = {"", "unknown", "generic", "通用", "none", "null"}
_MODEL_FAMILIES = (
    ("NE40E", "NE40E"),
    ("NE8000", "NE40E"),
    ("AR6000", "AR6000"),
    ("AR", "AR6000"),
    ("S6700", "S6700"),
    ("S67", "S6700"),
)


def normalize_device_model(model: str | None) -> str:
    raw = (model or "").strip()
    if raw.lower() in _UNSPECIFIED_MODELS:
        return _DEFAULT_MODEL_FAMILY
    upper = raw.upper().replace(" ", "")
    for prefix, family in _MODEL_FAMILIES:
        if upper.startswith(prefix):
            return family
    return raw


class VRPValidator:
    """VRP四层校验引擎"""

    def __init__(self):
        self.command_registry = VRP_COMMAND_REGISTRY

    def validate(self, config_text: str, device_model: str, current_view: str = "system") -> list:
        device_model = normalize_device_model(device_model)
        results = []
        for line_number, line in enumerate(config_text.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("!"):
                continue
            if line.endswith("-view"):
                current_view = line.replace("-view", "").strip()
                continue
            if line in ("quit", "return"):
                current_view = "system"
                continue

            l1 = self._check_command_exists(line)
            l1['line_number'] = line_number
            results.append(l1)
            if not l1["passed"]:
                continue
            l2 = self._check_view_match(line, current_view)
            l2['line_number'] = line_number
            results.append(l2)
            if not l2["passed"]:
                continue
            l3 = self._check_params(line)
            l3['line_number'] = line_number
            results.append(l3)
            if not l3["passed"]:
                continue
            l4 = self._check_model_match(line, device_model)
            l4['line_number'] = line_number
            results.append(l4)
            if l4["passed"] and self._find_command_key(line) == "interface":
                current_view = "interface"
        # BF-06：静态校验必须对已支持的地址语法给出确定反馈，不能把 999.1.1.1 当通过。
        for line_number, line in enumerate(config_text.splitlines(), 1):
            text = line.strip()
            match = re.match(r"ip address\s+(\S+)(?:\s+(\S+))?", text)
            if not match:
                continue
            try:
                ipaddress.ip_address(match.group(1))
                if match.group(2):
                    mask = match.group(2)
                    if mask.isdigit():
                        ipaddress.ip_network(f"0.0.0.0/{mask}")
                    else:
                        ipaddress.ip_network(f"0.0.0.0/{mask}")
            except ValueError:
                results.append({
                    "level": "L3", "command": text, "passed": False, "line_number": line_number,
                    "message": f"ip 地址/掩码格式不合法: {match.group(0)}（未下发）",
                })
        return results

    def assess(self, config_text: str, device_model: str) -> dict:
        """返回模拟器配置预检结果；真实执行仍由任务确认链路控制。"""
        details = self.validate(config_text, normalize_device_model(device_model))
        for detail in details:
            detail["risk_level"] = self._risk_level(detail)

        errors = [
            detail["message"] if not detail["passed"] else f"不允许作为配置任务执行: {detail['command']}"
            for detail in details
            if not detail["passed"] or detail["risk_level"] == RiskLevel.BLOCKED
        ]
        # 高危但未被阻断的命令（ospf / bgp 等）需要二次确认。
        # 此前这里硬编码 False，导致 DeployConfirmRequest.risk_confirm、
        # DeployTask.risk_confirmed_by/at 与前端"高风险二次确认"流程全是死代码。
        requires_confirmation = any(detail["risk_level"] == RiskLevel.DANGEROUS for detail in details)
        return {
            "valid": not errors,
            "deploy_allowed": not errors,
            "requires_confirmation": requires_confirmation,
            "config_preview": config_text,
            "details": details,
            "errors": errors,
            "diagnostics": [detail for detail in details if not detail['passed'] or detail['risk_level'] == RiskLevel.BLOCKED],
            "coverage": {
                "checked": ["VRP 命令注册/视图/参数格式/型号兼容", "ip address 地址语法"],
                "not_checked": ["设备真实 CLI 支持全集", "运行配置/保存配置/回显差异", "网络可达与业务影响"],
            },
        }

    @staticmethod
    def _risk_level(detail: dict) -> str:
        if not detail["passed"] or VRPValidator.check_high_risk_commands(detail["command"]):
            return RiskLevel.BLOCKED
        command = detail["command"].lower()
        if command.startswith(("ospf ", "bgp ")):
            return RiskLevel.DANGEROUS
        if command.startswith(("ip address ", "sysname ")):
            return RiskLevel.WARNING
        return RiskLevel.SAFE

    def _check_command_exists(self, line: str) -> dict:
        if line.lower() == "display" or line.lower().startswith(("display ", "dis ")):
            return {"level": "L1", "command": line, "passed": False, "message": "展示命令不能作为配置下发"}
        cmd_key = self._find_command_key(line)
        if cmd_key and cmd_key in self.command_registry:
            return {"level": "L1", "command": line, "passed": True, "message": f"命令已注册: {cmd_key}"}
        return {"level": "L1", "command": line, "passed": True, "message": "未注册命令交由模拟器设备校验"}

    def _check_view_match(self, line: str, current_view: str) -> dict:
        cmd_key = self._find_command_key(line)
        if not cmd_key:
            return {"level": "L2", "command": line, "passed": True, "message": "跳过"}
        expected_view = self.command_registry[cmd_key]["view"]
        if expected_view == current_view or expected_view == "*":
            return {"level": "L2", "command": line, "passed": True, "message": f"视图匹配: {current_view}"}
        return {"level": "L2", "command": line, "passed": False, "message": f"视图不匹配: 需要{expected_view}，当前{current_view}"}

    def _check_params(self, line: str) -> dict:
        cmd_key = self._find_command_key(line)
        if not cmd_key:
            return {"level": "L3", "command": line, "passed": True, "message": "跳过"}
        param_defs = self.command_registry[cmd_key].get("params", [])
        if not param_defs:
            return {"level": "L3", "command": line, "passed": True, "message": "无参数需校验"}
        parts = line.split()
        cmd_parts = cmd_key.split()
        param_values = parts[len(cmd_parts):]
        for i, param_def in enumerate(param_defs):
            if i >= len(param_values):
                return {"level": "L3", "command": line, "passed": False, "message": f"缺少参数: {param_def['name']}"}
            if not re.match(param_def["pattern"], param_values[i]):
                return {"level": "L3", "command": line, "passed": False, "message": f"参数{param_def['name']}格式不合法: {param_values[i]}"}
        return {"level": "L3", "command": line, "passed": True, "message": "参数校验通过"}

    def _check_model_match(self, line: str, model: str) -> dict:
        cmd_key = self._find_command_key(line)
        if not cmd_key:
            return {"level": "L4", "command": line, "passed": True, "message": "跳过"}
        compatible = self.command_registry[cmd_key].get("models", ["*"])
        if "*" in compatible or model in compatible:
            return {"level": "L4", "command": line, "passed": True, "message": f"型号兼容: {model}"}
        return {"level": "L4", "command": line, "passed": False, "message": f"型号不兼容: 命令适用于{compatible}，目标{model}"}

    def _find_command_key(self, line: str) -> Optional[str]:
        parts = line.split()
        for length in range(min(len(parts), 4), 0, -1):
            candidate = " ".join(parts[:length])
            if candidate in self.command_registry:
                return candidate
        return None

    @staticmethod
    def check_high_risk_commands(config_text: str) -> list:
        detected = []
        for line in config_text.strip().splitlines():
            line = line.strip()
            for pattern in HIGH_RISK_COMMANDS:
                if re.match(pattern, line, re.IGNORECASE):
                    detected.append(line)
                    break
        return detected

    @staticmethod
    def check_rollback_safe(config_text: str) -> list:
        """回滚前的破坏性命令检查；返回命中的行（空表示可安全重放）。"""
        detected = []
        for line in (config_text or "").strip().splitlines():
            line = line.strip()
            for pattern in ROLLBACK_FORBIDDEN_COMMANDS:
                if re.match(pattern, line, re.IGNORECASE):
                    detected.append(line)
                    break
        return detected
