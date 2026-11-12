from contextlib import suppress
from typing import Any
"""AI模块路由"""
import asyncio
import json
from datetime import datetime, timezone
import re
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from core.config import get_settings
from core.database import get_async_session
from core.dependencies import get_current_user, require_role
from core.logger import get_logger
from core.time_utils import iso_utc
from core.request_metrics import timed_stage
from core.rate_limiter import rate_limit
from modules.ai_text.cancel import registry as cancel_registry
from modules.knowledge.service import KnowledgeService
from modules.system.service import SystemService
from modules.ai_text.draft_guard import enforce as enforce_draft_guard
from modules.ai_text.trusted_context import load_verified_evidence, resolve_task_targets, resolve_draft_target, sanitize as sanitize_page_data
from modules.ai_text.draft_environment import resolve_draft_environment, blocked_draft_policy
from modules.ai_text.skills import select_skill
from modules.ai_text.kb_cache import cached_search
from modules.ai_text.retrieval import clean_chunk, expand_query, rerank
from modules.ai_text.context_bundle import prepare_sources, source_documents
from modules.ai_text import lexical_index
from modules.ai_text.protect_ports import load_protected_interfaces
from modules.ai_text.budget_policy import limits_for, select_tier
from modules.ai_text.schemas import (
    CLIRequest, CLIResponse, ReviewRequest, ReviewResponse, AskRequest,
    CopilotChatRequest, CopilotChatResponse, CopilotSessionSave,
    GenerateValidateRequest, GenerateValidateResponse, ConfigPlanRequest, ConfigPlanResponse,
    ReportRequest, ReportResponse, CoachRequest, CoachResponse,
    FeedbackRequest, AILogResponse, AILogListResponse,
    InspectionSummaryRequest, DiffExplanationRequest,
)
from modules.ai_text.llm_service import LLMService

logger = get_logger("ai")


def _kb_provider_label(knowledge: dict | None = None) -> str:
    if knowledge and knowledge.get("provider"):
        return str(knowledge["provider"])
    return get_settings().knowledge_provider or "anythingllm"

router = APIRouter(prefix="/ai", tags=["AI服务"])

# 所有触发外部 LLM/RAG 的接口按 IP+路径限流（30 次/分），防止滥用与计费失控
_AI_RATE_LIMIT = rate_limit(max_requests=30, window_seconds=60)

ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".txt", ".md", ".docx", ".csv", ".json", ".xlsx", ".xls", ".pptx", ".png", ".jpg", ".jpeg"}
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/csv",
    "application/json",
    "image/png",
    "image/jpeg",
}


async def _get_service(db: AsyncSession, current_user: dict) -> LLMService:
    """创建带日志的LLMService"""
    provider = await SystemService.build_llm_provider(db)
    return LLMService(db=db, user_id=current_user.get("user_id"), provider=provider, actor=current_user)


def _get_knowledge_service() -> KnowledgeService:
    """创建知识库服务。"""
    return KnowledgeService.from_settings()


@router.get("/capabilities", response_model=None)
async def get_ai_capabilities(current_user: dict = Depends(get_current_user)) -> dict:
    """Publish only attachment capabilities, never provider credentials/config."""
    configured = bool(get_settings().llm_vision_model.strip())
    allowed = sorted(LLMService._vision_mime_whitelist() & {"image/png", "image/jpeg", "image/webp", "image/gif"})
    return {"vision_enabled": configured and bool(allowed), "image_mime_types": allowed if configured else []}


@router.post("/generate-cli", response_model=CLIResponse, dependencies=[Depends(_AI_RATE_LIMIT)])
async def generate_cli(
    data: CLIRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """自然语言转CLI命令"""
    try:
        service = await _get_service(db, current_user)
        return await service.generate_cli_commands(data.natural_language, data.device_model)
    except Exception as e:
        logger.error("generate_cli_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="命令生成失败，请稍后重试")


@router.post("/generate-and-validate", response_model=GenerateValidateResponse, dependencies=[Depends(_AI_RATE_LIMIT)])
async def generate_and_validate(
    data: GenerateValidateRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """配置生成闭环：自然语言→LLM生成→VRP四层校验→预览"""
    try:
        service = await _get_service(db, current_user)
        return await service.generate_and_validate(data.natural_language, data.device_model)
    except Exception as e:
        logger.error("generate_and_validate_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="配置生成失败，请稍后重试")


@router.post("/config-plans", response_model=ConfigPlanResponse, dependencies=[Depends(_AI_RATE_LIMIT)])
async def generate_config_plan(data: ConfigPlanRequest, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    service = await _get_service(db, current_user)
    return await service.generate_config_plan(data.natural_language, [item.model_dump() for item in data.devices])


@router.post("/review-config", response_model=ReviewResponse, dependencies=[Depends(_AI_RATE_LIMIT)])
async def review_config(
    data: ReviewRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """配置智能审查"""
    try:
        service = await _get_service(db, current_user)
        return await service.review_config(data.config_text, data.device_model)
    except Exception as e:
        logger.error("review_config_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="配置审查失败，请稍后重试")


@router.post("/ask", dependencies=[Depends(_AI_RATE_LIMIT)], response_model=None)
async def ask_knowledge(
    data: AskRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """知识库问答（RAG检索 + LLM生成）"""
    try:
        knowledge = await _get_knowledge_service().ask(data.question, data.kb_id, data.top_k)
        sources = knowledge.get("sources", [])
        answer = knowledge.get("answer") or ""
        if not answer and sources:
            context_docs = []
            for s in sources:
                text = (s.get("content") or s.get("text") or "").strip()
                if not text:
                    continue
                title = s.get("filename") or s.get("title") or ""
                context_docs.append(f"[{title}]\n{text}" if title else text)
            if context_docs:
                service = await _get_service(db, current_user)
                answer = await service.ask_knowledge(data.question, context_docs)
        if not answer:
            answer = "当前知识库不可用或未命中文档，请先导入可信资料后再提问。"
            knowledge["status"] = "degraded"
        return {
            "question": data.question,
            "answer": answer,
            "sources": sources,
            "status": knowledge.get("status", "ok"),
            "provider": _kb_provider_label(knowledge),
        }
    except Exception as e:
        logger.error("ask_knowledge_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="知识库问答失败，请稍后重试")


def _copilot_context_docs(sources: list) -> list[str]:
    return source_documents(sources)


async def _lab_draft_policy(db: AsyncSession, data: CopilotChatRequest, actor: dict | None = None) -> dict[str, Any]:
    """AF-03：实验上下文统一环境防护。

    未核验/缺映射时不仅禁止草稿，也停止让模型生成现场配置（``allow_model=False``），
    只返回安全说明与只读核对；会话/内容来源不可信时同样保守处理。
    """
    default = {
        "lab_scoped": False, "allow_draft": True, "allow_model": True,
        "reason": "", "note": "", "safe_text": "", "content_warning": "",
    }
    if not data.lab_id and not data.lab_session_id:
        if data.lab_steps:
            return {
                **default, "lab_scoped": True, "allow_draft": False, "allow_model": False,
                "reason": "请求携带实验步骤但没有可核验的实验/会话身份，不能生成现场配置。",
                "safe_text": "当前请求没有可核验的实验身份，已停止生成现场配置。请从实训中心进入具体会话后再提问。",
            }
        return default

    from modules.training.content_source import resolve_session_content
    from modules.training.environment_policy import lab_environment, safe_environment_answer
    from modules.training.models import TrainingLab, TrainingSession

    session = None
    lab = None
    if data.lab_session_id:
        session = await db.get(TrainingSession, data.lab_session_id)
        if session is None:
            return {
                **default, "lab_scoped": True, "allow_draft": False, "allow_model": False,
                "reason": "找不到对应的实训会话，不能生成现场配置。",
                "safe_text": "找不到对应的实训会话，已停止生成现场配置。",
            }
        # Match the training routes' owner/admin rule before reading a private
        # session snapshot. A client lab id cannot be mixed with another session.
        if (not actor or (session.trainee_id != actor.get('user_id') and actor.get('role') != 'admin')
                or (data.lab_id is not None and data.lab_id != session.lab_id)):
            return {
                **default, 'lab_scoped': True, 'allow_draft': False, 'allow_model': False,
                'reason': '实训会话身份或访问权限未通过核验。',
                'safe_text': '实训会话身份或访问权限未通过核验，本次未调用模型。请从你有权访问的实训会话重新进入。',
            }
        lab = await db.get(TrainingLab, session.lab_id)
    if lab is None and data.lab_id:
        lab = await db.get(TrainingLab, data.lab_id)
    if lab is None:
        return {
            **default, "lab_scoped": True, "allow_draft": False, "allow_model": False,
            "reason": "找不到对应的实验，不能生成现场配置。",
            "safe_text": "找不到对应的实验，已停止生成现场配置。",
        }
    if session is not None and session.status != "in_progress":
        return {
            **default, "lab_scoped": True, "allow_draft": False, "allow_model": False,
            "reason": "该实训会话已结束，只能回看记录，不能生成现场配置。",
            "safe_text": "该实训会话已结束，只能回看记录；需要练习请新开会话。",
        }

    resolved = resolve_session_content(session, lab) if session is not None else {
        "source": "lab_current", "objectives": lab.objectives or [], "title": lab.title,
        "version": lab.content_version, "warning": "", "can_guide": True,
    }
    frozen_spec = resolved.get('environment_spec')
    if isinstance(frozen_spec, dict):
        from types import SimpleNamespace
        guard = lab_environment(SimpleNamespace(environment_spec=frozen_spec))
    else:
        guard = lab_environment(lab)
    if not resolved.get("can_guide", True):
        answer = safe_environment_answer(
            title=resolved["title"] or lab.title,
            reason=resolved["warning"],
            content_warning="",
        )
        return {
            **default, "lab_scoped": True, "allow_draft": False, "allow_model": False,
            "reason": resolved["warning"], "safe_text": answer["text"],
            "content_warning": resolved["warning"],
        }
    if not guard["allow_executable"]:
        answer = safe_environment_answer(
            title=resolved["title"] or lab.title,
            reason=guard["reason"],
            content_warning=resolved.get("warning") or "",
        )
        from modules.training.environment_policy import readonly_training_ui_help
        help_text = readonly_training_ui_help(data.message) if not data.want_draft else ''
        return {
            **default, "lab_scoped": True, "allow_draft": False, "allow_model": False,
            "reason": guard["reason"], "safe_text": help_text or answer["text"],
            "content_warning": resolved.get("warning") or "",
        }
    return {**default, "lab_scoped": True,
            'lab_steps':[item for item in (resolved.get('objectives') or []) if isinstance(item,dict)][:30],
            'lab_content':{key:resolved.get(key) for key in ('source','title','version','warning')}}


def _apply_policy_note(ui: dict, policy: dict) -> dict:
    note = policy.get("note") or ""
    if not note:
        return ui
    merged = {**ui}
    merged["notes"] = f"{ui.get('notes') or ''}\n{note}".strip()
    return merged


@timed_stage("retrieval")
async def _retrieve(message: str, top_k: int, cancel_event=None) -> list[dict]:
    """向量召回 + 网络术语扩展 + 同 K 重排；词法/融合为实验通道。"""
    expanded = expand_query(message)
    vector_hits: list[dict] = []
    retrieval_error = None
    try:
        # Candidate expansion occurs once; preserve the previously effective
        # pool size so cache repair does not silently change retrieval quality.
        vector_hits = await cached_search(_get_knowledge_service(), expanded, max(top_k * 4, 20))
        vector_hits = [{**h, "content": clean_chunk(str(h.get("content") or ""))} for h in vector_hits]
    except Exception as exc:  # noqa: BLE001
        logger.warning("vector_retrieval_failed", error=type(exc).__name__)
        retrieval_error = exc
    import os
    if os.environ.get("AI_DUAL_RETRIEVAL") == "1":
        try:
            lexical_hits = lexical_index.search(message, max(top_k * 2, 10))
            if lexical_hits:
                # Experimental fusion is not promoted without a quality win.
                return lexical_index.fuse(vector_hits, lexical_hits, top_k)
        except Exception as exc:  # noqa: BLE001
            logger.warning("lexical_retrieval_failed", error=type(exc).__name__)
    if retrieval_error is not None:
        # A failed provider without a successful optional fallback is not an
        # empty corpus. Let both transports report the actual degraded state.
        raise RuntimeError("Knowledge retrieval unavailable") from retrieval_error
    # Historical reranking measurements are not current whole-stage acceptance.
    return rerank(vector_hits, expanded, top_k, original_query=message)


async def _resolve_page_data(db: Any, data: CopilotChatRequest, current_user: dict) -> Any:
    """C-R2：优先按 evidence_id 回读服务端观察；客户端 JSON 仅作线索。"""
    from .skills import dashboard_summary_question
    if not data.want_draft and dashboard_summary_question(data.message, data.context.route if data.context else None):
        from .trusted_context import TrustedPageData
        from modules.dashboard.service import DashboardService
        try:
            if db is None:
                raise ValueError("No database session")
            summary = await DashboardService.get_summary(db, probe_services=False)
            topology = summary.get("topology")
            snapshot = {
                "kind": "dashboard_summary", "source": "database_snapshot",
                "collected_at": summary["generated_at"].isoformat(),
                "devices": summary["devices"],
                "tasks": {key: summary["tasks"][key] for key in ("active", "pending", "failed")},
                "alarms": {key: summary["alarms"][key] for key in ("active", "critical")},
                "topology": {key: topology.get(key) for key in ("name", "device_count", "link_count")} if topology else None,
                "topology_scope": "active_main_topology_only；null表示当前没有可用的活跃主拓扑，不代表没有其他实训拓扑，也不是零条链路。",
                "training": summary["training"],
                "pending_approval": summary["risks"]["pending_approval"],
                "monitor_scheduler_enabled": summary["monitor_scheduler_enabled"],
                "scope": "提问时读取的数据库汇总，可能比屏幕旧值更新；不是本轮设备探测或服务健康检查。在线数量不能证明协议与业务正常。",
            }
            return TrustedPageData(json.dumps(snapshot, ensure_ascii=False),
                                   {"trusted": True, "source": "database_snapshot", "kind": "dashboard_summary"})
        except Exception as exc:
            logger.warning("copilot_dashboard_summary_unavailable", error=type(exc).__name__)
            return TrustedPageData(None, {"trusted": False, "reasons": ["server_summary_unavailable"]})
    selection = data.context.selection if data.context else None
    evidence_id = None
    evidence_meta = None
    try:
        parsed = json.loads(data.page_data) if data.page_data else None
        if isinstance(parsed, dict):
            value = parsed.get("evidence_id")
            if type(value) is int and value > 0:
                evidence_id = value
    except (TypeError, ValueError):
        evidence_id = None
    if evidence_id and db is not None:
        verified = await load_verified_evidence(
            db, int(evidence_id), user=current_user, selection=selection
        )
        if verified is not None and (verified.trusted or verified.meta.get('record_origin') == 'server_observation_record'):
            logger.info("page_data_evidence_resolved", evidence_id=int(evidence_id),
                        trusted=verified.trusted, reasons=verified.meta.get('reasons', []))
            return verified
        evidence_meta = verified.meta if verified is not None else {"trusted": False, "reasons": ["evidence_not_found_or_forbidden"]}
        logger.info("page_data_evidence_untrusted", evidence_id=int(evidence_id),
                    reasons=(verified.meta.get("reasons") if verified else ["not_found"]))
    # 结构化包装里的 text 仍可作不可信线索；不因 evidence 失败丢掉页面上下文
    try:
        parsed = json.loads(data.page_data) if data.page_data else None
        if isinstance(parsed, dict) and isinstance(parsed.get("text"), str):
            page = sanitize_page_data(parsed["text"], selection=selection)
            if evidence_meta is not None:
                page.meta = evidence_meta
            return page
    except (TypeError, ValueError):
        pass
    page = sanitize_page_data(data.page_data, selection=selection)
    if evidence_meta is not None:
        page.meta = evidence_meta
    return page


async def _generate_copilot_chat(
    data: CopilotChatRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
    cancel_event: asyncio.Event | None = None,
) -> Any:
    """右侧常驻 Copilot：上下文感知 + RAG + 可选配置草稿（不执行）。"""
    try:
        page = await _resolve_page_data(db, data, current_user)
        policy = await _lab_draft_policy(db, data, current_user)
        lab_steps = policy.get('lab_steps',[])
        attachments = [
            {"contentString": a.contentString, "mime": a.mime}
            for a in (data.attachments or [])
        ]
        try:
            # C-04：检索与生成解耦。ask 会触发 AnythingLLM 内部再生成一次（慢且重复计费），
            # 改为只做检索，把命中片段交给同一次模型生成，来源仍可逐条追溯。
            intent = select_skill(data.message, want_draft=data.want_draft, lab_steps=lab_steps, history=data.history,
                                  page_data=page.text, page_data_trusted=page.trusted,
                                  route=data.context.route if data.context else None)
            hit_list = await _retrieve(data.message, data.top_k) if intent.needs_knowledge else []
            sources = prepare_sources((hit_list or [])[:data.top_k])
            knowledge = {"sources": sources, "status": ("not_requested" if not intent.needs_knowledge else "ok" if sources else "empty"), "provider": _kb_provider_label()}
        except Exception as exc:  # noqa: BLE001
            logger.warning("copilot_knowledge_degraded", error=str(exc))
            knowledge = {"sources": [], "status": "degraded", "provider": _kb_provider_label()}
        sources = knowledge.get("sources", [])
        context_docs = _copilot_context_docs(sources)

        draft_target = None
        draft_environment = None
        if data.want_draft and policy['allow_model'] and policy['allow_draft']:
            draft_target = await resolve_draft_target(db,data.message,data.context.selection if data.context else '',current_user)
            draft_environment = await resolve_draft_environment(db,draft_target,page=page)
            if not draft_environment.verified:
                policy = blocked_draft_policy(policy,draft_environment.reason)
                draft_target = None
        if not policy["allow_model"]:
            # 未核验环境：不调用模型，直接返回安全说明 + 教材引用（仍可阅读原文）
            answer = policy["safe_text"]
            return CopilotChatResponse(
                answer=answer,
                sources=sources[: data.top_k],
                draft_commands=[],
                draft_explanation="",
                draft_refused_reason=policy["reason"],
                request_id=data.request_id or "",
                assist_only=True,
                status="blocked_environment",
                provider=_kb_provider_label(knowledge),
                knowledge_status=knowledge.get("status", "unknown"),
            )
        try:
            service = await _get_service(db, current_user)
        except Exception as exc:  # noqa: BLE001
            logger.error("copilot_chat_provider_unavailable", error=type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "provider_unavailable",
                    "message": "模型服务初始化失败，本次未调用模型；请稍后重试或联系管理员检查模型配置。",
                },
            ) from exc
        ui = _apply_policy_note(data.context.model_dump() if data.context else {}, policy)
        # C-05：把已认证角色带入上下文，避免普通用户被引导到管理员专属页面
        ui["role"] = current_user.get("role") or "user"
        ui["page_data_trusted"] = page.trusted
        ui['server_page_validation'] = page
        ui['server_lab_content'] = policy.get('lab_content')
        ui['server_knowledge_status'] = knowledge.get('status')
        if page.meta.get("trusted") is False:
            reasons = ",".join(page.meta.get("reasons") or [])
            ui["notes"] = (
                (ui.get("notes") or "")
                + f"；页面数据未通过服务端可信核验（{reasons}），只能作为线索，不得当作现场事实"
            ).strip("；")
        skill = select_skill(
            data.message,
            want_draft=data.want_draft and policy["allow_draft"],
            lab_steps=lab_steps, history=data.history,
            page_data=page.text,
            page_data_trusted=page.trusted,
            route=(data.context.route if data.context else None),
        )
        ui["skill"] = skill.label
        ui["skill_prompt"] = skill.prompt
        ui["skill_id"] = skill.id
        ui["skill_version"] = skill.version
        if skill.id in {'live_evidence','troubleshooting','lab_coach'}:
            from .owned_history import load_owned_history
            ui['server_history'] = await load_owned_history(db, data.history, current_user)
        if draft_target:
            ui['server_draft_target'] = draft_target
            ui['server_draft_environment'] = draft_environment
        if skill.tools and skill.id in {"troubleshooting", "live_evidence"}:
            ui["server_targets"] = await resolve_task_targets(db, data.message, current_user)
        tier = select_tier(data.message, page_data=page.text,
                           want_draft=data.want_draft and policy["allow_draft"], skill_id=skill.id)
        if skill.reason in {'verified_observation_explanation','observation_provenance_explanation',
                            'operational_history_recap','verified_lab_step_explanation','verified_lab_assessment_explanation'}:
            tier = "direct"
        # C-R2：同步入口复用同一流式执行器，只做事件聚合，不再维护第二套流程。
        protected = await load_protected_interfaces(db, target=draft_target)
        ui['server_protected_interfaces']=tuple(protected)
        events: list[dict] = []
        async for _event in service.copilot_chat_stream(
            message=data.message,
            context_docs=context_docs,
            ui_context=ui,
            history=data.history,
            want_draft=data.want_draft and policy["allow_draft"],
            device_model=data.device_model,
            page_data=page.text,
            attachments=attachments,
            lab_steps=lab_steps,
            allowed_tools=skill.tools,
            protected_interfaces=protected,
            request_id=data.request_id,
            cancel_event=cancel_event,
            tier=tier,
        ):
            events.append(_event)
        answer_parts: list[str] = []
        draft_commands: list[str] = []
        draft_explanation = ""
        trace: dict = {}
        stream_status = "ok"
        error_message = ""
        stream_refused = ""
        for _event in events:
            _type = _event.get("type")
            if _type == "token":
                answer_parts.append(_event.get("text") or "")
            elif _type == "draft":
                draft_commands = _event.get("draft_commands") or draft_commands
                draft_explanation = _event.get("draft_explanation") or draft_explanation
            elif _type == "policy":
                stream_refused = _event.get("draft_refused_reason") or stream_refused
                if 'replace_answer' in _event:
                    answer_parts = [_event['replace_answer']]
                    draft_commands = []
                    draft_explanation = ''
                if 'draft_target' in _event and _event['draft_target'] is None:
                    draft_target = None
            elif _type == "done":
                trace = _event.get("trace") or {}
                stream_status = _event.get("status") or stream_status
            elif _type == "error":
                stream_status = "failed"
                error_message = _event.get("message") or ""
        result = {
            "answer": "".join(answer_parts),
            "draft_commands": draft_commands,
            "draft_explanation": draft_explanation,
            "status": stream_status,
            "trace": trace,
        }
        answer = result.get("answer") or ""
        refused = stream_refused or (policy["reason"] if data.want_draft and not policy["allow_draft"] else "")
        # CF-03：正文与结构化草稿统一过保护口防线，再返回给客户端。
        guarded = enforce_draft_guard(answer, result.get("draft_commands") or [], explanation=result.get("draft_explanation") or "", protected=protected)
        answer = guarded.answer
        if guarded.refused_reason:
            refused = refused or guarded.refused_reason
        if refused and f"未生成配置草稿：{refused}" not in answer:
            answer = f"{answer}\n\n> 未生成配置草稿：{refused}".strip()
        if not answer:
            answer = error_message or ("本次请求已取消，未完成回答。" if stream_status == "cancelled"
                                      else "本次未能生成回答正文，请稍后重试。")
            if stream_status == "ok":
                result["status"] = "failed"
        return CopilotChatResponse(
            answer=answer,
            sources=sources[: data.top_k],
            draft_commands=guarded.commands,
            draft_explanation=guarded.explanation,
            draft_refused_reason=refused,
            draft_target=draft_target.as_meta() if draft_target else None,
            request_id=data.request_id or "",
            assist_only=True,
            status=result.get("status") or knowledge.get("status") or "ok",
            provider=_kb_provider_label(knowledge),
            knowledge_status=knowledge.get("status", "unknown"),
            tier=tier,
            trace=result.get("trace") or {},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("copilot_chat_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Copilot 对话失败，请稍后重试")


async def _watch_request_disconnect(
    request: Request, cancel_event: asyncio.Event, on_disconnect=None
) -> bool:
    """在响应头发出前读取 http.disconnect；返回是否已断开。

    准备阶段还没有 Starlette 的流式 listener，因此由本函数独占 receive；请求体在进入
    路由前已由 FastAPI 解析。返回 StreamingResponse 前会取消本监听，流式阶段交回框架，
    避免两个 receive 消费者并发争抢。
    """
    try:
        # 请求体在进入路由前已由 FastAPI 解析；这里只等待真正的 disconnect 消息。
        # 不用 request.is_disconnected()：它是立即取消的非阻塞轮询，等不到后续断连。
        while True:
            message = await request.receive()
            if message.get("type") == "http.disconnect":
                if on_disconnect is not None:
                    on_disconnect()
                cancel_event.set()
                return True
            if message.get("type") == "http.request" and message.get("more_body"):
                continue
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        return False


async def _generate_copilot_stream(
    data: CopilotChatRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    cancel_event: asyncio.Event | None = None,
) -> Any:
    """右侧 Copilot SSE 流式对话（逐 token）。

    注意：这里**不**注入 get_async_session。FastAPI 会把 yield 依赖持有到响应结束，
    也就是整条 SSE 期间独占一个连接池连接；改为进入流之前用短会话取一次 provider，
    流内的工具调用与日志落库各自开短会话（LLMService.use_short_sessions=True）。
    """
    import json
    from core.database import get_session_factory

    from modules.ai_text.cancel import RequestCancelled, run_cancellable

    attachments = [
        {"contentString": a.contentString, "mime": a.mime}
        for a in (data.attachments or [])
    ]
    user_id = current_user.get("user_id")
    request_id = (data.request_id or "").strip() or f"req-{uuid.uuid4().hex[:16]}"
    factory = get_session_factory()
    # C.3：外层生命周期先登记取消并持久预留 ID，再进入准备/检索。
    if cancel_event is None:
        raise RuntimeError("Copilot stream requires a reserved request")
    def release_registration() -> None:
        cancel_registry.unregister(user_id, request_id, event=cancel_event)

    disconnect_task = asyncio.create_task(_watch_request_disconnect(request, cancel_event, release_registration))
    policy: dict[str, Any] = {
        "lab_scoped": False, "allow_draft": True, "allow_model": True,
        "reason": "", "note": "", "safe_text": "", "content_warning": "",
    }
    knowledge: dict[str, Any] = {"sources": [], "status": "ok", "provider": _kb_provider_label()}
    provider = None
    provider_error: str = ""
    draft_target = None
    draft_environment = None
    cancelled_during_setup = False
    page = sanitize_page_data(data.page_data, selection=data.context.selection if data.context else None)
    try:
        if factory is not None:
            try:
                async with factory() as setup_db:
                    policy = await run_cancellable(_lab_draft_policy(setup_db, data, current_user), cancel_event, release_registration)
                    page = await run_cancellable(_resolve_page_data(setup_db, data, current_user), cancel_event, release_registration)
                    if data.want_draft and policy['allow_model'] and policy['allow_draft']:
                        draft_target = await run_cancellable(resolve_draft_target(setup_db,data.message,data.context.selection if data.context else '',current_user),cancel_event)
                        draft_environment = await run_cancellable(resolve_draft_environment(setup_db,draft_target,page=page),cancel_event)
                        if not draft_environment.verified:
                            policy = blocked_draft_policy(policy,draft_environment.reason)
                            draft_target = None
            except RequestCancelled:
                cancelled_during_setup = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("copilot_policy_failed", error=str(exc))
                if data.want_draft or data.lab_id or data.lab_session_id or data.lab_steps:
                    policy = blocked_draft_policy(policy,'环境核验暂不可用，不能生成具体设备配置。')
                    draft_target = None
        elif data.want_draft or data.lab_id or data.lab_session_id or data.lab_steps:
            policy = blocked_draft_policy(policy,'环境核验暂不可用，不能生成具体设备配置。')
        lab_steps = policy.get('lab_steps',[])
        try:
            # CF-02：流式与同步统一走 search，来源/状态/provider 归一，避免 ask 的隐藏二次生成。
            intent = select_skill(data.message, want_draft=data.want_draft, lab_steps=lab_steps, history=data.history,
                                  page_data=page.text, page_data_trusted=page.trusted,
                                  route=data.context.route if data.context else None)
            hit_list = (await run_cancellable(_retrieve(data.message, data.top_k), cancel_event)
                        if intent.needs_knowledge else [])
            stream_sources = prepare_sources((hit_list or [])[:data.top_k])
            knowledge = {
                "sources": stream_sources,
                "status": "not_requested" if not intent.needs_knowledge else "ok" if stream_sources else "empty",
                "provider": _kb_provider_label(),
            }
        except RequestCancelled:
            cancelled_during_setup = True
        except Exception as e:
            logger.warning("copilot_knowledge_degraded", error=str(e))
            knowledge = {"sources": [], "status": "degraded", "provider": _kb_provider_label()}

        if policy.get("allow_model") and not cancelled_during_setup:
            try:
                if factory is not None:
                    async with factory() as setup_db:
                        provider = await run_cancellable(
                            SystemService.build_llm_provider(setup_db), cancel_event
                        )
                if provider is None:
                    from core.llm_provider import create_llm_provider
                    provider = await run_cancellable(
                            asyncio.to_thread(create_llm_provider), cancel_event, release_registration
                        )
            except RequestCancelled:
                cancelled_during_setup = True
            except Exception as exc:  # noqa: BLE001
                # AF2-04：初始化失败是依赖不可用，不是环境策略阻断；只暴露稳定类型，不带密钥/URL。
                provider_error = type(exc).__name__
                logger.warning("copilot_provider_init_failed", error=provider_error)
    except BaseException:
        if not disconnect_task.done():
            disconnect_task.cancel()
        with suppress(BaseException):
            await disconnect_task
        cancel_registry.unregister(user_id, request_id, event=cancel_event)
        raise

    if not disconnect_task.done():
        disconnect_task.cancel()
        with suppress(BaseException):
            await disconnect_task
        disconnected = False
    else:
        disconnected = bool(disconnect_task.result()) if not disconnect_task.cancelled() else False
    if disconnected:
        cancel_registry.unregister(user_id, request_id, event=cancel_event)
        return Response(status_code=204)

    if cancelled_during_setup:
        # 生成器可能还没被 Starlette 启动；先注销，避免登记泄漏。
        cancel_registry.unregister(user_id, request_id, event=cancel_event)

    sources = knowledge.get("sources", [])[: data.top_k]
    context_docs = _copilot_context_docs(sources)
    ui = _apply_policy_note(data.context.model_dump() if data.context else {}, policy)
    # CF-02：流式入口同样使用后端认证角色，客户端自报角色不参与。
    ui["role"] = current_user.get("role") or "user"
    protected: list[str] = []
    if factory is not None:
        async with factory() as _policy_db:
            if draft_target:
                ui['server_draft_target'] = draft_target
                ui['server_draft_environment'] = draft_environment
            protected = await load_protected_interfaces(_policy_db,target=draft_target)
    ui['server_protected_interfaces']=tuple(protected)
    ui["page_data_trusted"] = page.trusted
    ui['server_page_validation'] = page
    ui['server_lab_content'] = policy.get('lab_content')
    ui['server_knowledge_status'] = knowledge.get('status')
    if page.meta.get("trusted") is False:
        reasons = ",".join(page.meta.get("reasons") or [])
        ui["notes"] = (
            (ui.get("notes") or "")
            + f"；页面数据未通过服务端可信核验（{reasons}），只能作为线索，不得当作现场事实"
        ).strip("；")
    skill = select_skill(
        data.message,
        want_draft=data.want_draft and policy["allow_draft"],
        lab_steps=lab_steps, history=data.history,
        page_data=page.text,
        page_data_trusted=page.trusted,
        route=(data.context.route if data.context else None),
    )
    ui["skill"] = skill.label
    ui["skill_prompt"] = skill.prompt
    ui["skill_id"] = skill.id
    ui["skill_version"] = skill.version
    if factory is not None and not cancelled_during_setup and skill.id in {'live_evidence','troubleshooting','lab_coach'}:
        from .owned_history import load_owned_history
        try:
            async with factory() as history_db:
                ui['server_history'] = await run_cancellable(
                    load_owned_history(history_db, data.history, current_user), cancel_event)
        except RequestCancelled:
            cancelled_during_setup = True
    if factory is not None and skill.tools and skill.id in {"troubleshooting", "live_evidence"} and not cancelled_during_setup:
        async with factory() as target_db:
            ui["server_targets"] = await resolve_task_targets(target_db, data.message, current_user)
    tier = select_tier(data.message, page_data=page.text,
                       want_draft=data.want_draft and policy["allow_draft"], skill_id=skill.id)
    if skill.reason in {'verified_observation_explanation','observation_provenance_explanation',
                        'operational_history_recap','verified_lab_step_explanation','verified_lab_assessment_explanation'}:
        tier = "direct"
    draft_refused = policy["reason"] if data.want_draft and not policy["allow_draft"] else ""
    service = None
    if policy.get("allow_model") and provider is not None and not cancelled_during_setup:
        service = LLMService(
            db=None,
            user_id=user_id,
            provider=provider,
            use_short_sessions=True,
            actor=current_user,
        )
    # Both transports expose exactly the bounded generation excerpts and their
    # hashes; no second 1200-character truncation for stream consumers/judges.
    slim_sources = [{k: v for k, v in s.items() if k != "prompt_text"} for s in sources]

    def sse(event: dict) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    async def generate() -> Any:
        stream = None
        try:
            yield sse({
                "type": "meta", "request_id": request_id, "sources": slim_sources,
                "provider": _kb_provider_label(knowledge),
                "knowledge_status": knowledge.get("status", "unknown"),
                "skill": skill.as_meta(),
                "status": (
                    "blocked_environment" if not policy.get("allow_model")
                    else ("unavailable" if provider_error else (knowledge.get("status") or "ok"))
                ),
                "assist_only": True, "draft_refused_reason": draft_refused,
                "draft_target": draft_target.as_meta() if draft_target else None,
            })
            if draft_refused:
                yield sse({"type": "policy", "draft_refused_reason": draft_refused})
            if cancelled_during_setup or cancel_event.is_set():
                yield sse({
                    "type": "cancelled", "request_id": request_id,
                    "upstream": "abort_requested",
                    "note": "请求在准备阶段被取消；未调用模型，也未确认供应商计费状态",
                })
                yield sse({"type": "done", "status": "cancelled", "assist_only": True, "cancelled": True})
                return
            if service is None and provider_error:
                # AF2-04：模型依赖初始化失败；明确 failed/unavailable，不能冒充“环境未核验”。
                yield sse({
                    "type": "error", "code": "provider_unavailable", "retryable": True,
                    "message": "模型服务初始化失败，本次未调用模型。请稍后重试；若持续失败，请联系管理员检查模型配置。",
                })
                yield sse({
                    "type": "done", "status": "failed", "reason": "provider_unavailable",
                    "assist_only": True,
                })
                return
            if service is None:
                # 未核验环境：不调用模型，只输出安全说明与只读核对。
                text = policy.get("safe_text") or "当前环境未核验，已停止生成现场配置。"
                for index in range(0, len(text), 80):
                    if cancel_event.is_set():
                        break
                    yield sse({"type": "token", "text": text[index:index + 80], "request_id": request_id})
                yield sse({
                    "type": "done", "status": "blocked_environment",
                    "assist_only": True, "blocked": True,
                })
                return
            stream = service.copilot_chat_stream(
                message=data.message,
                context_docs=context_docs,
                ui_context=ui,
                history=data.history,
                want_draft=data.want_draft and policy["allow_draft"],
                device_model=data.device_model,
                page_data=page.text,
                attachments=attachments,
                lab_steps=lab_steps,
                request_id=request_id,
                cancel_event=cancel_event,
                allowed_tools=skill.tools,
                protected_interfaces=protected,
                tier=tier,
            )
            async for event in stream:
                event.setdefault("request_id", request_id)
                yield sse(event)
                if event.get("type") == "done":
                    break
        except asyncio.CancelledError:
            cancel_event.set()
            raise
        except Exception as e:
            logger.error("copilot_chat_stream_failed", error=str(e), exc_info=True)
            yield sse({"type": "error", "message": "Copilot 流式对话失败"})
            yield sse({"type": "done", "status": "failed"})
        finally:
            cancel_registry.unregister(user_id, request_id, event=cancel_event)
            if stream is not None:
                try:
                    await stream.aclose()
                except Exception:  # noqa: BLE001
                    pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/copilot/chat", response_model=CopilotChatResponse, dependencies=[Depends(_AI_RATE_LIMIT)])
async def copilot_chat(
    data: CopilotChatRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    from core.database import get_session_factory
    from .request_lifecycle import execute

    async def invoke(request_data, cancel_event):
        return await _generate_copilot_chat(request_data, db, current_user, cancel_event)
    return await execute(data, current_user, get_session_factory(), invoke, streaming=False)


@router.post("/copilot/chat/stream", dependencies=[Depends(_AI_RATE_LIMIT)])
async def copilot_chat_stream(
    data: CopilotChatRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> Any:
    from core.database import get_session_factory
    from .request_lifecycle import execute

    async def invoke(request_data, cancel_event):
        return await _generate_copilot_stream(request_data, request, current_user, cancel_event)
    return await execute(data, current_user, get_session_factory(), invoke, streaming=True)


@router.get("/copilot/requests/{request_id}")
async def get_copilot_request(request_id: str, current_user: dict = Depends(get_current_user)):
    from core.database import get_session_factory
    from .request_store import RequestStore
    return await RequestStore(get_session_factory()).read(request_id, current_user)


@router.post("/copilot/requests/{request_id}/cancel", response_model=None)
async def cancel_copilot_request(
    request_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """请求取消本次 AI 回答（检索/生成阶段均可）。

    只取消本次请求，不撤销任何已提交到设备的配置。返回 ``upstream`` 只是
    “已请求关闭上游连接”，供应商是否停止计费无法从客户端确认。
    """
    found = cancel_registry.request_cancel(current_user.get("user_id"), request_id)
    if not found:
        return {
            "request_id": request_id,
            "cancelled": False,
            "upstream": "not_found",
            "note": "请求已结束或不存在；没有可取消的活动请求",
        }
    return {
        "request_id": request_id,
        "cancelled": True,
        "upstream": "abort_requested",
        "note": "已请求关闭上游连接并停止转发；供应商是否停止计费无法确认",
    }


@router.get("/logs", response_model=AILogListResponse)
async def get_ai_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    request_type: str = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """查询AI交互日志"""
    try:
        service = await _get_service(db, current_user)
        return await service.get_logs(page, page_size, request_type)
    except Exception as e:
        logger.error("get_ai_logs_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="查询日志失败，请稍后重试")


@router.post("/logs/{log_id}/feedback", dependencies=[Depends(_AI_RATE_LIMIT)], response_model=None)
async def set_feedback(
    log_id: int,
    data: FeedbackRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """设置AI交互反馈"""
    try:
        service = await _get_service(db, current_user)
        success = await service.set_feedback(log_id, data.feedback)
        if not success:
            raise HTTPException(status_code=404, detail="日志不存在")
        return {"message": "反馈已记录"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("set_feedback_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="反馈记录失败，请稍后重试")


@router.post("/inspection-summary", dependencies=[Depends(_AI_RATE_LIMIT)], response_model=None)
async def inspection_summary(
    data: InspectionSummaryRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """B5：对一次巡检/采集任务的结果做 AI 归因总结。

    输入只取该任务的报告 JSON（metrics/alarm 统计），不重新采集；LLM 不可用时
    `generate_report` 内部走静态模板降级，不会 500。
    """
    from modules.monitor.models import MonitorJob

    job = await db.get(MonitorJob, data.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="巡检任务不存在，请先执行一次采集")
    if job.status == "running":
        raise HTTPException(status_code=409, detail="任务仍在执行，完成后才能总结")

    def _load(raw: str | None) -> Any:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    report_payload = _load(job.report_json)
    summary_payload = _load(job.summary_json)
    source_text = json.dumps(
        {
            "job_id": job.id,
            "job_type": getattr(job.job_type, "value", str(job.job_type)),
            "status": getattr(job.status, "value", str(job.status)),
            "trigger_mode": getattr(job.trigger_mode, "value", str(job.trigger_mode)),
            "device_count": job.device_count,
            "success_count": job.success_count,
            "failure_count": job.failure_count,
            "error_message": job.error_message,
            "report": report_payload,
            "summary": summary_payload,
        },
        ensure_ascii=False,
        indent=2,
    )
    try:
        service = await _get_service(db, current_user)
        report = await service.generate_report(
            title=f"巡检任务 #{job.id} 异常归因与处置建议",
            source_text=source_text,
            context="对象：华为 VRP 网络设备的指标采集/巡检结果。请给出异常归因、影响范围与处置建议。",
        )
        return {"job_id": job.id, **report}
    except Exception as e:
        logger.error("inspection_summary_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="巡检总结生成失败，请稍后重试")


@router.post("/diff-explanation", dependencies=[Depends(_AI_RATE_LIMIT)], response_model=None)
async def diff_explanation(
    data: DiffExplanationRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """B5：用白话解释两个配置版本之间的差异。

    只解释脱敏、有序、有界的差异及相邻行；保留原验证接口的兼容差异字段。
    """
    from modules.deploy.config_verifier import ConfigVerifier
    from modules.deploy.display_diff import display_diff_excerpt
    from modules.deploy.models import ConfigVersion
    from modules.ai_text.llm_service import redact_sensitive

    v1 = await db.get(ConfigVersion, data.version_id_a)
    v2 = await db.get(ConfigVersion, data.version_id_b)
    if not v1 or not v2:
        raise HTTPException(status_code=404, detail="配置版本不存在")
    if v1.id == v2.id:
        raise HTTPException(status_code=400, detail="请选择两个不同的配置版本")

    diff = ConfigVerifier.compare(redact_sensitive(v1.config_snapshot or ""), redact_sensitive(v2.config_snapshot or ""), preserve_case=True)
    excerpt = display_diff_excerpt(v1.config_snapshot or '', v2.config_snapshot or '')
    identity = {'version_id_a': v1.id, 'version_id_b': v2.id,
                'device_id_a': v1.device_id, 'device_id_b': v2.device_id,
                'same_device': v1.device_id == v2.device_id, 'text_excerpt_truncated': excerpt['truncated']}
    if not excerpt['text']:
        return {
            **identity,
            "explanation": ("当前片段没有可展示差异；材料已截断，不能判断完整变化。" if excerpt['truncated'] and excerpt['different'] else "可展示文本没有差异；凭据等字段已脱敏，其内容变化不能据此判断。"),
            "diff": diff,
        }

    try:
        service = await _get_service(db, current_user)
        report = await service.generate_report(
            title=f"配置差异说明：v{v1.version_number} → v{v2.version_number}",
            source_text=excerpt['text'],
            context=(f"对象：华为 VRP 脱敏有序文本。A设备#{v1.device_id}/快照#{v1.id}/版本{v1.version_number}，"
                     f"B设备#{v2.device_id}/快照#{v2.id}/版本{v2.version_number}。"
                     f"同设备={identity['same_device']}；片段截断={excerpt['truncated']}。"
                     "保留大小写、重复行及相邻视图；+/-只表示文本增删。不同设备只能作跨设备文本对照。"
                     "仅依据展示片段说明含义和可能影响；没有执行、设备回读或业务验证证据，不能认定已变更、恢复或根因。凭据内容无法判断。"
                     "这是简短的文本差异说明：summary最多60字，key_findings最多4项，recommendations最多3项，report_text最多300字。"
                     "没有原因证据时root_causes填空列表，不编造可能原因，不从行数变化推断整块重写。"
                     "建议只读核对，不主动建议统一、清理或写配置；接口Up不能证明业务正常。每个边界说明一次。"),
            field_limits={'summary':60,'report_text':300},
        )
        return {**identity, "diff": diff, **report}
    except Exception as e:
        logger.error("diff_explanation_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="差异说明生成失败，请稍后重试")


@router.post("/report", response_model=ReportResponse, dependencies=[Depends(_AI_RATE_LIMIT)])
async def generate_report(
    data: ReportRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """AI报告助手"""
    try:
        service = await _get_service(db, current_user)
        return await service.generate_report(data.title, data.source_text, data.context)
    except Exception as e:
        logger.error("generate_report_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="报告生成失败，请稍后重试")


@router.post("/coach", response_model=CoachResponse, dependencies=[Depends(_AI_RATE_LIMIT)])
async def coach_training(
    data: CoachRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    """AI实训教练"""
    try:
        service = await _get_service(db, current_user)
        return await service.coach_training(data.goal, data.scenario, data.current_step, data.history)
    except Exception as e:
        logger.error("coach_training_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="训练建议生成失败，请稍后重试")


@router.get("/knowledge/health", response_model=None)
async def knowledge_health(
    current_user: dict = Depends(get_current_user),
) -> Any:
    """知识库健康检查。"""
    try:
        return await _get_knowledge_service().health_check()
    except Exception as e:
        logger.error("knowledge_health_failed", error=str(e), exc_info=True)
        return {
            "available": False,
            "provider": _kb_provider_label(),
            "error": "知识库健康检查失败",
        }


@router.post("/knowledge/upload", dependencies=[Depends(_AI_RATE_LIMIT)], response_model=None)
async def upload_knowledge(
    kb_id: str = None,
    file: UploadFile = File(...),
    current_user: dict = Depends(require_role("admin")),
) -> Any:
    """上传知识库文档（仅管理员：知识库是全员共享语料，被投毒会影响所有用户的 RAG 上下文）"""
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="文件名缺失")
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_UPLOAD_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")
        if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(status_code=400, detail=f"不支持的MIME类型: {file.content_type}")

        policy = _get_knowledge_service().policy
        max_bytes = policy.max_file_size_mb * 1024 * 1024

        # 先按 Content-Length 早退，再分块读取（此前一次性 read() 到内存后才判大小，
        # 20MB 限制形同虚设：超大文件已经占满内存）
        declared = getattr(file, "size", None)
        if isinstance(declared, int) and declared > max_bytes:
            raise HTTPException(status_code=413, detail=f"文件大小超过限制(最大{policy.max_file_size_mb}MB)")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(status_code=413, detail=f"文件大小超过限制(最大{policy.max_file_size_mb}MB)")
            chunks.append(chunk)
        content = b"".join(chunks)

        # 校验文档数量上限（防止并发超限）
        ks = _get_knowledge_service()
        existing_docs = await ks.list_documents(kb_id)
        if len(existing_docs) >= policy.max_upload_files:
            raise HTTPException(
                status_code=400,
                detail=f"知识库文档数量已达上限({policy.max_upload_files}个)，请先删除部分文档",
            )

        safe_name = re.sub(r'[^\w\-.]', '_', Path(file.filename).name)[:255]
        return await ks.upload_document(
            safe_name,
            content,
            file.content_type,
            kb_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("upload_knowledge_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="文档上传失败，请稍后重试")


@router.get("/knowledge/documents", response_model=None)
async def list_knowledge_documents(
    kb_id: str = None,
    current_user: dict = Depends(get_current_user),
) -> Any:
    """获取知识库文档列表"""
    try:
        return await _get_knowledge_service().list_documents(kb_id)
    except Exception as e:
        logger.error("list_knowledge_documents_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unavailable",
                "error": "知识库文档列表失败，不是空库",
                "provider": _kb_provider_label(),
            },
        )


@router.get("/knowledge/catalog", response_model=None)
async def knowledge_document_catalog(current_user: dict = Depends(get_current_user)) -> dict:
    try:
        return await _get_knowledge_service().document_catalog()
    except Exception as exc:
        logger.warning('knowledge_catalog_unavailable', error=type(exc).__name__)
        raise HTTPException(503, detail={'message': '资料目录读取失败，不是空库。'}) from exc


@router.get("/knowledge/read", response_model=None)
async def read_knowledge_document(
    document_id: str | None = Query(None, min_length=1, max_length=1024),
    filename: str | None = Query(None, min_length=1, max_length=512),
    version: str | None = Query(None, min_length=1, max_length=128),
    current_user: dict = Depends(get_current_user),
) -> dict:
    from modules.knowledge.reader import DocumentReadError
    if not document_id and not filename:
        raise HTTPException(422, detail='请选择文档身份。')
    try:
        return await _get_knowledge_service().read_document(document_id, filename, version)
    except DocumentReadError as exc:
        raise HTTPException(exc.status, detail={'code': exc.code, 'message': exc.message}) from exc
    except Exception as exc:
        logger.warning('knowledge_read_unavailable', error=type(exc).__name__)
        raise HTTPException(503, detail={'message': '正文读取失败，请稍后重试。'}) from exc


@router.delete("/knowledge/documents/{doc_id:path}", response_model=None)
async def delete_knowledge_document(
    doc_id: str,
    kb_id: str = None,
    current_user: dict = Depends(require_role("admin")),
) -> Any:
    """删除知识库文档（仅管理员）"""
    try:
        return await _get_knowledge_service().delete_document(doc_id, kb_id)
    except Exception as e:
        logger.error("delete_knowledge_document_failed", error=str(e), exc_info=True)
        return {"deleted": [], "status": "degraded", "error": "删除文档失败"}


@router.post("/knowledge/search", dependencies=[Depends(_AI_RATE_LIMIT)], response_model=None)
async def search_knowledge(
    data: AskRequest,
    current_user: dict = Depends(get_current_user),
) -> Any:
    """检索知识库"""
    try:
        return await _get_knowledge_service().search(data.question, data.kb_id, data.top_k)
    except Exception as e:
        logger.error("search_knowledge_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unavailable",
                "error": "知识库检索失败，不是空结果",
                "provider": _kb_provider_label(),
            },
        )


# ── Copilot 会话持久化（跨浏览器不丢历史） ──────────────────────────────

@router.get("/copilot/citations/verify", response_model=None)
async def verify_citation(
    filename: str = Query(..., min_length=1),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """T14：打开历史引用前校验语料是否仍存在；撤权/删除则不展示旧片段。"""
    try:
        docs = await _get_knowledge_service().list_documents()
    except Exception as exc:  # noqa: BLE001
        logger.warning("citation_verify_unavailable", error=type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail={"code": "citation_verify_unavailable", "message": "暂时无法校验引用，未展示原文"},
        ) from exc
    names = {str(d.get("filename") or d.get("title") or "") for d in docs}
    if filename not in names:
        raise HTTPException(
            status_code=410,
            detail={"code": "citation_revoked", "message": "该引用已失效或已撤权，不再展示旧片段"},
        )
    return {"available": True, "filename": filename,
            "checked_at": datetime.now(timezone.utc).isoformat()}


@router.get("/copilot/citations/read", response_model=None)
async def read_citation(
    filename: str = Query(..., min_length=1),
    request_id: str | None = Query(None, min_length=1, max_length=128),
    source_id: str | None = Query(None, min_length=1, max_length=128),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Return the server-saved generation excerpt, after ownership and current availability checks.

    Legacy callers without a request identity receive explicitly current text;
    they must not confuse it with the excerpt used to generate an old answer.
    """
    original = None
    if bool(request_id) != bool(source_id):
        raise HTTPException(422, detail="引用请求与来源编号必须一起提供")
    if request_id and source_id:
        from core.database import get_session_factory
        from .request_store import RequestStore
        saved = await RequestStore(get_session_factory()).read(request_id, current_user)
        original = next((s for s in (saved.get("response") or {}).get("sources", [])
                         if s.get("source_id") == source_id and s.get("filename") == filename), None)
        if original is None:
            raise HTTPException(404, detail="原请求中没有此来源")
    try:
        docs = await _get_knowledge_service().list_documents()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail={"code": "citation_verify_unavailable"}) from exc
    if filename not in {str(d.get("filename") or d.get("title") or "") for d in docs}:
        raise HTTPException(status_code=410, detail={"code": "citation_revoked", "message": "该引用已失效或已撤权"})
    if original is not None:
        matches = [d for d in docs if (d.get("filename") or d.get("title")) == filename]
        if original.get("document_id"):
            matches = [d for d in matches if (d.get("document_id") or d.get("id")) == original["document_id"]]
        if not matches:
            raise HTTPException(410, detail={"code": "citation_revoked"})
        if len(matches) != 1:
            raise HTTPException(409, detail={"code": "citation_ambiguous", "message": "同名来源不唯一，暂时不能核验"})
        return {key: original.get(key) for key in ("filename", "title", "document_id", "source_id", "content", "version", "captured_at", "truncated", "reviewed_notes")} | {
            "scope": "answer_excerpt", "available_now": True,
            "message": "回答生成时使用的片段；当前仅核验资料仍可访问，不代表全文版本未变化。",
        }
    from modules.knowledge.reader import DocumentReadError
    try:
        doc = await _get_knowledge_service().read_document(None, filename, None)
    except DocumentReadError as exc:
        raise HTTPException(exc.status, detail={'code': exc.code, 'message': exc.message}) from exc
    except Exception as exc:
        raise HTTPException(503, detail={'code': 'citation_verify_unavailable'}) from exc
    return doc | {
        'document_id': doc['id'],
        'message': '当前资料全文；此历史回答缺少可定位的请求编号，无法还原当时片段。',
    }


@router.get("/copilot/sessions", response_model=None)
async def list_copilot_sessions(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> list[Any]:
    """获取当前用户全部 Copilot 会话（不含消息体，仅元信息）。"""
    try:
        from sqlalchemy import select
        from modules.ai_text.models import CopilotConversation
        stmt = (
            select(CopilotConversation)
            .where(CopilotConversation.user_id == current_user.get("user_id", 0))
            .order_by(CopilotConversation.updated_at.desc())
            .limit(50)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [
            {
                "id": c.id,
                "title": c.title,
                "created_at": iso_utc(c.created_at),
                "updated_at": iso_utc(c.updated_at),
                "message_count": len(c.messages or []),
                "revision": c.revision,
            }
            for c in rows
        ]
    except Exception as e:
        logger.error("list_copilot_sessions_failed", error=str(e), exc_info=True)
        # 失败不再伪装成"空列表"（200 + []），否则监控与用户都看不出后端出了问题
        raise HTTPException(status_code=503, detail="会话列表读取失败，请稍后重试") from e


@router.get("/copilot/sessions/{conv_id}", response_model=None)
async def get_copilot_session(
    conv_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """获取单个 Copilot 会话完整内容。"""
    try:
        from sqlalchemy import select
        from modules.ai_text.models import CopilotConversation
        stmt = select(CopilotConversation).where(
            CopilotConversation.id == conv_id,
            CopilotConversation.user_id == current_user.get("user_id", 0),
        )
        c = (await db.execute(stmt)).scalar_one_or_none()
        if not c:
            return {"id": conv_id, "title": "新对话", "messages": [], "revision": 0, "exists": False}
        return {
            "id": c.id,
            "title": c.title,
            "messages": c.messages or [],
            "revision": c.revision,
            "created_at": iso_utc(c.created_at),
            "updated_at": iso_utc(c.updated_at),
            "exists": True,
        }
    except Exception as e:
        logger.error("get_copilot_session_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=503, detail="会话读取失败，请稍后重试") from e


@router.put("/copilot/sessions/{conv_id}", response_model=None)
async def save_copilot_session(
    conv_id: str,
    data: CopilotSessionSave,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """按版本保存快照；陈旧客户端不能覆盖新历史或重建已删除的会话。"""
    from sqlalchemy import select, update
    from sqlalchemy.exc import IntegrityError
    from modules.ai_text.models import CopilotConversation
    user_id = current_user.get("user_id", 0)
    try:
        stmt = select(CopilotConversation).where(CopilotConversation.id == conv_id)
        c = (await db.execute(stmt)).scalar_one_or_none()
        if not c:
            if data.revision is not None:
                raise HTTPException(status_code=409, detail="会话已删除或版本冲突，本地内容已保留，请另存为新会话")
            next_revision = 1
            c = CopilotConversation(id=conv_id, user_id=user_id, title=data.title, messages=data.messages, revision=next_revision)
            db.add(c)
        else:
            if c.user_id != user_id:
                raise HTTPException(status_code=403, detail="无权修改他人会话")
            if data.revision is None:
                raise HTTPException(status_code=409, detail="会话版本冲突：缺少版本号，本地内容已保留，请重新读取或另存为新会话")
            next_revision = data.revision + 1
            changed = await db.execute(
                update(CopilotConversation).where(
                    CopilotConversation.id == conv_id,
                    CopilotConversation.user_id == user_id,
                    CopilotConversation.revision == data.revision,
                ).values(title=data.title, messages=data.messages, revision=next_revision)
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount != 1:
                await db.rollback()
                raise HTTPException(status_code=409, detail="会话版本冲突，服务器已有新内容。本地内容已保留，请另存为新会话")
        await db.commit()
        return {"success": True, "id": conv_id, "revision": next_revision}
    except HTTPException:
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="会话已被另一个请求创建，本地内容已保留，请重新读取或另存为新会话") from exc
    except Exception as e:
        logger.error("save_copilot_session_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=503, detail="会话保存失败，请稍后重试") from e


@router.delete("/copilot/sessions/{conv_id}", response_model=None)
async def delete_copilot_session(
    conv_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """删除 Copilot 会话。"""
    try:
        from sqlalchemy import delete
        from modules.ai_text.models import CopilotConversation
        await db.execute(
            delete(CopilotConversation).where(
                CopilotConversation.id == conv_id,
                CopilotConversation.user_id == current_user.get("user_id", 0),
            )
        )
        await db.commit()
        return {"success": True}
    except Exception as e:
        logger.error("delete_copilot_session_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=503, detail="会话删除失败，请稍后重试") from e
