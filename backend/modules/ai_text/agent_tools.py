"""AI 助手工具注册表（Function Calling）：让 Copilot 具备 DSH 级别的实时感知能力。

全部工具只读，不越"只辅助不代操作"红线：
- run_display_command 仅允许白名单只读命令（display 系），输出截断
- 其余工具复用现有模块 service，不新建设备访问逻辑
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from core.logger import get_logger
from core.redaction import redact_sensitive

logger = get_logger("ai")

# ── 只读命令白名单（命令级匹配；含参数均允许，输出截断） ──────────────
READONLY_PREFIXES = (
    "display version",
    "display interface brief",
    "display ip interface brief",
    "display current-configuration",
    "display ospf peer brief",
    "display ospf peer",
    "display ospf routing",
    "display ospf lsdb",
    "display ospf interface",
    "display ospf brief",
    "display isis peer",
    "display isis brief",
    "display isis routing-table",
    "display bgp peer",
    "display bgp routing-table",
    "display bgp summary",
    "display ip routing-table",
    "display cpu-usage",
    "display memory-usage",
    "display lldp neighbor brief",
    "display alarm active",
    "display alarm",
    "display clock",
    "display device",
    "display device brief",
    "display elabel",
    "display esn",
    "display ntp status",
)

# 禁止字符：命令分隔符、管道、重定向、命令替换、子 shell、控制字符（含换行）
_BLOCK_CHARS = (";", "|", "&", ">", "<", "`", "$", "(", ")", "\n", "\r", "\t", "\x00", "\x1a")
# 只读命令允许的字符集（接口名 / 点分十进制 / 冒号 / 斜杠 / 连字符 / 下划线 / 空格）
_ALLOWED_CHARS_RE = re.compile(r"^[A-Za-z0-9_\-./: ]+$")
_MAX_COMMAND_LEN = 160


def is_readonly_command(command: str) -> bool:
    """校验命令是否在只读白名单内。

    防护要点（历史缺陷：``display version\\nreset saved-configuration`` 曾通过校验）：
    1. 拒绝任何控制字符（含 \\n / \\r / \\t），杜绝一条 tool_call 塞进多条命令；
    2. 拒绝 ``; | & > < ` $ ( )`` 等 shell / VRP 分隔与替换字符；
    3. 字符集白名单 + 长度上限；
    4. 命令级匹配（前缀之后必须是空格或结束），避免 ``display versionX`` 这类前缀混淆。
    """
    cmd = (command or "").strip()
    if not cmd or len(cmd) > _MAX_COMMAND_LEN:
        return False
    if any(ch in cmd for ch in _BLOCK_CHARS):
        return False
    if not _ALLOWED_CHARS_RE.match(cmd):
        return False
    # 归一化多重空白，避免 "display  version" 之类伪装
    lower = " ".join(cmd.lower().split())
    for prefix in READONLY_PREFIXES:
        if lower == prefix or lower.startswith(prefix + " "):
            return True
    return False


# ── 工具定义（OpenAI function calling schema） ──────────────────────
def _fn(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or []},
        },
    }


TOOL_DEFS: list[dict] = [
    _fn("query_devices", "读取资产库中的设备标识、地址、记录状态与最后探测时间；不发起设备探测。已知可信设备ID时不必重复查询。",
        {"topology_id": {"type": "integer", "description": "可选，按拓扑过滤"}}),
    _fn("query_device_detail", "读取单台设备的资产详情与最近配置快照；不发起设备探测，快照不等于当前状态",
        {"device_id": {"type": "integer", "description": "设备ID"}}),
    _fn("run_display_command", "通过设备适配器读取指定设备。来源看返回mode，可能是sim；失败/拒绝不证明设备状态。只能用command列出的白名单，先取必要摘要。",
        {"device_id": {"type": "integer", "description": "设备ID"},
         "command": {"type": "string", "description": "单条命令，可带合法参数；不支持任意display、ping或管道。允许前缀：" + "；".join(READONLY_PREFIXES)}}),
    _fn("query_monitor_stats", "查询监控统计（设备总数/在线/活跃告警）与最近采集任务",
        {}),
    _fn("query_alarms", "查询活跃告警列表",
        {"limit": {"type": "integer", "description": "最多返回条数，默认10"}}),
    _fn("query_deploy_tasks", "查询配置下发任务列表与状态",
        {}),
    _fn("query_config_versions", "查询设备配置快照版本列表",
        {"device_id": {"type": "integer", "description": "可选，按设备过滤"}}),
    _fn("search_knowledge", "检索工作台知识库（华为教材/实验文档），返回相关片段",
        {"query": {"type": "string", "description": "检索关键词/问题"},
         "top_k": {"type": "integer", "description": "返回条数，默认5"}}),
    _fn("query_topology", "查询拓扑列表、链路与布局信息",
        {}),
    _fn("query_audit_logs", "查询最近操作审计日志（登录/配置/下发等）",
        {"limit": {"type": "integer", "description": "最多返回条数，默认10"}}),
]

TOOL_MAX_ROUNDS = 3          # 工具调用轮次上限
TOOL_MAX_CALLS = 8           # 单次对话工具调用总次数上限（防模型狂调工具挤爆上下文）
TOOL_CALLS_PER_ROUND = 3     # 单轮最多执行的工具数
TOOL_RESULT_LIMIT = 1500     # 单工具结果截断字符


def available_tool_defs(actor: dict | None = None, allowed: list[str] | None = None) -> list[dict]:
    tools = [tool for tool in TOOL_DEFS
             if tool["function"]["name"] != "query_audit_logs" or (actor or {}).get("role") == "admin"]
    if allowed is not None:
        tools = [t for t in tools if t["function"]["name"] in set(allowed)]
    return tools


def validate_tool_args(name: str, args: dict) -> str:
    """CA-T05：按工具 schema 校验参数；返回错误文本，空串表示通过。"""
    tool = next((t for t in TOOL_DEFS if t["function"]["name"] == name), None)
    if tool is None:
        return f"未知工具: {name}"
    if not isinstance(args, dict):
        return f"参数错误：{name} 需要 JSON 对象"
    schema = tool["function"].get("parameters") or {}
    props = schema.get("properties") or {}
    for key in schema.get("required") or []:
        if key not in args:
            return f"参数错误：缺少必填字段 {key}"
    types = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
             "array": list, "object": dict}
    for key, value in args.items():
        spec = props.get(key)
        if spec is None:
            return f"参数错误：不支持字段 {key}"
        want = types.get(spec.get("type"))
        if spec.get("type") in ("integer", "number") and isinstance(value, bool):
            return f"参数错误：字段 {key} 应为 {spec.get('type')}（不接受布尔）"
        if want and not isinstance(value, want):
            return f"参数错误：字段 {key} 应为 {spec.get('type')}"
    return ""


async def execute_tool(db: Any, name: str, args: dict, user_id: int | None = None,
                       actor: dict | None = None, allowed: list[str] | None = None,
                       *, _cached_result: str | None = None) -> str:
    from datetime import datetime, timezone
    from .tool_result import EvidenceText
    result = await _execute_tool(db, name, args, user_id, actor, allowed,
                                 _cached_result=_cached_result)
    if isinstance(result, EvidenceText):
        return result
    from .tool_result import classify
    outcome = classify(name, args, result)
    if name == 'run_display_command' or outcome.status not in {'ok', 'empty', 'partial'}:
        # Failed/rejected transport has no collected device output. Only the
        # adapter/observation path can supply a device timestamp and mode.
        return EvidenceText(result, source='server_tool', mode='unknown')
    # This timestamp is a database read time, not the device's last probe time.
    return EvidenceText(result, source="database_snapshot", mode="snapshot",
                        collected_at=datetime.now(timezone.utc).isoformat())


async def _execute_tool(db: Any, name: str, args: dict, user_id: int | None = None,
                       actor: dict | None = None, allowed: list[str] | None = None,
                       *, _cached_result: str | None = None) -> str:
    """执行工具，返回文本结果（截断、异常兜底）。

    每次执行重新检查当前账户；模型工具参数不能决定操作者和权限。
    """
    started = time.time()
    try:
        if name not in {tool["function"]["name"] for tool in TOOL_DEFS}:
            return f"未知工具: {name}"
        if allowed is not None and name not in set(allowed):
            return f"工具 {name} 不在当前技能允许范围内，已拒绝执行"
        arg_error = validate_tool_args(name, args)
        if arg_error:
            return arg_error
        if not user_id or db is None:
            return "无权执行工具：缺少有效的操作者"
        from modules.auth.models import User
        account = await db.get(User, user_id, populate_existing=True)
        if account is None or not account.is_active:
            return "无权执行工具：账号不存在或已禁用"
        current_actor = {"user_id": account.id, "role": account.role.value}
        if actor and (actor.get("user_id") != account.id or
                      actor.get("role") != current_actor["role"] or
                      actor.get("token_version", 0) != account.token_version):
            return "无权执行工具：登录状态已变更，请重新登录"
        if name == "query_audit_logs" and current_actor["role"] != "admin":
            return "无权查询系统审计日志：需要管理员权限"
        # Only the request-local coordinator supplies this value, never model arguments.
        # Reuse still passes every schema, skill and fresh account check above.
        if _cached_result is not None:
            from .tool_result import EvidenceText
            metadata = dict(_cached_result.metadata) if isinstance(_cached_result, EvidenceText) else {}
            return EvidenceText(_cached_result, **{**metadata, "reused": True})
        if name == "query_devices":
            return await _query_devices(db, args)
        if name == "query_device_detail":
            return await _query_device_detail(db, args)
        if name == "run_display_command":
            return await _run_display_command(db, args, user_id)
        if name == "query_monitor_stats":
            return await _query_monitor_stats(db)
        if name == "query_alarms":
            return await _query_alarms(db, args)
        if name == "query_deploy_tasks":
            return await _query_deploy_tasks(db, current_actor)
        if name == "query_config_versions":
            return await _query_config_versions(db, args)
        if name == "search_knowledge":
            return await _search_knowledge(db, args)
        if name == "query_topology":
            return await _query_topology(db)
        if name == "query_audit_logs":
            return await _query_audit_logs(db, args)
        return f"未知工具: {name}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_tool_failed", tool=name, error=redact_sensitive(str(exc)))
        return f"工具执行失败: {redact_sensitive(str(exc))}"
    finally:
        logger.info("agent_tool_done", tool=name, cost_ms=int((time.time() - started) * 1000))


async def _audit_tool(db: Any, user_id: int | None, action: str, detail: dict, result: str = "success") -> None:
    """把 AI 工具的设备动作写入审计日志（best-effort，失败不影响回答）。"""
    if not user_id:
        return
    try:
        from modules.auth.service import AuditService
        await AuditService.log(
            db, user_id, "", "ai", action, "device",
            str(detail.get("device_id") or ""), detail, result=result,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_tool_audit_failed", action=action, error=str(exc))


def _redact_output(text: str) -> str:
    """设备回显入库/入模前脱敏（口令、SNMP community、PSK 等）。"""
    return redact_sensitive(text)


def _limit(text: str) -> str:
    text = (text or "").strip()
    return text[:TOOL_RESULT_LIMIT] + f"\n…(截断，共{len(text)}字符)" if len(text) > TOOL_RESULT_LIMIT else text


# ── 工具实现 ─────────────────────────────────────────────────────────
async def _query_devices(db: Any, args: dict) -> str:
    from sqlalchemy import select
    from modules.device.models import Device
    q = select(Device)
    topo_id = args.get("topology_id")
    if topo_id:
        q = q.where(Device.topology_id == int(topo_id))
    devices = list((await db.execute(q)).scalars().all())
    if not devices:
        return "当前无设备记录"
    lines = ["设备列表:"]
    for d in devices:
        last = d.last_seen_at.isoformat() if d.last_seen_at else "-"
        lines.append(f"- id={d.id} {d.hostname} {d.mgmt_ip}:{d.ssh_port} 状态={d.status.value} 型号={d.model or d.device_type.value} 最后在线={last} 拓扑={d.topology_id}")
    return "\n".join(lines)


async def _query_device_detail(db: Any, args: dict) -> str:
    from modules.device.service import DeviceService
    from modules.deploy.models import ConfigVersion
    from sqlalchemy import select
    device = await DeviceService.get_device(db, int(args.get("device_id", 0)))
    lines = [
        f"设备 id={device.id} {device.hostname}",
        f"地址: {device.mgmt_ip}:{device.ssh_port}  类型: {device.device_type.value}  型号: {device.model or '-'}",
        f"状态: {device.status.value}  角色: {device.network_role}  拓扑: {device.topology_id}",
        f"最后在线: {device.last_seen_at.isoformat() if device.last_seen_at else '-'}",
    ]
    versions = list((await db.execute(
        select(ConfigVersion).where(ConfigVersion.device_id == device.id).order_by(ConfigVersion.version_number.desc()).limit(3)
    )).scalars().all())
    if versions:
        lines.append("最近配置快照:")
        for v in versions:
            lines.append(f"  - v{v.version_number} {v.source or '-'} {v.change_description or ''} {v.created_at.isoformat() if v.created_at else ''}")
    from modules.monitor.port_service import get_port_state
    state = await get_port_state(db, device.id)
    observed = state.get('observation') or {}
    lines.append('已保存端口观察（不新采集、不证明业务可达）: ' + json.dumps({
        'fresh': state['fresh'], 'policy_changed': state['policy_changed'], 'mode_changed': state['mode_changed'],
        'latest_attempt': state['latest_attempt'], 'policy_valid': state['policy']['valid'],
        'current_expectations': state['policy']['ports'][:8], 'expectations_total': len(state['policy']['ports']),
        'expectations_shown': min(8, len(state['policy']['ports'])),
        'expectations_truncated': len(state['policy']['ports']) > 8,
        'complete': observed.get('complete'), 'observed_at': observed.get('observed_at'),
        'expected_down': observed.get('expected_down'), 'review_count': observed.get('review_count'),
        'ports': observed.get('ports', [])[:8], 'ports_total': len(observed.get('ports', [])),
        'ports_shown': min(8, len(observed.get('ports', []))),
        'ports_truncated': len(observed.get('ports', [])) > 8,
        'missing_expected_ports': observed.get('missing_expected_ports', [])[:12],
        'missing_expected_ports_total': len(observed.get('missing_expected_ports', [])),
        'missing_expected_ports_shown': min(12, len(observed.get('missing_expected_ports', []))),
        'missing_expected_ports_truncated': len(observed.get('missing_expected_ports', [])) > 12,
        'scope_note': 'total为本次保存列表的总数，shown为当前摘要条数；截断列表中的分类数仅代表所示项，不等于全量分类数。',
    }, ensure_ascii=False))
    return "\n".join(lines)


async def _run_display_command(db: Any, args: dict, user_id: int | None = None) -> str:
    from modules.device.service import DeviceService
    from engines.device_adapter import get_device_adapter
    device = await DeviceService.get_device(db, int(args.get("device_id", 0)))
    command = str(args.get("command", "")).strip()
    if not is_readonly_command(command):
        logger.warning("agent_display_rejected", device_id=device.id, user_id=user_id, command=command[:120])
        await _audit_tool(
            db, user_id, "ai_display_command_rejected",
            {"device_id": device.id, "hostname": device.hostname, "command": command[:200]},
            result="rejected",
        )
        return f"拒绝执行：命令不在只读白名单内（仅允许 display 系命令）: {command}"
    # Reuse B's parser, observation ownership, redaction, adapter and lock path
    # for its supported commands. No duplicate network read is performed.
    from modules.trust.service import READ_ONLY_ACTIONS, collect_observation
    from .tool_result import EvidenceText
    from core.time_utils import iso_utc
    action = next((key for key, spec in READ_ONLY_ACTIONS.items()
                   if spec["command"] == " ".join(command.lower().split())), None)
    if action and db is not None:
        row = await collect_observation(db, user={"user_id": user_id}, device_id=device.id,
                                        action_id=action, environment_id=None)
        status = row.status
        if "DeviceBusyError" in (row.error_message or ""):
            status = "busy"
        elif "Timeout" in (row.error_message or "") or "超时" in (row.error_message or ""):
            status = "timeout"
        text = f"[{device.hostname}] {command} 回显:\n{row.raw_excerpt or row.error_message or '(空回显)'}"
        await _audit_tool(db, user_id, "ai_display_command",
                          {"device_id": device.id, "command": command, "evidence_id": row.id},
                          result="success" if status == "ok" else "failed")
        return EvidenceText(text, status=status, target=str(device.id), source=row.source,
                            mode=row.adapter_mode, collected_at=iso_utc(row.collected_at),
                            evidence_id=row.id, completeness=row.completeness,
                            parser_version=row.parser_version, error=row.error_message or "")
    adapter = await get_device_adapter(device)
    try:
        out = await adapter.run_command(command)
        await _audit_tool(
            db, user_id, "ai_display_command",
            {"device_id": device.id, "hostname": device.hostname, "command": command[:200]},
        )
        safe = _redact_output(out or "")
        from datetime import datetime, timezone
        from engines.device_adapter import get_device_mode
        from modules.trust.service import detect_cli_error, detect_incomplete
        status = "error" if detect_cli_error(safe) else "partial" if detect_incomplete(safe) else "ok" if safe else "empty"
        return EvidenceText(f"[{device.hostname}] {command} 回显:\n{safe or '(空回显)'}",
                            status=status, source="server_observed", target=str(device.id),
                            mode="sim" if get_device_mode() == "sim" else "real",
                            collected_at=datetime.now(timezone.utc).isoformat(),
                            completeness="complete" if status == "ok" else status)
    except Exception as exc:
        from engines.device_lock import DeviceBusyError
        await _audit_tool(
            db, user_id, "ai_display_command",
            {"device_id": device.id, "hostname": device.hostname, "command": command[:200],
             "error": type(exc).__name__},
            result="failed",
        )
        if isinstance(exc, DeviceBusyError):
            return f"[{device.hostname}] 设备终端占用中，请稍后重试"
        raise
    finally:
        await adapter.close()


async def _query_monitor_stats(db: Any) -> str:
    from modules.device.models import Device
    from modules.monitor.models import Alarm, AlarmStatus
    from sqlalchemy import select, func
    total = (await db.execute(select(func.count(Device.id)))).scalar() or 0
    online = (await db.execute(select(func.count(Device.id)).where(Device.status == "online"))).scalar() or 0
    active = (await db.execute(select(func.count(Alarm.id)).where(Alarm.status.in_([AlarmStatus.FIRED, AlarmStatus.ACKNOWLEDGED])))).scalar() or 0
    return f"设备总数={total} 在线={online} 活跃告警={active}"


async def _query_alarms(db: Any, args: dict) -> str:
    from modules.monitor.models import Alarm, AlarmStatus
    from sqlalchemy import select
    limit = min(int(args.get("limit") or 10), 30)
    alarms = list((await db.execute(select(Alarm).where(
        Alarm.status.in_([AlarmStatus.FIRED, AlarmStatus.ACKNOWLEDGED])
    ).order_by(Alarm.id.desc()).limit(limit))).scalars().all())
    if not alarms:
        return "当前无告警"
    lines = [f"活跃告警 {len(alarms)} 条（含已确认；处理状态不等于设备恢复；旧interface_down_high仅为未分用途的历史总数规则）:"]
    for a in alarms:
        sev = a.severity.value if hasattr(a.severity, "value") else a.severity
        st = a.status.value if hasattr(a.status, "value") else a.status
        lines.append(f"- id={a.id} 设备={a.device_id} 类型={a.alarm_type} 级别={sev} 状态={st} 消息={a.message or ''} 时间={a.created_at}")
    return "\n".join(lines)


async def _query_deploy_tasks(db: Any, actor: dict) -> str:
    from modules.deploy.models import DeployTask
    from sqlalchemy import select
    query = select(DeployTask)
    if actor["role"] != "admin":
        query = query.where(DeployTask.operator_id == actor["user_id"])
    tasks = list((await db.execute(query.order_by(DeployTask.id.desc()).limit(10))).scalars().all())
    if not tasks:
        return "当前无配置下发任务"
    return "\n".join(
        f"- task#{t.id} 设备={t.device_id} 状态={t.status.value} 引擎={t.engine} 创建={t.created_at}"
        for t in tasks
    )


async def _query_config_versions(db: Any, args: dict) -> str:
    from modules.deploy.models import ConfigVersion
    from sqlalchemy import select
    q = select(ConfigVersion).order_by(ConfigVersion.id.desc()).limit(10)
    device_id = args.get("device_id")
    if device_id:
        q = select(ConfigVersion).where(ConfigVersion.device_id == int(device_id)).order_by(ConfigVersion.id.desc()).limit(10)
    versions = list((await db.execute(q)).scalars().all())
    if not versions:
        return "无配置快照版本"
    return "\n".join(
        f"- v{v.version_number} 设备={v.device_id} 来源={v.source or '-'} 说明={v.change_description or '-'} 时间={v.created_at}"
        for v in versions
    )


async def _search_knowledge(db: Any, args: dict) -> str:
    from datetime import datetime, timezone
    from .context_bundle import prepare_sources, source_documents
    from .tool_result import EvidenceText
    from modules.knowledge.service import KnowledgeService
    service = KnowledgeService.from_settings()
    top_k = max(1, min(int(args.get("top_k") or 5), 10))
    query = str(args.get("query", "")).strip()
    provenance = {"source": "knowledge_corpus", "mode": "reference", "error": "",
                  "collected_at": datetime.now(timezone.utc).isoformat()}
    if not query:
        return EvidenceText("检索词为空", **provenance, status="rejected")
    try:
        hits = await service.search(query, None, top_k)
    except Exception as exc:
        logger.warning("knowledge_tool_search_failed", error=type(exc).__name__)
        return EvidenceText("知识检索暂时不可用，未获得参考资料；不能据此判断知识库为空。",
                            **{**provenance, "error": type(exc).__name__}, status="error", completeness="unknown")
    if not hits:
        return EvidenceText("知识库未命中相关文档", **provenance, status="empty", completeness="empty")
    # Leave room for source labels/separators and the explicit omitted-content
    # notice. No downstream 1500-character limit should cut a surviving claim.
    sources = prepare_sources(hits[:top_k], max_total_chars=1300, max_document_chars=1300)
    partial = len(sources) < len(hits) or any(s["truncated"] for s in sources)
    lines = [f"知识检索返回 {len(hits)} 条，提供 {len(sources)} 条完整段落片段（仅供参考，不是现场证据）。"]
    lines.extend(source_documents(sources))
    if partial:
        lines.append("[部分来源未能完整提供；仅保留预算内的完整段落，不得将省略内容视为不存在。]")
    return EvidenceText("\n\n".join(lines), **provenance, status="partial" if partial else "ok",
                        completeness="partial" if partial else "complete", truncated=partial,
                        knowledge_sources=sources)


async def _query_topology(db: Any) -> str:
    from modules.device.models import Topology, TopologyLink
    from modules.device.service import TopologyService
    from sqlalchemy import select
    topologies = list((await db.execute(select(Topology).order_by(Topology.id))).scalars().all())
    if not topologies:
        return "无拓扑"
    lines = ["拓扑库存/基线及已保存LLDP观察；本次读取不采集设备。LLDP不证明完整物理网络或业务可达。"]
    for t in topologies:
        links = list((await db.execute(select(TopologyLink).where(TopologyLink.topology_id == t.id))).scalars().all())
        baseline_count = sum(lk.source_type == 'baseline' for lk in links)
        lines.append(f"- id={t.id} {t.name} 类型={t.topology_type.value} 状态={t.status} 基线关系={baseline_count}条 非基线关系={len(links)-baseline_count}条")
        for lk in links[:5]:
            lines.append(f"    {lk.source_device_id}({lk.source_interface}) <-> {lk.target_device_id}({lk.target_interface}) 记录类型={lk.source_type} 来源={lk.discovery_source or 'unknown'}")
        latest = await TopologyService.get_latest_runtime_check(db, t.id)
        if not latest:
            lines.append('    已保存LLDP观察: 无；发现覆盖未知')
            continue
        coverage = latest.get('coverage') or {}
        summary = {'check_id': latest['check_id'], 'status': latest['status'],
                   'observed_at': str(latest.get('created_at') or ''), 'baseline_changed': latest['is_stale'],
                   'observation_stale_or_unknown': latest['evidence_stale'], 'mode_changed': latest['mode_changed'],
                   'ssh_returned': latest['ssh_success'], 'ssh_failed': latest['ssh_failed'],
                   'parsed_devices': coverage.get('parsed_devices'), 'expected_devices': coverage.get('expected_devices'),
                   'observation_mode': coverage.get('mode'),
                   'missing_adjacencies': len(latest['diff']['missing']), 'unexpected_adjacencies': len(latest['diff']['unexpected']),
                   'devices': [{k: row.get(k) for k in ('hostname', 'state', 'complete', 'observed_at')}
                               for row in coverage.get('devices', [])[:12]],
                   'unmanaged_neighbor_count': len(coverage.get('unmanaged_neighbors', [])),
                   'unmanaged_neighbors': coverage.get('unmanaged_neighbors', [])[:5],
                   'multi_neighbor_port_count': len(coverage.get('multi_neighbor_ports', [])),
                   'multi_neighbor_ports': coverage.get('multi_neighbor_ports', [])[:5],
                   'one_sided_links': coverage.get('one_sided_links'), 'bidirectional_links': coverage.get('bidirectional_links')}
        summary['device_rows_truncated'] = len(coverage.get('devices', [])) > 12
        summary['device_rows_total'] = len(coverage.get('devices', []))
        summary['device_rows_shown'] = min(12, len(coverage.get('devices', [])))
        for label, key in [('unmanaged_neighbor', 'unmanaged_neighbors'), ('multi_neighbor_port', 'multi_neighbor_ports')]:
            summary[label + '_shown'] = len(summary[key])
            summary[label + '_truncated'] = summary[label + '_count'] > len(summary[key])
        summary['scope_note'] = 'count/total为保存覆盖快照内总数，shown为摘要条数；部分覆盖不能外推为全网总数。'
        lines.append('    已保存LLDP观察: ' + json.dumps(summary, ensure_ascii=False, default=str))
    return "\n".join(lines)


async def _query_audit_logs(db: Any, args: dict) -> str:
    from modules.auth.models import AuditLog
    from sqlalchemy import select
    limit = min(int(args.get("limit") or 10), 30)
    logs = list((await db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))).scalars().all())
    if not logs:
        return "无审计日志"
    return "\n".join(
        f"- #{l.id} {l.username} {l.module}/{l.action} 资源={l.resource_type}:{l.resource_id or '-'} 结果={l.result} {l.created_at}"
        for l in logs
    )
