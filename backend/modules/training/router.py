from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
"""实训模块路由"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import update, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_async_session
from core.dependencies import get_current_user
from modules.training.models import TrainingSession
import re

from core.logger import get_logger
from core.rate_limiter import rate_limit
from core.time_utils import iso_utc
from modules.ai_text.llm_service import LLMService
from modules.ai_text.context_bundle import prepare_sources, source_documents
from modules.knowledge.service import KnowledgeService
from modules.system.service import SystemService
from modules.training import reports as report_store
from modules.training.content_source import content_brief, resolve_session_content
from modules.training.environment_policy import lab_environment, safe_environment_answer
from modules.training.mode_facts import current_mode_facts, session_mode_facts
from modules.training.schemas import (
    FaultInjectRequest, LabCreate, LabUpdate, OperationLogCreate,
    SandboxStartRequest, SessionCreate, ScoreResponse, TrainingHintResponse,
    TrainingReportEnvelope, TrainingReportGenerate, TrainingWorkspaceResponse, TrainingWorkspaceUpdate,
    LabEnvironmentBinding, StepVerificationRequest,
)
from modules.training.service import TrainingService, UNVERIFIED_NOTE, _report_write_lock

logger = get_logger("training")

_SECRET_PATTERN = re.compile(r"(sk-[A-Za-z0-9_-]{6,}|api[_-]?key\s*[=:]\s*\S+)", re.IGNORECASE)


def _safe_exc_text(exc: Exception) -> str:
    """失败原因脱敏：去掉可能的密钥片段，只保留类型与短消息。"""
    raw = f"{type(exc).__name__}: {exc}"
    return _SECRET_PATTERN.sub("[redacted]", raw)[:300]

router = APIRouter(prefix="/training", tags=["实训考核"])

# hint/report 会触发知识库检索 + DeepSeek 生成，按 IP+路由模板限流
_AI_RATE_LIMIT = rate_limit(max_requests=20, window_seconds=60)


async def _require_session_owner(
    session_id: int,
    db: AsyncSession,
    current_user: dict,
) -> Any:
    """验证当前用户是会话拥有者或管理员"""
    session = await TrainingService.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    is_owner = session.trainee_id == current_user["user_id"]
    is_admin = current_user["role"] == "admin"
    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="无权操作此会话")
    return session


async def _get_ai_service(db: AsyncSession, current_user: dict) -> LLMService:
    provider = await SystemService.build_llm_provider(db)
    return LLMService(db=db, user_id=current_user.get("user_id"), provider=provider)


def _get_knowledge_service() -> KnowledgeService:
    return KnowledgeService.from_settings()


async def _training_sources(content_lab, logs) -> tuple[list[dict], str]:
    """One bounded excerpt contract for hints, reports and their visible sources."""
    query = TrainingService.build_hint_search_query(content_lab, logs)
    if not query:
        return [], "not_requested"
    try:
        hits = await _get_knowledge_service().search(query, top_k=3)
        prepared = prepare_sources(hits)
        sources = list({source["source_id"]: source for source in prepared}.values())
        return sources, "available" if sources else "empty"
    except Exception as exc:
        logger.warning("training_knowledge_search_failed", error=type(exc).__name__)
        return [], "unavailable"


# ── Lab 管理 ──────────────────────────────────────────────────────────
@router.post("/labs", response_model=None)
async def create_lab(
    data: LabCreate,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    if current_user["role"] not in ["admin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    lab = await TrainingService.create_lab(
        db, data.title, data.description, data.topology_id,
        current_user["user_id"], data.objectives, data.scoring_rules,
        data.time_limit_minutes, data.is_sandbox,
    )
    return {"id": lab.id, "title": lab.title, "status": lab.status.value}


@router.get("/labs", response_model=None)
async def list_labs(
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    labs = await TrainingService.list_labs(db)
    if current_user["role"] != "admin":
        labs = [l for l in labs if l["status"] != "draft"]
    return labs


@router.get("/labs/{lab_id}", response_model=None)
async def get_lab(
    lab_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    lab = await TrainingService.get_lab(db, lab_id)
    if not lab:
        raise HTTPException(status_code=404, detail="Lab不存在")
    status = lab.status.value if hasattr(lab.status, "value") else str(lab.status)
    if current_user["role"] != "admin" and status == "draft":
        raise HTTPException(status_code=404, detail="Lab不存在")
    return {
        "id": lab.id, "title": lab.title, "description": lab.description,
        "status": lab.status.value, "topology_id": lab.topology_id,
        "objectives": lab.objectives, "scoring_rules": lab.scoring_rules,
        "time_limit_minutes": lab.time_limit_minutes, "is_sandbox": lab.is_sandbox,
        "content_version": lab.content_version,
        "environment_spec": lab.environment_spec,
        "mode_facts": current_mode_facts(lab),
        "created_at": iso_utc(lab.created_at),
    }


@router.put("/labs/{lab_id}", response_model=None)
async def update_lab(
    lab_id: int,
    data: LabUpdate,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    if current_user["role"] not in ["admin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    try:
        lab = await TrainingService.update_lab(db, lab_id, **data.model_dump(exclude_unset=True))
        return {"id": lab.id, "title": lab.title, "status": lab.status.value}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/labs/{lab_id}", response_model=None)
async def delete_lab(
    lab_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    if current_user["role"] not in ["admin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    try:
        await TrainingService.delete_lab(db, lab_id)
        return {"detail": "已删除"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put('/labs/{lab_id}/environment', response_model=None)
async def bind_lab_environment(
    lab_id: int, data: LabEnvironmentBinding,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    """Bind new sessions to an existing profile; no device calls or old-session writes."""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail='需要管理员权限')
    from copy import deepcopy
    from modules.trust.models import EnvironmentProfile
    from modules.auth.service import AuditService
    lab = await TrainingService.get_lab(db, lab_id)
    if lab is None:
        raise HTTPException(status_code=404, detail='Lab不存在')
    spec = deepcopy(lab.environment_spec or {})
    if not lab.content_version or not isinstance(spec, dict) or not spec.get('devices'):
        raise HTTPException(status_code=409, detail='请先完成实验内容版本与角色要求配置')
    if data.environment_id is not None:
        env = await db.get(EnvironmentProfile, data.environment_id)
        if env is None:
            raise HTTPException(status_code=404, detail='环境不存在')
        roles = [d.get('role') for d in spec['devices'] if isinstance(d, dict)]
        mapped = [d for d in env.devices or [] if isinstance(d, dict) and d.get('role') in roles]
        if (len(mapped) != len(roles) or len({d.get('role') for d in mapped}) != len(roles)
                or len({d.get('device_id') for d in mapped}) != len(roles)):
            raise HTTPException(status_code=409, detail='环境需为实验每个角色绑定唯一的独立设备')
        spec['trust_environment_id'] = env.id
    else:
        spec.pop('trust_environment_id', None)
        spec.pop('environment_id', None)
    # Profile readiness never certifies protocol-specific prerequisites or authorizes writes.
    spec['binding_status'] = 'unverified'
    lab.environment_spec = spec
    await AuditService.log(db, user_id=current_user['user_id'], username=current_user.get('username','unknown'),
                           module='training', action='bind_environment', resource_type='training_lab',
                           resource_id=str(lab.id), detail={'environment_id': data.environment_id,
                           'scope': 'new_sessions_only'}, result='success', commit=False)
    await db.commit()
    return {'lab_id': lab.id, 'environment_id': data.environment_id, 'scope': 'new_sessions_only',
            'detail': '后续新会话冻结所选环境；已有会话保持原绑定，协议先修与写入权限单独核对'}


@router.post('/sessions/{session_id}/steps/{step_id}/verify', response_model=None)
async def verify_training_step(
    session_id: int, step_id: int, data: StepVerificationRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    from modules.training.step_verification import evaluate_frozen_step
    from modules.trust.models import EnvironmentProfile, ReadOnlyObservation
    from modules.trust.service import serialize_environment, environment_hash
    session = await _require_session_owner(session_id, db, current_user)
    env = await db.get(EnvironmentProfile, session.trust_environment_id) if session.trust_environment_id else None
    current = serialize_environment(env) if env else None
    if env and env.content_hash != environment_hash(env):
        current['content_hash'] = ''  # Reject a stale stored hash, never repair it during checks.
    rows = (await db.execute(select(ReadOnlyObservation).where(
        ReadOnlyObservation.id.in_(data.observation_ids)))).scalars().all() if data.observation_ids else []
    result = evaluate_frozen_step(session, step_id, data.observation_ids, rows, current, current_user)
    # Do not leak other users' observation contents through a failed request.
    if current_user['role'] != 'admin' and any(r.created_by != current_user['user_id'] for r in rows):
        raise HTTPException(status_code=403, detail='无权使用这些观察记录')
    return result


@router.delete("/sessions/{session_id}", response_model=None)
async def delete_session(
    session_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """删除实训会话（本人或管理员）。删掉会话后，其所属实验才可删除。"""
    try:
        await TrainingService.delete_session(
            db,
            session_id,
            user_id=current_user["user_id"],
            is_admin=current_user["role"] == "admin",
        )
        return {"detail": "已删除"}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 会话管理 ──────────────────────────────────────────────────────────
@router.post("/sessions", response_model=None)
async def start_session(
    data: SessionCreate,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        session = await TrainingService.start_session(db, data.lab_id, current_user["user_id"])
        return {"id": session.id, "lab_id": session.lab_id, "status": session.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sessions", response_model=None)
async def list_sessions(
    status: str | None = None,
    lab_id: int | None = None,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """当前用户的实训会话列表（管理员可见全部）。关闭弹窗后从此重新进入。"""
    trainee_id = None if current_user["role"] == "admin" else current_user["user_id"]
    return await TrainingService.list_sessions(
        db, trainee_id=trainee_id, status=status, lab_id=lab_id,
    )


@router.get("/sessions/{session_id}", response_model=None)
async def get_session(
    session_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    session = await _require_session_owner(session_id, db, current_user)
    lab = await TrainingService.get_lab(db, session.lab_id)
    facts, mode_source = session_mode_facts(session, lab)
    resolved = resolve_session_content(session, lab)
    return {
        "id": session.id, "lab_id": session.lab_id, "trainee_id": session.trainee_id,
        "status": session.status, "score": session.score, "score_detail": session.score_detail,
        "passed": session.passed, "started_at": iso_utc(session.started_at),
        "completed_at": iso_utc(session.completed_at),
        "time_spent_seconds": session.time_spent_seconds,
        "content_version": session.content_version,
        "content_snapshot": session.content_snapshot,
        "mode_facts": facts,
        "mode_source": mode_source,
        "content_source": resolved["source"],
        "content_warning": resolved["warning"],
        "trust_environment": {
            "id": session.trust_environment_id,
            "version": session.trust_environment_version,
            "snapshot": session.trust_environment_snapshot or {},
        },
        "is_active": session.status == "in_progress",
    }


@router.post("/sessions/{session_id}/abandon", response_model=None)
async def abandon_session(
    session_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """放弃会话：之后只读回看，不能继续记日志、绑定终端或请求教练。"""
    await _require_session_owner(session_id, db, current_user)
    try:
        return await TrainingService.abandon_session(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sessions/{session_id}/complete", response_model=None)
async def complete_session(
    session_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    await _require_session_owner(session_id, db, current_user)
    try:
        return await TrainingService.complete_session(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 故障注入（只写库，不下发设备） ──────────────────────────────────
@router.post("/sessions/{session_id}/inject", response_model=None)
async def inject_faults(
    session_id: int,
    data: FaultInjectRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """管理员记账：只写入会话故障记录，不 SSH、不改设备。applied 恒为 false。"""
    if current_user["role"] not in ["admin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    session = await TrainingService.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.status != "in_progress":
        raise HTTPException(status_code=400, detail="只能对进行中的会话注入故障")
    fault_dicts = [item.model_dump() for item in data.fault_scenario]
    try:
        injections = await TrainingService.inject_faults(db, session_id, fault_dicts)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "injected": len(injections),
        "applied": False,
        "note": "仅写入会话记录，未向设备下发命令",
    }


@router.post("/faults/{fault_id}/resolve", response_model=None)
async def resolve_fault(
    fault_id: int,
    resolved_correctly: bool = True,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    from modules.training.models import FaultInjection
    fault = await db.get(FaultInjection, fault_id)
    if not fault:
        raise HTTPException(status_code=404, detail="故障记录不存在")
    is_admin = current_user["role"] == "admin"
    if not is_admin:
        await _require_session_owner(fault.session_id, db, current_user)
        if resolved_correctly:
            # 学员自评"已解决"会让 fault_score 变成自证：判定通过必须由教员（admin）确认
            raise HTTPException(
                status_code=403,
                detail="判定故障已解决需要管理员（教员）确认；学员可标记为未解决",
            )
    try:
        fault = await TrainingService.resolve_fault(db, fault_id, resolved_correctly)
        return {"id": fault.id, "resolved_correctly": fault.resolved_correctly}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 评分 ──────────────────────────────────────────────────────────────
@router.post("/sessions/{session_id}/score", response_model=ScoreResponse)
async def score_session(
    session_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    await _require_session_owner(session_id, db, current_user)
    try:
        return await TrainingService.score_session(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 独立Lab模式(沙箱) ────────────────────────────────────────────────
@router.post("/sandbox/start", response_model=None)
async def start_sandbox(
    data: SandboxStartRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        session = await TrainingService.start_sandbox_session(
            db, data.lab_id, current_user["user_id"], data.fault_types,
        )
        return {"id": session.id, "lab_id": session.lab_id, "status": session.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 操作日志 ──────────────────────────────────────────────────────────
@router.post("/sessions/{session_id}/log", response_model=None)
async def log_operation(
    session_id: int,
    data: OperationLogCreate,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    await _require_session_owner(session_id, db, current_user)
    try:
        log = await TrainingService.log_operation(
            db, session_id, data.lab_id, data.action,
            data.target_device, data.command, data.result,
            data.success, data.meta,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": log.id}


@router.get("/sessions/{session_id}/faults", response_model=None)
async def list_session_faults(
    session_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """列出会话的故障注入记录（注入/解决闭环）。"""
    await _require_session_owner(session_id, db, current_user)
    return await TrainingService.list_session_faults(db, session_id)


@router.get("/sessions/{session_id}/logs", response_model=None)
async def get_logs(
    session_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    await _require_session_owner(session_id, db, current_user)
    return await TrainingService.get_operation_logs(db, session_id)


@router.get("/sessions/{session_id}/logs/jsonl", response_class=PlainTextResponse, response_model=None)
async def export_logs_jsonl(
    session_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    await _require_session_owner(session_id, db, current_user)
    return await TrainingService.export_operation_logs_jsonl(db, session_id)


@router.get("/sessions/{session_id}/hint", response_model=TrainingHintResponse, dependencies=[Depends(_AI_RATE_LIMIT)])
async def get_training_hint(
    session_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """生成训练步骤提示。仅进行中的会话可请求；已结束会话只允许回看。"""
    session = await _require_session_owner(session_id, db, current_user)
    if session.status != "in_progress":
        raise HTTPException(
            status_code=409,
            detail="该会话已结束（completed/abandoned），只能回看记录，不能继续请求教练提示。",
        )
    snapshot = await TrainingService.build_session_snapshot(db, session_id)
    resolved = resolve_session_content(snapshot["session"], snapshot["lab"])
    frozen_spec = resolved.get('environment_spec')
    guard = lab_environment(SimpleNamespace(environment_spec=frozen_spec) if isinstance(frozen_spec, dict) else snapshot["lab"])
    content_lab = SimpleNamespace(
        title=resolved["title"] or snapshot["lab"].title,
        objectives=resolved["objectives"],
    )
    knowledge_sources, knowledge_status = await _training_sources(content_lab, snapshot["logs"])
    blocked_reason = ""
    if not resolved["can_guide"]:
        blocked_reason = resolved["warning"]
    elif not guard["allow_executable"]:
        blocked_reason = guard["reason"]
    if blocked_reason:
        # AF-03：未核验/无映射/旧内容未知时不调用配置教练，只返回原因与只读核对。
        safe = safe_environment_answer(
            title=content_lab.title,
            reason=blocked_reason,
            content_warning=resolved["warning"] if resolved["can_guide"] else "",
        )
        return {
            "session_id": snapshot["session"].id,
            "lab_id": snapshot["lab"].id,
            "goal": content_lab.title,
            "summary": "当前环境未核验，已停止生成现场配置步骤；可先做只读核对或阅读教材原文。",
            "next_steps": safe["next_steps"],
            "corrections": [],
            "explanations": [blocked_reason, "教材中的接口/地址是示例，未与现场映射核对前不要直接粘贴执行。"],
            "risk_notes": safe["risk_notes"],
            "coach_text": safe["text"],
            "sources": knowledge_sources,
            "degraded": False,
            "knowledge_status": knowledge_status,
            "environment_status": guard["status"],
            "content_source": resolved["source"],
            "config_blocked": True,
            "blocked_reason": blocked_reason,
        }

    objective_brief = content_brief(resolved)
    # 把完整步骤清单交给教练：否则它只能凭实验名泛泛而谈，学员追问才有细节（2026-10-05 实测）
    steps = [st for st in (resolved["objectives"] or []) if isinstance(st, dict)]
    steps_text = "\n".join(
        f"步骤{st.get('id', '?')}: {st.get('name', '')}"
        f" | 目标: {st.get('goal', '')}"
        f" | 配置提示: {st.get('config_hint', '')}"
        f" | 只读观察建议: {st.get('verify_command', '')}"
        f" | 核对目标: {st.get('expected', '')}"
        f" | 核验范围: {(st.get('verification') or {}).get('limitations') or '未配置确定性步骤规则，不按关键词或AI结论判通过'}"
        for st in steps
    )
    try:
        ai_service = await _get_ai_service(db, current_user)
        coach = await ai_service.coach_training(
            goal=content_lab.title,
            scenario="\n".join([
                f"训练目标: {content_lab.title}",
                f"内容来源: {resolved['source']}（版本 {resolved['version'] or '未记录'}）",
                f"训练要求: {objective_brief}",
                f"实验步骤清单（共 {len(steps)} 步）:\n{steps_text or '（本实验未配置步骤）'}",
                f"当前会话状态: {snapshot['session'].status}",
                resolved["warning"] or "",
                UNVERIFIED_NOTE,
                f"最新操作: {snapshot['logs'][-1] if snapshot['logs'] else '无'}",
                f"知识检索状态: {knowledge_status}。unavailable 表示检索失败，不是知识库为空。",
                "检索参考不是现场证据；只使用与本次问题相关的内容，指出对应来源。",
                *source_documents(knowledge_sources),
            ]),
            current_step="未验证；最近命令不代表当前步骤，不能据日志条数宣称步骤达标",
            history="\n".join([str(item) for item in snapshot["logs"][-10:]]),
        )
        return {
            "session_id": snapshot["session"].id,
            "lab_id": snapshot["lab"].id,
            "goal": content_lab.title,
            "summary": coach.get("summary", "已生成训练提示。"),
            "next_steps": coach.get("next_steps", []),
            "corrections": coach.get("corrections", []),
            "explanations": coach.get("explanations", []),
            "risk_notes": coach.get("risk_notes", []),
            "coach_text": coach.get("coach_text", ""),
            "sources": knowledge_sources,
            "degraded": coach.get("degraded") is True,
            "knowledge_status": knowledge_status,
            "environment_status": guard["status"],
            "content_source": resolved["source"],
            "config_blocked": False,
            "blocked_reason": "",
        }
    except Exception as exc:
        logger.warning("training_hint_llm_failed", error_type=type(exc).__name__)
        fallback_snapshot = {**snapshot, "lab": SimpleNamespace(
            id=snapshot["lab"].id, title=content_lab.title, objectives=resolved["objectives"],
        )}
        hint = TrainingService.build_training_hint(fallback_snapshot)
        hint["sources"] = knowledge_sources
        hint["degraded"] = True
        hint["knowledge_status"] = knowledge_status
        hint["environment_status"] = guard["status"]
        hint["content_source"] = resolved["source"]
        hint["config_blocked"] = False
        hint["blocked_reason"] = ""
        return hint


async def _generate_training_report(
    db: AsyncSession,
    session_id: int,
    current_user: dict,
    *,
    regenerate: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """生成（或复用）复盘报告的新版本。

    - 幂等键命中 → 直接返回已有版本，不调用模型；
    - 证据指纹未变且不是显式重生成 → 返回已有版本，不调用模型；
    - 生成失败 → 写入一条 failed 记录并抛出 502，旧 ready 版本保持可读。
    """
    session = await _require_session_owner(session_id, db, current_user)
    if session.status == "pending":
        raise HTTPException(status_code=400, detail="会话尚未开始，无法生成复盘报告")

    key = (idempotency_key or "").strip() or None
    async with _report_write_lock(session_id):
        # AF3-02：请求在拿到生成锁之前可能已开启旧事务快照；先结束它，
        # 否则并发重生成看不到前一个请求刚提交的版本，会分配重复版本号。
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        session = await _require_session_owner(session_id, db, current_user)
        versions = await report_store.list_versions(db, session_id)
        keyed = await report_store.find_by_idempotency_key(db, session_id, key)
        if keyed is not None:
            return report_store.envelope(session, versions, reused=True)

        snapshot = await TrainingService.build_session_snapshot(db, session_id)
        resolved = resolve_session_content(snapshot["session"], snapshot["lab"])
        content_lab = SimpleNamespace(title=resolved["title"] or snapshot["lab"].title, objectives=resolved["objectives"])
        input_payload = report_store.build_report_input(snapshot)
        digest = report_store.report_input_hash(input_payload)
        summary = report_store.input_summary(input_payload)
        latest = await report_store.latest_ready(db, session_id)
        if latest is not None and not regenerate and latest.input_hash == digest:
            return report_store.envelope(session, versions, reused=True)

        knowledge_sources, knowledge_status = await _training_sources(content_lab, snapshot["logs"])
        summary = {**summary, "knowledge_status": knowledge_status, "source_count": len(knowledge_sources)}

        objective_brief = content_brief(resolved)
        source_lines = [
            f"训练目标: {content_lab.title}",
            f"训练要求: {objective_brief}",
            f"当前状态: {snapshot['session'].status}",
            f"内容来源: {resolved['source']}（版本 {resolved['version'] or '未记录'}）",
            resolved["warning"] or "",
            f"实验内容版本: {summary.get('content_version') or '未记录'}",
            UNVERIFIED_NOTE,
            f"历史参考分（未经验证）: {snapshot['session'].score}",
            "操作记录:",
            *[str(item) for item in snapshot["logs"]],
            f"知识检索状态: {knowledge_status}。unavailable 表示检索失败，不是知识库为空。",
            "以下是检索参考材料，不是现场证据，也不保证每个片段都支持本次结论。仅使用与结论有关的内容，指出对应来源；无依据的根因应列为待验证。",
            "检索参考片段（后续界面保留相同片段供核对）:",
            *source_documents(knowledge_sources),
        ]
        version = report_store.next_version(versions)
        # AF2-03/AF3-02：初始化之前就建立有效异常上下文；未知模型明确记 unknown。
        # 同时保存回滚后仍可用的标量快照，避免 rollback() 使 ORM 对象过期后再访问。
        model_name = "unknown"
        stage = "provider_init"
        ai_service = None
        latest_version = latest.version if latest is not None else None
        session_lab_id = session.lab_id
        try:
            ai_service = await _get_ai_service(db, current_user)
            model_name = str(
                getattr(ai_service, "model_name", None)
                or getattr(getattr(ai_service, "provider", None), "model", None)
                or "unknown"
            )
            stage = "generate"
            report = await ai_service.generate_report(
                title=f"{content_lab.title} 复盘报告",
                source_text="\n".join(source_lines),
                context="训练复盘与过程记录",
            )
            body = {
                "title": report.get("title", f"{content_lab.title} 复盘报告"),
                "summary": report.get("summary", ""),
                "key_findings": report.get("key_findings", []),
                "root_causes": report.get("root_causes", []),
                "impact_analysis": report.get("impact_analysis", []),
                "recommendations": report.get("recommendations", []),
                "report_text": report.get("report_text", ""),
            }
            stage = "save"
            degraded = bool(report.get("degraded"))
            summary = {**summary, "degraded": degraded}
            if degraded:
                model_name = "local-template"
            row = report_store.build_report_row(
                session_id,
                version,
                status=report_store.REPORT_STATUS_READY,
                payload=input_payload,
                input_hash=digest,
                summary=summary,
                model=model_name,
                body=body,
                sources=knowledge_sources,
                idempotency_key=key,
            )
            db.add(row)
            try:
                await db.commit()
            except Exception as commit_exc:
                # 提交可能已在服务端成功、只是客户端收到异常；先恢复事务，再核实该版本是否已落库。
                try:
                    await db.rollback()
                except Exception as rollback_exc:  # noqa: BLE001
                    logger.error("training_report_save_rollback_failed", error=_safe_exc_text(rollback_exc))
                    raise HTTPException(
                        status_code=503,
                        detail="复盘报告保存失败，且数据库事务无法恢复；请检查数据库后重试。旧报告仍可查看。",
                    ) from commit_exc
                try:
                    versions_now = await report_store.list_versions(db, session_id)
                except Exception as read_exc:  # noqa: BLE001
                    logger.error("training_report_save_verify_failed", error=_safe_exc_text(read_exc))
                    raise commit_exc
                persisted = next((item for item in versions_now if item.version == version), None)
                if persisted is not None:
                    # 版本已经存在（commit 实际成功或已有同版记录）：不要再插 failed 造成重复。
                    return report_store.envelope(session, versions_now)
                raise
            try:
                versions = await report_store.list_versions(db, session_id)
            except Exception as read_exc:  # noqa: BLE001
                # 已提交成功但回读失败：不重插同版本、不伪记失败，返回已保存的这条记录。
                logger.error("training_report_readback_failed", error=_safe_exc_text(read_exc))
                versions = [row]
            return report_store.envelope(session, versions)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("training_report_failed", stage=stage, error=_safe_exc_text(exc), exc_info=True)
            failure_summary = {**summary, "failure_stage": stage}
            # 先恢复可写事务；rollback 后不再访问已过期 ORM 对象（只用上面捕获的标量）。
            try:
                await db.rollback()
            except Exception as rollback_exc:  # noqa: BLE001
                logger.error("training_report_rollback_failed", error=_safe_exc_text(rollback_exc))
                raise HTTPException(
                    status_code=503,
                    detail="复盘报告生成失败，且数据库事务无法恢复；失败尝试未保存。旧报告仍可查看。",
                ) from exc
            # 若同一版本已经存在（提交结果不确定），不重复插入；按已记录处理。
            try:
                existing_versions = await report_store.list_versions(db, session_id)
            except Exception:  # noqa: BLE001
                existing_versions = []
            existing = next((item for item in existing_versions if item.version == version), None)
            if existing is not None:
                previous = f"，仍可读取旧版本 v{latest_version}" if latest_version is not None else ""
                raise HTTPException(
                    status_code=502,
                    detail=f"复盘报告生成失败（结果保存失败，第 {version} 次尝试已记录{previous}）。请稍后重试。",
                ) from exc
            row = report_store.build_report_row(
                session_id,
                version,
                status=report_store.REPORT_STATUS_FAILED,
                payload=input_payload,
                input_hash=digest,
                summary=failure_summary,
                model=model_name,
                error=f"{stage}: {_safe_exc_text(exc)}"[:1000],
                idempotency_key=key,
            )
            db.add(row)
            try:
                await db.commit()
            except Exception as save_exc:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass
                logger.error("training_report_failed_attempt_not_saved", error=_safe_exc_text(save_exc))
                raise HTTPException(
                    status_code=503,
                    detail="复盘报告生成失败，且失败尝试未能保存；请检查数据库后重试。旧报告仍可查看。",
                ) from exc
            previous = f"，仍可读取旧版本 v{latest_version}" if latest_version is not None else ""
            stage_label = {"provider_init": "模型服务初始化失败", "generate": "模型生成失败", "save": "结果保存失败"}.get(stage, "生成失败")
            raise HTTPException(
                status_code=502,
                detail=f"复盘报告生成失败（{stage_label}，第 {version} 次尝试已记录{previous}）。请稍后重试。",
            ) from exc


def _valid_workspace_revision(value) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return 0


def _effective_workspace_revision(stored, workspace: dict) -> int:
    stored_int = _valid_workspace_revision(stored)
    if stored_int > 0:
        return stored_int
    # 列 0 才兼容旧 JSON；非法/负数/非整数一律归一为 0，不能再次制造 500/负版本。
    return _valid_workspace_revision(workspace.get("revision")) if isinstance(workspace, dict) else 0


@router.get("/sessions/{session_id}/workspace", response_model=TrainingWorkspaceResponse)
async def get_training_workspace(
    session_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """B-10：读取实训连续任务视图（笔记/步骤）；已结束会话只读。"""
    session = await _require_session_owner(session_id, db, current_user)
    workspace = session.workspace if isinstance(session.workspace, dict) else {}
    return {
        "session_id": session.id,
        "notes": workspace.get("notes") or "",
        "steps": workspace.get("steps") or [],
        "revision": _effective_workspace_revision(session.workspace_revision, workspace),
        "updated_at": workspace.get("updated_at") or "",
        "read_only": session.status != "in_progress",
    }


@router.put("/sessions/{session_id}/workspace", response_model=TrainingWorkspaceResponse)
async def update_training_workspace(
    session_id: int,
    data: TrainingWorkspaceUpdate,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """B-10/BF-04：CAS 持久化笔记/步骤；两个编辑者同一 revision 只能一个成功。"""
    session = await _require_session_owner(session_id, db, current_user)
    if session.status != "in_progress":
        raise HTTPException(status_code=409, detail="该实训会话已结束，只能回看，不能修改笔记")
    workspace = session.workspace if isinstance(session.workspace, dict) else {}
    # BF9：迁移可能留下负数/非法 revision；对用户按 0 归一，但 CAS 必须匹配列里的
    # 真实旧值，否则 GET 报 0、PUT 永远 409，会话被卡死。
    raw_revision = session.workspace_revision
    stored_revision = _valid_workspace_revision(raw_revision)
    current_revision = _effective_workspace_revision(stored_revision, workspace)
    if data.revision != current_revision:
        raise HTTPException(status_code=409, detail=f"笔记已被其他页面修改（当前 revision={current_revision}），请保留本地稿并合并最新内容")
    revision = current_revision + 1
    updated_at = iso_utc(datetime.now(timezone.utc))
    payload = {
        "notes": data.notes,
        "steps": data.steps,
        "revision": revision,
        "updated_at": updated_at,
        "updated_by": current_user.get("user_id"),
    }
    revision_condition = (
        TrainingSession.workspace_revision.is_(None) if raw_revision is None
        else TrainingSession.workspace_revision == raw_revision
    )
    # 原子 CAS：revision 与 active 状态都在同一个 UPDATE 条件内；不能先读后写。
    result = await db.execute(
        update(TrainingSession)
        .where(
            TrainingSession.id == session_id,
            TrainingSession.status == "in_progress",
            revision_condition,
        )
        .values(workspace=payload, workspace_revision=revision)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="笔记并发冲突或会话已结束，本地稿未覆盖；请刷新查看最新版本后合并")
    await db.commit()
    return {
        "session_id": session_id, "notes": payload["notes"],
        "steps": payload["steps"], "revision": revision,
        "updated_at": updated_at, "read_only": False,
    }


@router.get("/sessions/{session_id}/report", response_model=TrainingReportEnvelope)
async def get_training_report(
    session_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
    version: int | None = None,
) -> Any:
    """读取已保存的复盘报告（严格只读，不调用模型）。

    B 起移除 ``?generate=true`` 的 GET 副作用；生成只允许显式 POST。
    传入旧参数会被 FastAPI 忽略（无查询参数声明），不会触发生成。
    """
    session = await _require_session_owner(session_id, db, current_user)
    versions = await report_store.list_versions(db, session_id)
    from modules.training.exports import select_report
    selected = select_report(versions, version)
    result = report_store.envelope(session, versions)
    result['report'] = report_store.serialize_report(selected) if selected is not None else None
    return result


@router.get('/sessions/{session_id}/export', response_model=None)
async def export_training_session(
    session_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
    version: int | None = None,
) -> Any:
    """Export saved notes/logs and the requested ready report; never generate."""
    await _require_session_owner(session_id, db, current_user)
    snapshot = await TrainingService.build_session_snapshot(db, session_id)
    workspace = await get_training_workspace(session_id, db, current_user)
    versions = await report_store.list_versions(db, session_id)
    from modules.training.exports import build_export
    return build_export(snapshot, workspace, versions, version)


@router.post(
    "/sessions/{session_id}/report/generate",
    response_model=TrainingReportEnvelope,
    dependencies=[Depends(_AI_RATE_LIMIT)],
)
async def generate_training_report(
    session_id: int,
    data: TrainingReportGenerate | None = None,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """显式生成复盘报告；``regenerate=true`` 才新增版本。"""
    payload = data or TrainingReportGenerate()
    return await _generate_training_report(
        db,
        session_id,
        current_user,
        regenerate=payload.regenerate,
        idempotency_key=payload.idempotency_key,
    )
