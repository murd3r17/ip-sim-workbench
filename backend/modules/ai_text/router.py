from contextlib import suppress
from typing import Any
"""AI模块路由"""
import asyncio
import json
from datetime import datetime, timezone
from hashlib import sha256
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
from core.redaction import redact_payload
from core.time_utils import iso_utc
from core.request_metrics import timed_stage
from core.rate_limiter import rate_limit
from modules.ai_text.cancel import registry as cancel_registry
from modules.knowledge.service import KnowledgeService
from modules.system.service import SystemService
from modules.ai_text.draft_guard import enforce as enforce_draft_guard
from modules.ai_text.trusted_context import (
    TrustedPageData, config_comparison_guidance, config_comparison_question, exclude_previous_config_comparison,
    load_config_comparison, load_verified_evidence,
    resolve_task_targets, resolve_draft_target, sanitize as sanitize_page_data,
)
from modules.ai_text.draft_environment import resolve_draft_environment, blocked_draft_policy
from modules.ai_text.skills import knowledge_retrieval_query, request_evidence_scope, select_skill
from modules.ai_text.question_intent import new_device_read_scope
from modules.ai_text.kb_cache import cached_search
from modules.ai_text.retrieval import clean_chunk, expand_query, rerank
from modules.ai_text.context_bundle import answer_references, prepare_sources, source_documents
from modules.ai_text import lexical_index
from modules.ai_text.protect_ports import load_protected_interfaces
from modules.ai_text.budget_policy import limits_for, select_tier
from modules.ai_text.schemas import (
    CLIRequest, CLIResponse, ReviewRequest, ReviewResponse, AskRequest, OriginalQuoteRequest,
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


def _has_copilot_model_configuration(provider) -> bool:
    """Short-circuit unconfigured hosted defaults without probing providers."""
    from urllib.parse import urlsplit
    from core.llm_provider import FailoverProvider, FallbackProvider, OpenAICompatibleProvider

    if isinstance(provider, FallbackProvider):
        return _has_copilot_model_configuration(provider.primary)
    if isinstance(provider, FailoverProvider):
        return any(_has_copilot_model_configuration(item) for item in (provider.primary, provider.secondary))
    if isinstance(provider, OpenAICompatibleProvider):
        if provider.base_url in {'http://127.0.0.1:1', 'http://127.0.0.1:1/v1'}:
            # The offline bootstrap pins this address to represent no model.
            return False
        if urlsplit(provider.base_url).hostname in {'api.deepseek.com', 'api.openai.com'}:
            key = str(provider.api_key or '').strip()
            return bool(key) and not key.startswith('<')
    # Local and custom endpoints can serve without a key; their own errors
    # remain the authority on reachability.
    return True


def _textbook_scope_notice(knowledge_status: str) -> str:
    if knowledge_status == 'degraded':
        return '本次知识服务暂不可用，未能核对教材，暂无法按教材给出解释或引用。'
    if knowledge_status == 'empty':
        return '本次检索没有找到可引用的教材片段，暂无法按教材给出解释。'
    if knowledge_status == 'not_requested':
        return '本次没有可引用的教材片段，暂无法按教材给出解释。'
    return ''


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
    """Authorize access to the lab and gate concrete configuration separately."""
    from modules.training.environment_policy import requests_site_configuration
    site_config = data.want_draft or requests_site_configuration(data.message)
    default = {
        "lab_scoped": False, "allow_draft": True, "allow_model": True,
        "reason": "", "note": "", "safe_text": "", "content_warning": "",
    }
    from .skills import concept_only_question

    if not site_config:
        history = [] if exclude_previous_config_comparison(data.message) else data.history
        scope = request_evidence_scope(data.message, history)
        textbook_independent = scope.textbook_only and not re.search(
            r'(?:当前|本次|正在做的|我的)(?:实训|实验|会话)', data.message)
        if concept_only_question(data.message) or scope.provided_only or textbook_independent:
            # The open lab is incidental to a self-contained explanation.
            return default
    if not data.lab_id and not data.lab_session_id:
        if data.lab_steps and site_config:
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
    if session is not None and session.status != "in_progress" and site_config:
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
    steps = [item for item in (resolved.get("objectives") or []) if isinstance(item, dict)][:30]
    if not resolved.get("can_guide"):
        steps = []
    lab_content = {key: resolved.get(key) for key in ("source", "title", "version", "warning")}
    if session is not None:
        lab_content["session_status"] = session.status
        workspace = session.workspace if isinstance(session.workspace, dict) else {}
        marked = {str(item.get("id")) for item in (workspace.get("steps") or [])
                  if isinstance(item, dict) and item.get("status") == "done"}
        pending = next((item for item in steps if str(item.get("id")) not in marked), None)
        lab_content["first_unmarked_step_id"] = pending.get("id") if pending else None
        if not site_config:
            from .evidence_context import session_evidence
            if owned := session_evidence(data.message, data, actor, session, lab_content):
                lab_content['owned_session_evidence'] = owned
    context = {
        **default, "lab_scoped": True,
        "lab_steps": steps, "lab_content": lab_content,
    }
    if not site_config:
        reason = resolved.get("warning") or guard.get("reason") or ""
        if session is not None and session.status != "in_progress":
            reason = "会话已结束。可以解释已保存的内容；需要新操作请开启会话。"
        return {
            **context, "allow_draft": False,
            "note": "本轮为解释或步骤指导。依据课程内容说明目标、应看字段、判断方法和记录方式。"
                    "具体对象和参数须先核对。区分教材示例、历史观察与当前事实。" + reason,
        }
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
        return {
            **default, "lab_scoped": True, "allow_draft": False, "allow_model": False,
            "reason": guard["reason"], "safe_text": answer["text"],
            "content_warning": resolved.get("warning") or "",
        }
    return context


async def _copilot_attachments(db: AsyncSession, data: CopilotChatRequest, actor: dict) -> list[dict]:
    """Resolve a previous upload from the owner's saved conversation."""
    if data.attachments or not data.attachment_message_id:
        return [item.model_dump(exclude_none=True) for item in data.attachments]

    from sqlalchemy import select
    from modules.ai_text.models import CopilotConversation
    from modules.ai_text.schemas import CopilotAttachment

    query = select(CopilotConversation.messages).where(
        CopilotConversation.id == data.conversation_id,
        CopilotConversation.user_id == actor.get("user_id"),
    )
    messages = (await db.execute(query)).scalar_one_or_none()
    matches = [
        message for message in (messages or [])
        if isinstance(message, dict) and message.get("role") == "user"
        and message.get("id") == data.attachment_message_id
    ]
    if len(matches) == 1:
        saved = matches[0].get("attachments")
        if isinstance(saved, list):
            attachments = []
            for item in saved[:4]:
                try:
                    attachment = CopilotAttachment.model_validate(item)
                except ValueError:
                    continue
                if attachment.contentString.strip():
                    attachments.append(attachment.model_dump(exclude_none=True))
            if attachments:
                return attachments
    raise HTTPException(status_code=409, detail={
        "code": "attachment_unavailable",
        "message": "暂时无法读取这份对话附件。请确认该会话已同步，或重新选取原文件。",
    })


def _apply_policy_note(ui: dict, policy: dict) -> dict:
    note = policy.get("note") or ""
    if not note:
        return ui
    merged = {**ui}
    merged["notes"] = f"{ui.get('notes') or ''}\n{note}".strip()
    return merged


class _FacetHits(list):
    """Request-local evidence can accompany hits without changing public search results."""

    def __init__(self, hits, evidence, ranked=None, pool=()):
        super().__init__(hits)
        self.evidence = evidence
        self.ranked = ranked
        self.pool = pool


@timed_stage("retrieval")
async def _retrieve(message: str, top_k: int, cancel_event=None) -> list[dict]:
    """向量召回 + 网络术语扩展 + 同 K 重排；词法/融合为实验通道。"""
    service = _get_knowledge_service()
    edition = service.edition() if isinstance(service, KnowledgeService) else None
    from .retrieval import select_vrrp_mechanism_hits, supports_vrrp_mechanism, vrrp_mechanism_queries

    focuses = vrrp_mechanism_queries(message)
    candidates = []
    if edition is not None:
        if not focuses and 4 <= top_k <= 8 and not edition.has_search_scope(message):
            async def load_ranked():
                result = await service.search_ranked_evidence(message, None, top_k)
                if result.pool or result.facet_evidence:
                    return _FacetHits(result.hits, result.facet_evidence, result.ranked, result.pool)
                return result.hits

            return await cached_search(service, message, top_k, load_ranked, variant='ranked-evidence')
        # The edition handles literal phrases, titles, chapters and page scope.
        # Never replace that exact lookup with an unscoped child query or legacy fusion.
        candidates = await cached_search(service, message, top_k)
        if edition.has_search_scope(message) or not focuses:
            return candidates[:top_k]
    if focuses:
        from modules.knowledge.query_focus import lookup_parts

        titles, phrases, pages, _ = lookup_parts(message)
        if titles or phrases or pages:
            return (await cached_search(service, message, top_k))[:top_k]

        async def search_focus(focus):
            supported = [hit for hit in candidates if supports_vrrp_mechanism(hit, focus.facet)]
            if supported:
                return supported
            group = await cached_search(service, focus.query, max(top_k, 8))
            return [hit for hit in group if supports_vrrp_mechanism(hit, focus.facet)]

        groups = await asyncio.gather(*(search_focus(focus) for focus in focuses), return_exceptions=True)
        errors = [group for group in groups if isinstance(group, Exception)]
        qualified = [group if isinstance(group, list) else [] for group in groups]
        hits = select_vrrp_mechanism_hits(focuses, qualified, top_k)
        if not hits and errors:
            raise RuntimeError('Knowledge retrieval unavailable') from errors[0]
        if errors:
            logger.warning('copilot_focused_retrieval_partial', failed=len(errors))
        return hits
    expanded = expand_query(message)
    vector_hits: list[dict] = []
    retrieval_error = None
    try:
        # Candidate expansion occurs once; preserve the previously effective
        # pool size so cache repair does not silently change retrieval quality.
        vector_hits = await cached_search(service, expanded, max(top_k * 4, 20))
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
    if vector_hits and all(hit.get("retriever") == "reviewed_excerpt" for hit in vector_hits):
        return vector_hits[:top_k]
    # Historical reranking measurements are not current whole-stage acceptance.
    return rerank(vector_hits, expanded, top_k, original_query=message)


async def _resolve_page_data(db: Any, data: CopilotChatRequest, current_user: dict) -> Any:
    """C-R2：优先按 evidence_id 回读服务端观察；客户端 JSON 仅作线索。"""
    from .question_intent import config_change_log_question, explicit_device_read, plain_question
    from .skills import concept_only_question, dashboard_summary_question

    if (data.context and data.context.route == '/config-versions'
            and not data.want_draft and not concept_only_question(data.message)
            and not config_change_log_question(plain_question(data.message), data.context.route,
                                               data.context.page_record.kind if data.context.page_record else None)
            and not explicit_device_read(data.message) and config_comparison_question(data.message)):
        try:
            return await load_config_comparison(db, data.context.config_comparison)
        except Exception as exc:
            logger.warning('copilot_config_comparison_unavailable', error=type(exc).__name__)
            return TrustedPageData('已保存的 A/B 快照暂时无法回读。请稍后重试。',
                                   {'trusted': True, 'kind': 'config_comparison', 'source': 'workbench', 'guidance_only': True})
    if not data.want_draft and dashboard_summary_question(data.message, data.context.route if data.context else None):
        from modules.dashboard.service import DashboardService
        try:
            if db is None:
                raise ValueError("No database session")
            summary = await DashboardService.get_summary(db, actor=current_user, probe_services=False)
            topology = summary.get("topology")
            snapshot = {
                "kind": "dashboard_summary", "source": "database_snapshot",
                "collected_at": summary["generated_at"].isoformat(),
                "devices": summary["devices"],
                "tasks": {"deploy_batches": summary["tasks"]["deploy_batches"]},
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


async def _saved_evidence_guidance(db, data, actor, page, scope, attachments) -> str:
    from .evidence_context import (configuration_change_answer, monitor_sample_answer, practice_outcome_guidance,
                                   previous_citation_answer, runtime_mode_answer,
                                   saved_device_observation_answer, saved_neighbor_answer, saved_route_answer,
                                   selected_record_answer, selected_record_kind, terminal_read_only_access_answer,
                                   training_notes_answer)
    from .question_intent import (config_change_log_question, monitor_sample_time_question, new_device_read_scope, plain_question,
                                   previous_citation_status_question, read_only_workbench_answer, runtime_mode_question,
                                   training_notes_question, workflow_question)
    from .skills import concept_only_question

    if data.want_draft or new_device_read_scope(data.message):
        return ''
    context = data.context
    route = context.route if context else None
    if guidance := practice_outcome_guidance(page, data.message, route):
        return guidance
    if scope.provided_only or attachments:
        return ''
    selected = context.page_record if context else None
    text = plain_question(data.message)
    workflow = workflow_question(text, route)
    kind = selected_record_kind(route, data.message, selected.kind if selected else None) if route else None
    if workflow in {'monitor_saved_samples', 'original_reader_return', 'copilot_citation_return'} and not scope.textbook_only:
        guidance = read_only_workbench_answer(text, route)
        if guidance:
            if workflow == 'monitor_saved_samples' and monitor_sample_time_question(text):
                if sample := await monitor_sample_answer(db, data, actor):
                    guidance += '\n\n' + sample
            elif workflow == 'copilot_citation_return' and previous_citation_status_question(text):
                guidance += '\n\n' + await previous_citation_answer(db, data, actor, read_citation)
            elif workflow == 'original_reader_return' and kind == 'original_page':
                guidance += '\n\n' + await selected_record_answer(db, data, actor, kind, _get_knowledge_service)
            return guidance
    if selected and selected.kind == 'original_page' and kind == 'original_page':
        return await selected_record_answer(db, data, actor, kind, _get_knowledge_service)
    if scope.knowledge_lookup is True:
        return ''
    if guidance := terminal_read_only_access_answer(text, route):
        return guidance
    if runtime_mode_question(text, route):
        return runtime_mode_answer(actor)
    if config_change_log_question(text, route, selected.kind if selected else None):
        return await configuration_change_answer(db, data, actor)
    if training_notes_question(text, route):
        return await training_notes_answer(db, data, actor)
    if route == '/devices' and not concept_only_question(text):
        if guidance := (saved_neighbor_answer(page, text) or saved_route_answer(page, text)
                        or saved_device_observation_answer(page, text, actor=actor)):
            return guidance
    if kind in {'approval_task', 'alarm_record'}:
        return await selected_record_answer(db, data, actor, kind, _get_knowledge_service)
    if guidance := read_only_workbench_answer(data.message, route):
        return guidance
    if kind:
        return await selected_record_answer(db, data, actor, kind, _get_knowledge_service)
    return saved_route_answer(page, data.message)


async def _copilot_knowledge_hits(data, history, actor, skill, attachments, *, db=None, factory=None):
    from .knowledge_continuation import continue_sources, refers_to_previous_source, wants_same_source
    from .request_store import prior_source_context

    continuity = ''
    if skill.id == 'knowledge_answer' and not attachments and wants_same_source(data):
        try:
            if factory is not None:
                async with factory() as source_db:
                    prior = await prior_source_context(source_db, data, actor)
            else:
                prior = await prior_source_context(db, data, actor)
            # Earlier prose and user-supplied history cannot be this turn's evidence.
            result = await continue_sources(prior, data, _get_knowledge_service, data.message)
        except Exception as exc:
            logger.warning('copilot_book_continuity_unavailable', error=type(exc).__name__)
            return [], 'degraded'
        if result.status != 'independent':
            return result.hits, result.status
        history = []
        continuity = result.status
    elif skill.id == 'knowledge_answer' and (refers_to_previous_source(data.message)
            or (data.context and data.context.knowledge_source and data.context.knowledge_source.mode == 'cleared')):
        history = []
        continuity = 'independent'
    retrieval_query = knowledge_retrieval_query(data.message, history)
    hits = await _retrieve(retrieval_query, data.top_k)
    if (not continuity and retrieval_query == data.message and not attachments and not data.attachments
            and not data.attachment_message_id and not data.want_draft and skill.id == 'knowledge_answer'
            and not isinstance(hits, _FacetHits)):
        hits = await _recover_scoped_observations(data, hits)
    return hits, continuity


async def _recover_scoped_observations(data, hits):
    """Check a wider local pool only when it can complete a scoped exhibit request."""
    from .evidence_refinement import example_evidence_query, prepare_example_evidence
    from .example_scope import IllustratedExample
    from .question_intent import plain_question, textbook_reference_question
    from .source_scope import explicit_physical_scope

    if not 4 <= data.top_k <= 8:
        return hits
    question = plain_question(data.message)
    if explicit_physical_scope(question):
        return hits
    route = data.context.route if data.context else None
    query = example_evidence_query(question, allow_explicit=route == '/knowledge' or textbook_reference_question(question, route))
    if (not isinstance(query, IllustratedExample) or not query.needs_result or not query.devices
            or not (query.concepts or query.literals or query.witnesses)):
        return hits
    service = _get_knowledge_service()
    edition = service.edition() if isinstance(service, KnowledgeService) else None
    if not edition or edition.has_search_scope(data.message):
        return hits
    limit = min(data.top_k, 6)
    initial = prepare_example_evidence(query, prepare_sources(hits), limit)
    if not initial.notice:
        return hits
    try:
        deeper = await cached_search(service, data.message, min(24, data.top_k * 3))
    except Exception as exc:  # noqa: BLE001
        logger.warning('copilot_scoped_recovery_unavailable', error=type(exc).__name__)
        return hits
    bounded = {}
    for hit in (*hits, *deeper):
        for source in prepare_sources([hit]):
            if (source['source_id'] not in bounded and not source['truncated']
                    and _readable_edition_page(edition, source)):
                bounded[source['source_id']] = (hit, source)
    complete = prepare_example_evidence(query, [source for _, source in bounded.values()], limit)
    if complete.notice or not complete.sources or len(complete.sources) > data.top_k:
        return hits
    if not _preserves_edition_sources(initial.sources, complete.sources):
        return hits
    recovered = [bounded[source['source_id']][0] for source in complete.sources]
    bundle = prepare_sources(recovered)
    if len(bundle) != len(recovered) or any(source['truncated'] for source in bundle):
        return hits
    return recovered


def _prepare_copilot_sources(data, hits, skill, continuity, *, keep_page_pointers=False):
    from .evidence_refinement import direct_evidence_limit, example_evidence_query, prepare_example_evidence, refine_sources
    from .example_scope import exclude_conflicting_examples
    from .question_intent import plain_question, textbook_reference_question
    from .source_scope import explicit_physical_scope, prepare_scoped_sources
    from modules.knowledge.query_focus import lookup_parts

    hits = hits or []
    question = plain_question(data.message)
    if skill.id != 'knowledge_answer' or data.want_draft or data.attachments or data.attachment_message_id:
        return prepare_sources(hits[:data.top_k]), ''
    if explicit_physical_scope(question) or continuity in {'page', 'chapter'}:
        service = _get_knowledge_service()
        edition = service.edition() if isinstance(service, KnowledgeService) else None
        limit = data.top_k if keep_page_pointers else min(data.top_k, 6)
        return prepare_scoped_sources(question, hits, limit, edition, continuity, keep_page_pointers=keep_page_pointers)
    limit = min(data.top_k, 6)
    sources = prepare_sources(hits[:limit])
    if keep_page_pointers or continuity:
        return sources, ''
    if isinstance(hits, _FacetHits) and hits.evidence and (pair := hits.evidence.select_hits(data.message, hits)):
        prepared = prepare_sources(pair, max_documents=limit)
        if len(prepared) == 2 and not any(source['truncated'] for source in prepared):
            service = _get_knowledge_service()
            edition = service.edition() if isinstance(service, KnowledgeService) else None
            if edition and all(_readable_edition_page(edition, source) for source in prepared):
                return prepared, ''
    if isinstance(hits, _FacetHits) and hits.ranked and hits.ranked.query_sha256 == sha256(data.message.encode('utf-8')).hexdigest():
        ranked = hits.ranked
        if getattr(ranked, 'ambiguous_precise_case', False):
            return [], '教材中有多处同样符合所给方向和读回线索。请补充所问实验的章节、图表编号或 PDF 物理页。'
        if getattr(ranked, 'precise_case', None) and (precise := ranked.select_precise_hits(data.message, hits.pool)):
            service = _get_knowledge_service()
            edition = service.edition() if isinstance(service, KnowledgeService) else None
            prepared = prepare_sources(precise, max_documents=limit)
            if (edition and len(prepared) == len(precise)
                    and all(not source['truncated'] and _readable_edition_page(edition, source) for source in prepared)):
                return prepared, ''
        if verified := _prepare_verified_claims(data.message, ranked, hits.pool, sources, limit):
            verified_sources, gaps = verified
            scoped, notice = exclude_conflicting_examples(question, verified_sources)
            return scoped, notice or gaps
    route = data.context.route if data.context else None
    example = example_evidence_query(question, allow_explicit=route == '/knowledge' or textbook_reference_question(question, route))
    if example:
        service = _get_knowledge_service()
        edition = service.edition() if isinstance(service, KnowledgeService) else None
        if edition:
            doc_ids = edition.search_scope(question)[2] if lookup_parts(question)[0] else None
            checked = [source for source in sources if (doc_ids is None or source.get('document_id') in doc_ids)
                       and _readable_edition_page(edition, source)]
            result = prepare_example_evidence(example, _with_example_scope(checked, hits), limit)
            if result.notice and isinstance(hits, _FacetHits) and hits.pool and doc_ids is None:
                extended, notice = _prepare_ranked_example(example, hits, edition, limit)
                if (extended and _preserves_edition_sources(result.sources, extended)
                        and (not notice or any(not _preserves_edition_sources([source], result.sources)
                                               for source in extended))):
                    return extended, notice
            selected = {_example_source_key(source) for source in result.sources[:limit]}
            return [source for source in checked if _example_source_key(source) in selected], result.notice
    if not sources or not sources[0].get('edition_version'):
        return sources, ''
    scoped, scope_notice = exclude_conflicting_examples(question, _with_example_scope(sources, hits))
    allowed = {_example_source_key(source) for source in scoped}
    sources = [source for source in sources if _example_source_key(source) in allowed]
    if scope_notice:
        return sources, scope_notice
    if limited := direct_evidence_limit(question, sources):
        bound_sources, limit_notice = limited
        service = _get_knowledge_service()
        edition = service.edition() if isinstance(service, KnowledgeService) else None
        if all(_readable_edition_page(edition, source) for source in bound_sources):
            return bound_sources, limit_notice
    if isinstance(hits, _FacetHits) and hits.ranked:
        service = _get_knowledge_service()
        edition = service.edition() if isinstance(service, KnowledgeService) else None
        if edition:
            ranked = _prepare_ranked_facets(data.message, hits, edition, sources, limit)
            if ranked is not None:
                ranked_sources, ranked_notice = ranked
                scoped, notice = exclude_conflicting_examples(question, ranked_sources)
                return scoped, notice or ranked_notice
    if not sources:
        return sources, ''
    refined, _ = refine_sources(question, sources, sources[0]['edition_version'])
    if refined is sources:
        return sources, ''
    service = _get_knowledge_service()
    edition = service.edition() if isinstance(service, KnowledgeService) else None
    if edition and all(source['edition_version'] == edition.version
                       and edition.documents.get(source['document_id'], {}).get('sha256') == source['document_version']
                       for source in refined):
        return refined, ''
    return sources, ''


def _prepare_verified_claims(question, ranked, pool, baseline, limit):
    from modules.knowledge.facet_evidence import FacetEvidenceRef

    observation_ids = set(getattr(ranked, 'observation_facets', ()))
    all_ids = {number for number, _, _ in ranked.facets}
    only_observations = bool(observation_ids and observation_ids == all_ids)
    ambiguous = set(getattr(ranked, 'ambiguous_observation_facets', ()))
    observed = (ranked.select_verified_observations(question, pool) or []) if observation_ids else []
    explanation_matches = getattr(ranked, 'verified_explanation', ())
    explanations = (ranked.select_verified_explanations(question, pool) or []) if explanation_matches else []
    selected = {FacetEvidenceRef.from_hit(hit): hit for hit in (*observed, *explanations)}
    if not selected:
        if only_observations and ambiguous:
            return [], '教材中有不止一处符合所给线索的实际记录。请补充设备、实验阶段、图表编号或 PDF 物理页。'
        return None
    if len(selected) > limit:
        return None
    service = _get_knowledge_service()
    edition = service.edition() if isinstance(service, KnowledgeService) else None
    if not edition:
        return None
    by_ref = {}
    for number, reference in (*getattr(ranked, 'verified_observation', ()), *explanation_matches):
        if reference in selected:
            by_ref.setdefault(reference, set()).add(number)
    focused = [{**hit, 'query_focus': '问题的第 ' + '、'.join(map(str, sorted(by_ref[reference]))) + ' 项'}
               for reference, hit in selected.items()]
    sources = prepare_sources(focused, max_documents=limit)
    if len(sources) != len(selected) or any(source['truncated'] or not _readable_edition_page(edition, source)
                                             for source in sources):
        return None
    found = set().union(*by_ref.values())
    if found == all_ids:
        return sources, ''
    if not only_observations and baseline and not ambiguous:
        topics = dict(getattr(ranked, 'comparison_topics', ()))
        same_passage = {number for number, reference in getattr(ranked, 'matches', ()) if reference in selected}
        keep_topics = tuple(topic for number, topic in topics.items() if number not in found) if (
            found.intersection(topics) and all_ids - topics.keys() <= found | same_passage
        ) else ()
        merged = _merge_ranked_sources(question, baseline, sources, limit, keep_topics=keep_topics)
        # A mixed reply can have other usable baseline proof. Preserve it and
        # let the verified mechanism supplement it when the budget permits.
        return (merged, '') if merged else None
    return sources, _observation_gap(ranked.facets, all_ids - found - ambiguous, ambiguous - found)


def _observation_gap(facets, absent, ambiguous):
    gaps = []
    for numbers, reason in ((absent, '尚缺直接教材证据'), (ambiguous, '有多处可能的实验记录')):
        labels = [f'第 {number} 项「{clause[:70]}」' for number, clause, _ in facets if number in numbers]
        if labels:
            gaps.append('、'.join(labels) + reason + '。')
    return ''.join(gaps) + '可补充章节、图表编号或 PDF 物理页。' if gaps else ''


def _prepare_ranked_facets(question, hits, edition, baseline, limit):
    from modules.knowledge.facet_evidence import FacetEvidenceRef

    ranked = hits.ranked
    if len(ranked.facets) < 2:
        return None
    selected = ranked.select_hits(question, hits.pool)
    if selected is None:
        return None
    scopes = {}
    for number, reference in ranked.matches:
        scopes.setdefault(reference, []).append(number)
    focused = [{**hit, 'query_focus': '问题的第 ' + '、'.join(map(str, scopes[FacetEvidenceRef.from_hit(hit)])) + ' 项'}
               for hit in selected]
    if ranked.missing and baseline:
        return None
    sources = prepare_sources(focused, max_documents=limit)
    if (len(sources) != len(selected) or any(source['truncated'] or not _readable_edition_page(edition, source)
                                             for source in sources)):
        return None
    combined = _merge_ranked_sources(question, baseline, sources, limit)
    if combined is None:
        return None
    notice = _observation_gap(ranked.facets, set(ranked.missing), set())
    return combined, notice


def _merge_ranked_sources(question, baseline, sources, limit, *, keep_topics=()):
    from modules.knowledge.query_focus import protocol_names
    from .context_bundle import MAX_DOCUMENTS_CHARS

    additions = [source for source in sources if not _preserves_edition_sources([source], baseline)]
    if not additions:
        return None
    retained = [source for source in baseline if not _preserves_edition_sources([source], additions)]
    if len(retained) + len(additions) > limit:
        subjects = protocol_names(question)
        contrasts = [re.compile(r'(?<![A-Za-z0-9_-])' + re.escape(topic) + r'(?![A-Za-z0-9_-])', re.I)
                     for topic in keep_topics]
        if not all(any(pattern.search(source['title'] + '\n' + source['content']) for source in retained)
                   for pattern in contrasts):
            contrasts = []
        for index in range(len(retained) - 1, -1, -1):
            source = retained[index]
            declared = protocol_names(source['title'])
            foreign = (subjects and declared and subjects.isdisjoint(declared)
                       and subjects.isdisjoint(protocol_names(source['content'])))
            duplicate = _preserves_edition_sources([source], retained[:index])
            protects_counterpart = any(pattern.search(source['title'] + '\n' + source['content']) for pattern in contrasts)
            outside_counterpart = contrasts and not protects_counterpart
            if (foreign and not protects_counterpart) or duplicate or outside_counterpart:
                retained.pop(index)
                if len(retained) + len(additions) <= limit:
                    break
        if len(retained) + len(additions) > limit:
            return None
    combined = [*additions, *retained]
    if sum(len(source['prompt_text']) for source in combined) > MAX_DOCUMENTS_CHARS:
        return None
    return combined


_EXAMPLE_LOCATOR_FIELDS = ('edition_version', 'document_id', 'document_version', 'page', 'section_id')
_EXAMPLE_CONTEXT_FIELDS = ('source_heading_path', 'source_experiment_key', 'source_phase_key')


def _example_source_key(source):
    return tuple(source.get(field) for field in (*_EXAMPLE_LOCATOR_FIELDS, 'source_id'))


def _with_example_scope(sources, hits):
    if not isinstance(hits, _FacetHits) or not sources:
        return sources
    from modules.knowledge.facet_evidence import FacetEvidenceRef

    by_ref = {FacetEvidenceRef.from_hit(hit): hit for hit in hits.pool
              if any(hit.get(field) for field in _EXAMPLE_CONTEXT_FIELDS)}
    scope = {}
    for hit in hits:
        verified = by_ref.get(FacetEvidenceRef.from_hit(hit))
        if verified:
            for source in prepare_sources([hit]):
                scope[_example_source_key(source)] = {field: verified[field] for field in _EXAMPLE_CONTEXT_FIELDS
                                                      if verified.get(field)}
    return [{**source, **scope.get(_example_source_key(source), {})} for source in sources]


def _preserves_edition_sources(before, after):
    """The same selected text or a contiguous expansion at its exact locator."""
    by_locator = {}
    for source in after:
        key = tuple(source.get(field) for field in _EXAMPLE_LOCATOR_FIELDS)
        if all(key):
            by_locator.setdefault(key, []).append(' '.join(source['content'].split()))
    for source in before:
        key = tuple(source.get(field) for field in _EXAMPLE_LOCATOR_FIELDS)
        original = ' '.join(source['content'].split())
        if not original or not any(original in text for text in by_locator.get(key, ())):
            return False
    return True


def _prepare_ranked_example(example, hits, edition, limit):
    from .evidence_refinement import prepare_example_evidence

    candidates = {}
    raw = {}
    readings = {}
    for hit in (*hits.pool, *hits):
        for source in prepare_sources([hit]):
            identifier = _example_source_key(source)
            if identifier in candidates or source['truncated'] or not _readable_edition_page(edition, source, readings):
                continue
            candidates[identifier] = {**source, **{key: hit[key] for key in _EXAMPLE_CONTEXT_FIELDS if key in hit}}
            raw[identifier] = hit
    result = prepare_example_evidence(example, list(candidates.values()), limit)
    chosen = [raw[_example_source_key(source)] for source in result.sources[:limit]]
    sources = prepare_sources(chosen, max_documents=limit)
    if len(result.sources) > limit or len(sources) < len(chosen) or any(source['truncated'] for source in sources):
        return [], '完整呈现该实验的证据需要缩小问题范围。可指定章节、阶段或各查一个字段。'
    return sources, result.notice


def _source_continuity_notice(status):
    if status in {'unavailable', 'degraded'}:
        return ('本轮无法核验要继续引用的同版教材出处。'
                '请在同一对话中重选最近回答的引用，或告诉我教材名和 PDF 物理页。')
    return ''


_ONLY_SOURCE_LOCATION = re.compile(r'(?:只|仅)(?:需要|需|要|列出|提供|给出|给我|告诉我|想知道|找).{0,8}(?:出处|页码|章节|位置|原页|物理页)|'
                                   r'(?:不要|无需|不用|不需要|不必)(?:做)?(?:解释|总结|归纳|回答原理)')
_OFFLINE_EDITION_FIELD_TASK = re.compile(r'工单|贴出的回显|(?:下面|以下|上面|此前|之前|已给出).{0,12}(?:样例|回显|拓扑|记录)|'
                                         r'现场(?:结论|观察|状态)|(?:现场|重新|实际去|现在|当前|本轮|我这边).{0,4}实测|'
                                         r'已保存.{0,8}(?:观察|记录)|'
                                         r'配置草稿|下发脚本|可执行(?:的)?配置|'
                                         r'(?:审批|下发|生成|编写|起草|发起|执行|回滚|授予).{0,8}(?:任务|配置|设备|权限|核验)')


def _offline_edition_intent(data, history, scope, skill, attachments) -> str:
    from modules.knowledge.complementary_facets import complementary_request
    from modules.knowledge.query_focus import protocol_names
    from .evidence_refinement import classroom_route_question
    from .question_intent import (explicit_device_read, explicit_study, network_reasoning_question,
                                  new_device_read_scope, plain_question, study_followup,
                                  textbook_reference_question)

    text = plain_question(data.message)
    locator = bool(_ONLY_SOURCE_LOCATION.search(text) and re.search(r'教材|课本|知识库|原书', text)
                   and re.search(r'出处|页码|章节|位置|原页|物理页', text))
    concepts = skill.reason == 'explicit_concepts_only' and bool(protocol_names(text))
    evidence_pair = not explicit_device_read(text) and bool(complementary_request(text))
    classroom = ((textbook_reference_question(text, data.context.route if data.context else None)
                  or network_reasoning_question(text) or evidence_pair)
                 and not new_device_read_scope(text))
    if (data.want_draft or data.attachments or data.attachment_message_id or attachments or scope.provided_only
            or scope.saved_record_only or scope.previous_material or scope.knowledge_lookup is False
            or (scope.knowledge_lookup is not True and not (locator or concepts or classroom))
            or skill.id != 'knowledge_answer' or not skill.needs_knowledge or skill.tools
            or _OFFLINE_EDITION_FIELD_TASK.search(text) or (not classroom and explicit_device_read(text))):
        return ''
    if not (scope.textbook_only or skill.reason == 'explicit_knowledge_lookup' or explicit_study(text)
            or classroom or classroom_route_question(text) or study_followup(text, history) or locator or concepts):
        return ''
    return 'locator' if locator else 'explanation'


def _readable_edition_page(edition, source: dict, readings=None) -> dict | None:
    """Recheck the exact saved locator against the permitted, readable edition."""
    from modules.knowledge.reader import DocumentReadError

    if (edition is None or source.get('edition_version') != edition.version or not source.get('document_id') or not source.get('book_title')
            or not source.get('document_version') or not source.get('section_id') or not source.get('content')
            or type(source.get('page')) is not int or source['page'] <= 0):
        return None
    identity = source['document_id'], source['document_version']
    if readings is None:
        readings = {}
    if identity not in readings:
        try:
            readings[identity] = edition.read(*identity, include_original_status=False)
        except (DocumentReadError, OSError, ValueError, KeyError):
            readings[identity] = {}
    reading = readings[identity]
    return next((page for page in reading.get('original_pages', []) if page['physical'] == source['page']
                 and page['section_id'] == source['section_id'] and page.get('evidence_eligible')), None)


def _assistant_source_guide(data, skill, hits, sources, notice, *, continuity='', status='empty', textbook_only=False):
    """Local navigation for unresolved textbook requests, independent of model evidence."""
    from .source_scope import explicit_physical_scope

    if (skill.id != 'knowledge_answer' or continuity or data.want_draft or data.attachments
            or data.attachment_message_id or not (notice or textbook_only and not sources)):
        return None
    kind = ('ambiguous' if re.search('多处|不止一处|多个可能', notice)
            else 'partial' if sources else 'unavailable' if status == 'degraded' else 'no_match')
    candidates = []
    # An explicitly specified page stays scoped even when its name or number
    # cannot be resolved. Do not suggest other pages from general search.
    if isinstance(hits, _FacetHits) and not explicit_physical_scope(data.message):
        service = _get_knowledge_service()
        try:
            edition = service.edition() if isinstance(service, KnowledgeService) else None
        except (OSError, ValueError, KeyError, TypeError):
            edition = None
        if edition:
            used = {(s.get('document_id'), s.get('page')) for s in sources}
            readings = {}
            for hit in hits.pool:
                # A keyword hit can lead to a different experiment even when
                # it has a valid page. Only suggest pages matched to a facet.
                if not hit.get('facet_ids'):
                    continue
                document_id, page = hit.get('document_id'), hit.get('page')
                document = getattr(edition, 'documents', {}).get(document_id)
                if ((document_id, page) in used or not document or not hit.get('document_version')
                        or document.get('sha256') != hit['document_version']):
                    continue
                entry = {**hit, 'content': hit.get('text')}
                if not _readable_edition_page(edition, entry, readings):
                    continue
                used.add((document_id, page))
                candidates.append({
                    'document_id': document_id, 'document_version': hit['document_version'],
                    'edition_version': edition.version, 'page': page,
                    'book_title': hit['book_title'], 'title': document.get('title') or hit['book_title'],
                })
                if len(candidates) == 3:
                    break
    return {'status': kind, 'candidates': candidates}


async def _current_edition_excerpt(edition, source: dict) -> dict | None:
    return await asyncio.to_thread(_readable_edition_page, edition, source)


async def _offline_edition_result(intent, sources, *, question, scope_notice='', provider_failed=False,
                                  knowledge_status='', trace=None):
    from .question_intent import plain_question
    from .source_scope import missing_physical_page_notice

    if not intent:
        return None
    try:
        service = _get_knowledge_service()
        edition = service.edition() if isinstance(service, KnowledgeService) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    supplied_count = len(sources)
    sources = [{key: value for key, value in source.items() if key != 'prompt_text'}
               for source in sources if await _current_edition_excerpt(edition, source) is not None]
    source_changed = len(sources) < supplied_count
    text = plain_question(question)
    missing = scope_notice or missing_physical_page_notice(text, sources, edition)
    if source_changed:
        missing = (missing + '\n\n原检索结果中有片段已无法通过当前教材版本校验。').strip()
    if not sources and not missing and provider_failed and edition:
        missing = _textbook_scope_notice('degraded' if knowledge_status == 'degraded' else 'empty')
    if not sources and not missing:
        return None
    answer = '模型服务暂不可用，未完成对教材的归纳。' if provider_failed else ''
    if sources:
        locations = '\n'.join(f"- [{index}] {source['book_title']} · PDF 物理第 {source['page']} 页"
                              for index, source in enumerate(sources, 1))
        heading = answer or '已定位下列同版教材。'
        answer = (f'{heading}以下是来源定位。\n\n**检索到的教材**\n\n{locations}\n\n'
                  '点编号可查看本次保存的教材片段，再点「阅读同版正文」。原图是否可查看，以该页「原教材页位」的状态为准。')
    if missing:
        answer = f'{answer}\n\n{missing}'.strip()
    return {'answer': answer, 'sources': sources, 'generation_status': 'retrieval_only' if sources else 'not_generated',
            'knowledge_status': 'ok' if sources else 'degraded' if knowledge_status == 'degraded' else 'empty',
            'provider': _kb_provider_label(),
            'status': 'failed' if provider_failed else 'ok' if sources else 'degraded',
            'trace': {'model_calls': 0, 'tool_dispatch_attempts': 0, 'tool_calls': 0, **(trace or {}),
                      **({'provider_error': 'provider_unavailable'} if provider_failed else {})}}


def _locate_offline_edition_page(edition, query):
    """A named book and explicit physical pages need no topical search."""
    from modules.knowledge.edition import _page_texts
    from modules.knowledge.query_focus import separate_pdf_pages
    from modules.knowledge.reader import DocumentReadError

    selected = separate_pdf_pages(query)
    if selected:
        requested, before, after = selected
        query = f'{before}PDF 第 {requested[0]} 页{after}'
    _, _, document_ids, pages, phrases = edition.search_scope(query)
    if not document_ids or not pages or pages[0] != pages[1] or phrases:
        return []
    if not selected:
        requested = (pages[0],)
    if len({edition.documents[identifier]['book'] for identifier in document_ids}) != 1:
        return []
    hits = []
    for page in requested:
        candidates = []
        for identifier in document_ids:
            record = edition.documents[identifier]
            if not record.get('ingest') or not record['page_start'] <= page <= record['page_end']:
                continue
            try:
                reading = edition.read(identifier, record['sha256'], include_original_status=False)
            except (DocumentReadError, OSError, ValueError, KeyError):
                continue
            if entry := _page_texts(reading).get(page):
                section, excerpt = entry
                candidates.append(edition._bound_hit({'retriever': 'edition_local'}, record, excerpt, section, page))
        if len(candidates) == 1:
            hits.extend(candidates)
    return hits


async def _offline_edition_search(data, actor, skill, attachments, intent, *, db=None, factory=None):
    service = _get_knowledge_service()
    edition = service.edition() if isinstance(service, KnowledgeService) else None
    if edition is None:
        return [], '', None
    if intent == 'locator':
        hits = await asyncio.to_thread(_locate_offline_edition_page, edition, data.message)
        if hits:
            return prepare_sources(hits[:data.top_k]), '', None
    # The edition's default search is local. Bind any explicit continuation
    # in the request store and do not add client-supplied chat history.
    hits, continuity = await _copilot_knowledge_hits(data, [], actor, skill, attachments, db=db, factory=factory)
    sources, notice = _prepare_copilot_sources(data, hits, skill, continuity, keep_page_pointers=intent == 'locator')
    guide = await asyncio.to_thread(_assistant_source_guide, data, skill, hits, sources, notice,
                                    continuity=continuity, textbook_only=True)
    return sources, notice, guide


async def _try_offline_edition_lookup(data, actor, skill, attachments, intent, *, db=None, factory=None, provider_failed=False):
    try:
        sources, notice, guide = await _offline_edition_search(data, actor, skill, attachments, intent, db=db, factory=factory)
        result = await _offline_edition_result(intent, sources, question=data.message, scope_notice=notice,
                                               provider_failed=provider_failed)
        if result is not None and guide:
            result['source_guide'] = guide
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning('copilot_local_textbook_unavailable', error=type(exc).__name__)
        return None


def _saved_evidence_trace(page):
    from .owned_history import history_page_evidence_id
    return {'model_calls': 0, 'tool_calls': 0, 'tool_dispatch_attempts': 0,
            'page_evidence_id': history_page_evidence_id(page)}


async def _authorized_copilot_tools(db, message, actor, scope, skill, ui) -> list[str]:
    """Bind the current user's request to inventory targets before planning."""
    ui['server_allow_device_reads'] = False
    if not skill.tools or not scope.allow_device_reads or not (action_scope := new_device_read_scope(message)):
        return []
    targets = await resolve_task_targets(db, action_scope, actor)
    ui['server_targets'] = targets
    if targets is None or targets.ambiguous or not targets.resolved:
        ui['server_read_scope_note'] = '未核验出这次读取的明确设备，请用户补充目标名称；不会从页面、附件或上一轮代选。'
        return []
    ui['server_allow_device_reads'] = True
    ui['server_read_device_ids'] = frozenset(row['device_id'] for row in targets.resolved)
    return skill.tools


async def _generate_copilot_chat(
    data: CopilotChatRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
    cancel_event: asyncio.Event | None = None,
) -> Any:
    """右侧常驻 Copilot：上下文感知 + RAG + 可选配置草稿（不执行）。"""
    try:
        history = [] if exclude_previous_config_comparison(data.message) else data.history
        scope = request_evidence_scope(data.message, history)
        page = TrustedPageData(None) if scope.provided_only else await _resolve_page_data(db, data, current_user)
        if scope.saved_record_only and page.meta.get('record_origin') != 'server_observation_record':
            page = TrustedPageData(None, {'trusted': False, 'reasons': ['evidence_not_found_or_forbidden']})
        if scope.provided_only or scope.saved_record_only:
            history = []
        policy = await _lab_draft_policy(db, data, current_user)
        lab_steps = [] if scope.provided_only else policy.get('lab_steps',[])
        attachments = await _copilot_attachments(db, data, current_user) if policy["allow_model"] else []
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
                sources=[],
                draft_commands=[],
                draft_explanation="",
                draft_refused_reason=policy["reason"],
                request_id=data.request_id or "",
                assist_only=True,
                status="blocked_environment",
                provider=_kb_provider_label(),
                knowledge_status="not_requested",
            )
        guidance = config_comparison_guidance(page, data.message, has_attachments=bool(attachments),
                                             requests_knowledge=scope.knowledge_lookup is True)
        if guidance:
            return CopilotChatResponse(answer=guidance, request_id=data.request_id or '', status='ok',
                provider=_kb_provider_label(), knowledge_status='not_requested', tier='direct',
                trace={'model_calls': 0, 'tool_dispatch_attempts': 0})
        if evidence_guidance := await _saved_evidence_guidance(db, data, current_user, page, scope, attachments):
            return CopilotChatResponse(answer=evidence_guidance, request_id=data.request_id or '', status='ok',
                provider=_kb_provider_label(), knowledge_status='not_requested', tier='direct', trace=_saved_evidence_trace(page))
        ui = _apply_policy_note(data.context.model_dump(exclude={'config_comparison', 'page_record', 'knowledge_source'}) if data.context and not scope.provided_only else {}, policy)
        ui['provided_material_only'] = scope.provided_only
        ui['server_previous_material'] = scope.previous_material
        # C-05：把已认证角色带入上下文，避免普通用户被引导到管理员专属页面
        ui["role"] = current_user.get("role") or "user"
        ui["page_data_trusted"] = page.trusted
        ui['server_page_validation'] = page
        ui['server_lab_content'] = None if scope.provided_only else policy.get('lab_content')
        if page.meta.get("trusted") is False:
            reasons = ",".join(page.meta.get("reasons") or [])
            ui["notes"] = (
                (ui.get("notes") or "")
                + f"；页面数据未通过服务端可信核验（{reasons}），只能作为线索，不得当作现场事实"
            ).strip("；")
        skill = select_skill(
            data.message,
            want_draft=data.want_draft and policy["allow_draft"],
            lab_steps=lab_steps, history=history,
            has_attachments=bool(attachments),
            saved_observation=page.meta.get("record_origin") == "server_observation_record"
            and "device_mismatch" not in page.meta.get("reasons", []),
            page_data=page.text,
            page_data_trusted=page.trusted,
            route=(data.context.route if data.context else None), evidence_scope=scope,
            config_comparison=page.meta.get('kind') == 'config_comparison',
        )
        if skill.reason == 'saved_configuration_comparison':
            history = []
        offline_intent = _offline_edition_intent(data, history, scope, skill, attachments)
        if offline_intent == 'locator':
            result = await _try_offline_edition_lookup(data, current_user, skill, attachments, offline_intent, db=db)
            if result:
                return CopilotChatResponse(**result, request_id=data.request_id or '', tier='direct')
        try:
            service = await _get_service(db, current_user)
            if not _has_copilot_model_configuration(getattr(service, 'provider', None)):
                raise RuntimeError('Copilot model credentials are not configured')
        except Exception as exc:  # noqa: BLE001
            logger.error("copilot_chat_provider_unavailable", error=type(exc).__name__)
            if offline_intent == 'explanation':
                result = await _try_offline_edition_lookup(data, current_user, skill, attachments, offline_intent,
                                                           db=db, provider_failed=True)
                if result:
                    return CopilotChatResponse(**result, request_id=data.request_id or '', tier='direct')
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "provider_unavailable",
                    "message": "模型服务初始化失败，本次未调用模型；请稍后重试或联系管理员检查模型配置。",
                },
            ) from exc
        knowledge = {'sources': [], 'status': 'not_requested', 'provider': _kb_provider_label()}
        continuity = ''
        page_scope_notice = ''
        hits = []
        if skill.needs_knowledge:
            try:
                hits, continuity = await _copilot_knowledge_hits(data, history, current_user, skill, attachments, db=db)
                if continuity:
                    history = []
                    ui['server_source_continuity'] = continuity
                sources, page_scope_notice = _prepare_copilot_sources(data, hits, skill, continuity)
                knowledge.update(sources=sources, status='ok' if sources else 'degraded' if continuity == 'degraded' else 'empty')
            except Exception as exc:  # noqa: BLE001
                logger.warning('copilot_knowledge_degraded', error=type(exc).__name__)
                knowledge['status'] = 'degraded'
        if notice := _source_continuity_notice(continuity):
            return CopilotChatResponse(answer=notice, request_id=data.request_id or '', status='degraded',
                provider=_kb_provider_label(knowledge), knowledge_status=knowledge['status'], tier='direct',
                trace={'model_calls': 0, 'tool_calls': 0, 'tool_dispatch_attempts': 0, 'source_continuity': continuity})
        sources = knowledge['sources']
        context_docs = _copilot_context_docs(sources)
        ui['server_knowledge_status'] = knowledge['status']
        ui['server_source_scope_notice'] = page_scope_notice
        ui['server_textbook_only'] = scope.textbook_only and skill.id == 'knowledge_answer' and not attachments and not data.want_draft
        source_guide = await asyncio.to_thread(_assistant_source_guide, data, skill, hits, sources, page_scope_notice,
                                               continuity=continuity, status=knowledge['status'],
                                               textbook_only=ui['server_textbook_only'])
        strict_notice = (page_scope_notice if not sources else '') or (
            _textbook_scope_notice(knowledge['status']) if ui['server_textbook_only'] else '')
        if strict_notice:
            return CopilotChatResponse(answer=strict_notice, request_id=data.request_id or '', status='degraded',
                provider=_kb_provider_label(knowledge), knowledge_status=knowledge['status'], tier='direct',
                source_guide=source_guide,
                trace={'model_calls': 0, 'tool_calls': 0, 'tool_dispatch_attempts': 0, 'knowledge_scope': 'textbook_only'})
        ui["skill"] = skill.label
        ui["skill_prompt"] = skill.prompt
        ui["skill_id"] = skill.id
        ui["skill_version"] = skill.version
        if not scope.provided_only and not scope.saved_record_only and skill.id in {'live_evidence','troubleshooting','lab_coach'}:
            from .owned_history import load_owned_history
            ui['server_history'] = await load_owned_history(db, history, current_user)
        if draft_target:
            ui['server_draft_target'] = draft_target
            ui['server_draft_environment'] = draft_environment
        allowed_tools = await _authorized_copilot_tools(db, data.message, current_user, scope, skill, ui)
        tier = select_tier(data.message, page_data=page.text,
                           want_draft=data.want_draft and policy["allow_draft"], skill_id=skill.id)
        if skill.reason in {'verified_observation_explanation','observation_provenance_explanation','verified_attachment_comparison',
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
            history=history,
            want_draft=data.want_draft and policy["allow_draft"],
            device_model=data.device_model,
            page_data=page.text,
            attachments=attachments,
            lab_steps=lab_steps,
            allowed_tools=allowed_tools,
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
        provider_failed = False
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
                provider_failed = _event.get('code') == 'provider_unavailable'
        if provider_failed and stream_status == 'failed':
            locations = await _offline_edition_result(offline_intent, sources, question=data.message,
                                                      scope_notice=page_scope_notice, provider_failed=True,
                                                      knowledge_status=knowledge['status'], trace=trace)
            if locations:
                if source_guide:
                    locations['source_guide'] = source_guide
                return CopilotChatResponse(**locations, request_id=data.request_id or '', tier=tier)
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
        if page_scope_notice and result['status'] == 'ok':
            answer += '\n\n' + page_scope_notice
        generation_status, answer_sources = answer_references(
            sources[:data.top_k], "".join(answer_parts), result["status"],
        )
        return CopilotChatResponse(
            answer=answer,
            sources=answer_sources,
            source_guide=source_guide,
            generation_status=generation_status,
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

    attachments = [item.model_dump(exclude_none=True) for item in data.attachments]
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
    knowledge: dict[str, Any] = {"sources": [], "status": "not_requested", "provider": _kb_provider_label()}
    continuity = ''
    provider = None
    provider_error: str = ""
    draft_target = None
    draft_environment = None
    cancelled_during_setup = False
    evidence_guidance = ''
    offline_intent = ''
    offline_result = None
    page_scope_notice = ''
    hits = []
    history = [] if exclude_previous_config_comparison(data.message) else data.history
    scope = request_evidence_scope(data.message, history)
    if scope.provided_only or scope.saved_record_only:
        history = []
    page = TrustedPageData(None) if scope.provided_only else sanitize_page_data(data.page_data, selection=data.context.selection if data.context else None)
    try:
        if factory is not None:
            try:
                async with factory() as setup_db:
                    policy = await run_cancellable(_lab_draft_policy(setup_db, data, current_user), cancel_event, release_registration)
                    if not scope.provided_only:
                        page = await run_cancellable(_resolve_page_data(setup_db, data, current_user), cancel_event, release_registration)
                    if policy["allow_model"]:
                        attachments = await run_cancellable(
                            _copilot_attachments(setup_db, data, current_user), cancel_event, release_registration
                        )
                        evidence_guidance = await run_cancellable(
                            _saved_evidence_guidance(setup_db, data, current_user, page, scope, attachments), cancel_event,
                        )
                    if data.want_draft and policy['allow_model'] and policy['allow_draft']:
                        draft_target = await run_cancellable(resolve_draft_target(setup_db,data.message,data.context.selection if data.context else '',current_user),cancel_event)
                        draft_environment = await run_cancellable(resolve_draft_environment(setup_db,draft_target,page=page),cancel_event)
                        if not draft_environment.verified:
                            policy = blocked_draft_policy(policy,draft_environment.reason)
                            draft_target = None
            except RequestCancelled:
                cancelled_during_setup = True
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("copilot_policy_failed", error=str(exc))
                if data.attachment_message_id and not data.attachments:
                    raise HTTPException(status_code=503, detail={
                        "code": "attachment_unavailable", "message": "暂时无法读取对话附件，请稍后重试。",
                    }) from exc
                if data.want_draft or data.lab_id or data.lab_session_id or data.lab_steps:
                    policy = blocked_draft_policy(policy,'环境核验暂不可用，不能生成具体设备配置。')
                    draft_target = None
        else:
            if data.attachment_message_id and not data.attachments:
                raise HTTPException(status_code=503, detail={
                    'code': 'attachment_unavailable', 'message': '暂时无法读取对话附件，请稍后重试。',
                })
            if data.want_draft or data.lab_id or data.lab_session_id or data.lab_steps:
                policy = blocked_draft_policy(policy,'环境核验暂不可用，不能生成具体设备配置。')
        if scope.saved_record_only and page.meta.get('record_origin') != 'server_observation_record':
            page = TrustedPageData(None, {'trusted': False, 'reasons': ['evidence_not_found_or_forbidden']})
        lab_steps = [] if scope.provided_only else policy.get('lab_steps',[])
        comparison_guidance = config_comparison_guidance(page, data.message, has_attachments=bool(attachments),
                                                        requests_knowledge=scope.knowledge_lookup is True)
        if policy.get("allow_model") and not cancelled_during_setup and not comparison_guidance and not evidence_guidance:
            intent = select_skill(data.message, want_draft=data.want_draft and policy['allow_draft'],
                                  lab_steps=lab_steps, history=history, has_attachments=bool(attachments),
                                  saved_observation=page.meta.get('record_origin') == 'server_observation_record'
                                  and 'device_mismatch' not in page.meta.get('reasons', []),
                                  page_data=page.text, page_data_trusted=page.trusted,
                                  route=data.context.route if data.context else None, evidence_scope=scope,
                                  config_comparison=page.meta.get('kind') == 'config_comparison')
            offline_intent = _offline_edition_intent(data, history, scope, intent, attachments)
            if offline_intent == 'locator':
                try:
                    offline_result = await run_cancellable(
                        _try_offline_edition_lookup(data, current_user, intent, attachments, offline_intent, factory=factory),
                        cancel_event,
                    )
                except RequestCancelled:
                    cancelled_during_setup = True
        if policy.get("allow_model") and not cancelled_during_setup and not comparison_guidance and not evidence_guidance and not offline_result:
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
                if not _has_copilot_model_configuration(provider):
                    raise RuntimeError('Copilot model credentials are not configured')
            except RequestCancelled:
                cancelled_during_setup = True
            except Exception as exc:  # noqa: BLE001
                # AF2-04：初始化失败是依赖不可用，不是环境策略阻断；只暴露稳定类型，不带密钥/URL。
                provider_error = type(exc).__name__
                provider = None
                logger.warning("copilot_provider_init_failed", error=provider_error)
                if offline_intent == 'explanation':
                    try:
                        offline_result = await run_cancellable(
                            _try_offline_edition_lookup(data, current_user, intent, attachments, offline_intent,
                                                        factory=factory, provider_failed=True), cancel_event,
                        )
                    except RequestCancelled:
                        cancelled_during_setup = True
        if provider is not None and not cancelled_during_setup:
            try:
                if intent.needs_knowledge:
                    query_history = [] if intent.reason == 'saved_configuration_comparison' else history
                    hits, continuity = await run_cancellable(
                        _copilot_knowledge_hits(data, query_history, current_user, intent, attachments, factory=factory), cancel_event,
                    )
                    if continuity:
                        history = []
                    stream_sources, page_scope_notice = _prepare_copilot_sources(data, hits, intent, continuity)
                    knowledge.update(sources=stream_sources, status='ok' if stream_sources else 'degraded' if continuity == 'degraded' else 'empty')
            except RequestCancelled:
                cancelled_during_setup = True
            except Exception as exc:  # noqa: BLE001
                logger.warning('copilot_knowledge_degraded', error=type(exc).__name__)
                knowledge['status'] = 'degraded'
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
    ui = _apply_policy_note(data.context.model_dump(exclude={'config_comparison', 'page_record', 'knowledge_source'}) if data.context and not scope.provided_only else {}, policy)
    ui['server_source_continuity'] = continuity
    ui['provided_material_only'] = scope.provided_only
    ui['server_previous_material'] = scope.previous_material
    # CF-02：流式入口同样使用后端认证角色，客户端自报角色不参与。
    ui["role"] = current_user.get("role") or "user"
    protected: list[str] = []
    if factory is not None and provider is not None and not cancelled_during_setup:
        async with factory() as _policy_db:
            if draft_target:
                ui['server_draft_target'] = draft_target
                ui['server_draft_environment'] = draft_environment
            protected = await load_protected_interfaces(_policy_db,target=draft_target)
    ui['server_protected_interfaces']=tuple(protected)
    ui["page_data_trusted"] = page.trusted
    ui['server_page_validation'] = page
    ui['server_lab_content'] = None if scope.provided_only else policy.get('lab_content')
    ui['server_knowledge_status'] = knowledge.get('status')
    ui['server_source_scope_notice'] = page_scope_notice
    if page.meta.get("trusted") is False:
        reasons = ",".join(page.meta.get("reasons") or [])
        ui["notes"] = (
            (ui.get("notes") or "")
            + f"；页面数据未通过服务端可信核验（{reasons}），只能作为线索，不得当作现场事实"
        ).strip("；")
    skill = select_skill(
        data.message,
        want_draft=data.want_draft and policy["allow_draft"],
        lab_steps=lab_steps, history=history,
        has_attachments=bool(attachments),
        saved_observation=page.meta.get("record_origin") == "server_observation_record"
        and "device_mismatch" not in page.meta.get("reasons", []),
        page_data=page.text,
        page_data_trusted=page.trusted,
        route=(data.context.route if data.context else None), evidence_scope=scope,
        config_comparison=page.meta.get('kind') == 'config_comparison',
    )
    if skill.reason == 'saved_configuration_comparison':
        history = []
    ui["skill"] = skill.label
    ui["skill_prompt"] = skill.prompt
    ui["skill_id"] = skill.id
    ui["skill_version"] = skill.version
    ui['server_textbook_only'] = scope.textbook_only and skill.id == 'knowledge_answer' and not attachments and not data.want_draft
    source_guide = await asyncio.to_thread(_assistant_source_guide, data, skill, hits, sources, page_scope_notice,
                                           continuity=continuity, status=knowledge['status'],
                                           textbook_only=ui['server_textbook_only'])
    strict_notice = (page_scope_notice if not sources else '') or (
        _textbook_scope_notice(knowledge['status']) if ui['server_textbook_only'] else '')
    if (factory is not None and provider is not None and not scope.provided_only and not scope.saved_record_only
            and not cancelled_during_setup and skill.id in {'live_evidence','troubleshooting','lab_coach'}):
        from .owned_history import load_owned_history
        try:
            async with factory() as history_db:
                ui['server_history'] = await run_cancellable(
                    load_owned_history(history_db, history, current_user), cancel_event)
        except RequestCancelled:
            cancelled_during_setup = True
    allowed_tools = []
    if factory is not None and provider is not None and skill.tools and not cancelled_during_setup:
        async with factory() as target_db:
            allowed_tools = await _authorized_copilot_tools(target_db, data.message, current_user, scope, skill, ui)
    tier = select_tier(data.message, page_data=page.text,
                       want_draft=data.want_draft and policy["allow_draft"], skill_id=skill.id)
    if skill.reason in {'verified_observation_explanation','observation_provenance_explanation','verified_attachment_comparison',
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
        answer_parts = []
        provider_failure_event = None
        try:
            yield sse({
                "type": "meta", "request_id": request_id, "sources": [],
                "provider": _kb_provider_label(knowledge),
                "knowledge_status": offline_result['knowledge_status'] if offline_result else knowledge.get("status", "unknown"),
                "skill": skill.as_meta(),
                "status": (
                    "blocked_environment" if not policy.get("allow_model")
                    else (offline_result['status'] if offline_result else "unavailable" if provider_error else (knowledge.get("status") or "ok"))
                ),
                "assist_only": True, "draft_refused_reason": draft_refused,
                "generation_status": "not_generated",
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
            if comparison_guidance and policy.get('allow_model'):
                yield sse({'type': 'token', 'text': comparison_guidance, 'request_id': request_id})
                yield sse({'type': 'references', 'sources': [], 'generation_status': 'not_generated'})
                yield sse({'type': 'done', 'status': 'ok', 'assist_only': True,
                           'trace': {'model_calls': 0, 'tool_dispatch_attempts': 0}})
                return
            if evidence_guidance and policy.get('allow_model'):
                yield sse({'type': 'token', 'text': evidence_guidance, 'request_id': request_id})
                yield sse({'type': 'references', 'sources': [], 'generation_status': 'not_generated'})
                yield sse({'type': 'done', 'status': 'ok', 'assist_only': True, 'trace': _saved_evidence_trace(page)})
                return
            if offline_result:
                yield sse({'type': 'token', 'text': offline_result['answer']})
                yield sse({'type': 'references', 'sources': offline_result['sources'],
                           'generation_status': offline_result['generation_status']})
                if guide := offline_result.get('source_guide'):
                    yield sse({'type': 'source_guide', 'source_guide': guide, 'request_id': request_id})
                if offline_result['status'] == 'failed':
                    yield sse({'type': 'error', 'code': 'provider_unavailable', 'retryable': True,
                               'message': '模型服务暂不可用，未完成对教材的归纳。'})
                yield sse({'type': 'done', 'status': offline_result['status'], 'assist_only': True,
                           'trace': offline_result['trace'], **({'reason': 'provider_unavailable'} if provider_error else {})})
                return
            if notice := _source_continuity_notice(continuity):
                yield sse({'type': 'token', 'text': notice, 'request_id': request_id})
                yield sse({'type': 'references', 'sources': [], 'generation_status': 'not_generated'})
                yield sse({'type': 'done', 'status': 'degraded', 'assist_only': True,
                           'trace': {'model_calls': 0, 'tool_calls': 0, 'tool_dispatch_attempts': 0, 'source_continuity': continuity}})
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
            if strict_notice:
                yield sse({'type': 'token', 'text': strict_notice, 'request_id': request_id})
                yield sse({'type': 'references', 'sources': [], 'generation_status': 'not_generated'})
                if source_guide:
                    yield sse({'type': 'source_guide', 'source_guide': source_guide, 'request_id': request_id})
                yield sse({'type': 'done', 'status': 'degraded', 'assist_only': True,
                           'trace': {'model_calls': 0, 'tool_calls': 0, 'tool_dispatch_attempts': 0,
                                     'knowledge_scope': 'textbook_only'}})
                return
            if source_guide:
                yield sse({'type': 'source_guide', 'source_guide': source_guide, 'request_id': request_id})
            stream = service.copilot_chat_stream(
                message=data.message,
                context_docs=context_docs,
                ui_context=ui,
                history=history,
                want_draft=data.want_draft and policy["allow_draft"],
                device_model=data.device_model,
                page_data=page.text,
                attachments=attachments,
                lab_steps=lab_steps,
                request_id=request_id,
                cancel_event=cancel_event,
                allowed_tools=allowed_tools,
                protected_interfaces=protected,
                tier=tier,
            )
            async for event in stream:
                event.setdefault("request_id", request_id)
                kind = event.get("type")
                if kind == "token":
                    answer_parts.append(event.get("text", ""))
                elif kind == "policy" and "replace_answer" in event:
                    answer_parts = [event["replace_answer"]]
                elif kind == 'error' and event.get('code') == 'provider_unavailable' and offline_intent:
                    provider_failure_event = event
                    continue
                elif kind == "done":
                    if provider_failure_event:
                        if event.get('status') == 'failed' and not cancel_event.is_set():
                            locations = await _offline_edition_result(offline_intent, slim_sources, question=data.message,
                                                                     scope_notice=page_scope_notice, provider_failed=True,
                                                                     knowledge_status=knowledge['status'], trace=event.get('trace'))
                            if locations:
                                if locations['knowledge_status'] != knowledge['status']:
                                    yield sse({'type': 'meta', 'knowledge_status': locations['knowledge_status'],
                                               'status': locations['status'], 'generation_status': locations['generation_status']})
                                yield sse({'type': 'policy', 'replace_answer': locations['answer'],
                                           'retrieval_only': locations['generation_status'] == 'retrieval_only'})
                                yield sse({'type': 'references', 'sources': locations['sources'],
                                           'generation_status': locations['generation_status']})
                                yield sse(provider_failure_event)
                                yield sse({**event, 'reason': 'provider_unavailable', 'trace': locations['trace']})
                                break
                        yield sse(provider_failure_event)
                    if page_scope_notice and event.get('status') == 'ok':
                        yield sse({'type': 'token', 'request_id': request_id, 'text': '\n\n' + page_scope_notice})
                    generation_status, answer_sources = answer_references(
                        slim_sources, "".join(answer_parts), event.get("status", "failed"),
                    )
                    yield sse({"type": "references", "generation_status": generation_status, "sources": answer_sources})
                yield sse(event)
                if kind == "done":
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
    if job.status in {"pending", "running"}:
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
    summary_values = summary_payload if isinstance(summary_payload, dict) else {}
    coverage = {
        "target": job.device_count,
        "observed": job.success_count,
        "failed": job.failure_count,
        "skipped": summary_values.get("skipped"),
        "finished_at": iso_utc(job.finished_at),
    }
    devices = summary_values.get("devices")
    missing_devices = [
        {"device_id": item.get("device_id"), "hostname": str(item.get("hostname") or "未标识设备")[:128],
         "status": item["status"], "reason": str(item.get("reason") or "")[:180]}
        for item in devices if isinstance(item, dict) and item.get("status") in ("failed", "skipped")
    ] if isinstance(devices, list) else []
    if job.success_count == 0:
        reasons = summary_values.get("errors")
        findings = [str(item)[:180] for item in reasons[:4]] if isinstance(reasons, list) else []
        next_step = (
            "先到设备页检查管理连接。修复失败或跳过的设备后，对同一拓扑重新巡检。"
            if job.device_count else "先在拓扑中确认要巡检的设备，再运行巡检。"
        )
        return redact_payload({
            "job_id": job.id, "coverage": coverage, "basis": "no_current_observations",
            "missing_devices": missing_devices,
            "summary": "本次未取得可用设备观察，当前健康情况未知。",
            "key_findings": findings, "root_causes": [],
            "recommendations": [next_step], "report_text": "",
        })
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
    )
    try:
        service = await _get_service(db, current_user)
        report = await service.generate_report(
            title=f"巡检任务 #{job.id} 异常归因与处置建议",
            source_text=source_text,
            context=("只解读本任务实际采到的设备与指标。开头给出采集覆盖和最重要的事实，"
                     "区分失败、跳过与无告警。没有证据时列出待验证方向，避免归因为已证实故障。"
                     "建议最多三项，每项说明下一次要核对的对象和结果。"),
        )
        return {**report, "job_id": job.id, "coverage": coverage, "basis": "saved_job",
                "missing_devices": redact_payload(missing_devices)}
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


@router.get("/knowledge/original-figure", response_model=None)
async def read_original_figure(
    document_id: str = Query(..., min_length=1, max_length=128),
    version: str = Query(..., min_length=64, max_length=64),
    page: int = Query(..., ge=1, le=10000),
    current_user: dict = Depends(get_current_user),
) -> Response:
    from modules.knowledge.reader import DocumentReadError
    try:
        image = await _get_knowledge_service().original_figure(document_id, version, page)
    except DocumentReadError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": exc.message}) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(424, detail={"message": "原页图读取失败，请管理员核对资料目录。"}) from exc
    return Response(image, media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.post("/knowledge/original-quote", dependencies=[Depends(_AI_RATE_LIMIT)], response_model=None)
async def locate_original_quote(data: OriginalQuoteRequest, _: dict = Depends(get_current_user)) -> dict:
    from modules.knowledge.original_index import search_original_quote
    from modules.knowledge.reader import DocumentReadError

    try:
        service = _get_knowledge_service()
        edition = await asyncio.to_thread(service.edition)
        results = await asyncio.to_thread(search_original_quote, edition, data.quote, data.book)
    except DocumentReadError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": exc.message}) from exc
    return {"edition": edition.version, "results": results}


@router.get("/knowledge/legacy-locator", response_model=None)
async def locate_legacy_knowledge(
    document_id: str = Query(..., min_length=1, max_length=256),
    version: str = Query(..., min_length=64, max_length=64),
    section_id: str | None = Query(None, max_length=80),
    current_user: dict = Depends(get_current_user),
) -> dict:
    return await _get_knowledge_service().legacy_locator(document_id, version, section_id)


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
        results = await _get_knowledge_service().search(data.question, data.kb_id, data.top_k)
        return [{key: value for key, value in item.items() if key not in {"prompt_text", "prompt_sha256"}}
                for item in prepare_sources(results, max_document_chars=1300, max_documents=data.top_k)]
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
        if (saved.get('response') or {}).get('generation_status') == 'retrieval_only':
            service = _get_knowledge_service()
            edition = service.edition() if isinstance(service, KnowledgeService) else None
            if await _current_edition_excerpt(edition, original) is None:
                raise HTTPException(410, detail={'code': 'citation_revoked', 'message': '该次检索的同版教材页位已不可回读。'})
            return {key: original.get(key) for key in ('filename', 'title', 'document_id', 'source_id', 'content',
                    'version', 'captured_at', 'truncated', 'reviewed_notes', 'document_version', 'section_id',
                    'page', 'book_title', 'edition_version')} | {
                'scope': 'retrieval_excerpt', 'available_now': True,
                'message': '本次保存的教材片段，仅供定位和回读。',
            }
        if original.get("document_id") and original.get("document_version"):
            locator = await _get_knowledge_service().legacy_locator(
                original["document_id"], original["document_version"], original.get("section_id"),
            )
            if locator.get("status") in {"exact-page-locator", "archive-only"}:
                return {key: original.get(key) for key in ("filename", "title", "source_id", "content", "version",
                            "captured_at", "truncated", "reviewed_notes", "page", "book_title", "edition_version")} | {
                    "scope": "answer_excerpt", "available_now": True, "legacy_locator": locator,
                    "message": locator["message"],
                }
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
        return {key: original.get(key) for key in ("filename", "title", "document_id", "source_id", "content", "version",
                   "captured_at", "truncated", "reviewed_notes", "document_version", "section_id", "page", "book_title", "edition_version")} | {
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
