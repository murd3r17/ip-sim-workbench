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
        if re.search(r"只读|display\s", part, re.I) and not re.search(r"配置草稿|下发|修改配置|改写", part):
            continue
        if (re.search(r"生成|给我|写一份|输出|准备|下发", part)
                and re.search(r"现场|实机|真实设备|(?:当前|我的|这台|该台)设备|直接(?:粘贴|执行|下发|用)|可执行", part)
                and re.search(r"配置|命令|脚本|草稿", part)):
            return True
    return False

READ_ONLY_CHECKS = [
    "只读核对接口：display ip interface brief",
    "只读核对邻居：display ospf peer",
    "只读核对路由：display ip routing-table",
]


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
        "请管理员到「环境映射」核对设备与接口并运行预检，再在该实训的步骤页选择环境。新的会话会使用该环境。",
        "确认环境后，可在「配置下发」准备和校验草稿。提交后到「变更审批」核对目标和差异，由有权限的人员确认、执行并查看验证结果。",
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
