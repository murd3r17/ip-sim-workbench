"""V7-A AF-03：所有学习入口共用的环境防护判定。

A 阶段没有完整的 EnvironmentBinding；在缺少可信映射/核验时，统一拒绝“现场可执行
配置”，只提供原因、只读核对方法和教材引用。不得只给模型加一句提示，也不得靠隐藏
按钮代替后端拒绝。
"""
from __future__ import annotations

import re


def requests_site_configuration(message: str) -> bool:
    """Recognize explicit requests for runnable site config even without the UI toggle."""
    segments = re.split(r"[。；;！!?？\n]|[，,](?=\s*(?:但|只要|请|改为))", message or "")
    for part in segments:
        if re.search(r"(?:不要|不用|不必|无需|不)(?:再)?(?:生成|提供|写|输出|给)|只(?:讲|说明|解释)|怎么理解", part):
            continue
        part = re.sub(r"(?:不要|不用|无需|不)(?:实际|真的)?(?:下发|执行)", "", part)
        if re.search(r"只读|display\s", part, re.I) and not re.search(r"配置草稿|下发|修改配置|改配置|改写", part):
            continue
        if (re.search(r"生成|给我|给.{0,10}一(?:份|段|套)|写一(?:份|段|套)|输出|准备|下发", part)
                and re.search(r"现场|实机|真实设备|(?:当前|我的|这台|该台)设备|直接(?:粘贴|执行|下发|用)|可执行", part)
                and re.search(r"配置|命令|脚本|草稿", part)):
            return True
    return False

READ_ONLY_CHECKS = [
    "只读核对接口：display ip interface brief",
    "只读核对邻居：display ospf peer",
    "只读核对路由：display ip routing-table",
]


def lab_environment_id(spec) -> int | None:
    if not isinstance(spec, dict):
        return None
    value = spec.get("trust_environment_id") or spec.get("environment_id")
    if type(value) is int:
        return value if value > 0 else None
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,9}", value):
        return int(value)
    return None


def lab_binding_issue(spec, devices) -> str:
    """Describe the same role constraints at preparation and at bind time."""
    requirements = spec.get("devices") if isinstance(spec, dict) else None
    if not isinstance(requirements, list) or not requirements:
        return "请先为课程登记设备角色。"
    roles = [item.get("role") for item in requirements if isinstance(item, dict)]
    if len(roles) != len(requirements) or any(not isinstance(role, str) or not role.strip() for role in roles):
        return "请先为课程登记设备角色。"
    if len(roles) != len(set(roles)):
        return "课程角色重复，请管理员检查课程要求。"
    members = devices if isinstance(devices, list) else []
    mapped = [item for item in members if isinstance(item, dict) and item.get("role") in roles]
    present = {item["role"] for item in mapped}
    missing = [role for role in roles if role not in present]
    if missing:
        return f"环境缺少角色 {'、'.join(missing)}。请在环境映射中为这些角色选择设备。"
    if len(mapped) != len(roles):
        return "同一角色存在多条映射。请为每个课程角色保留一台设备。"
    ids = [item.get("device_id") for item in mapped]
    if any(type(device_id) is not int or device_id <= 0 for device_id in ids):
        return "有角色尚未选择有效设备。请在环境映射中补齐。"
    if len(ids) != len(set(ids)):
        return "多个课程角色使用了同一台设备。请分别选择独立设备。"
    return ""


def lab_availability(lab, mode: str, environment, *, has_local_devices: bool) -> dict:
    """Course publication and environment readiness do not grant write permissions."""
    def state(kind, label, detail):
        return {"state": kind, "label": label, "detail": detail}

    if lab.status == "draft":
        return state("unpublished", "未发布", "发布后学员可以查看。")
    spec = lab.environment_spec if isinstance(lab.environment_spec, dict) else {}
    if spec.get("kind") == "workflow_demo":
        if mode == "sim" and has_local_devices:
            return state("local_practice", "可做本地巡检", "查看拓扑和接口，保存一条观察记录并回看。")
        return state("reading_only", "可阅读步骤", "本地巡检需要模拟设备和对应的设备拓扑。")
    if not spec.get("requires_binding") and not spec.get("devices"):
        return state("reading_only", "可阅读与记录", "打开步骤查看教学目标和操作要求。")
    if environment is None:
        return state("needs_environment", "可阅读 · 待绑定环境", "请管理员在实验步骤中选择并预检环境。")
    issue = lab_binding_issue(spec, environment.devices)
    if issue:
        return state("needs_environment", "可阅读 · 映射待补", issue)
    expected_mode = {"sim": "sim", "ssh": "real"}.get(mode)
    if (not expected_mode or environment.status != "ready"
            or environment.last_preflight_status != "ready" or environment.last_preflight_mode != expected_mode):
        return state("needs_preflight", "已绑定 · 待预检", "请管理员按当前连接方式在环境映射中运行预检。")
    if mode == "sim":
        return state("limited_practice", "可做部分只读观察", "映射已预检。配置和协议状态变化需要对应设备环境。")
    return state("device_observation", "环境已预检", "可按步骤核对绑定设备。开始前请检查课程的协议与操作条件。")


def lab_environment(lab) -> dict:
    """返回 ``{allow_executable, status, reason}``，由服务端实验声明决定。"""
    spec = getattr(lab, "environment_spec", None) or {}
    if spec.get("requires_binding") is False:
        return {"allow_executable": True, "status": "not_required", "reason": ""}
    status = str(spec.get("binding_status") or "").strip().lower()
    devices = spec.get("devices") or []
    if status == "verified" and devices:
        return {"allow_executable": True, "status": "verified", "reason": ""}
    if status == "verified" and not devices:
        return {
            "allow_executable": False,
            "status": "unknown",
            "reason": "实验声明为已核验，但缺少设备角色/接口映射，不能生成现场可执行配置。",
        }
    if status == "unverified":
        return {
            "allow_executable": False,
            "status": "unverified",
            "reason": "管理员尚未核对本实验使用的设备、接口和地址。",
        }
    return {
        "allow_executable": False,
        "status": "unknown",
            "reason": "当前会话没有可核对的设备与接口映射。",
    }


def safe_environment_answer(*, title: str, reason: str, content_warning: str = "") -> dict:
    """不调用模型的安全回答（Copilot 与训练提示共用）。"""
    lines = [
        f"「{title}」暂时不能生成面向设备的配置草稿。{reason}",
        "你可以继续阅读实验步骤，或在设备页选择对象做只读观察。",
        *[f"- {item}" for item in READ_ONLY_CHECKS],
        "- 可以打开知识库查看教材。教材的地址与接口需要按实际环境核对。",
        "请管理员从实训详情点「为本实验准备环境」，保存设备、接口与保护项并运行预检，再回实训详情保存环境绑定。新开的会话使用通过预检的环境。",
        "环境核对后，可在「配置下发」准备和校验自己的草稿。提交后在「变更审批」核对目标和差异；确认、执行和核对分别取决于任务模式及权限。",
    ]
    if content_warning:
        lines.insert(1, content_warning)
    text = "\n".join(lines)
    return {
        "text": text,
        "next_steps": READ_ONLY_CHECKS,
        "risk_notes": ["未核验环境不生成可执行配置；模拟下发开关不代表 SSH 终端只读。"],
        "status": "blocked_environment",
    }
