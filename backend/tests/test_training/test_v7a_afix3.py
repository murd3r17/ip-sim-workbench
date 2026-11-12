# -*- coding: utf-8 -*-
"""AF3-02：报告保存失败后恢复事务、记录失败尝试，并处理提交/回读边界。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from modules.training.models import TrainingReport
from tests.test_training.test_v7a_state_and_reports import _admin_token, _lab, _session, auth_header


async def _v1(client, token, monkeypatch):
    from modules.training import router

    lab_id = await _lab(client, token)
    sid = await _session(client, token, lab_id)
    monkeypatch.setattr(router, "_get_knowledge_service", lambda: SimpleNamespace(search=AsyncMock(return_value=[])))
    good = SimpleNamespace(model_name="af3-model", generate_report=AsyncMock(return_value={"title": "old", "report_text": "old body"}))
    monkeypatch.setattr(router, "_get_ai_service", AsyncMock(return_value=good))
    response = await client.post(f"/api/v1/training/sessions/{sid}/report/generate", json={}, headers=auth_header(token))
    assert response.status_code == 200
    return sid, good


def _is_pending_ready_v2(db, sid):
    return any(
        isinstance(row, TrainingReport) and row.session_id == sid and row.version == 2 and row.status == "ready"
        for row in db.new
    )


@pytest.mark.asyncio
async def test_transient_commit_failure_records_one_failed_save_and_retry_succeeds(client, test_session_factory, monkeypatch):
    token = await _admin_token(test_session_factory)
    sid, good = await _v1(client, token, monkeypatch)
    original_commit = AsyncSession.commit
    injected = False

    async def commit_with_failure(db):
        nonlocal injected
        if not injected and _is_pending_ready_v2(db, sid):
            injected = True
            raise RuntimeError("controlled transient commit failure")
        return await original_commit(db)

    monkeypatch.setattr(AsyncSession, "commit", commit_with_failure)
    response = await client.post(f"/api/v1/training/sessions/{sid}/report/generate", json={"regenerate": True}, headers=auth_header(token))
    assert response.status_code == 502
    assert "结果保存失败" in response.json()["detail"]
    async with test_session_factory() as db:
        rows = (await db.execute(select(TrainingReport).where(TrainingReport.session_id == sid).order_by(TrainingReport.version))).scalars().all()
        assert [(row.version, row.status) for row in rows] == [(1, "ready"), (2, "failed")]
        assert rows[0].report_text == "old body"
        assert rows[1].input_summary["failure_stage"] == "save"
    monkeypatch.setattr(AsyncSession, "commit", original_commit)
    retry = await client.post(f"/api/v1/training/sessions/{sid}/report/generate", json={"regenerate": True}, headers=auth_header(token))
    assert retry.status_code == 200
    async with test_session_factory() as db:
        rows = (await db.execute(select(TrainingReport).where(TrainingReport.session_id == sid).order_by(TrainingReport.version))).scalars().all()
        assert [(row.version, row.status) for row in rows] == [(1, "ready"), (2, "failed"), (3, "ready")]


@pytest.mark.asyncio
async def test_real_flush_failure_rolls_back_and_next_generation_succeeds(client, test_session_factory, monkeypatch):
    token = await _admin_token(test_session_factory)
    sid, good = await _v1(client, token, monkeypatch)
    original_flush = Session.flush
    injected = False

    def flush_with_failure(db, *args, **kwargs):
        nonlocal injected
        if not injected and _is_pending_ready_v2(db, sid):
            injected = True
            raise RuntimeError("controlled flush failure")
        return original_flush(db, *args, **kwargs)

    monkeypatch.setattr(Session, "flush", flush_with_failure)
    response = await client.post(f"/api/v1/training/sessions/{sid}/report/generate", json={"regenerate": True}, headers=auth_header(token))
    assert response.status_code == 502
    async with test_session_factory() as db:
        rows = (await db.execute(select(TrainingReport).where(TrainingReport.session_id == sid).order_by(TrainingReport.version))).scalars().all()
        assert [(row.version, row.status) for row in rows] == [(1, "ready"), (2, "failed")]
        assert rows[1].input_summary["failure_stage"] == "save"
        assert len([row for row in rows if row.status == "failed"]) == 1
    monkeypatch.setattr(Session, "flush", original_flush)
    retry = await client.post(f"/api/v1/training/sessions/{sid}/report/generate", json={"regenerate": True}, headers=auth_header(token))
    assert retry.status_code == 200


@pytest.mark.asyncio
async def test_persistent_database_failure_is_honest_and_keeps_old_version(client, test_session_factory, monkeypatch):
    token = await _admin_token(test_session_factory)
    sid, good = await _v1(client, token, monkeypatch)
    async with test_session_factory() as db:
        before = (await db.execute(select(TrainingReport).where(TrainingReport.session_id == sid))).scalars().one()
        before_snapshot = (before.version, before.report_text, before.input_hash, before.created_at)
    original_commit = AsyncSession.commit

    async def always_fail(db):
        raise RuntimeError("database is unwritable")

    monkeypatch.setattr(AsyncSession, "commit", always_fail)
    response = await client.post(f"/api/v1/training/sessions/{sid}/report/generate", json={"regenerate": True}, headers=auth_header(token))
    assert response.status_code == 503
    assert "失败尝试未能保存" in response.json()["detail"]
    async with test_session_factory() as db:
        rows = (await db.execute(select(TrainingReport).where(TrainingReport.session_id == sid))).scalars().all()
        assert len(rows) == 1 and rows[0].status == "ready"
        assert (rows[0].version, rows[0].report_text, rows[0].input_hash, rows[0].created_at) == before_snapshot
    monkeypatch.setattr(AsyncSession, "commit", original_commit)
    retry = await client.post(f"/api/v1/training/sessions/{sid}/report/generate", json={"regenerate": True}, headers=auth_header(token))
    assert retry.status_code == 200


@pytest.mark.asyncio
async def test_commit_succeeded_but_readback_failed_does_not_insert_duplicate(client, test_session_factory, monkeypatch):
    from modules.training import reports as report_store

    token = await _admin_token(test_session_factory)
    sid, good = await _v1(client, token, monkeypatch)
    original_commit = AsyncSession.commit
    original_list = report_store.list_versions
    committed = False
    readback_failed = False

    async def commit_tracking(db):
        nonlocal committed
        result = await original_commit(db)
        if _is_pending_ready_v2(db, sid) or any(
            isinstance(row, TrainingReport) and row.session_id == sid and row.version == 2 and row.status == "ready"
            for row in db.identity_map.values()
        ):
            committed = True
        return result

    async def list_with_readback_failure(db, session_id):
        nonlocal readback_failed
        if committed and not readback_failed:
            readback_failed = True
            raise RuntimeError("controlled readback failure after commit")
        return await original_list(db, session_id)

    monkeypatch.setattr(AsyncSession, "commit", commit_tracking)
    monkeypatch.setattr(report_store, "list_versions", list_with_readback_failure)
    response = await client.post(f"/api/v1/training/sessions/{sid}/report/generate", json={"regenerate": True}, headers=auth_header(token))
    assert response.status_code == 200
    assert readback_failed is True
    async with test_session_factory() as db:
        rows = (await db.execute(select(TrainingReport).where(TrainingReport.session_id == sid).order_by(TrainingReport.version))).scalars().all()
        assert [(row.version, row.status) for row in rows] == [(1, "ready"), (2, "ready")]
    monkeypatch.setattr(report_store, "list_versions", original_list)
    calls_before = good.generate_report.await_count
    reused = await client.post(f"/api/v1/training/sessions/{sid}/report/generate", json={"regenerate": False}, headers=auth_header(token))
    assert reused.status_code == 200
    assert good.generate_report.await_count == calls_before
