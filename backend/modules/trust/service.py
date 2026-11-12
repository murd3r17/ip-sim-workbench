# -*- coding: utf-8 -*-
"""V7-B 可信基础服务（BF 返修版）。

边界：
- 环境映射只是“声明”；preflight 必须用固定只读事实核对实体/接口/地址/保护项。
- 证据记录来源、adapter 模式、环境版本/快照、完整性、解析器和受控原文。
- 模拟证据显式标 sim，不得被当成真实设备已通过。
- 规则只接受服务端采集、受支持解析器、完整/新鲜、目标一致的证据。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.time_utils import iso_utc
from modules.deploy.models import DeployStatus, DeployTask, DeviceWriteLock
from modules.device.models import Device, DeviceStatus
from modules.trust.models import EnvironmentProfile, ReadOnlyObservation

PARSER_VERSION = "v7b.4"
# Previously parsed positive observations retain their original interpretation.
# Old empty results are never retroactively re-parsed into a known zero.
SUPPORTED_PARSERS = {"v7b.3", PARSER_VERSION}
SERVER_MAX_AGE_SECONDS = 300
CURRENT_INSTANCE_ID = uuid.uuid4().hex
CURRENT_PID = os.getpid()
TERMINAL_ACTIVE_GRACE_SECONDS = 120

def _process_started_at(pid: int) -> float | None:
    """Windows 进程创建时间；用于避免 PID 复用。非 Windows 返回 None。"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return None
        try:
            created = wintypes.FILETIME()
            exited = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
                return None
            ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
            return ticks / 10_000_000 - 11644473600
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def _process_alive(pid: int, started_at: float | None) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                err = ctypes.get_last_error()
                if err in (5, 87, 1168):
                    return False if err in (87, 1168) else None
                return None
            try:
                code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return None
                if code.value != 259:
                    return False
            finally:
                kernel32.CloseHandle(handle)
            if started_at is not None:
                actual = _process_started_at(pid)
                if actual is None:
                    return None
                if abs(actual - started_at) > 2:
                    return False
            return True
        except Exception:
            return None
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


async def ensure_service_instance(db: AsyncSession) -> None:
    from modules.deploy.models import ServiceInstance
    now = _now().replace(tzinfo=None)
    row = await db.get(ServiceInstance, CURRENT_INSTANCE_ID)
    started = _process_started_at(CURRENT_PID)
    if row is None:
        db.add(ServiceInstance(instance_id=CURRENT_INSTANCE_ID, pid=CURRENT_PID,
                               process_started_at=datetime.fromtimestamp(started, timezone.utc).replace(tzinfo=None) if started else None,
                               started_at=now, last_heartbeat_at=now))
    else:
        row.pid = CURRENT_PID
        row.last_heartbeat_at = now
        if started:
            row.process_started_at = datetime.fromtimestamp(started, timezone.utc).replace(tzinfo=None)
    await db.flush()


async def reconcile_terminal_locks(db: AsyncSession) -> None:
    """新进程读取旧实例锁：PID/创建时间证明旧持有者已结束则持久标 orphaned。"""
    from modules.deploy.models import DeviceWriteLock, ServiceInstance
    rows = (await db.execute(select(DeviceWriteLock).where(
        DeviceWriteLock.owner_type == "terminal",
        DeviceWriteLock.owner_instance_id.is_not(None),
        DeviceWriteLock.state.in_(["active", "closing", "unknown"]),
    ))).scalars().all()
    changed = False
    for lock in rows:
        if lock.owner_instance_id == CURRENT_INSTANCE_ID and lock.state != "unknown":
            continue
        inst = await db.get(ServiceInstance, lock.owner_instance_id)
        if inst is None:
            lock.state = "unknown"
            lock.release_error = "owner instance identity missing"
            changed = True
            continue
        started_at = inst.process_started_at.replace(tzinfo=timezone.utc).timestamp() if inst.process_started_at else None
        alive = _process_alive(inst.pid, started_at)
        if alive is False:
            lock.state = "orphaned"
            lock.release_state = "orphaned"
            lock.release_error = "owner process ended"
            changed = True
        elif alive is None:
            lock.state = "unknown"
            lock.release_error = "owner process identity unknown"
            changed = True
        else:
            # 未知后条件恢复：进程可确认活着，回到 active，仍禁止恢复。
            if lock.state != "active":
                lock.state = "active"
                lock.release_state = None
                lock.release_error = None
                changed = True
    if changed:
        await db.commit()


def _token_fingerprint(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()[:32]


def _release_outbox_path() -> Path:
    path = Path(os.environ.get("TERMINAL_RELEASE_OUTBOX", str(Path(__file__).resolve().parents[2] / ".runtime" / "terminal_release_pending.jsonl")))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# 释放 outbox 需跨线程、跨进程追加；仅靠 O_APPEND 在 Windows 上会丢行（BF8 实测 40 写丢 1）。
_OUTBOX_THREAD_LOCK = threading.Lock()


def _lock_outbox_handle(fh) -> None:
    if os.name == "nt":
        import msvcrt

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)


def _unlock_outbox_handle(fh) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception:  # noqa: BLE001
        pass


def _append_release_outbox(device_id: int, token: str) -> None:
    line = json.dumps({"device_id": int(device_id), "token": _token_fingerprint(token),
                       "at": iso_utc(_now())}, ensure_ascii=False) + "\n"
    try:
        with _OUTBOX_THREAD_LOCK:
            path = _release_outbox_path()
            with path.open("a", encoding="utf-8") as fh:
                _lock_outbox_handle(fh)
                try:
                    fh.write(line)
                    fh.flush()
                    os.fsync(fh.fileno())
                finally:
                    _unlock_outbox_handle(fh)
    except Exception:  # noqa: BLE001
        pass


def _pending_release_tokens(device_id: int) -> set[str]:
    path = _release_outbox_path()
    if not path.exists():
        return set()
    result = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if int(item.get("device_id", -1)) == int(device_id):
                result.add(str(item.get("token", "")))
    except Exception:
        return set()
    return result


def _clear_release_outbox(device_id: int, token: str) -> None:
    path = _release_outbox_path()
    if not path.exists():
        return
    target = _token_fingerprint(token)
    try:
        with _OUTBOX_THREAD_LOCK:
            with path.open("r+", encoding="utf-8") as fh:
                _lock_outbox_handle(fh)
                try:
                    kept = []
                    for line in fh.read().splitlines():
                        item = json.loads(line)
                        if int(item.get("device_id", -1)) != int(device_id) or str(item.get("token")) != target:
                            kept.append(line)
                    fh.seek(0)
                    fh.truncate(0)
                    fh.write("\n".join(kept) + ("\n" if kept else ""))
                    fh.flush()
                    os.fsync(fh.fileno())
                finally:
                    _unlock_outbox_handle(fh)
    except Exception:  # noqa: BLE001
        pass


# BF3-02：按设备+终端实例令牌记录释放失败，不能以 device_id 误伤新会话。
TERMINAL_RELEASE_FAILURES: dict[int, set[str]] = {}


def mark_terminal_release_failure(device_id: int, token: str = "") -> None:
    TERMINAL_RELEASE_FAILURES.setdefault(int(device_id), set()).add(str(token or ""))
    _append_release_outbox(device_id, token)


def clear_terminal_release_failure(device_id: int, token: str = "") -> None:
    key = int(device_id)
    if key in TERMINAL_RELEASE_FAILURES:
        TERMINAL_RELEASE_FAILURES[key].discard(str(token or ""))
        if not TERMINAL_RELEASE_FAILURES[key]:
            TERMINAL_RELEASE_FAILURES.pop(key, None)
    _clear_release_outbox(device_id, token)
MAX_RAW_EXCERPT = 2000

_ACTION_ALIASES = {
    "observe_interfaces": "interface_brief",
    "observe_ospf_peer": "ospf_peer",
    "observe_ospf_route": "ospf_route",
}

READ_ONLY_ACTIONS: dict[str, dict[str, Any]] = {
    "interface_brief": {
        "label": "接口状态与地址",
        "command": "display ip interface brief",
        "action": "observe_interfaces",
        "action_id": "interface_brief",
        "risk": "read_only",
    },
    "ospf_peer": {
        "label": "OSPF 邻居",
        "command": "display ospf peer",
        "action": "observe_ospf_peer",
        "action_id": "ospf_peer",
        "risk": "read_only",
    },
    "ospf_route": {
        "label": "OSPF 路由",
        "command": "display ospf routing",
        "action": "observe_ospf_route",
        "action_id": "ospf_route",
        "risk": "read_only",
    },
}

PAGE_CATALOG = [
    {"page_id": "dashboard", "route": "/dashboard", "label": "工作台", "group": "工作台", "actions": ["observe_interfaces", "open_report"]},
    {"page_id": "devices", "route": "/devices", "label": "设备", "group": "设备与变更", "actions": ["observe_interfaces", "observe_ospf_peer", "observe_ospf_route"]},
    {"page_id": "environments", "route": "/environments", "label": "环境映射", "group": "设备与变更", "roles": ["admin"], "actions": ["preflight_environment", "update_environment"]},
    {"page_id": "topology", "route": "/topology", "label": "拓扑", "group": "总览", "actions": ["observe_interfaces", "check_lldp_runtime"]},
    {"page_id": "webssh", "route": "/webssh", "label": "终端", "group": "设备与变更", "actions": []},
    {"page_id": "deploy", "route": "/deploy", "label": "配置下发", "group": "设备与变更", "actions": ["deploy_preview", "deploy_confirm", "deploy_execute"]},
    {"page_id": "approvals", "route": "/approvals", "label": "变更审批", "group": "设备与变更", "actions": ["approval_confirm"]},
    {"page_id": "config_versions", "route": "/config-versions", "label": "配置版本", "group": "设备与变更", "actions": ["view_snapshot", "compare_saved_configs"]},
    {"page_id": "training", "route": "/training", "label": "实训", "group": "工具", "actions": ["start_session", "log_operation", "verify_training_step", "bind_training_environment", "open_report", "generate_report"]},
    {"page_id": "knowledge", "route": "/knowledge", "label": "知识库", "group": "工具", "actions": ["knowledge_catalog", "read_knowledge_document"]},
    {"page_id": "monitor", "route": "/monitor", "label": "监控", "group": "观测", "actions": ["read_port_observation", "save_port_expectations"]},
    {"page_id": "alarms", "route": "/alarms", "label": "告警", "group": "观测", "actions": []},
    {"page_id": "system_info", "route": "/system/info", "label": "系统信息", "group": "系统", "roles": ["admin"], "actions": []},
    {"page_id": "system_config", "route": "/system/config", "label": "系统配置", "group": "系统", "roles": ["admin"], "actions": ["read_effective_config", "test_model_connectivity", "update_config"]},
    {"page_id": "system_audit", "route": "/system/audit", "label": "审计日志", "group": "系统", "roles": ["admin"], "actions": []},
    {"page_id": "system_tasks", "route": "/system/tasks", "label": "后台任务", "group": "系统", "roles": ["admin"], "actions": []},
    {"page_id": "system_logs", "route": "/system/logs", "label": "日志文件", "group": "系统", "roles": ["admin"], "actions": []},
]

ACTION_CATALOG = [
    {"action_id":"read_effective_config","label":"刷新配置快照","method":"GET","path":"/api/v1/system/effective-config","risk":"read_only","roles":["admin"],"ownership":"admin","params":[],"handler":"GET /system/effective-config","cost":"none","device_effect":"none","side_effects":"none"},
    {"action_id":"test_model_connectivity","label":"测试模型连通性","method":"POST","path":"/api/v1/system/llm-health","risk":"read_only","roles":["admin"],"ownership":"admin","params":[],"handler":"POST /system/llm-health","cost":"provider_probe","device_effect":"none","side_effects":"writes_audit"},
    {"action_id": "check_lldp_runtime", "label": "运行态校验", "method": "POST", "path": "/api/v1/topologies/{id}/discover", "risk": "read_only", "roles": ["admin"], "ownership": "admin", "params": ["id"], "handler": "POST /topologies/{id}/discover", "cost": "device_read", "device_effect": "read_only", "side_effects": "writes_local_evidence"},
    {"action_id": "knowledge_catalog", "label": "资料目录", "method": "GET", "path": "/api/v1/ai/knowledge/catalog", "risk": "read_only", "roles": ["admin", "user"], "ownership": "any_authenticated", "params": [], "handler": "GET /ai/knowledge/catalog", "cost": "none", "device_effect": "none", "side_effects": "none"},
    {"action_id": "read_knowledge_document", "label": "阅读全文", "method": "GET", "path": "/api/v1/ai/knowledge/read", "risk": "read_only", "roles": ["admin", "user"], "ownership": "any_authenticated", "resource_scope": "current_workspace_document", "params": ["document_id", "filename", "version"], "handler": "GET /ai/knowledge/read", "cost": "none", "device_effect": "none", "side_effects": "none"},
    {"action_id": "read_port_observation", "label": "查看端口观察", "method": "GET", "path": "/api/v1/monitor/ports/{device_id}", "risk": "read_only", "roles": ["admin", "user"], "ownership": "any_authenticated", "params": ["device_id"], "handler": "GET /monitor/ports/{device_id}", "cost": "none", "device_effect": "none", "side_effects": "none"},
    {"action_id": "save_port_expectations", "label": "保存本地期望", "method": "PUT", "path": "/api/v1/monitor/ports/{device_id}/expectations", "risk": "local_write", "roles": ["admin"], "ownership": "admin", "params": ["device_id", "base_revision", "ports"], "handler": "PUT /monitor/ports/{device_id}/expectations", "cost": "none", "device_effect": "none", "side_effects": "writes_local_expectations_audit"},
    {"action_id": "observe_interfaces", "label": "采集接口只读事实", "method": "POST", "path": "/api/v1/trust/observations", "risk": "read_only", "roles": ["admin", "user"], "ownership": "any_authenticated", "params": ["device_id", "environment_id", "action_id"], "param_defaults": {"action_id": "interface_brief"}, "handler": "POST /trust/observations", "cost": "device_read", "device_effect": "read_only", "side_effects": "writes_local_evidence"},
    {"action_id": "observe_ospf_peer", "label": "采集 OSPF 邻居", "method": "POST", "path": "/api/v1/trust/observations", "risk": "read_only", "roles": ["admin", "user"], "ownership": "any_authenticated", "params": ["device_id", "environment_id", "action_id"], "param_defaults": {"action_id": "ospf_peer"}, "handler": "POST /trust/observations", "cost": "device_read", "device_effect": "read_only", "side_effects": "writes_local_evidence"},
    {"action_id": "observe_ospf_route", "label": "采集 OSPF 路由", "method": "POST", "path": "/api/v1/trust/observations", "risk": "read_only", "roles": ["admin", "user"], "ownership": "any_authenticated", "params": ["device_id", "environment_id", "action_id"], "param_defaults": {"action_id": "ospf_route"}, "handler": "POST /trust/observations", "cost": "device_read", "device_effect": "read_only", "side_effects": "writes_local_evidence"},
    {"action_id": "preflight_environment", "label": "预检环境映射", "method": "POST", "path": "/api/v1/trust/environments/{id}/preflight", "risk": "read_only", "roles": ["admin"], "ownership": "admin", "params": ["id"], "handler": "POST /trust/environments/{id}/preflight", "cost": "device_read", "device_effect": "read_only", "side_effects": "writes_preflight_status"},
    {"action_id": "update_environment", "label": "修改环境映射", "method": "PUT", "path": "/api/v1/trust/environments/{id}", "risk": "system_write", "roles": ["admin"], "ownership": "admin", "params": ["id", "devices", "protections", "expected_neighbors", "expected_routes"], "handler": "PUT /trust/environments/{id}", "cost": "none", "device_effect": "none", "side_effects": "invalidates_preflight"},
    {"action_id": "generate_report", "label": "生成复盘报告", "method": "POST", "path": "/api/v1/training/sessions/{id}/report/generate", "risk": "model_call", "roles": ["admin", "user"], "ownership": "owner_or_admin", "params": ["id", "regenerate"], "handler": "POST /training/sessions/{id}/report/generate", "cost": "model_call", "device_effect": "none", "side_effects": "new_report_version"},
    {"action_id": "open_report", "label": "查看已保存复盘", "method": "GET", "path": "/api/v1/training/sessions/{id}/report", "risk": "read_only", "roles": ["admin", "user"], "ownership": "owner_or_admin", "params": ["id"], "handler": "GET /training/sessions/{id}/report", "cost": "none", "device_effect": "none", "side_effects": "none"},
    {"action_id": "start_session", "label": "开始实训会话", "method": "POST", "path": "/api/v1/training/sessions", "risk": "training_state", "roles": ["admin", "user"], "ownership": "any_authenticated", "params": ["lab_id"], "handler": "POST /training/sessions", "cost": "none", "device_effect": "none", "side_effects": "creates_session"},
    {"action_id": "verify_training_step", "label": "核对本步", "method": "POST", "path": "/api/v1/training/sessions/{id}/steps/{step_id}/verify", "risk": "read_only", "roles": ["admin", "user"], "ownership": "owner_or_admin", "params": ["id", "step_id", "observation_ids"], "handler": "POST /training/sessions/{id}/steps/{step_id}/verify", "cost": "none", "device_effect": "none", "side_effects": "none"},
    {"action_id": "bind_training_environment", "label": "保存环境绑定", "method": "PUT", "path": "/api/v1/training/labs/{id}/environment", "risk": "training_state", "roles": ["admin"], "ownership": "admin", "params": ["id", "environment_id"], "handler": "PUT /training/labs/{id}/environment", "cost": "none", "device_effect": "none", "side_effects": "binds_new_sessions_only"},
    {"action_id": "log_operation", "label": "记录实训操作", "method": "POST", "path": "/api/v1/training/sessions/{id}/log", "risk": "training_state", "roles": ["admin", "user"], "ownership": "owner_or_admin", "params": ["id", "action", "target_device", "command", "result", "success", "meta"], "handler": "POST /training/sessions/{id}/log", "cost": "none", "device_effect": "none", "side_effects": "append_log"},
    {"action_id": "view_snapshot", "label": "查看配置版本", "method": "GET", "path": "/api/v1/config-versions", "risk": "read_only", "roles": ["admin", "user"], "ownership": "any_authenticated", "params": ["device_id"], "handler": "GET /config-versions", "cost": "none", "device_effect": "none", "side_effects": "none"},
    {"action_id": "compare_saved_configs", "label": "比对快照", "method": "GET", "path": "/api/v1/config-versions/compare", "risk": "read_only", "roles": ["admin", "user"], "ownership": "any_authenticated", "params": ["version1", "version2"], "handler": "GET /config-versions/compare", "cost": "none", "device_effect": "none", "side_effects": "none"},
    {"action_id": "deploy_preview", "label": "校验配置草稿", "method": "POST", "path": "/api/v1/deploy/validate", "risk": "read_only", "roles": ["admin", "user"], "ownership": "any_authenticated", "params": ["config_content", "device_model"], "handler": "POST /deploy/validate", "cost": "none", "device_effect": "none", "side_effects": "none"},
    {"action_id": "deploy_confirm", "label": "确认下发", "method": "POST", "path": "/api/v1/deploy/tasks/{id}/confirm", "risk": "device_write", "roles": ["admin", "user"], "ownership": "owner_or_admin", "params": ["id", "risk_confirm"], "handler": "POST /deploy/tasks/{id}/confirm", "cost": "none", "device_effect": "none", "side_effects": "acquires_device_lock"},
    {"action_id": "deploy_execute", "label": "执行下发", "method": "POST", "path": "/api/v1/deploy/tasks/{id}/execute", "risk": "device_write", "roles": ["admin", "user"], "ownership": "owner_or_admin", "params": ["id"], "handler": "POST /deploy/tasks/{id}/execute", "cost": "device_write", "device_effect": "write", "side_effects": "writes_device"},
    {"action_id": "approval_confirm", "label": "审批结论/确认下发", "method": "POST", "path": "/api/v1/deploy/tasks/{id}/confirm", "risk": "device_write", "roles": ["admin"], "ownership": "admin_cross_owner", "params": ["id", "risk_confirm"], "handler": "POST /deploy/tasks/{id}/confirm", "cost": "none", "device_effect": "none", "side_effects": "acquires_device_lock"},
    {"action_id": "update_config", "label": "更新系统配置", "method": "PUT", "path": "/api/v1/system/config/{key}", "risk": "system_write", "roles": ["admin"], "ownership": "admin", "params": ["key", "value"], "handler": "PUT /system/config/{key}", "cost": "none", "device_effect": "none", "side_effects": "system_config"},
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def environment_hash(row: EnvironmentProfile) -> str:
    return hashlib.sha256(_canonical({
        "name": row.name, "version": row.version, "site": row.site or "",
        "devices": row.devices or [], "protections": row.protections or [],
        "expected": row.expected or {},
    }).encode("utf-8")).hexdigest()


def serialize_environment(row: EnvironmentProfile) -> dict:
    expected = row.expected or {}
    return {
        "id": row.id, "name": row.name, "version": row.version, "site": row.site or "",
        "status": row.status, "devices": row.devices or [], "protections": row.protections or [],
        "expected_neighbors": expected.get("neighbors") or [], "expected_routes": expected.get("routes") or [],
        "source": row.source, "revision": int(row.revision or 1),
        "content_hash": row.content_hash or environment_hash(row),
        "last_preflight_status": row.last_preflight_status or "",
        "last_preflight_mode": row.last_preflight_mode or "",
        "last_preflight_at": iso_utc(row.last_preflight_at) if row.last_preflight_at else "",
        "updated_at": iso_utc(row.updated_at or row.created_at),
    }


def _redact(text: str) -> str:
    text = text or ""
    text = re.sub(r"(?i)(password|passwd|secret|community|api[_-]?key|token)\s*[:=]\s*\S+", r"\1=[REDACTED]", text)
    if len(text) > MAX_RAW_EXCERPT:
        return text[:MAX_RAW_EXCERPT] + "\n[truncated]"
    return text


def serialize_observation(row: ReadOnlyObservation) -> dict:
    return {
        "id": row.id, "environment_id": row.environment_id,
        "environment_version": row.environment_version or "",
        "environment_snapshot": row.environment_snapshot or {},
        "device_id": row.device_id, "action_id": row.action_id, "command": row.command,
        "collected_at": iso_utc(row.collected_at), "source": row.source, "mode": row.mode,
        "adapter_mode": row.adapter_mode or "unknown", "completeness": row.completeness,
        "parser_version": row.parser_version, "facts": row.facts or {},
        "raw_excerpt": row.raw_excerpt or "", "status": row.status,
        "error_message": row.error_message or "",
    }


def detect_incomplete(output: str) -> bool:
    return bool(re.search(r"(-{2,}\s*More\s*-{2,}|--\s*More\s*--|<\s*More\s*>|Press any key)", output or "", re.I))


def detect_cli_error(output: str) -> bool:
    return bool(re.search(r"(^|\n)\s*(Error\s*:|Unrecognized command|Invalid input|Failure\s*:|%\s*(Error|Invalid))", output or "", re.I))


def _normalize_ifname(value: str) -> str:
    name = (value or "").strip()
    aliases = ((r"^GE(?=\d)", "GigabitEthernet"), (r"^Gig(?=\d)", "GigabitEthernet"),
               (r"^Eth(?=\d)", "Ethernet"), (r"^Loop(?=\d)", "LoopBack"))
    for pattern, prefix in aliases:
        name = re.sub(pattern, prefix, name, flags=re.I)
    return name.lower()


def parse_interface_brief(output: str) -> dict:
    interfaces = []
    for line in (output or "").splitlines():
        text = line.strip()
        if not text or re.match(r"^(Interface|PHY|display|GigabitEthernet\s+PHY)", text, re.I):
            continue
        parts = re.split(r"\s+", text)
        if len(parts) < 2:
            continue
        name = parts[0]
        if not re.search(r"(ge|gigabitethernet|loopback|ethernet|vlan|eth-trunk)", name, re.I):
            continue
        addresses = [part for part in parts[1:] if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?$", part)]
        # Both physical and protocol columns must be up. VRP IP brief places
        # the address first; older physical-brief fixtures placed it last.
        # up(s) is a valid spoofed protocol state (for example LoopBack).
        states = [m[1].lower() for part in parts[1:]
                  if (m := re.fullmatch(r"\*?(up|down)(?:\([a-z]+\))?", part, re.I))][:2]
        state = "down" if "down" in states else "up" if states == ["up", "up"] else "unknown"
        interfaces.append({"name": name, "state": state, "address": addresses[0] if addresses else ""})
    return {"interfaces": interfaces}


def parse_ospf_peer(output: str) -> dict:
    peers = []
    pending_neighbor = None
    for line in (output or "").splitlines():
        text = line.strip()
        # `display ospf peer` uses separate Router ID and State lines. Do not
        # confuse the process's own Router ID, DR or interface address with it.
        detail = re.match(r"^Router\s+ID\s*:\s*(\d{1,3}(?:\.\d{1,3}){3})\b", text, re.I)
        if detail:
            pending_neighbor = detail[1]
        detail_state = re.search(r"\bState\s*:\s*(Full|2-Way|Init|ExStart|Exchange|Loading|Down)\b", text, re.I)
        if detail_state and pending_neighbor:
            state = next(s for s in ("Full", "2-Way", "Init", "ExStart", "Exchange", "Loading", "Down")
                         if s.lower() == detail_state[1].lower())
            peers.append({"neighbor_id": pending_neighbor, "state": state})
            pending_neighbor = None
            continue
        if re.match(r"^(?:OSPF Process|Area\s)", text, re.I):
            pending_neighbor = None
        if not text or re.search(r"(Router ID|Neighbor brief|Area |Interface\s)", text, re.I):
            continue
        ips = re.findall(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", text)
        if not ips:
            continue
        state = ""
        for token in ("Full", "2-Way", "Init", "ExStart", "Exchange", "Loading", "Down"):
            if re.search(rf"\b{re.escape(token)}\b", text):
                state = token
                break
        if state:
            peers.append({"neighbor_id": ips[0], "state": state})
    facts = {"peers": peers}
    processes = re.findall(r'^\s*OSPF\s+Process\s+(\d+)\s+with\s+Router\s+ID\s+(\d{1,3}(?:\.\d{1,3}){3})\s*$', output or '', re.I | re.M)
    counts = re.findall(r'^\s*Total\s+Peer\(s\)\s*:\s*(\d+)\s*$', output or '', re.I | re.M)
    # Only this unambiguous single-process zero is newly recognized. A blank
    # table, multiple process scopes, errors or paging remain insufficient.
    if (not peers and len(processes) == 1 and counts == ['0']
            and not detect_cli_error(output) and not detect_incomplete(output)):
        process, router = processes[0]
        facts['reported_peer_counts'] = [{'process_id': int(process), 'router_id': router, 'peer_count': 0}]
    return facts


def parse_ospf_routes(output: str) -> dict:
    routes = []
    for line in (output or "").splitlines():
        text = line.strip()
        dest = re.match(r"^(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})\s+(.*)$", text)
        if not dest:
            continue
        rest = dest.group(2)
        ips = re.findall(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", rest)
        routes.append({"destination": dest.group(1), "next_hop": ips[0] if ips else ""})
    return {"routes": routes}


PARSERS = {
    "interface_brief": parse_interface_brief,
    "ospf_peer": parse_ospf_peer,
    "ospf_route": parse_ospf_routes,
}


def _adapter_mode() -> str:
    from engines.device_adapter import get_device_mode
    return "sim" if get_device_mode() == "sim" else "real"


def _normalize_action(action_id: str) -> str:
    return _ACTION_ALIASES.get(action_id, action_id)


def _attachment_matches(row: ReadOnlyObservation, device_id: int | None, environment_id: int | None) -> bool:
    if device_id is not None and row.device_id != device_id:
        return False
    if environment_id is not None and row.environment_id != environment_id:
        return False
    return True


async def _read_interface_facts(device: Device) -> tuple[dict, str, str, str, list[dict]]:
    """返回 (facts, raw, status, completeness, checks)。adapter 模式由当前配置决定。"""
    from engines.device_adapter import get_device_adapter

    adapter_mode = _adapter_mode()
    checks: list[dict[str, Any]] = [{"check": "adapter", "status": "simulated" if adapter_mode == "sim" else "ok", "detail": f"adapter_mode={adapter_mode}"}]
    adapter = None
    try:
        adapter = await get_device_adapter(device)
        output = await adapter.run_command("display ip interface brief")
        output = "" if output is None else str(output)
    except Exception as exc:  # noqa: BLE001
        checks.append({"check": "reachability", "status": "unreachable", "detail": f"只读采集失败：{type(exc).__name__}: {exc}"[:240]})
        return {}, "", "unreachable", "error", checks
    finally:
        if adapter is not None:
            try:
                await adapter.close()
            except Exception:  # noqa: BLE001
                pass
    if detect_cli_error(output):
        checks.append({"check": "completeness", "status": "error", "detail": "输出包含 CLI 错误，不能作为完整事实"})
        return PARSERS["interface_brief"](output), output, "error", "partial", checks
    if detect_incomplete(output):
        checks.append({"check": "completeness", "status": "partial", "detail": "输出包含分页/截断标记，不能作为完整事实"})
        return PARSERS["interface_brief"](output), output, "partial", "partial", checks
    facts = PARSERS["interface_brief"](output)
    if not facts.get("interfaces"):
        checks.append({"check": "completeness", "status": "unknown", "detail": "未解析到接口行，可能为空输出、未知平台或权限不足"})
        return facts, output, "unknown", "empty", checks
    checks.append({"check": "observation", "status": "ok", "detail": f"解析到 {len(facts['interfaces'])} 个接口"})
    return facts, output, "ok", "complete", checks


async def preflight_environment(db: AsyncSession, env: EnvironmentProfile, user_id: int | None = None) -> dict:
    checks: list[dict[str, Any]] = []
    devices = env.devices or []
    adapter_mode = _adapter_mode()
    if not isinstance(devices, list) or not devices:
        checks.append({"check": "mapping", "status": "mismatch", "detail": "环境没有设备/角色映射"})
        env.status = "mismatch"
        env.last_preflight_status = "mismatch"
        env.last_preflight_at = _now()
        await db.commit()
        return {"environment_id": env.id, "version": env.version, "status": "mismatch", "checks": checks,
                "checked_at": iso_utc(_now()), "verification_mode": adapter_mode, "real_device_verified": False,
                "environment_revision": int(env.revision or 1)}

    protections = env.protections or []
    allowed_kinds = {"mgmt_port", "uplink", "loopback", "management", "unmanaged"}
    interface_target = re.compile(r"^(GE|GigabitEthernet|XGE|10GE|Eth|Ethernet|LoopBack|Vlan)\S*\d", re.I)
    bad_protections = []
    for item in protections:
        if not isinstance(item, dict):
            bad_protections.append(item)
            continue
        kind = str(item.get("kind") or "").strip()
        target = str(item.get("target") or "").strip()
        if kind not in allowed_kinds or not target or not interface_target.match(target):
            bad_protections.append(item)
    if not protections or bad_protections:
        checks.append({"check": "protection", "status": "mismatch", "detail": "保护项不能为空；kind 必须是受控值，target 必须是有效接口/受控对象"})
    else:
        checks.append({"check": "protection", "status": "ok", "detail": f"已声明 {len(protections)} 项保护"})

    statuses: list[str] = []
    all_observed_names: set[str] = set()
    observed_by_device: dict[int, set[str]] = {}
    for item in devices:
        if not isinstance(item, dict):
            statuses.append("mismatch")
            checks.append({"check": "mapping", "status": "mismatch", "detail": "设备映射项不是对象"})
            continue
        device_id = item.get("device_id")
        device = await db.get(Device, device_id) if device_id else None
        if device is None:
            statuses.append("mismatch")
            checks.append({"check": "device", "device_id": device_id, "status": "mismatch", "detail": "映射的设备不存在"})
            continue
        role = (item.get("role") or "").strip()
        if not role:
            statuses.append("mismatch")
            checks.append({"check": "role", "device_id": device.id, "status": "mismatch", "detail": "缺少角色"})
        else:
            checks.append({"check": "role", "device_id": device.id, "status": "ok", "detail": role})

        mapped_mgmt = (item.get("mgmt_ip") or "").strip()
        if mapped_mgmt and mapped_mgmt != (device.mgmt_ip or "").strip():
            statuses.append("mismatch")
            checks.append({"check": "mgmt_ip", "device_id": device.id, "status": "mismatch", "detail": f"映射管理地址 {mapped_mgmt} 与实际库存 {device.mgmt_ip} 不一致"})
        else:
            checks.append({"check": "mgmt_ip", "device_id": device.id, "status": "ok", "detail": device.mgmt_ip or "库存未登记"})

        mapped_vendor = (item.get("vendor") or "").strip()
        actual_vendor = getattr(device.vendor, "value", device.vendor)
        if mapped_vendor and actual_vendor and mapped_vendor.lower() != str(actual_vendor).lower():
            statuses.append("mismatch")
            checks.append({"check": "vendor", "device_id": device.id, "status": "mismatch", "detail": f"映射厂商 {mapped_vendor} 与实际 {actual_vendor} 不一致"})
        else:
            checks.append({"check": "vendor", "device_id": device.id, "status": "ok", "detail": str(actual_vendor or "库存未登记")})

        mapped_interfaces = item.get("interfaces") or []
        if not mapped_interfaces:
            statuses.append("mismatch")
            checks.append({"check": "interface", "device_id": device.id, "status": "mismatch", "detail": "缺少接口映射"})
            mapped_interfaces = []

        lock = await db.get(DeviceWriteLock, device.id)
        if lock is not None:
            statuses.append("busy")
            checks.append({"check": "lock", "device_id": device.id, "status": "busy", "detail": f"设备被 {lock.owner_type}/{lock.task_id} 占用，拒绝新写/新采集"})
            continue

        facts, raw, obs_status, completeness, obs_checks = await _read_interface_facts(device)
        checks.extend({**check, "device_id": device.id} for check in obs_checks)
        evidence_id = None
        if raw or facts:
            observation = ReadOnlyObservation(
                environment_id=env.id, environment_version=env.version,
                environment_snapshot=serialize_environment(env), device_id=device.id,
                action_id="interface_brief", command="display ip interface brief",
                source="server_observed", mode=adapter_mode, adapter_mode=adapter_mode,
                completeness=completeness, parser_version=PARSER_VERSION, facts=facts,
                raw_excerpt=_redact(raw), status=obs_status,
                error_message="" if obs_status == "ok" else "只读接口事实不完整或不可用",
                created_by=user_id,
            )
            db.add(observation)
            await db.flush()
            evidence_id = observation.id
        if obs_status != "ok":
            statuses.append(obs_status if obs_status in {"unreachable", "partial", "unknown"} else "unknown")
            continue
        observed = {_normalize_ifname(str(row.get("name", ""))): row for row in facts.get("interfaces", [])}
        all_observed_names.update(observed)
        observed_by_device[device.id] = set(observed)
        for iface in mapped_interfaces:
            if not isinstance(iface, dict) or not iface.get("name"):
                statuses.append("mismatch")
                checks.append({"check": "interface", "device_id": device.id, "status": "mismatch", "detail": "接口映射缺 name"})
                continue
            name = str(iface["name"]).strip()
            actual = observed.get(_normalize_ifname(name))
            if actual is None:
                statuses.append("mismatch")
                checks.append({"check": "interface", "device_id": device.id, "status": "mismatch", "detail": f"实际接口列表没有 {name}"})
                continue
            expected_addr = (iface.get("address") or "").strip()
            actual_addr = (actual.get("address") or "").strip()
            if expected_addr and expected_addr != actual_addr:
                statuses.append("mismatch")
                checks.append({"check": "interface_address", "device_id": device.id, "status": "mismatch", "detail": f"{name} 映射地址 {expected_addr}，实际 {actual_addr or '未配置'}"})
            elif actual.get("state") != "up":
                statuses.append("mismatch")
                checks.append({"check": "interface_state", "device_id": device.id, "status": "mismatch", "detail": f"{name} 实际状态 {actual.get('state')}"})
            else:
                checks.append({"check": "interface", "device_id": device.id, "status": "ok", "detail": f"{name} {actual_addr or '无地址'} 已核对", "evidence_id": evidence_id})
        if mapped_interfaces:
            checks.append({"check": "fact", "device_id": device.id, "status": "ok", "detail": f"证据 #{evidence_id}（{completeness}）", "evidence_id": evidence_id})

        if device.status == DeviceStatus.OFFLINE:
            statuses.append("unreachable")
            checks.append({"check": "reachability", "device_id": device.id, "status": "unreachable", "detail": "库存状态离线"})

    if all_observed_names:
        missing_targets = []
        device_ids = {int(item.get("device_id")) for item in devices if isinstance(item, dict) and item.get("device_id") is not None}
        roles = {str(item.get("role")): int(item.get("device_id")) for item in devices if isinstance(item, dict) and item.get("role") and item.get("device_id") is not None}
        for protection in protections:
            if not isinstance(protection, dict):
                continue
            target = _normalize_ifname(str(protection.get("target") or ""))
            pid = protection.get("device_id")
            prole = protection.get("role")
            if pid is not None and prole and str(prole) in roles and int(pid) != roles[str(prole)]:
                missing_targets.append(f"{protection.get('target') or ''}（归属冲突）")
                continue
            if pid is not None:
                owned = observed_by_device.get(int(pid))
            elif prole:
                owned = observed_by_device.get(roles.get(str(prole), -1))
            elif len(observed_by_device) == 1:
                owned = next(iter(observed_by_device.values()))
            else:
                owned = None
            if owned is None or target not in owned:
                missing_targets.append(str(protection.get("target") or ""))
        if missing_targets:
            statuses.append("mismatch")
            checks.append({"check": "protection_target", "status": "mismatch", "detail": "保护目标不存在于实际接口：" + "、".join(sorted(set(missing_targets)))})
        else:
            checks.append({"check": "protection_target", "status": "ok", "detail": "保护目标均在实际接口列表中"})
    if adapter_mode == "sim":
        checks.append({"check": "verification_mode", "status": "simulated", "detail": "模拟适配器只读事实；可核对映射，但不能宣称真实设备已通过"})
    if any(check.get("status") == "mismatch" for check in checks):
        statuses.append("mismatch")
    if "mismatch" in statuses or bad_protections:
        status = "mismatch"
    elif "unreachable" in statuses:
        status = "unreachable"
    elif "busy" in statuses:
        status = "busy"
    elif "partial" in statuses or "unknown" in statuses:
        status = "unknown"
    else:
        status = "ready"
    env.status = status
    env.last_preflight_status = status
    env.last_preflight_mode = adapter_mode
    env.last_preflight_at = _now()
    env.content_hash = environment_hash(env)
    await db.commit()
    return {"environment_id": env.id, "version": env.version, "status": status, "checks": checks,
            "checked_at": iso_utc(env.last_preflight_at), "verification_mode": adapter_mode,
            "real_device_verified": status == "ready" and adapter_mode == "real",
            "environment_revision": int(env.revision or 1)}


async def collect_observation(
    db: AsyncSession,
    *,
    user: dict,
    device_id: int,
    action_id: str,
    environment_id: int | None,
) -> ReadOnlyObservation:
    action_id = _normalize_action(action_id)
    spec = READ_ONLY_ACTIONS.get(action_id)
    if spec is None:
        raise ValueError("不支持的只读动作；只允许目录内动作，拒绝任意命令")
    device = await db.get(Device, device_id)
    if device is None:
        raise ValueError("设备不存在")
    env = None
    if environment_id is not None:
        env = await db.get(EnvironmentProfile, environment_id)
        if env is None:
            raise ValueError("环境不存在")
        mapped = {int(item.get("device_id") or 0) for item in (env.devices or []) if isinstance(item, dict)}
        if device_id not in mapped:
            raise ValueError("设备不在该环境映射中，不能把观察归到该环境")
    adapter_mode = _adapter_mode()
    row = ReadOnlyObservation(
        environment_id=environment_id, environment_version=env.version if env else None,
        environment_snapshot=serialize_environment(env) if env else None,
        device_id=device_id, action_id=action_id, command=spec["command"],
        source="server_observed", mode=adapter_mode, adapter_mode=adapter_mode,
        parser_version=PARSER_VERSION, created_by=user.get("user_id"),
    )
    adapter = None
    try:
        vendor = getattr(device.vendor, "value", device.vendor)
        if str(vendor or "").lower() not in {"huawei", "h3c", "other", ""}:
            raise ValueError(f"不支持的设备厂商/平台：{vendor}")
        from engines.device_adapter import get_device_adapter

        adapter = await get_device_adapter(device)
        output = await adapter.run_command(spec["command"])
        output = "" if output is None else str(output)
        row.raw_excerpt = _redact(output)
        if detect_cli_error(output):
            row.completeness = "partial"
            row.facts = PARSERS[action_id](output)
            row.status = "error"
            row.error_message = "输出包含 CLI 错误，不能据此判断通过"
        elif detect_incomplete(output):
            row.completeness = "partial"
            row.facts = PARSERS[action_id](output)
            row.status = "partial"
            row.error_message = "输出包含分页/截断标记，不能据此判断通过"
        else:
            facts = PARSERS[action_id](output)
            non_empty = any(value for value in facts.values())
            row.facts = facts
            row.completeness = "complete" if non_empty else "empty"
            row.status = "ok" if non_empty else "empty"
            row.error_message = "" if non_empty else "命令返回为空或未解析到事实，不能据此判断通过"
    except Exception as exc:  # noqa: BLE001
        row.completeness = "error"
        row.facts = {}
        row.status = "error"
        row.error_message = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        if adapter is not None:
            try:
                await adapter.close()
            except Exception:  # noqa: BLE001
                pass
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def _rule_result(status: str, reason: str, *, expected: dict | None = None, observed: dict | None = None,
                 missing: list | None = None, unexpected: list | None = None, ids: list | None = None,
                 mode: str = "unknown", versions: list | None = None, expected_source: str = "unknown",
                 evaluation_scope: str = "official", target_version: str = "", rejected_reason: str = "") -> dict:
    return {"status": status, "reason": reason, "expected": expected or {}, "observed": observed or {},
            "missing": missing or [], "unexpected": unexpected or [], "evidence_ids": ids or [],
            "checked_at": iso_utc(_now()), "verification_mode": mode, "evidence_versions": versions or [],
            "expected_source": expected_source, "evaluation_scope": evaluation_scope,
            "target_version": target_version, "rejected_reason": rejected_reason}


async def evaluate_ospf_rules(db: AsyncSession, payload, user: dict | None = None) -> dict:
    ids = list(payload.observation_ids) if payload.observation_ids else ([payload.observation_id] if payload.observation_id else [])
    if not ids:
        return _rule_result("insufficient_evidence", "没有提供观察证据", rejected_reason="no_evidence")
    rows = (await db.execute(select(ReadOnlyObservation).where(ReadOnlyObservation.id.in_(ids)))).scalars().all()
    by_id = {row.id: row for row in rows}
    evidence_ids = [item for item in ids if item in by_id]
    if len(evidence_ids) != len(ids):
        return _rule_result("insufficient_evidence", "部分证据不存在或无权读取", ids=evidence_ids, rejected_reason="missing_evidence")
    if user is not None and user.get("role") != "admin" and any(row.created_by != user.get("user_id") for row in rows):
        return _rule_result("insufficient_evidence", "证据不属于当前用户", ids=evidence_ids, rejected_reason="not_owner")
    env = await db.get(EnvironmentProfile, payload.environment_id) if payload.environment_id is not None else None
    if payload.environment_id is not None and env is None:
        return _rule_result("insufficient_evidence", "目标环境不存在", ids=evidence_ids, rejected_reason="missing_environment")
    versions = [{"id": row.id, "environment_id": row.environment_id, "environment_version": row.environment_version,
                 "mode": row.adapter_mode or row.mode, "parser_version": row.parser_version,
                 "collected_at": iso_utc(row.collected_at)} for row in rows]
    targets = {(row.device_id, row.environment_id) for row in rows}
    if len(targets) > 1:
        return _rule_result("not_matched", "证据混用多个设备/环境，不能合并成一个达标结论", ids=evidence_ids,
                            versions=versions, rejected_reason="mixed_targets")
    for row in rows:
        if not _attachment_matches(row, payload.device_id, payload.environment_id):
            return _rule_result("not_matched", "证据目标与请求设备/环境不一致", ids=evidence_ids,
                                versions=versions, rejected_reason="target_mismatch")
        if row.source != "server_observed":
            return _rule_result("not_matched", f"证据 {row.id} 来源 {row.source} 不是服务端观察", ids=evidence_ids,
                                versions=versions, rejected_reason="untrusted_source")
        if row.parser_version not in SUPPORTED_PARSERS:
            return _rule_result("not_matched", f"证据 {row.id} 解析器 {row.parser_version} 不受支持", ids=evidence_ids,
                                versions=versions, rejected_reason="unsupported_parser")
        if row.completeness != "complete" or row.status != "ok":
            return _rule_result("insufficient_evidence", f"证据 {row.id} 不完整或采集失败（{row.completeness}/{row.status}）", ids=evidence_ids,
                                versions=versions, rejected_reason="incomplete")
        if row.action_id not in {"ospf_peer", "ospf_route"}:
            return _rule_result("not_matched", f"证据 {row.id} 动作 {row.action_id} 不能用于 OSPF 规则", ids=evidence_ids,
                                versions=versions, rejected_reason="wrong_action")
        mode = (row.adapter_mode or row.mode or "unknown").lower()
        if mode != "real":
            if mode == "sim" and payload.allow_simulated:
                pass
            else:
                return _rule_result("not_matched", f"证据 {row.id} 模式 {mode} 不能作为正式真实验收", ids=evidence_ids,
                                    versions=versions, mode=mode, rejected_reason="untrusted_mode")
        if env is not None:
            if row.environment_id != env.id:
                return _rule_result("not_matched", "证据不属于目标环境", ids=evidence_ids, versions=versions,
                                    rejected_reason="environment_mismatch")
            if not row.environment_version:
                return _rule_result("insufficient_evidence", "证据缺少 environment_version，不能作为正式身份",
                                    ids=evidence_ids, versions=versions, target_version=env.version,
                                    rejected_reason="missing_environment_version")
            if row.environment_version != env.version:
                return _rule_result("not_matched", f"证据版本 {row.environment_version} 不是当前环境 {env.version}，只能做历史比较",
                                    ids=evidence_ids, versions=versions, target_version=env.version,
                                    rejected_reason="stale_environment_version")
            snapshot_hash = (row.environment_snapshot or {}).get("content_hash") if isinstance(row.environment_snapshot, dict) else None
            if not snapshot_hash:
                return _rule_result("insufficient_evidence", "证据缺少环境 content_hash，不能作为正式身份",
                                    ids=evidence_ids, versions=versions, target_version=env.version,
                                    rejected_reason="missing_environment_hash")
            if not env.content_hash or snapshot_hash != env.content_hash:
                return _rule_result("not_matched", "证据环境内容摘要与当前环境不一致，不能给当前版本盖章",
                                    ids=evidence_ids, versions=versions, target_version=env.version,
                                    rejected_reason="stale_environment_content")
        collected = row.collected_at
        if collected.tzinfo is None:
            collected = collected.replace(tzinfo=timezone.utc)
        age = (_now() - collected).total_seconds()
        max_age = min(max(int(payload.max_age_seconds), 1), SERVER_MAX_AGE_SECONDS)
        if age < -60:
            return _rule_result("stale", f"证据 {row.id} 时间在未来，拒绝使用", ids=evidence_ids, versions=versions,
                                rejected_reason="future_evidence")
        if age > max_age:
            return _rule_result("stale", f"证据 {row.id} 已过期（{int(age)}s > {max_age}s）", ids=evidence_ids,
                                versions=versions, rejected_reason="stale_evidence")
    observed_neighbors: set[str] = set()
    observed_routes: set[str] = set()
    for row in rows:
        facts = row.facts or {}
        if row.action_id == "ospf_peer":
            for peer in facts.get("peers", []):
                if peer.get("state") == "Full":
                    observed_neighbors.add(str(peer.get("neighbor_id", "")))
        elif row.action_id == "ospf_route":
            for route in facts.get("routes", []):
                observed_routes.add(str(route.get("destination", "")))
    server_neighbors = set((env.expected or {}).get("neighbors") or []) if env is not None else set()
    server_routes = set((env.expected or {}).get("routes") or []) if env is not None else set()
    client_neighbors = set(payload.expected_neighbors)
    client_routes = set(payload.expected_routes)
    if env is not None and (server_neighbors or server_routes):
        if (client_neighbors and client_neighbors != server_neighbors) or (client_routes and client_routes != server_routes):
            return _rule_result("not_matched", "客户端不能替换/缩减环境服务端预期；请在环境映射中维护预期",
                                ids=evidence_ids, versions=versions, expected_source="environment", target_version=env.version,
                                rejected_reason="client_expected_override")
        expected_neighbors, expected_routes = server_neighbors, server_routes
        expected_source = "environment"
        scope = "official"
    else:
        expected_neighbors, expected_routes = client_neighbors, client_routes
        expected_source = "client_ad_hoc" if (client_neighbors or client_routes) else "none"
        scope = "ad_hoc"
    if not expected_neighbors and not expected_routes:
        return _rule_result("insufficient_evidence", "没有可追溯的环境/任务预期，不能把空集合当达标",
                            ids=evidence_ids, versions=versions, expected_source=expected_source,
                            evaluation_scope=scope, target_version=env.version if env else "",
                            rejected_reason="no_expected")
    expected = {"neighbors": sorted(expected_neighbors), "routes": sorted(expected_routes)}
    observed = {"neighbors": sorted(observed_neighbors), "routes": sorted(observed_routes)}
    if not observed_neighbors and not observed_routes:
        return _rule_result("insufficient_evidence", "证据中没有可比较的 OSPF 事实", expected=expected, observed=observed,
                            ids=evidence_ids, versions=versions, expected_source=expected_source,
                            evaluation_scope=scope, target_version=env.version if env else "", rejected_reason="empty_facts")
    missing = sorted((expected_neighbors - observed_neighbors) | (expected_routes - observed_routes))
    unexpected = sorted((observed_neighbors - expected_neighbors) | (observed_routes - expected_routes))
    if missing or unexpected:
        return _rule_result("not_matched", "预期对象与实际观察不一致", expected=expected, observed=observed,
                            missing=missing, unexpected=unexpected, ids=evidence_ids, versions=versions,
                            expected_source=expected_source, evaluation_scope=scope,
                            target_version=env.version if env else "", rejected_reason="objects_mismatch")
    modes = {(row.adapter_mode or row.mode or "unknown").lower() for row in rows}
    mode = "real" if modes == {"real"} else ("sim" if modes <= {"sim"} else "unknown")
    return _rule_result("satisfied", "预期对象全部匹配，来源/目标/版本/完整性/新鲜度一致",
                        expected=expected, observed=observed, ids=evidence_ids, versions=versions, mode=mode,
                        expected_source=expected_source, evaluation_scope=scope,
                        target_version=env.version if env else "")


async def list_locks(db: AsyncSession, user: dict | None = None) -> list[dict]:
    await reconcile_terminal_locks(db)
    rows = (await db.execute(select(DeviceWriteLock))).scalars().all()
    result = []
    for lock in rows:
        device = await db.get(Device, lock.device_id)
        task = await db.get(DeployTask, lock.task_id) if lock.task_id else None
        now = _now()
        stale = bool(lock.expire_at and lock.expire_at.replace(tzinfo=timezone.utc) < now)
        failed_tokens = TERMINAL_RELEASE_FAILURES.get(int(lock.device_id), set())
        durable_failed = _token_fingerprint(lock.owner_token or "") in _pending_release_tokens(lock.device_id)
        memory_failed = bool((lock.owner_token and lock.owner_token in failed_tokens) or (not lock.owner_token and "" in failed_tokens) or durable_failed)
        if memory_failed and lock.release_state != "failed":
            # BF4-01：内存只是触发信号；首次可读时落持久状态，进程重启后仍可恢复。
            lock.release_state = "failed"
            lock.state = lock.state or "closed"
            lock.release_error = lock.release_error or "release task failed"
            await db.commit()
        state = (lock.state or "").lower()
        last_seen = lock.last_seen_at or lock.created_at
        live = bool(state == "active" and last_seen and (now - last_seen.replace(tzinfo=timezone.utc)).total_seconds() <= TERMINAL_ACTIVE_GRACE_SECONDS)
        release_failed = bool(lock.release_state == "failed" or memory_failed)
        orphaned = bool(state in {"closed", "orphaned"} or (not state and stale))
        task_done = bool(task and task.status in (DeployStatus.SUCCESS, DeployStatus.FAILED, DeployStatus.CANCELLED))
        recovery = bool(release_failed or orphaned or task_done)
        owner_id = lock.owner_id if lock.owner_id is not None else (task.operator_id if task else None)
        owner_type = lock.owner_type or ("deploy" if task else "unknown")
        same_owner = bool(user and owner_id == user.get("user_id"))
        result.append({
            "device_id": lock.device_id, "hostname": device.hostname if device else "",
            "task_id": lock.task_id, "lock_type": lock.lock_type, "owner_type": owner_type,
            "owner_id": owner_id, "owner": f"{owner_type}#{owner_id}" if owner_id else owner_type,
            "created_at": iso_utc(lock.created_at), "expire_at": iso_utc(lock.expire_at) if lock.expire_at else "",
            "last_seen_at": iso_utc(last_seen) if last_seen else "",
            "state": state or "legacy", "live": live, "stale": stale,
            "recovery_required": recovery,
            "readable": True,
            "can_continue": bool(same_owner and state == "active" and live and not recovery),
            "writable": False,
            "new_write_allowed": False,
            "reason": "release_failed" if release_failed else ("orphaned" if orphaned else ("recovery_required" if recovery else "occupied")),
        })
    return result


async def _audit_lock(db: AsyncSession, user: dict | None, action: str, device_id: int, detail: dict, result: str = "success", commit: bool = True) -> bool:
    if not user:
        return True
    from modules.auth.service import AuditService
    try:
        await AuditService.log(db, user_id=user.get("user_id") or 0, username=user.get("username") or "unknown",
                               module="trust", action=action, resource_type="device_write_lock",
                               resource_id=str(device_id), detail=detail, result=result, commit=commit)
    except Exception:
        if result == "success" or commit is False:
            raise
        return False
    return True


async def recover_terminal_lock(db: AsyncSession, device_id: int, user: dict) -> dict:
    """BF4-01：只恢复已关闭/释放失败/旧孤儿；活动或未知活动状态拒绝。"""
    from sqlalchemy import delete
    from modules.deploy.models import DeviceWriteLock
    lock = await db.get(DeviceWriteLock, device_id)
    if lock is None:
        return {"released": False, "reason": "no_lock", "idempotent": True}
    if (lock.owner_type or "") != "terminal":
        return {"released": False, "reason": "not_terminal_lock"}
    now = _now()
    stale = bool(lock.expire_at and lock.expire_at.replace(tzinfo=timezone.utc) < now)
    state = (lock.state or "").lower()
    last_seen = lock.last_seen_at or lock.created_at
    live = bool(state == "active" and last_seen and (now - last_seen.replace(tzinfo=timezone.utc)).total_seconds() <= TERMINAL_ACTIVE_GRACE_SECONDS)
    failed_tokens = TERMINAL_RELEASE_FAILURES.get(int(device_id), set())
    durable_failed = _token_fingerprint(lock.owner_token or "") in _pending_release_tokens(device_id)
    failed = bool(lock.release_state == "failed" or durable_failed or (lock.owner_token and lock.owner_token in failed_tokens) or (not lock.owner_token and "" in failed_tokens))
    if live and not failed:
        await _audit_lock(db, user, "terminal_lock_recover_rejected", device_id, {"reason": "active", "state": state}, "rejected")
        return {"released": False, "reason": "active_terminal_requires_disconnect"}
    if state and state not in {"closed", "orphaned"} and not failed:
        await _audit_lock(db, user, "terminal_lock_recover_rejected", device_id, {"reason": "state_unknown", "state": state}, "rejected")
        return {"released": False, "reason": "active_state_unknown_requires_disconnect"}
    if not stale and not failed and state not in {"orphaned", "closed"}:
        await _audit_lock(db, user, "terminal_lock_recover_rejected", device_id, {"reason": "not_stale_or_failed", "state": state}, "rejected")
        return {"released": False, "reason": "active_terminal_requires_disconnect"}
    condition = (DeviceWriteLock.owner_token == lock.owner_token) if lock.owner_token else DeviceWriteLock.owner_token.is_(None)
    # BF9/R9：资格检查与删除之间必须原子校验“检查时的恢复依据”。token 不变
    # 不代表状态没变：同 token 被改回 active、租期/活动时间被刷新后，旧检查结论作废。
    # 先固定检查时的快照，后续审计 hook / 并发写不能改写本次删除条件。
    expected = {
        "state": lock.state,
        "release_state": lock.release_state,
        "last_seen_at": lock.last_seen_at,
        "expire_at": lock.expire_at,
    }

    def _same(column, value):
        return column.is_(None) if value is None else column == value

    try:
        # 成功审计与 DELETE 同一事务：审计写入失败则不删锁。
        await _audit_lock(db, user, "terminal_lock_recovered", device_id,
                          {"reason": "release_failed" if failed else "expired_legacy_orphan", "state": state or "legacy"}, "success", commit=False)
        result = await db.execute(delete(DeviceWriteLock).where(
            DeviceWriteLock.device_id == device_id,
            DeviceWriteLock.owner_type == "terminal",
            condition,
            _same(DeviceWriteLock.state, expected["state"]),
            _same(DeviceWriteLock.release_state, expected["release_state"]),
            _same(DeviceWriteLock.last_seen_at, expected["last_seen_at"]),
            _same(DeviceWriteLock.expire_at, expected["expire_at"]),
        ))
        if result.rowcount != 1:
            await db.rollback()
            return {"released": False, "reason": "lock_changed"}
        await db.commit()
    except Exception:
        await db.rollback()
        return {"released": False, "reason": "audit_failed",
                "status": "error", "detail": "审计写入失败，锁未释放"}
    clear_terminal_release_failure(device_id, lock.owner_token or "")
    return {"released": True, "reason": "release_failure_recovered" if failed else "expired_legacy_orphan", "device_id": device_id}
