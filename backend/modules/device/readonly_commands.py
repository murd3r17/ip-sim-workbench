"""Read-only command profiles used by topology runtime checks."""

COMMON_READONLY_COMMANDS = (
    "display version",
    "display interface brief",
    "display lldp neighbor brief",
)

# 二层设备没有 OSPF 进程，运行时校验补一条 STP。
# 此前两个入参被完全忽略，调用方以为按型号做了区分，实际没有。
_SWITCH_L2_READONLY_COMMANDS = (
    "display version",
    "display interface brief",
    "display lldp neighbor brief",
    "display stp brief",
)

_SWITCH_L2_TYPES = {"switch_l2"}


def get_readonly_commands(device_type: str | None, model: str | None = None) -> tuple[str, ...]:
    """按设备类型返回只读命令集（model 参数保留用于将来按型号细分）。"""
    kind = (device_type or "").strip().lower()
    if kind in _SWITCH_L2_TYPES:
        return _SWITCH_L2_READONLY_COMMANDS
    return COMMON_READONLY_COMMANDS
