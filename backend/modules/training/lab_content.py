# -*- coding: utf-8 -*-
"""V7-A 实验内容单一参数源（A-02/A-03）。

精简版与完整版 OSPF 实验必须共享同一套现场参数（接口名、地址、验证命令），
差别只允许出现在讲解深度。教材原文里的 AR 系列接口/地址（GE0/0/3、10.0.1.1 等）
只作为“教材示例”保留在知识库，不写进可执行的现场步骤。

本模块同时提供：
- ``CONTENT_VERSION``：写进 training_lab.content_version 与 training_session.content_snapshot；
- ``ENVIRONMENT_SPEC``：实验要求的设备/接口/保护项，供接口返回、界面展示与
  “未绑定环境不得生成可执行草稿”的判断使用；
- ``lab_seed_payloads()``：seed 与迁移脚本共用的实验定义。
"""
from __future__ import annotations

import hashlib
import json

CONTENT_VERSION = "v7a.2026-10-26"

# 现场实测（2026-10 交付轮次，NE40E-X16；来源：docs/ops/环境与部署上下文.md）：
#   R1 互联 GE3/0/3 = 10.0.123.1/24，LoopBack0 = 10.0.0.1/24，管理口 GE0/0/0 = 192.168.254.11
#   R2 互联 GE3/0/4 = 10.0.123.2/24，LoopBack0 = 10.0.0.2/24，管理口 GE0/0/0 = 192.168.254.12
#   R3 互联 GE3/0/4 = 10.0.123.3/24，LoopBack0 = 10.0.0.3/24，管理口 GE0/0/0 = 192.168.254.13
# 这些是“当前实验环境的映射”，不是所有接收方的常量；B 批会用 EnvironmentBinding 承载。
OSPF_SITE = {
    "subnet": "10.0.123.0/24",
    "mgmt_subnet": "192.168.254.0/24",
    "protected_interfaces": ["GE0/0/0"],
    "devices": [
        {
            "role": "R1",
            "hostname": "R1",
            "link_interface": "GigabitEthernet3/0/3",
            "link_address": "10.0.123.1/24",
            "loopback": "LoopBack0",
            "loopback_address": "10.0.0.1/24",
            "router_id": "10.0.0.1",
            "mgmt_interface": "GE0/0/0",
            "mgmt_address": "192.168.254.11",
        },
        {
            "role": "R2",
            "hostname": "R2",
            "link_interface": "GigabitEthernet3/0/4",
            "link_address": "10.0.123.2/24",
            "loopback": "LoopBack0",
            "loopback_address": "10.0.0.2/24",
            "router_id": "10.0.0.2",
            "mgmt_interface": "GE0/0/0",
            "mgmt_address": "192.168.254.12",
        },
        {
            "role": "R3",
            "hostname": "R3",
            "link_interface": "GigabitEthernet3/0/4",
            "link_address": "10.0.123.3/24",
            "loopback": "LoopBack0",
            "loopback_address": "10.0.0.3/24",
            "router_id": "10.0.0.3",
            "mgmt_interface": "GE0/0/0",
            "mgmt_address": "192.168.254.13",
        },
    ],
}

OSPF_PROCESS_ID = 1
OSPF_AREA = "0.0.0.0"
OSPF_AUTH = "authentication-mode simple plain huawei"

# 页面/接口统一使用的环境要求（不含凭据）。B 批会用数据库中的绑定替换它。
ENVIRONMENT_SPEC = {
    "kind": "static_reference",
    "label": "当前实验环境参考（R1/R2/R3）",
    "requires_binding": True,
    "binding_status": "unverified",
    "devices": [
        {
            "role": d["role"],
            "link_interface": d["link_interface"],
            "link_address": d["link_address"],
            "loopback": d["loopback"],
            "loopback_address": d["loopback_address"],
            "mgmt_interface": d["mgmt_interface"],
        }
        for d in OSPF_SITE["devices"]
    ],
    "protected": [
        "管理口 GE0/0/0（192.168.254.x）：只读查看，禁止 shutdown、改地址、改描述",
        "S1 二层交换机不在工作台纳管范围，不能对其下发命令",
    ],
    "source": "docs/ops/环境与部署上下文.md",
    "captured_at": "2026-10-15",
}


def site_device(role: str) -> dict:
    for item in OSPF_SITE["devices"]:
        if item["role"] == role:
            return item
    raise KeyError(role)


def _link_map_text() -> str:
    return "；".join(
        f"{d['role']} 互联 {d['link_interface']} {d['link_address']}、{d['loopback']} {d['loopback_address']}"
        for d in OSPF_SITE["devices"]
    )


def _router_config_example(role: str) -> str:
    d = site_device(role)
    return (
        f"{role}: ospf {OSPF_PROCESS_ID} router-id {d['router_id']} → area {OSPF_AREA} → "
        f"{OSPF_AUTH} → network {d['link_address'].split('/')[0]} 0.0.0.0 → "
        f"network {d['loopback_address'].split('/')[0]} 0.0.0.0"
    )


def _router_network_example(role: str) -> str:
    """精简版用：不含认证步骤，但接口/地址与完整版完全相同。"""
    d = site_device(role)
    return (
        f"{role}: ospf {OSPF_PROCESS_ID} router-id {d['router_id']} → area {OSPF_AREA} → "
        f"network {d['link_address'].split('/')[0]} 0.0.0.0 → "
        f"network {d['loopback_address'].split('/')[0]} 0.0.0.0"
    )


# ── 完整版（手册 01-11 OSPF 单区域，7 步） ─────────────────────────────
def full_ospf_steps() -> list[dict]:
    return [
        {
            "id": 1,
            "name": "互联与环回地址核对",
            "goal": f"确认 R1/R2/R3 互联口与 LoopBack0 地址已就绪，三台在同一广播域 {OSPF_SITE['subnet']}",
            "config_hint": (
                f"现场已配好，不要按教材改成 GE0/0/3 或 10.0.1.x/10.0.2.x/10.0.3.x 这类示例地址。{_link_map_text()}。"
                f"在 R1 上 ping {site_device('R2')['link_address'].split('/')[0]}、"
                f"{site_device('R3')['link_address'].split('/')[0]}。"
                "GE0/0/0 是网管口，不要改、不要 shutdown。S1 不在工作台，二层互通即可。"
            ),
            "verify_command": "display ip interface brief",
            "verify_contains": ["10.0.123.", "LoopBack0"],
            "expected": "互联口与 LoopBack0 均为 up，地址为 10.0.123.x 与 10.0.0.x",
        },
        {
            "id": 2,
            "name": "单区域 OSPF 与区域明文认证",
            "goal": (
                f"在 R1/R2/R3 上启动 OSPF 进程 {OSPF_PROCESS_ID}，Router ID 用本机 LoopBack0，"
                f"互联口和环回口宣告进区域 {OSPF_AREA}，并配置区域明文认证"
            ),
            "config_hint": (
                "NE40E VRP8 示例（R1）："
                + _router_config_example("R1")
                + "。"
                + _router_config_example("R2")
                + "。"
                + _router_config_example("R3")
                + "。三台认证方式和密码必须一致，否则邻居建不起来。"
            ),
            "verify_command": f"display ospf {OSPF_PROCESS_ID} brief",
            "verify_contains": [f"OSPF Process {OSPF_PROCESS_ID}", "Router ID"],
            "expected": "OSPF 进程 1 运行，Router ID 分别为 10.0.0.1/2/3",
        },
        {
            "id": 3,
            "name": "邻居、路由与环回互通",
            "goal": "三台 Full 邻居，学到对端 LoopBack0，并用环回地址互 ping",
            "config_hint": (
                "display ospf peer / display ospf routing / "
                f"ping -c 1 -a {site_device('R1')['loopback_address'].split('/')[0]} "
                f"{site_device('R2')['loopback_address'].split('/')[0]}（在 R1）。"
                "广播网会选 DR/BDR。可选：display ospf lsdb 看 Type-1/Type-2 LSA。"
            ),
            "verify_command": "display ospf peer",
            "verify_contains": ["Full"],
            "expected": "每台至少 2 个 Full 邻居；OSPF 路由含对端 10.0.0.x；环回互 ping 通",
        },
        {
            "id": 4,
            "name": "观察邻居建立与 DR 选举",
            "goal": "shutdown 互联口后开 debugging ospf event，再 undo shutdown，观察 Down→Init→2-Way→ExStart→Exchange→Loading→Full 以及 DR/BDR",
            "config_hint": (
                f"只关互联口：R1 {site_device('R1')['link_interface']}，"
                f"R2/R3 {site_device('R2')['link_interface']}。禁止关 GE0/0/0。"
                "user-view：terminal debugging、terminal monitor、debugging ospf 1 event；再 undo shutdown。"
                "做完 undo debugging all。DR 非抢占，同时 up 时选举结果可能与先配先起不同。"
            ),
            "verify_command": "display ospf peer",
            "verify_contains": ["Full", "DR"],
            "expected": "邻居重新 Full；能从 debug 或 peer 输出看出 DR/BDR",
        },
        {
            "id": 5,
            "name": "修改环回 OSPF 网络类型",
            "goal": "把 R2 LoopBack0 的 OSPF 网络类型改成 broadcast，观察路由掩码由 /32 变为真实 /24",
            "config_hint": (
                f"改前在 R1：display ospf routing {site_device('R2')['loopback_address'].split('/')[0]}，应为 /32。"
                f"然后 [R2-LoopBack0] ospf network-type broadcast。再查应变为 10.0.0.0/24。"
                "原因：Loopback 默认按主机路由通告（RFC 2328）。"
            ),
            "verify_command": f"display ospf routing {site_device('R2')['loopback_address'].split('/')[0]}",
            "verify_contains": ["10.0.0."],
            "expected": "改类型后 R2 环回在 OSPF 路由中以 /24 出现",
        },
        {
            "id": 6,
            "name": "修改 OSPF 接口 Cost",
            "goal": "改互联口 Cost，确认对端环回路由 Cost 跟着变",
            "config_hint": (
                f"[R1-{site_device('R1')['link_interface']}] ospf cost 20；"
                f"[R3-{site_device('R3')['link_interface']}] ospf cost 10。"
                f"R1 上看 display ospf routing {site_device('R2')['loopback_address'].split('/')[0]}，Cost 应为 20；"
                f"R3 上看 {site_device('R1')['loopback_address'].split('/')[0]}，Cost 应为 10。"
            ),
            "verify_command": "display ospf routing",
            "verify_contains": ["Cost"],
            "expected": "R1 侧经互联口学到的路由 Cost 为 20，R3 侧为 10",
        },
        {
            "id": 7,
            "name": "Silent-Interface 对比",
            "goal": "对比互联口与 LoopBack0 做成 silent-interface 的不同现象，做完恢复互联口",
            "config_hint": (
                f"先 [R1-ospf-1] silent-interface {site_device('R1')['link_interface']}，邻居会掉，"
                f"display ospf interface {site_device('R1')['link_interface']} 含 Silent interface。"
                "undo silent-interface 恢复。再在 R2/R3 对 LoopBack0 做 silent-interface，"
                "环回路由仍在（不发 Hello，但仍通告）。"
            ),
            "verify_command": f"display ospf interface {site_device('R1')['link_interface']}",
            "verify_contains": ["GigabitEthernet"],
            "expected": "互联口 silent 后无 Hello、邻居消失；环回 silent 后对端仍能看到该环回路由。实验结束请恢复互联口 Hello。",
        },
    ]


# ── 精简版（与完整版共享同一套参数，只压缩讲解） ────────────────────────
def simplified_ospf_steps() -> list[dict]:
    return [
        {
            "id": 1,
            "name": "OSPF 进程与区域配置",
            "goal": f"在三台设备上启动 OSPF 进程 {OSPF_PROCESS_ID}，把互联地址与 LoopBack0 宣告进区域 {OSPF_AREA}",
            "config_hint": (
                f"参数与完整版一致：{_link_map_text()}。"
                + "。".join(
                    _router_network_example(role) for role in ("R1", "R2", "R3")
                )
                + "。管理口 GE0/0/0 只读，不要改。"
            ),
            "verify_command": f"display ospf {OSPF_PROCESS_ID} brief",
            "verify_contains": [f"OSPF Process {OSPF_PROCESS_ID}", "Router ID"],
            "expected": "OSPF 进程 1 已建立并运行，Router ID 为 10.0.0.x",
        },
        {
            "id": 2,
            "name": "OSPF 邻居建立",
            "goal": "三台设备之间形成 OSPF 邻居关系（Full）",
            "config_hint": "无需额外配置；同一广播域内邻居自动建立。",
            "verify_command": "display ospf peer brief",
            "verify_contains": ["Full"],
            "expected": "至少看到 2 个邻居状态为 Full",
        },
        {
            "id": 3,
            "name": "路由学习验证",
            "goal": "确认三台设备都学到彼此 LoopBack0 的路由并互通",
            "config_hint": "OSPF 内部路由自动学习，无需额外配置。",
            "verify_command": "display ip routing-table",
            "verify_contains": ["10.0.0."],
            "expected": "路由表中可见其他设备 Loopback 路由（10.0.0.x/32）",
        },
        {
            "id": 4,
            "name": "邻居状态机观察（思考题）",
            "goal": "理解 OSPF 邻居状态机：Init/2-Way/ExStart/Exchange/Loading/Full",
            "config_hint": "可在终端执行 display ospf peer verbose 查看详细状态。",
            "verify_command": "display ospf peer verbose",
            "verify_contains": ["State"],
            "expected": "能看到邻居状态字段（Full）与状态机相关输出",
        },
    ]


def lab_seed_payloads() -> list[dict]:
    """seed 与迁移共用的实验定义（不含 id；id 由数据库或历史别名决定）。"""
    link_text = _link_map_text()
    return [
        {
            "title": "OSPF 单区域基础实验完整版",
            "description": (
                f"手册《01-11-ospf-单区域》：三台路由器经二层组成 {OSPF_SITE['subnet']} 广播网，"
                "完成地址核对、单区域 OSPF、区域明文认证、邻居/路由/环回互通、debug 观察邻居与 DR、"
                "Loopback 网络类型、Cost、Silent-Interface。现场按 NE40E-X16 改："
                f"{link_text}；S1 不纳管；禁止操作管理口 GE0/0/0。"
            ),
            "objectives": full_ospf_steps(),
            "time_limit_minutes": 90,
            "is_sandbox": False,
            "content_version": CONTENT_VERSION,
            "environment_spec": ENVIRONMENT_SPEC,
            "legacy_title_aliases": ["OSPF 单区域基础实验完整版"],
        },
        {
            "title": "OSPF 单区域基础实验精简版",
            "description": (
                f"三台 NE40E（R1/R2/R3）组成 {OSPF_SITE['subnet']} 广播网。参数与完整版共用同一来源，"
                "只压缩讲解：OSPF 进程/区域配置、邻居建立（Full）、路由学习与状态机观察。"
                "参考《03-13-ospf-的邻接关系和lsa.md》《01-11-ospf-单区域.md》。"
            ),
            "objectives": simplified_ospf_steps(),
            "time_limit_minutes": 45,
            "is_sandbox": False,
            "content_version": CONTENT_VERSION,
            "environment_spec": ENVIRONMENT_SPEC,
            "legacy_title_aliases": ["OSPF 单区域基础实验精简版"],
        },
    ]


def content_fingerprint(objectives) -> str:
    """实验步骤指纹：只关心步骤语义。"""
    payload = json.dumps(objectives or [], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def system_lab_fingerprint(*, description, time_limit_minutes, is_sandbox, objectives) -> str:
    """整行系统样例指纹（A-fix AF-05）。

    只用 objectives 指纹授权更新会覆盖用户改过的 description/time_limit；
    这里把系统内容版本管理的字段一起纳入，任何一项被用户改过都不匹配。
    """
    payload = json.dumps({
        "description": description,
        "time_limit_minutes": time_limit_minutes,
        "is_sandbox": bool(is_sandbox),
        "objectives": objectives or [],
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def legacy_managed_defaults() -> dict[str, dict]:
    """迁移还会写入、但不在四字段指纹里的旧值证据。

    V6.0 seed 未设置 environment_spec 与 content_version（列可空），因此历史系统
    样例的可靠旧值就是 None；任何非 None 值都视为用户修改或来源未知，保守跳过。
    """
    return {
        "OSPF 单区域基础实验完整版": {"environment_spec": None, "content_version": None},
        "OSPF 单区域基础实验精简版": {"environment_spec": None, "content_version": None},
    }


def known_legacy_fingerprints() -> dict[str, set[str]]:
    """历史系统整行指纹（标题 → 指纹集合）。

    2026-08 V6.0 seed 的实测值：description、时限、is_sandbox、objectives 全量参与。
    用户改过任一字段（包括只改描述或时限）都不匹配，迁移必须跳过并报告。
    """
    return {
        "OSPF 单区域基础实验完整版": {
            "56b66501cf965c4e009ca7c656b131736ffd854a730d3eb20eea70c1839328a2",
        },
        "OSPF 单区域基础实验精简版": {
            "fd3cd73cb49bc36908a2ba592e4289e1a6f63be26a6424b2f99753e70cee134c",
        },
    }
