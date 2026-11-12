"""V7-A AF-03：所有学习入口共用的环境防护判定。

A 阶段没有完整的 EnvironmentBinding；在缺少可信映射/核验时，统一拒绝“现场可执行
配置”，只提供原因、只读核对方法和教材引用。不得只给模型加一句提示，也不得靠隐藏
按钮代替后端拒绝。
"""
from __future__ import annotations

import re


def readonly_training_ui_help(message: str) -> str:
    """Known UI guidance is useful even while executable lab advice is blocked.

    This never enables a model/tool/draft or reads another session. Call only
    after the usual session owner and content-source checks.
    """
    if re.search(r'步骤核对|核对本步|采集当前观察', message or ''):
        return ('在实训会话中展开「步骤核对」→选择步骤→「采集当前观察」→选择记录→「核对本步」。'
                '采集只发固定只读命令；核对只比较已选记录，不发设备命令、不调用模型、不出技能成绩。'
                '观察需属于本会话冻结角色/环境，采集时间不早于会话开始且距核对不超过五分钟。'
                '未支持的步骤显示需人工复核；手动勾选、Full和本步事实匹配都不代表整项技能通过。')
    if re.search(r'保存环境绑定|实训.{0,12}绑定|实验.{0,12}绑定', message or ''):
        return ('管理员在实训实验行点步骤数量链接，打开「实验步骤」，选择已有环境后点「保存环境绑定」。'
                '环境映射需先预检，协议先修另行核对。绑定只影响之后的新会话，旧会话保留当时版本；'
                '环境改版后重新预检并新开会话。普通用户请管理员处理绑定。')
    if re.search(r'笔记.{0,12}(?:保存|在哪|哪里)|(?:保存|哪里).{0,12}笔记', message or ''):
        return ('在会话内展开「连续任务 · 笔记与步骤」，填写结论并点「保存笔记/步骤」。'
                '已保存复盘报告不能直接编辑；「查看复盘」只读版本，显式「生成复盘报告」才调用模型生成新版本。')
    return ''

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
            "reason": "当前实验环境尚未绑定并核验（binding_status=unverified），不能生成现场可执行配置。",
        }
    return {
        "allow_executable": False,
        "status": "unknown",
        "reason": "当前实验没有可信的环境绑定信息，不能生成现场可执行配置。",
    }


def safe_environment_answer(*, title: str, reason: str, content_warning: str = "") -> dict:
    """不调用模型的安全回答（Copilot 与训练提示共用）。"""
    lines = [
        f"关于「{title}」的现场配置建议已暂停：{reason}",
        "现在可以做的事：",
        *[f"- {item}" for item in READ_ONLY_CHECKS],
        "- 阅读右侧教材/知识库原文；教材中的接口、地址是示例，未与现场映射核对前不要直接粘贴执行。",
        "需要生成可执行配置时，请先由管理员完成环境绑定与只读核验（V7-B 提供正式绑定）。",
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
