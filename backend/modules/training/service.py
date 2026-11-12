"""实训模块服务

包含7种故障场景、复盘参考明细(操作规范60%+故障排除30%+用时10%)、
独立Lab模式和JSON Lines操作日志。
客户端上报记录不构成技能达标证据，不据此生成综合技能成绩。
"""
import asyncio
from copy import deepcopy
import json
import re
from datetime import datetime, timezone
from functools import wraps
from typing import Optional
from weakref import WeakValueDictionary

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logger import get_logger
from core.time_utils import iso_utc
from modules.training.mode_facts import build_mode_snapshot, current_mode_facts
from modules.device.models import Device
from modules.training.models import (
    FaultType, FaultInjection, LabStatus, OperationLog,
    TrainingLab, TrainingSession,
)

logger = get_logger("training")

# SQLite does not implement FOR UPDATE. Serialize writes within the application
# process as well; MySQL row locks below protect writes across worker processes.
_session_write_locks: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()


def _session_write_lock(session_id: int) -> asyncio.Lock:
    return _session_write_locks.setdefault(session_id, asyncio.Lock())


# AF-07：复盘生成只与其他复盘生成串行，不能占用会话写锁——
# 否则模型调用期间学员无法结束/放弃会话或追加记录（实测会死锁）。
_report_write_locks: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()


def _report_write_lock(session_id: int) -> asyncio.Lock:
    return _report_write_locks.setdefault(session_id, asyncio.Lock())


def _serialize_session_write(method):
    @wraps(method)
    async def guarded(db, session_id, *args, **kwargs):
        async with _session_write_lock(session_id):
            return await method(db, session_id, *args, **kwargs)
    return guarded


UNVERIFIED_NOTE = "技能达标未验证：操作记录由客户端上报，仅供复盘；参考明细不构成技能成绩或通过判定。"

# ── 7种故障注入模板 ───────────────────────────────────────────────────
# 每个故障包含: inject(注入命令), rollback(回滚命令), verify(验证命令)
FAULT_TEMPLATES: dict[FaultType, dict] = {
    FaultType.INTERFACE_SHUTDOWN: {
        "description": "接口shutdown导致链路中断",
        "inject": [
            "interface {interface}",
            "shutdown",
        ],
        "rollback": [
            "interface {interface}",
            "undo shutdown",
        ],
        "verify": [
            "display interface {interface} | include {interface}",
        ],
    },
    FaultType.OSPF_NEIGHBOR_DOWN: {
        "description": "OSPF邻居关系断开",
        "inject": [
            "interface {interface}",
            "undo ospf {process_id} area {area_id}",
        ],
        "rollback": [
            "interface {interface}",
            "ospf {process_id} area {area_id}",
        ],
        "verify": [
            "display ospf peer",
        ],
    },
    FaultType.VLAN_MISMATCH: {
        "description": "VLAN配置错误导致二层隔离",
        "inject": [
            "interface {interface}",
            "port link-type access",
            "port default vlan {wrong_vlan}",
        ],
        "rollback": [
            "interface {interface}",
            "port default vlan {correct_vlan}",
        ],
        "verify": [
            "display vlan {correct_vlan}",
        ],
    },
    FaultType.ACL_BLOCK: {
        "description": "ACL策略阻断合法流量",
        "inject": [
            "acl {acl_number}",
            "rule deny ip source any destination any",
        ],
        "rollback": [
            "undo acl {acl_number}",
        ],
        "verify": [
            "display acl {acl_number}",
        ],
    },
    FaultType.ROUTE_BLACKHOLE: {
        "description": "静态路由指向不可达下一跳形成路由黑洞",
        "inject": [
            "ip route-static {dest_network} {dest_mask} {blackhole_nexthop}",
        ],
        "rollback": [
            "undo ip route-static {dest_network} {dest_mask} {blackhole_nexthop}",
            "ip route-static {dest_network} {dest_mask} {correct_nexthop}",
        ],
        "verify": [
            "display ip routing-table {dest_network}",
        ],
    },
    FaultType.MTU_MISMATCH: {
        "description": "MTU不匹配导致大包丢弃",
        "inject": [
            "interface {interface}",
            "mtu {wrong_mtu}",
        ],
        "rollback": [
            "interface {interface}",
            "mtu {correct_mtu}",
        ],
        "verify": [
            "display interface {interface} | include MTU",
        ],
    },
    FaultType.DNS_FAULT: {
        "description": "DNS配置错误导致域名解析失败",
        "inject": [
            "dns resolve",
            "dns server {wrong_dns}",
        ],
        "rollback": [
            "undo dns server {wrong_dns}",
            "dns server {correct_dns}",
        ],
        "verify": [
            "display dns server",
        ],
    },
}

# ── 评分权重 ──────────────────────────────────────────────────────────
DEFAULT_SCORING = {
    "operation_weight": 0.60,
    "fault_weight": 0.30,
    "time_weight": 0.10,
    "pass_threshold": 60,
}


class TrainingService:
    """实训核心服务"""

    # ── Lab 管理 ──────────────────────────────────────────────────────
    @staticmethod
    async def create_lab(
        db: AsyncSession,
        title: str,
        description: str,
        topology_id: int,
        instructor_id: int,
        objectives: list | None = None,
        scoring_rules: dict | None = None,
        time_limit_minutes: int = 60,
        is_sandbox: bool = False,
    ) -> TrainingLab:
        lab = TrainingLab(
            title=title,
            description=description,
            topology_id=topology_id,
            instructor_id=instructor_id,
            objectives=objectives,
            scoring_rules=scoring_rules or dict(DEFAULT_SCORING),
            time_limit_minutes=time_limit_minutes,
            is_sandbox=is_sandbox,
            status=LabStatus.READY,
        )
        db.add(lab)
        await db.commit()
        await db.refresh(lab)
        return lab

    _UPDATABLE_LAB_FIELDS = frozenset({
        "title", "description", "status", "objectives",
        "scoring_rules", "time_limit_minutes", "is_sandbox",
    })

    @staticmethod
    async def update_lab(db: AsyncSession, lab_id: int, **fields) -> TrainingLab:
        lab = await db.get(TrainingLab, lab_id)
        if not lab:
            raise ValueError("Lab不存在")
        for key, value in fields.items():
            if value is not None and key in TrainingService._UPDATABLE_LAB_FIELDS:
                if key == "status" and not isinstance(value, LabStatus):
                    raise ValueError(f"无效的状态值: {value}")
                setattr(lab, key, value)
        await db.commit()
        await db.refresh(lab)
        return lab

    @staticmethod
    async def get_lab(db: AsyncSession, lab_id: int) -> TrainingLab | None:
        return await db.get(TrainingLab, lab_id)

    @staticmethod
    async def list_labs(db: AsyncSession) -> list[dict]:
        result = await db.execute(select(TrainingLab))
        labs = result.scalars().all()
        return [
            {
                "id": l.id,
                "title": l.title,
                "description": l.description,
                "status": l.status.value if l.status else "draft",
                "topology_id": l.topology_id,
                "objectives": l.objectives,
                "scoring_rules": l.scoring_rules,
                "time_limit_minutes": l.time_limit_minutes,
                "is_sandbox": l.is_sandbox,
                "content_version": l.content_version,
                "environment_spec": l.environment_spec,
                "mode_facts": current_mode_facts(l),
                "created_at": iso_utc(l.created_at),
            }
            for l in labs
        ]

    @staticmethod
    async def delete_lab(db: AsyncSession, lab_id: int) -> None:
        """删除实验。

        实训会话（`training_session.lab_id`）与操作日志（`operation_log.lab_id`）都是
        NOT NULL 外键且无级联，直接删 Lab 会撞外键 → 接口 500。这里给出明确的可读错误，
        而不是把 IntegrityError 抛成 500：历史会话属于受训记录，不做静默级联删除。
        """
        lab = await db.get(TrainingLab, lab_id)
        if not lab:
            raise ValueError("Lab不存在")
        session_count = (
            await db.execute(
                select(func.count()).select_from(TrainingSession).where(TrainingSession.lab_id == lab_id)
            )
        ).scalar() or 0
        if session_count:
            raise ValueError(f"该实验下还有 {session_count} 个实训会话，请先删除会话再删除实验")
        await db.delete(lab)
        await db.commit()

    @staticmethod
    async def delete_session(db: AsyncSession, session_id: int, *, user_id: int, is_admin: bool) -> None:
        """删除实训会话（连同它的故障注入与操作日志）。

        此前没有任何删除会话的入口，而 `delete_lab` 又受会话外键约束 —— 结果“上过课的
        实验”永远删不掉。会话是受训记录，所以这里要求"本人或管理员"，并先删子行。
        """
        session = await db.get(TrainingSession, session_id)
        if not session:
            raise ValueError("会话不存在")
        if not is_admin and session.trainee_id != user_id:
            raise PermissionError("无权删除此会话")
        await db.execute(delete(FaultInjection).where(FaultInjection.session_id == session_id))
        await db.execute(delete(OperationLog).where(OperationLog.session_id == session_id))
        await db.delete(session)
        await db.commit()

    # ── 会话管理 ──────────────────────────────────────────────────────
    @staticmethod
    def content_snapshot(lab: TrainingLab) -> dict:
        """会话开始时固定实验版本与步骤，内容更新不改变历史任务。"""
        return {
            "version": lab.content_version,
            "title": lab.title,
            "objectives": deepcopy(lab.objectives or []),
            "environment_spec": deepcopy(lab.environment_spec or {}),
            "scoring_rules": deepcopy(lab.scoring_rules or {}),
        }

    @staticmethod
    async def _bind_trust_environment(db: AsyncSession, lab: TrainingLab, session: TrainingSession) -> None:
        """BF-01：有 trust 环境时冻结版本/摘要；无则保持未绑定，不猜测成已核验。"""
        spec = lab.environment_spec or {}
        if not isinstance(spec, dict):
            return
        env_id = spec.get("trust_environment_id") or spec.get("environment_id")
        if not env_id:
            return
        from modules.trust.models import EnvironmentProfile
        from modules.trust.service import serialize_environment
        env = await db.get(EnvironmentProfile, int(env_id))
        if env is None:
            return
        content = serialize_environment(env)
        session.trust_environment_id = env.id
        session.trust_environment_version = env.version
        session.trust_environment_snapshot = {
            "id": env.id, "version": env.version, "revision": int(env.revision or 1),
            "content_hash": content.get("content_hash") or "",
            "environment": content,
            "devices": content.get("devices") or [],
            "protections": content.get("protections") or [],
            "expected_neighbors": content.get("expected_neighbors") or [],
            "expected_routes": content.get("expected_routes") or [],
            "preflight": {
                "status": env.last_preflight_status or "unknown",
                "mode": env.last_preflight_mode or "unknown",
                "checked_at": content.get("last_preflight_at") or "",
            },
            "bound_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    async def start_session(db: AsyncSession, lab_id: int, trainee_id: int) -> TrainingSession:
        lab = await db.get(TrainingLab, lab_id)
        if not lab:
            raise ValueError("Lab不存在")
        if lab.status == LabStatus.DRAFT:
            raise ValueError("Lab尚未就绪，无法开始实训")

        session = TrainingSession(
            lab_id=lab_id,
            trainee_id=trainee_id,
            started_at=datetime.now(timezone.utc),
            status="in_progress",
            content_version=lab.content_version,
            content_snapshot=TrainingService.content_snapshot(lab),
            mode_snapshot=build_mode_snapshot(lab),
        )
        await TrainingService._bind_trust_environment(db, lab, session)
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session

    @staticmethod
    @_serialize_session_write
    async def complete_session(db: AsyncSession, session_id: int) -> dict:
        session = await db.get(TrainingSession, session_id, with_for_update=True, populate_existing=True)
        if not session:
            raise ValueError("会话不存在")
        if session.status == "completed":
            return {"session_id": session_id, "time_spent_seconds": session.time_spent_seconds}
        if session.status != "in_progress":
            raise ValueError("会话不在进行中")

        now = datetime.now(timezone.utc)
        session.completed_at = now
        if session.started_at:
            started_at = session.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            session.time_spent_seconds = int((now - started_at).total_seconds())
        session.status = "completed"
        await db.commit()
        return {"session_id": session_id, "time_spent_seconds": session.time_spent_seconds}

    @staticmethod
    @_serialize_session_write
    async def abandon_session(db: AsyncSession, session_id: int) -> dict:
        """放弃会话：保留记录但只读回看，不再绑定终端/教练。"""
        session = await db.get(TrainingSession, session_id, with_for_update=True, populate_existing=True)
        if not session:
            raise ValueError("会话不存在")
        if session.status == "abandoned":
            return {"session_id": session_id, "status": "abandoned"}
        if session.status != "in_progress":
            raise ValueError("只有进行中的会话可以放弃")
        now = datetime.now(timezone.utc)
        session.completed_at = now
        if session.started_at:
            started_at = session.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            session.time_spent_seconds = int((now - started_at).total_seconds())
        session.status = "abandoned"
        await db.commit()
        return {"session_id": session_id, "status": "abandoned"}

    @staticmethod
    async def list_sessions(
        db: AsyncSession,
        *,
        trainee_id: int | None = None,
        status: str | None = None,
        lab_id: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        query = select(TrainingSession).order_by(TrainingSession.id.desc()).limit(limit)
        if trainee_id is not None:
            query = query.where(TrainingSession.trainee_id == trainee_id)
        if status:
            query = query.where(TrainingSession.status == status)
        if lab_id is not None:
            query = query.where(TrainingSession.lab_id == lab_id)
        result = await db.execute(query)
        sessions = list(result.scalars().all())
        lab_ids = {s.lab_id for s in sessions}
        titles: dict[int, str] = {}
        if lab_ids:
            labs = (await db.execute(select(TrainingLab).where(TrainingLab.id.in_(lab_ids)))).scalars().all()
            titles = {lab.id: lab.title for lab in labs}
        return [
            {
                "id": s.id,
                "lab_id": s.lab_id,
                "lab_title": titles.get(s.lab_id) or f"Lab #{s.lab_id}",
                "trainee_id": s.trainee_id,
                "status": s.status,
                "score": s.score,
                "passed": s.passed,
                "started_at": iso_utc(s.started_at),
                "completed_at": iso_utc(s.completed_at),
                "time_spent_seconds": s.time_spent_seconds,
                "created_at": iso_utc(s.created_at),
                "is_active": s.status == "in_progress",
                "content_version": s.content_version,
            }
            for s in sessions
        ]

    @staticmethod
    async def get_session(db: AsyncSession, session_id: int) -> TrainingSession | None:
        return await db.get(TrainingSession, session_id)

    # ── 故障注入 ──────────────────────────────────────────────────────
    # 每种故障类型的必需配置参数
    _FAULT_REQUIRED_KEYS: dict[FaultType, set[str]] = {
        FaultType.INTERFACE_SHUTDOWN: {"interface"},
        FaultType.OSPF_NEIGHBOR_DOWN: {"interface", "process_id", "area_id"},
        FaultType.VLAN_MISMATCH: {"interface", "wrong_vlan", "correct_vlan"},
        FaultType.ACL_BLOCK: {"acl_number"},
        FaultType.ROUTE_BLACKHOLE: {"dest_network", "dest_mask", "blackhole_nexthop", "correct_nexthop"},
        FaultType.MTU_MISMATCH: {"interface", "wrong_mtu", "correct_mtu"},
        FaultType.DNS_FAULT: {"wrong_dns", "correct_dns"},
    }

    @staticmethod
    def _validate_config_keys(fault_type: FaultType, config: dict) -> None:
        """验证config包含模板所需的所有键,且无非法字符"""
        required = TrainingService._FAULT_REQUIRED_KEYS.get(fault_type, set())
        missing = required - set(config.keys())
        if missing:
            raise ValueError(f"故障类型 {fault_type.value} 缺少必需配置: {', '.join(sorted(missing))}")
        for key, value in config.items():
            if not isinstance(value, str):
                raise ValueError(f"配置值必须是字符串: {key}")
            if "{" in value or "}" in value:
                raise ValueError(f"配置值不能包含花括号: {key}")

    _FAULT_DEFAULT_CONFIG: dict[FaultType, dict[str, str]] = {
        FaultType.INTERFACE_SHUTDOWN: {"interface": "GigabitEthernet0/0/0"},
        FaultType.OSPF_NEIGHBOR_DOWN: {
            "interface": "GigabitEthernet0/0/0",
            "process_id": "1",
            "area_id": "0",
        },
        FaultType.VLAN_MISMATCH: {
            "interface": "GigabitEthernet0/0/0",
            "wrong_vlan": "20",
            "correct_vlan": "10",
        },
        FaultType.ACL_BLOCK: {"acl_number": "3000"},
        FaultType.ROUTE_BLACKHOLE: {
            "dest_network": "8.8.8.0",
            "dest_mask": "255.255.255.0",
            "blackhole_nexthop": "127.0.0.1",
            "correct_nexthop": "192.168.1.1",
        },
        FaultType.MTU_MISMATCH: {
            "interface": "GigabitEthernet0/0/0",
            "wrong_mtu": "1400",
            "correct_mtu": "1500",
        },
        FaultType.DNS_FAULT: {"wrong_dns": "0.0.0.0", "correct_dns": "8.8.8.8"},
    }

    @staticmethod
    @_serialize_session_write
    async def inject_faults(db: AsyncSession, session_id: int, fault_scenario: list) -> list:
        """只把故障场景写入会话记录，不 SSH、不调用设备适配器。"""
        session = await db.get(TrainingSession, session_id, with_for_update=True, populate_existing=True)
        if not session:
            raise ValueError("会话不存在")
        if session.status != "in_progress":
            raise ValueError("会话不在进行中，不能追加故障记录")
        injections = []
        for fault in fault_scenario:
            fault_type = FaultType(fault["fault_type"])
            config = dict(fault.get("config") or {})
            defaults = TrainingService._FAULT_DEFAULT_CONFIG.get(fault_type, {})
            for key, value in defaults.items():
                config.setdefault(key, value)
            template = FAULT_TEMPLATES[fault_type]

            TrainingService._validate_config_keys(fault_type, config)

            inject_cmds = [cmd.format(**config) if config else cmd for cmd in template["inject"]]
            rollback_cmds = [cmd.format(**config) if config else cmd for cmd in template["rollback"]]

            injection = FaultInjection(
                session_id=session_id,
                device_id=fault["device_id"],
                fault_type=fault_type,
                fault_config=config,
                injected_commands="\n".join(inject_cmds),
                rollback_commands="\n".join(rollback_cmds),
            )
            db.add(injection)
            injections.append(injection)

        await db.commit()
        for inj in injections:
            await db.refresh(inj)
        return injections

    @staticmethod
    async def resolve_fault(
        db: AsyncSession, fault_id: int, resolved_correctly: bool
    ) -> FaultInjection:
        fault = await db.get(FaultInjection, fault_id)
        if not fault:
            raise ValueError("故障记录不存在")
        async with _session_write_lock(fault.session_id):
            session = await db.get(TrainingSession, fault.session_id, with_for_update=True, populate_existing=True)
            if not session or session.status != "in_progress":
                raise ValueError("会话不在进行中，不能修改故障判定")
            fault.resolved_at = datetime.now(timezone.utc)
            fault.resolved_correctly = resolved_correctly
            await db.commit()
            await db.refresh(fault)
        return fault

    @staticmethod
    async def list_session_faults(db: AsyncSession, session_id: int) -> list[dict]:
        """列出会话的全部故障注入记录（供前端注入/解决闭环使用）。"""
        result = await db.execute(
            select(FaultInjection)
            .where(FaultInjection.session_id == session_id)
            .order_by(FaultInjection.injected_at.desc())
        )
        return [
            {
                "id": f.id,
                "session_id": f.session_id,
                "device_id": f.device_id,
                "fault_type": f.fault_type.value,
                "fault_config": f.fault_config,
                "injected_commands": f.injected_commands,
                "rollback_commands": f.rollback_commands,
                "injected_at": iso_utc(f.injected_at),
                "resolved_at": iso_utc(f.resolved_at),
                "resolved_correctly": f.resolved_correctly,
            }
            for f in result.scalars().all()
        ]

    # ── 评分引擎 ──────────────────────────────────────────────────────
    @staticmethod
    @_serialize_session_write
    async def score_session(db: AsyncSession, session_id: int) -> dict:
        """冻结复盘参考明细；客户端记录不能证明技能达标。"""
        session = await db.get(TrainingSession, session_id, with_for_update=True, populate_existing=True)
        if not session:
            raise ValueError("会话不存在")
        completed = session.status == "completed"
        if completed and session.score_detail is not None:
            return {"session_id": session_id, "score": session.score, "passed": session.passed, "detail": session.score_detail}
        if not completed and session.status != "in_progress":
            raise ValueError("会话不在进行中")
        lab = await db.get(TrainingLab, session.lab_id)
        scoring = {**DEFAULT_SCORING, **(lab.scoring_rules or {})}
        time_limit = (lab.time_limit_minutes or 60) * 60

        # 故障排除得分 (30%)
        result = await db.execute(
            select(FaultInjection).where(FaultInjection.session_id == session_id)
        )
        injection_list = result.scalars().all()
        total_faults = len(injection_list)
        resolved_faults = sum(1 for inj in injection_list if inj.resolved_correctly)

        # 用时效率得分 (10%)：会话还没结束时 time_spent_seconds 是 None，
        # 直接用"现在"算，否则中途评分会白送 100 分（2026-10-05 审计发现）
        duration = session.time_spent_seconds
        if duration is None:
            started = session.started_at or session.created_at
            if started is not None:
                started_aware = started if started.tzinfo else started.replace(tzinfo=timezone.utc)
                ended = session.completed_at if completed else datetime.now(timezone.utc)
                if ended is not None:
                    ended_aware = ended if ended.tzinfo else ended.replace(tzinfo=timezone.utc)
                    duration = max(int((ended_aware - started_aware).total_seconds()), 0)
        time_score = TrainingService._calculate_time_score(duration, time_limit)

        # 操作规范得分 (60%)
        operation_score = TrainingService._analyze_command_quality(session.command_log)

        # 权重：没有注入过故障时，"故障排除"这项不适用 —— 此前按 100 分计入，
        # 等于白送 30% 权重（学员不做排障也能轻松通过）。改为把该权重按比例分给其余两项。
        weights = {
            "operation": float(scoring["operation_weight"]),
            "fault": float(scoring["fault_weight"]),
            "time": float(scoring["time_weight"]),
        }
        fault_applicable = total_faults > 0
        if fault_applicable:
            fault_score = resolved_faults / total_faults * 100
            applied_weights = dict(weights)
        else:
            fault_score = 0.0
            rest = weights["operation"] + weights["time"]
            if rest > 0:
                applied_weights = {
                    "operation": weights["operation"] / rest,
                    "fault": 0.0,
                    "time": weights["time"] / rest,
                }
            else:  # 配置异常（两项权重都是 0）时退回等权，避免除零
                applied_weights = {"operation": 0.5, "fault": 0.0, "time": 0.5}

        # 加权综合
        final_score = round(
            operation_score * applied_weights["operation"]
            + (fault_score * applied_weights["fault"] if fault_applicable else 0.0)
            + time_score * applied_weights["time"],
            1,
        )

        session.score_detail = {
            "verification_status": "unverified",
            "reference_score": final_score,
            "rules_version": "client-records-reference-v1",
            "operation_score": round(operation_score, 1),
            "fault_score": round(fault_score, 1) if fault_applicable else None,
            "time_score": round(time_score, 1),
            "fault_applicable": fault_applicable,
            "note": UNVERIFIED_NOTE + " " + (
                f"本会话注入故障 {total_faults} 个，已正确解决 {resolved_faults} 个"
                if fault_applicable
                else "本会话未注入故障，故障排除项不计分；操作与用时权重已按比例放大"
            ),
            "weights": {
                "operation": round(applied_weights["operation"], 3),
                "fault": round(applied_weights["fault"], 3),
                "time": round(applied_weights["time"], 3),
            },
        }
        # 评分即结束：用时冻结、操作日志与故障注入区关闭，界面必须提前告知
        if session.time_spent_seconds is None:
            session.time_spent_seconds = duration
        # Preserve historical values if an already-completed legacy record has
        # no detail. New sessions receive no skill grade from untrusted input.
        if not completed:
            session.score = None
            session.passed = None
            session.status = "completed"
            session.completed_at = datetime.now(timezone.utc)
        await db.commit()

        return {
            "session_id": session_id,
            "score": session.score,
            "passed": session.passed,
            "detail": session.score_detail,
        }

    @staticmethod
    def _analyze_command_quality(command_log: str | None) -> float:
        """操作规范分析: 扣分制, 基于undo/错误/无效命令"""
        if not command_log:
            return 50.0
        try:
            commands = [json.loads(line) for line in command_log.strip().splitlines()]
        except json.JSONDecodeError:
            return 50.0
        score = 100.0
        # command 允许为 null（OperationLogCreate.command 默认 None），
        # 此前 `.get("command", "")` 返回 None → None.startswith → AttributeError → /score 500
        undo_count = sum(1 for cmd in commands if str(cmd.get("command") or "").startswith("undo "))
        score -= min(20, undo_count * 2)
        error_count = sum(1 for cmd in commands if cmd.get("error") or cmd.get("success") is False)
        score -= min(30, error_count * 5)
        repeated = TrainingService._find_repeated_commands(commands)
        score -= min(15, repeated * 3)
        return max(0.0, score)

    @staticmethod
    def _find_repeated_commands(commands: list[dict]) -> int:
        seen: dict[str, int] = {}
        for cmd in commands:
            c = str(cmd.get("command") or "")
            if c:
                seen[c] = seen.get(c, 0) + 1
        return sum(v - 1 for v in seen.values() if v > 1)

    @staticmethod
    def _calculate_time_score(time_spent: int | None, time_limit: int) -> float:
        if not time_spent or time_limit <= 0:
            return 100.0
        ratio = time_spent / time_limit
        if ratio <= 1.0:
            return max(60.0, 100.0 - (ratio * 40))
        elif ratio <= 1.5:
            return max(30.0, 60.0 - ((ratio - 1.0) * 60))
        else:
            return max(0.0, 30.0 - ((ratio - 1.5) * 60))

    # ── 独立Lab模式(沙箱) ────────────────────────────────────────────
    @staticmethod
    async def start_sandbox_session(
        db: AsyncSession,
        lab_id: int,
        trainee_id: int,
        fault_types: list[str] | None = None,
    ) -> TrainingSession:
        """独立Lab模式: 自动注入预定义故障,允许学员自由排错"""
        lab = await db.get(TrainingLab, lab_id)
        if not lab:
            raise ValueError("Lab不存在")

        device_ids: list[int] = []
        if fault_types:
            if not lab.topology_id:
                raise ValueError("该实验未绑定拓扑，无法注入故障")
            result = await db.execute(
                select(Device.id).where(Device.topology_id == lab.topology_id).order_by(Device.id)
            )
            device_ids = list(result.scalars().all())
            if not device_ids:
                raise ValueError("该实验拓扑下没有设备，无法注入故障")

        session = TrainingSession(
            lab_id=lab_id,
            trainee_id=trainee_id,
            started_at=datetime.now(timezone.utc),
            status="in_progress",
            content_version=lab.content_version,
            content_snapshot=TrainingService.content_snapshot(lab),
            mode_snapshot=build_mode_snapshot(lab),
        )
        await TrainingService._bind_trust_environment(db, lab, session)
        db.add(session)
        await db.commit()
        await db.refresh(session)

        if fault_types:
            auto_faults = [
                {"device_id": device_ids[0], "fault_type": ft}
                for ft in fault_types
            ]
            await TrainingService.inject_faults(db, session.id, auto_faults)

        return session

    # ── 操作日志(JSON Lines) ──────────────────────────────────────────
    @staticmethod
    @_serialize_session_write
    async def log_operation(
        db: AsyncSession,
        session_id: int,
        lab_id: int,
        action: str,
        target_device: str | None = None,
        command: str | None = None,
        result: str | None = None,
        success: bool = True,
        meta: dict | None = None,
    ) -> OperationLog:
        """记录一条JSON Lines格式的操作日志"""
        session = await db.get(TrainingSession, session_id, with_for_update=True, populate_existing=True)
        if not session:
            raise ValueError("会话不存在")
        if session.status != "in_progress":
            raise ValueError("会话不在进行中，不能追加操作记录")
        # Even a browser-originated WebSSH record is not server-attested evidence.
        meta = {**(meta or {}), "evidence_trust": "client_reported"}
        log_entry = OperationLog(
            session_id=session_id,
            lab_id=session.lab_id,
            timestamp=datetime.now(timezone.utc),
            action=action,
            target_device=target_device,
            command=command,
            result=result,
            success=success,
            meta=meta,
        )
        db.add(log_entry)
        command_line = json.dumps(
            {
                "timestamp": iso_utc(log_entry.timestamp),
                "action": action,
                "target_device": target_device,
                "command": command,
                "result": result,
                "success": success,
                "meta": meta or {},
            },
            ensure_ascii=False,
        )
        if session.command_log:
            session.command_log = f"{session.command_log}\n{command_line}"
        else:
            session.command_log = command_line
        # 防止 command_log 无限增长：保留最近 500 条
        lines = session.command_log.splitlines()
        if len(lines) > 500:
            session.command_log = "\n".join(lines[-500:])
        await db.commit()
        await db.refresh(log_entry)

        logger.info(
            "operation_logged",
            session_id=session_id,
            action=action,
            device=target_device,
            success=success,
        )
        return log_entry

    @staticmethod
    async def get_operation_logs(
        db: AsyncSession, session_id: int
    ) -> list[dict]:
        result = await db.execute(
            select(OperationLog)
            .where(OperationLog.session_id == session_id)
            .order_by(OperationLog.timestamp)
        )
        logs = result.scalars().all()
        return [
            {
                "id": log.id,
                "timestamp": iso_utc(log.timestamp),
                "action": log.action,
                "target_device": log.target_device,
                "command": log.command,
                "result": log.result,
                "success": log.success,
                "meta": log.meta,
            }
            for log in logs
        ]

    @staticmethod
    async def export_operation_logs_jsonl(
        db: AsyncSession, session_id: int
    ) -> str:
        """导出操作日志为JSON Lines字符串"""
        logs = await TrainingService.get_operation_logs(db, session_id)
        from core.redaction import redact_payload
        lines = [json.dumps(redact_payload(log), ensure_ascii=False) for log in logs]
        return "\n".join(lines)

    # ── 训练提示 / 复盘报告 ───────────────────────────────────────────
    @staticmethod
    async def build_session_snapshot(db: AsyncSession, session_id: int) -> dict:
        session = await db.get(TrainingSession, session_id)
        if not session:
            raise ValueError("会话不存在")
        lab = await db.get(TrainingLab, session.lab_id)
        if not lab:
            raise ValueError("Lab不存在")
        logs = await TrainingService.get_operation_logs(db, session_id)
        fault_result = await db.execute(
            select(FaultInjection).where(FaultInjection.session_id == session_id)
        )
        faults = fault_result.scalars().all()
        return {
            "session": session,
            "lab": lab,
            "logs": logs,
            "faults": faults,
        }

    @staticmethod
    def _latest_log_line(logs: list[dict]) -> dict | None:
        return logs[-1] if logs else None

    @staticmethod
    def _summarize_faults(faults: list[FaultInjection]) -> list[str]:
        if not faults:
            return ["当前会话尚未注入故障，按正常操作流程训练。"]
        items = []
        for fault in faults[:5]:
            status = "已恢复" if fault.resolved_correctly else ("未恢复" if fault.resolved_correctly is False else "未处理")
            items.append(f"{fault.fault_type.value}: {status}")
        return items

    @staticmethod
    def build_hint_search_query(lab, logs: list | None = None) -> str:
        """拼知识库检索词：实验标题 + 步骤名/目标 + 最近命令。

        objectives 现在是步骤 dict 列表；直接 join 会 TypeError，导致 /hint 静默 sources=[]。
        """
        parts: list[str] = []
        title = getattr(lab, "title", None) or ""
        if title:
            parts.append(str(title))
        for item in (getattr(lab, "objectives", None) or []):
            if isinstance(item, dict):
                for key in ("name", "goal"):
                    value = item.get(key)
                    if value:
                        parts.append(str(value))
            elif item:
                parts.append(str(item))
        latest = logs[-1] if logs else None
        if isinstance(latest, dict):
            cmd = latest.get("command") or latest.get("action")
            if cmd:
                parts.append(str(cmd))
        query = "\n".join(p.strip() for p in parts if p and str(p).strip())
        return query[:800]

    @staticmethod
    def _objective_step_label(item) -> str:
        if isinstance(item, dict):
            return str(item.get("name") or item.get("goal") or "").strip()
        return str(item or "").strip()

    @staticmethod
    def _objective_brief(lab) -> str:
        objs = lab.objectives or []
        if not isinstance(objs, list):
            return TrainingService._objective_step_label(objs) or "未设置"
        labels = [TrainingService._objective_step_label(x) for x in objs]
        return "；".join(x for x in labels if x) or "未设置"

    @staticmethod
    def build_training_hint(snapshot: dict) -> dict:
        session = snapshot["session"]
        lab = snapshot["lab"]
        logs = snapshot["logs"]
        faults = snapshot["faults"]
        latest = TrainingService._latest_log_line(logs)
        objectives = lab.objectives or []
        next_steps = []
        corrections = []
        explanations = []
        risk_notes = []
        if objectives:
            first = TrainingService._objective_step_label(objectives[0])
            if first:
                next_steps.append(f"先对照训练目标推进: {first}")
        if latest and latest.get("success") is False:
            corrections.append(f"上一条操作失败: {latest.get('command') or latest.get('action')}")
            explanations.append(latest.get("result") or "请检查命令语法、接口状态和前置条件。")
        if faults:
            unresolved = [fault for fault in faults if fault.resolved_correctly is not True]
            if unresolved:
                next_steps.append(f"优先处理未恢复故障: {unresolved[0].fault_type.value}")
                risk_notes.append("存在未恢复故障，建议先恢复链路再继续后续步骤。")
        if not next_steps:
            next_steps.append("继续按实验步骤推进，并记录每一步命令和观察结果。")
        return {
            "session_id": session.id,
            "lab_id": lab.id,
            "goal": lab.title,
            "summary": "已根据当前训练进度生成步骤提示。",
            "next_steps": next_steps[:5],
            "corrections": corrections[:5],
            "explanations": explanations[:5] or ["参考训练目标和最近操作，保持步骤与目标一致。"],
            "risk_notes": risk_notes[:5],
            "coach_text": "\n".join([
                f"训练目标: {lab.title}",
                f"当前状态: {session.status}",
                f"最近操作: {latest.get('command') if latest else '无'}",
            ]).strip(),
        }

    @staticmethod
    def build_recap_report(snapshot: dict) -> dict:
        session = snapshot["session"]
        lab = snapshot["lab"]
        logs = snapshot["logs"]
        faults = snapshot["faults"]
        failed_logs = [log for log in logs if not log.get("success")]
        command_entries: list[dict] = []
        if session.command_log:
            for line in session.command_log.splitlines():
                if not line.strip():
                    continue
                try:
                    command_entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        repeated_actions = TrainingService._find_repeated_commands(command_entries)
        key_findings = []
        if failed_logs:
            key_findings.append(f"存在 {len(failed_logs)} 条失败操作记录。")
        if faults:
            key_findings.append(f"已记录 {len(faults)} 个故障注入点。")
        if repeated_actions:
            key_findings.append(f"发现 {repeated_actions} 次重复操作，建议整理步骤后重试。")
        if not key_findings:
            key_findings.append("自报记录未标记失败，实际执行结果仍待验证。" if logs else "没有操作记录，无法验证技能达标。")

        root_causes = []
        for fault in faults:
            if fault.resolved_correctly is False:
                root_causes.append(f"故障 {fault.fault_type.value} 未按预期恢复。")
        for log in failed_logs[:3]:
            root_causes.append(log.get("result") or log.get("command") or "命令执行失败。")
        if not root_causes:
            root_causes.append("当前复盘未识别到显著根因，建议结合操作细节进一步核对。")

        impact_analysis = [
            "操作时间线来自客户端上报，可供复盘，不构成设备执行或技能达标证据。",
            f"会话状态: {session.status}，技能达标未验证。",
        ]
        if session.score is not None:
            impact_analysis.append(f"历史参考分: {session.score}（未经技能验证，保留原记录）。")

        recommendations = [
            "先确认目标、故障和当前设备状态，再执行下一步命令。",
            "每次操作后记录命令、现象和结果，避免重复尝试。",
        ]
        if failed_logs:
            recommendations.append("对失败命令进行逐条回放和语法复核。")
        if faults:
            recommendations.append("对未恢复故障优先执行验证命令，确认链路恢复后再结束会话。")

        report_lines = [
            f"# {lab.title} 复盘报告",
            "",
            f"- 会话ID: {session.id}",
            f"- 状态: {session.status}",
            f"- 历史参考分（未验证）: {session.score if session.score is not None else '无'}",
            "- 技能达标: 未验证",
            "",
            "## 关键发现",
            *[f"- {item}" for item in key_findings],
            "",
            "## 根因分析",
            *[f"- {item}" for item in root_causes],
            "",
            "## 影响分析",
            *[f"- {item}" for item in impact_analysis],
            "",
            "## 建议",
            *[f"- {item}" for item in recommendations],
        ]

        return {
            "session_id": session.id,
            "lab_id": lab.id,
            "title": f"{lab.title} 复盘报告",
            "summary": "已根据训练过程、操作记录和故障注入生成复盘摘要。",
            "key_findings": key_findings,
            "root_causes": root_causes[:5],
            "impact_analysis": impact_analysis[:5],
            "recommendations": recommendations[:5],
            "timeline": logs,
            "faults": [
                {
                    "id": fault.id,
                    "fault_type": fault.fault_type.value,
                    "resolved_correctly": fault.resolved_correctly,
                    "device_id": fault.device_id,
                }
                for fault in faults
            ],
            "report_text": "\n".join(report_lines).strip(),
        }
