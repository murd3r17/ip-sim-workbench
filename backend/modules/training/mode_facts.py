"""V7-A AF-04：设备连接、下发方式与环境绑定的可信事实。

界面不再把“教学方式”或某个开关当作“是否真实设备”的证明。这里统一生成：
- ``device_mode``：sim / ssh / unknown（来自服务端配置，不由前端传入）
- ``deploy_mode``：simulated / real / unknown（新任务的下发方式）
- ``environment_binding``：verified / unverified / unknown（来自实验环境声明）
- ``webssh_write_risk``：none / possible / unknown（模拟开关不能证明原始终端只读）

会话开始时把事实写入 ``mode_snapshot``；历史没有快照时返回 unknown，而不是用
当前设置推断当时的行为。
"""
from __future__ import annotations

from core.config import get_settings

DEVICE_LABELS = {
    "sim": "模拟设备（不连接真实网络）",
    "ssh": "真实共享设备（无隔离）",
    "unknown": "设备连接方式未知",
}
DEPLOY_LABELS = {
    "simulated": "模拟下发（不写设备）",
    "real": "真实下发（需授权确认）",
    "unknown": "下发方式未知",
}
BINDING_LABELS = {
    "verified": "环境绑定已核验",
    "unverified": "环境绑定未核验",
    "unknown": "无环境绑定信息",
}


def _binding_status(lab) -> str:
    spec = getattr(lab, "environment_spec", None) or {}
    status = str(spec.get("binding_status") or "").strip().lower()
    if status in ("verified", "unverified"):
        return status
    return "unknown"


def _facts(device_mode: str, deploy_mode: str, binding: str, teaching: str) -> dict:
    device_mode = device_mode if device_mode in DEVICE_LABELS else "unknown"
    deploy_mode = deploy_mode if deploy_mode in DEPLOY_LABELS else "unknown"
    binding = binding if binding in BINDING_LABELS else "unknown"
    if device_mode == "sim":
        risk = "none"
        summary = "模拟设备，不连接真实网络；模拟下发的“成功”不能证明真实设备通过。"
    elif device_mode == "ssh" and deploy_mode == "simulated":
        risk = "possible"
        summary = "真实设备 + 模拟下发：WebSSH 原始终端仍可能写入设备，模拟开关不保证只读。"
    elif device_mode == "ssh" and deploy_mode == "real":
        risk = "possible"
        summary = "真实设备 + 真实下发：写入需审批、白名单与人工确认。"
    elif device_mode == "ssh":
        risk = "possible"
        summary = "真实共享设备，无环境隔离；下发方式未记录。"
    else:
        risk = "unknown"
        summary = "设备连接或下发方式未记录，不能推断为模拟或真实。"
    return {
        "teaching_mode": teaching,
        "device_mode": device_mode,
        "device_label": DEVICE_LABELS[device_mode],
        "deploy_mode": deploy_mode,
        "deploy_label": DEPLOY_LABELS[deploy_mode],
        "environment_binding": binding,
        "environment_binding_label": BINDING_LABELS[binding],
        "webssh_write_risk": risk,
        "summary": summary,
    }


def _current_deploy_mode() -> str:
    settings = get_settings()
    return "simulated" if bool(getattr(settings, "deploy_simulate_only", True)) else "real"


def _current_device_mode() -> str:
    settings = get_settings()
    mode = str(getattr(settings, "device_mode", "") or "").strip().lower()
    if mode in ("sim", "ssh"):
        return mode
    return "unknown"


def current_mode_facts(lab) -> dict:
    """当前服务端事实（用于新建会话/实验列表），不读取任何前端参数。"""
    return _facts(
        _current_device_mode(),
        _current_deploy_mode(),
        _binding_status(lab),
        "free" if getattr(lab, "is_sandbox", False) else "guided",
    )


def unknown_mode_facts(lab) -> dict:
    """历史会话没有快照时：连接/下发未知，绑定仍按实验声明展示。"""
    return _facts("unknown", "unknown", _binding_status(lab), "free" if getattr(lab, "is_sandbox", False) else "guided")


def build_mode_snapshot(lab) -> dict:
    return current_mode_facts(lab)


def session_mode_facts(session, lab) -> tuple[dict, str]:
    snapshot = getattr(session, "mode_snapshot", None)
    if isinstance(snapshot, dict) and snapshot.get("device_mode"):
        # Old/partial snapshots still describe only what was saved, never
        # today's process settings. Canonical labels avoid blank/undefined UI.
        return _facts(snapshot.get('device_mode'), snapshot.get('deploy_mode'),
                      snapshot.get('environment_binding'),
                      snapshot.get('teaching_mode') if snapshot.get('teaching_mode') in {'free','guided'} else 'unknown'), "session_snapshot"
    return unknown_mode_facts(lab), "unknown_history"
