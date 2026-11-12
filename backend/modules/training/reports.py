# -*- coding: utf-8 -*-
"""V7-A A-05：复盘报告的持久版本与读写分离契约。

设计要点：
- 报告是持久记录：每次成功生成都写入新的 ``training_report`` 版本，不覆盖旧版本；
- 读取（GET）只读数据库，不触发检索/模型调用；
- 生成（POST）才调用模型，并支持幂等键与“证据未变则复用”；
- 生成失败写入 ``status=failed`` 的一次尝试，保留错误原因，旧 ready 版本继续可读。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logger import get_logger
from core.time_utils import iso_utc
from modules.training.content_source import content_brief, resolve_session_content
from modules.training.models import TrainingReport, TrainingSession
from modules.training.service import TrainingService, UNVERIFIED_NOTE

logger = get_logger("training")

PROMPT_VERSION = "training-recap-v7c-source-identity"
REPORT_STATUS_READY = "ready"
REPORT_STATUS_FAILED = "failed"


def _resolved(snapshot: dict) -> dict:
    return resolve_session_content(snapshot["session"], snapshot["lab"])


def _snapshot_objectives(snapshot: dict) -> list:
    return _resolved(snapshot)["objectives"]


def _objective_brief(snapshot: dict) -> str:
    return content_brief(_resolved(snapshot))


def build_report_input(snapshot: dict) -> dict:
    """生成输入摘要（确定性，可哈希）。只放证据，不放凭据。"""
    session = snapshot["session"]
    lab = snapshot["lab"]
    logs = snapshot["logs"]
    faults = snapshot["faults"]
    resolved = _resolved(snapshot)
    evidence = {
        "logs": [
            {
                "id": item.get("id"),
                "timestamp": item.get("timestamp"),
                "action": item.get("action"),
                "command": item.get("command"),
                "target_device": item.get("target_device"),
                "result": item.get("result"),
                "success": item.get("success"),
                "trust": (item.get("meta") or {}).get("evidence_trust"),
            }
            for item in logs
        ],
        "faults": [
            {"id": fault.id, "fault_type": fault.fault_type.value, "resolved": fault.resolved_correctly}
            for fault in faults
        ],
    }
    return {
        "session_id": session.id,
        "session_status": session.status,
        "lab_id": lab.id,
        "lab_title": resolved["title"] or lab.title,
        "content_version": resolved["version"],
        "content_source": resolved["source"],
        "content_warning": resolved["warning"],
        "objectives": resolved["objectives"],
        "objective_brief": content_brief(resolved),
        "reference_score": session.score,
        "verification_note": UNVERIFIED_NOTE,
        "evidence": evidence,
    }


def report_input_hash(payload: dict) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def input_summary(payload: dict) -> dict:
    evidence = payload.get("evidence") or {}
    logs = evidence.get("logs") or []
    faults = evidence.get("faults") or []
    timestamps = [item.get("timestamp") for item in logs if item.get("timestamp")]
    trust: dict[str, int] = {}
    for item in logs:
        key = item.get("trust") or "unknown"
        trust[key] = trust.get(key, 0) + 1
    return {
        "session_status": payload.get("session_status"),
        "content_version": payload.get("content_version"),
        "content_source": payload.get("content_source"),
        "content_warning": payload.get("content_warning"),
        "log_count": len(logs),
        "fault_count": len(faults),
        "evidence_trust": trust,
        "first_log_at": min(timestamps) if timestamps else None,
        "last_log_at": max(timestamps) if timestamps else None,
        "reference_score": payload.get("reference_score"),
        "verification_note": payload.get("verification_note"),
    }


def serialize_report(model: TrainingReport) -> dict:
    return {
        "session_id": model.session_id,
        "version": model.version,
        "status": model.status,
        "title": model.title,
        "summary": model.summary,
        "key_findings": model.key_findings or [],
        "root_causes": model.root_causes or [],
        "impact_analysis": model.impact_analysis or [],
        "recommendations": model.recommendations or [],
        "report_text": model.report_text or "",
        "sources": model.sources or [],
        "input_hash": model.input_hash,
        "input_summary": model.input_summary or {},
        "model": model.model,
        "prompt_version": model.prompt_version,
        "generated_at": iso_utc(model.generated_at),
    }


async def list_versions(db: AsyncSession, session_id: int) -> list[TrainingReport]:
    result = await db.execute(
        select(TrainingReport)
        .where(TrainingReport.session_id == session_id)
        .order_by(TrainingReport.version)
    )
    return list(result.scalars().all())


async def latest_ready(db: AsyncSession, session_id: int) -> TrainingReport | None:
    result = await db.execute(
        select(TrainingReport)
        .where(
            TrainingReport.session_id == session_id,
            TrainingReport.status == REPORT_STATUS_READY,
        )
        .order_by(TrainingReport.version.desc())
        .limit(1)
    )
    return result.scalars().first()


async def find_by_idempotency_key(
    db: AsyncSession, session_id: int, key: str | None,
) -> TrainingReport | None:
    if not key:
        return None
    result = await db.execute(
        select(TrainingReport).where(
            TrainingReport.session_id == session_id,
            TrainingReport.idempotency_key == key,
        )
    )
    return result.scalars().first()


def envelope(
    session: TrainingSession,
    versions: list[TrainingReport],
    *,
    reused: bool = False,
) -> dict:
    ready = [item for item in versions if item.status == REPORT_STATUS_READY]
    failed = [item for item in versions if item.status == REPORT_STATUS_FAILED]
    latest = ready[-1] if ready else None
    last_failure = failed[-1] if failed else None
    return {
        "session_id": session.id,
        "lab_id": session.lab_id,
        "status": REPORT_STATUS_READY if latest else "none",
        "report": serialize_report(latest) if latest else None,
        "versions": [
            {
                "version": item.version,
                "status": item.status,
                "input_hash": item.input_hash,
                "generated_at": iso_utc(item.generated_at),
                "model": item.model,
            }
            for item in versions
        ],
        "last_failure": (
            {
                "version": last_failure.version,
                "status": last_failure.status,
                "error": last_failure.error,
                "stage": (last_failure.input_summary or {}).get("failure_stage"),
                "generated_at": iso_utc(last_failure.generated_at),
            }
            if last_failure else None
        ),
        "reused": reused,
    }


def next_version(versions: list[TrainingReport]) -> int:
    return (max((item.version for item in versions), default=0) + 1)


def build_report_row(
    session_id: int,
    version: int,
    *,
    status: str,
    payload: dict,
    input_hash: str,
    summary: dict,
    model: str | None,
    body: dict | None = None,
    sources: list[dict] | None = None,
    error: str | None = None,
    idempotency_key: str | None = None,
) -> TrainingReport:
    body = body or {}
    return TrainingReport(
        session_id=session_id,
        version=version,
        status=status,
        title=(body.get("title") or f"会话 #{session_id} 复盘报告")[:256],
        summary=body.get("summary"),
        key_findings=body.get("key_findings") or [],
        root_causes=body.get("root_causes") or [],
        impact_analysis=body.get("impact_analysis") or [],
        recommendations=body.get("recommendations") or [],
        report_text=body.get("report_text"),
        sources=sources or body.get("sources") or [],
        input_hash=input_hash,
        input_summary=summary,
        model=model,
        prompt_version=PROMPT_VERSION,
        error=error,
        idempotency_key=idempotency_key,
        generated_at=datetime.now(timezone.utc),
    )
