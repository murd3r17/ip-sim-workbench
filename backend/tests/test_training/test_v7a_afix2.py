# -*- coding: utf-8 -*-
"""V7-A AF2 第二轮返修回归：迁移字段保护、取消生命周期、报告/助手失败语义。"""
import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from starlette.requests import Request

from core.database import Base
from core.security import create_access_token, hash_password
from modules.ai_text.cancel import (
    CancellationRegistry,
    RequestCapacityExceeded,
    RequestIdConflict,
    iterate_cancellable,
    run_cancellable,
)
from modules.training.lab_content import CONTENT_VERSION, ENVIRONMENT_SPEC
from modules.device.models import Device, DeviceStatus, DeviceType
from modules.training.models import FaultInjection, OperationLog, TrainingLab, TrainingReport, TrainingSession
from tests.test_training.test_v7a_afix import _engine_factory, _seed_lab
from tests.test_training.test_v7a_state_and_reports import _admin_token, _lab, _session, auth_header

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures' / 'training' / 'legacy_seed_2026_08.json'


async def _seed_real_legacy(factory, title: str):
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    row = next(item for item in data['labs'] if item['title'] == title)
    return await _seed_lab(
        factory,
        title=row['title'],
        description=row['description'],
        objectives=row['objectives'],
        time_limit=row['time_limit_minutes'],
    )


async def _managed_state(factory, lab_id: int):
    async with factory() as db:
        lab = await db.get(TrainingLab, lab_id)
        sessions = (await db.execute(select(TrainingSession).where(TrainingSession.lab_id == lab_id))).scalars().all()
        session_ids = [row.id for row in sessions]
        logs = (await db.execute(select(OperationLog).where(OperationLog.lab_id == lab_id))).scalars().all()
        faults = (await db.execute(select(FaultInjection).where(FaultInjection.session_id.in_(session_ids)))).scalars().all() if session_ids else []
        return {
            'fields': {
                'title': lab.title, 'description': lab.description, 'objectives': lab.objectives,
                'time_limit_minutes': lab.time_limit_minutes, 'is_sandbox': lab.is_sandbox,
                'content_version': lab.content_version, 'environment_spec': lab.environment_spec,
            },
            'sessions': [(row.id, row.status) for row in sessions],
            'logs': [(row.id, row.command, row.success) for row in logs],
            'faults': [(row.id, row.fault_type.value, row.resolved_correctly) for row in faults],
        }


@pytest.mark.asyncio
async def test_real_legacy_seed_upgrades_once_without_fingerprint_patch(tmp_path, monkeypatch):
    from scripts import migrate_training_content_v7a as migrator

    engine, factory = await _engine_factory(tmp_path)
    monkeypatch.setattr(migrator, 'init_db', AsyncMock(return_value=(engine, factory)))
    monkeypatch.setattr(migrator, 'close_db', AsyncMock())
    monkeypatch.setattr(migrator, 'get_session_factory', lambda: factory)
    full_id = await _seed_real_legacy(factory, 'OSPF 单区域基础实验完整版')
    simple_id = await _seed_real_legacy(factory, 'OSPF 单区域基础实验精简版')

    first = await migrator.migrate(False)
    assert first['updated_count'] == 2
    async with factory() as db:
        full = await db.get(TrainingLab, full_id)
        simple = await db.get(TrainingLab, simple_id)
        assert full.content_version == CONTENT_VERSION and full.environment_spec == ENVIRONMENT_SPEC
        assert simple.content_version == CONTENT_VERSION and simple.environment_spec == ENVIRONMENT_SPEC
        assert '现场按 NE40E-X16 改' in full.description
    second = await migrator.migrate(False)
    assert second['updated_count'] == 0
    assert len(second['already_current']) == 2
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['environment_spec', 'content_version'])
async def test_managed_field_edit_is_not_overwritten(tmp_path, monkeypatch, field):
    from scripts import migrate_training_content_v7a as migrator

    engine, factory = await _engine_factory(tmp_path)
    monkeypatch.setattr(migrator, 'init_db', AsyncMock(return_value=(engine, factory)))
    monkeypatch.setattr(migrator, 'close_db', AsyncMock())
    monkeypatch.setattr(migrator, 'get_session_factory', lambda: factory)
    lab_id = await _seed_real_legacy(factory, 'OSPF 单区域基础实验完整版')
    value = {'requires_binding': True, 'devices': [], 'owner_note': 'PRESERVE_USER_ENV'} if field == 'environment_spec' else 'manual-edit'
    async with factory() as db:
        lab = await db.get(TrainingLab, lab_id)
        setattr(lab, field, value)
        await db.commit()
    result = await migrator.migrate(False)
    async with factory() as db:
        lab = await db.get(TrainingLab, lab_id)
        assert getattr(lab, field) == value
        assert lab.content_version != CONTENT_VERSION if field == 'environment_spec' else True
    assert result['updated_count'] == 0
    assert result['skipped_user_modified'][0]['reason_code'] == 'legacy_managed_field_mismatch'
    assert field in result['skipped_user_modified'][0]['differences_from_legacy']
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['description', 'time_limit_minutes', 'objectives', 'is_sandbox'])
async def test_user_edited_legacy_fields_are_preserved(tmp_path, monkeypatch, field):
    from scripts import migrate_training_content_v7a as migrator

    engine, factory = await _engine_factory(tmp_path)
    monkeypatch.setattr(migrator, 'init_db', AsyncMock(return_value=(engine, factory)))
    monkeypatch.setattr(migrator, 'close_db', AsyncMock())
    monkeypatch.setattr(migrator, 'get_session_factory', lambda: factory)
    lab_id = await _seed_real_legacy(factory, 'OSPF 单区域基础实验完整版')
    edited = {'description': 'USER_DESCRIPTION', 'time_limit_minutes': 77,
              'objectives': [{'id': 1, 'name': 'USER_STEP'}], 'is_sandbox': True}[field]
    async with factory() as db:
        setattr(await db.get(TrainingLab, lab_id), field, edited)
        await db.commit()
    result = await migrator.migrate(False)
    async with factory() as db:
        lab = await db.get(TrainingLab, lab_id)
        assert getattr(lab, field) == edited
        assert lab.content_version is None
    assert result['updated_count'] == 0
    assert result['skipped_user_modified'][0]['reason_code'] == 'fingerprint_mismatch'
    await engine.dispose()


@pytest.mark.asyncio
async def test_same_title_user_record_is_not_overwritten(tmp_path, monkeypatch):
    from scripts import migrate_training_content_v7a as migrator

    engine, factory = await _engine_factory(tmp_path)
    monkeypatch.setattr(migrator, 'init_db', AsyncMock(return_value=(engine, factory)))
    monkeypatch.setattr(migrator, 'close_db', AsyncMock())
    monkeypatch.setattr(migrator, 'get_session_factory', lambda: factory)
    legacy_id = await _seed_real_legacy(factory, 'OSPF 单区域基础实验完整版')
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))['labs'][0]
    user_id = await _seed_lab(
        factory, title=data['title'], description=data['description'],
        objectives=data['objectives'], time_limit=data['time_limit_minutes'],
    )
    result = await migrator.migrate(False)
    async with factory() as db:
        assert (await db.get(TrainingLab, legacy_id)).content_version == CONTENT_VERSION
        user = await db.get(TrainingLab, user_id)
        assert user.content_version is None and user.description == data['description']
    assert result['updated_count'] == 1
    assert result['skipped_same_title'][0]['id'] == user_id
    assert result['skipped_same_title'][0]['reason_code'] == 'same_title_unknown_origin'
    await engine.dispose()


@pytest.mark.asyncio
async def test_dry_run_and_failure_rollback_keep_content_sessions_logs_faults(tmp_path, monkeypatch):
    from scripts import migrate_training_content_v7a as migrator

    engine, factory = await _engine_factory(tmp_path, 'drill.db')
    db_path = tmp_path / 'drill.db'
    monkeypatch.setattr(migrator, 'init_db', AsyncMock(return_value=(engine, factory)))
    monkeypatch.setattr(migrator, 'close_db', AsyncMock())
    monkeypatch.setattr(migrator, 'get_session_factory', lambda: factory)
    first_id = await _seed_real_legacy(factory, 'OSPF 单区域基础实验完整版')
    second_id = await _seed_real_legacy(factory, 'OSPF 单区域基础实验精简版')
    async with factory() as db:
        session = TrainingSession(lab_id=first_id, trainee_id=1, status='completed')
        db.add(session)
        lab = await db.get(TrainingLab, first_id)
        device = Device(hostname='AF2-R1', mgmt_ip='192.0.2.1', device_type=DeviceType.ROUTER,
                        status=DeviceStatus.UNKNOWN, topology_id=lab.topology_id)
        db.add(device)
        await db.flush()
        db.add(OperationLog(lab_id=first_id, session_id=session.id, action='command', command='display ospf peer', success=True))
        db.add(FaultInjection(session_id=session.id, device_id=device.id, fault_type='interface_shutdown'))
        await db.commit()
    before = {lab_id: await _managed_state(factory, lab_id) for lab_id in (first_id, second_id)}
    dry = await migrator.migrate(True)
    assert dry['updated_count'] == 2
    assert {lab_id: await _managed_state(factory, lab_id) for lab_id in before} == before
    failed = await migrator.migrate(False, fail_after=1)
    assert failed['failure']['rolled_back'] is True
    assert {lab_id: await _managed_state(factory, lab_id) for lab_id in before} == before
    await engine.dispose()


@pytest.mark.asyncio
async def test_backup_is_restorable_and_restore_compares_content(tmp_path, monkeypatch):
    from scripts import migrate_training_content_v7a as migrator

    engine, factory = await _engine_factory(tmp_path, 'backup.db')
    monkeypatch.setattr(migrator, 'init_db', AsyncMock(return_value=(engine, factory)))
    monkeypatch.setattr(migrator, 'close_db', AsyncMock())
    monkeypatch.setattr(migrator, 'get_session_factory', lambda: factory)
    lab_id = await _seed_real_legacy(factory, 'OSPF 单区域基础实验完整版')
    async with factory() as db:
        session = TrainingSession(lab_id=lab_id, trainee_id=1, status='completed')
        db.add(session)
        lab = await db.get(TrainingLab, lab_id)
        device = Device(hostname='AF2-BACKUP-R1', mgmt_ip='192.0.2.2', device_type=DeviceType.ROUTER,
                        status=DeviceStatus.UNKNOWN, topology_id=lab.topology_id)
        db.add(device)
        await db.flush()
        db.add(OperationLog(lab_id=lab_id, session_id=session.id, action='command', command='display ospf peer', success=True))
        db.add(FaultInjection(session_id=session.id, device_id=device.id, fault_type='interface_shutdown'))
        await db.commit()
    before = await _managed_state(factory, lab_id)
    backup = tmp_path / 'backup.json'
    first = await migrator.migrate(False, backup_path=str(backup))
    payload = json.loads(backup.read_text(encoding='utf-8'))
    assert payload['kind'] == 'restorable_managed_content'
    assert {'environment_spec', 'content_version', 'objectives'} <= set(payload['fields'])
    assert first['backup']['restorable'] is True
    async with factory() as db:
        lab = await db.get(TrainingLab, lab_id)
        lab.description = 'POST_BACKUP_EDIT'
        lab.environment_spec = {'owner_note': 'changed'}
        await db.commit()
    restored = await migrator.restore_backup(str(backup))
    assert restored['restored_count'] == 1
    after = await _managed_state(factory, lab_id)
    assert after == before  # 受管内容、原用户修改、会话、操作日志、故障记录全部回到备份时
    async with factory() as db:
        lab = await db.get(TrainingLab, lab_id)
        assert lab.description == payload['rows'][0]['description']
        assert lab.environment_spec is None
        assert lab.content_version is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_outer_cancel_closes_owned_upstream_task():
    entered, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    children = []

    async def upstream():
        children.append(asyncio.current_task())
        try:
            entered.set()
            await release.wait()
        finally:
            closed.set()

    wrapper = asyncio.create_task(run_cancellable(upstream(), asyncio.Event()))
    await asyncio.wait_for(entered.wait(), 2)
    wrapper.cancel()
    with pytest.raises(asyncio.CancelledError):
        await wrapper
    await asyncio.sleep(0)
    assert closed.is_set() and children[0].done()


@pytest.mark.asyncio
async def test_iterate_explicit_cancel_closes_upstream_and_pump():
    closed = asyncio.Event()

    async def agen():
        try:
            yield 'first'
            await asyncio.sleep(30)
            yield 'late'
        finally:
            closed.set()

    event = asyncio.Event()
    iterator = iterate_cancellable(agen(), event)
    assert await asyncio.wait_for(iterator.__anext__(), 2) == 'first'
    event.set()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(iterator.__anext__(), 2)
    await asyncio.sleep(0.05)
    assert closed.is_set()


@pytest.mark.asyncio
async def test_iterate_upstream_error_closes_upstream():
    closed = asyncio.Event()

    async def agen():
        try:
            yield 'first'
            raise RuntimeError('upstream boom')
        finally:
            closed.set()

    iterator = iterate_cancellable(agen(), asyncio.Event())
    assert await asyncio.wait_for(iterator.__anext__(), 2) == 'first'
    with pytest.raises(RuntimeError, match='upstream boom'):
        await asyncio.wait_for(iterator.__anext__(), 2)
    await asyncio.sleep(0.05)
    assert closed.is_set()


@pytest.mark.asyncio
async def test_iterate_normal_completion_closes_upstream():
    closed = asyncio.Event()

    async def agen():
        try:
            yield 'only'
        finally:
            closed.set()

    iterator = iterate_cancellable(agen(), asyncio.Event())
    assert await asyncio.wait_for(iterator.__anext__(), 2) == 'only'
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(iterator.__anext__(), 2)
    assert closed.is_set()


@pytest.mark.asyncio
async def test_iterate_consumer_close_cleans_pump_and_upstream():
    closed, produced = asyncio.Event(), asyncio.Event()

    async def agen():
        try:
            yield 'one'
            produced.set()
            await asyncio.sleep(30)
        finally:
            closed.set()

    iterator = iterate_cancellable(agen(), asyncio.Event())
    value = await asyncio.wait_for(iterator.__anext__(), 2)
    assert value == 'one'
    await iterator.aclose()
    await asyncio.sleep(0.05)
    assert closed.is_set()
    assert not any(task.get_name().startswith('pump') for task in asyncio.all_tasks() if task is not asyncio.current_task())


def test_duplicate_request_id_is_rejected_and_unregister_is_identity_bound():
    registry = CancellationRegistry()
    first = registry.register(7, 'same')
    with pytest.raises(RequestIdConflict):
        registry.register(7, 'same')
    assert registry.request_cancel(7, 'same') and first.is_set()
    assert registry.unregister(7, 'same', event=asyncio.Event()) is False
    assert registry.request_cancel(7, 'same') is True
    assert registry.unregister(7, 'same', event=first) is True
    second = registry.register(7, 'same')
    assert second.is_set() is False
    registry.clear()


def test_registry_capacity_rejects_new_request_instead_of_evicting_old():
    registry = CancellationRegistry(max_entries=1)
    first = registry.register(7, 'one')
    with pytest.raises(RequestCapacityExceeded):
        registry.register(7, 'two')
    assert registry.request_cancel(7, 'one') and first.is_set()
    registry.unregister(7, 'one', event=first)
    assert registry.register(7, 'two') is not None


@pytest.mark.asyncio
async def test_http_duplicate_request_id_returns_409(client, test_session_factory, monkeypatch):
    from modules.ai_text import router
    from starlette.responses import StreamingResponse

    entered, release = asyncio.Event(), asyncio.Event()

    calls = 0

    async def slow_generation(*args):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        async def stream():
            yield 'data: {"type":"done","status":"ok"}\n\n'
        return StreamingResponse(stream(), media_type='text/event-stream')

    # C3 requires a durable reservation before invoking provider work. A None
    # factory now correctly fails closed, so this HTTP test uses its isolated DB.
    monkeypatch.setattr(router, '_generate_copilot_stream', slow_generation)
    monkeypatch.setattr('core.database.get_session_factory', lambda: test_session_factory)
    token = await _admin_token(test_session_factory)
    headers = auth_header(token)
    first = asyncio.create_task(client.post('/api/v1/ai/copilot/chat/stream', json={'message': 'hi', 'request_id': 'dup-http'}, headers=headers))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        second = await client.post('/api/v1/ai/copilot/chat/stream', json={'message': 'hi', 'request_id': 'dup-http'}, headers=headers)
    finally:
        release.set()
        response = await asyncio.wait_for(first, 3)
    assert second.status_code == 409
    assert second.json()['detail']['code'] == 'request_in_progress'
    assert response.status_code == 200
    replay = await client.post('/api/v1/ai/copilot/chat/stream', json={'message': 'hi', 'request_id': 'dup-http'}, headers=headers)
    assert replay.status_code == 200 and calls == 1
    await response.aclose()


@pytest.mark.asyncio
async def test_report_init_failure_saves_failed_attempt_and_keeps_v1(client, test_session_factory, monkeypatch):
    from modules.training import router

    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token)
    sid = await _session(client, token, lab_id)
    monkeypatch.setattr(router, '_get_knowledge_service', lambda: SimpleNamespace(search=AsyncMock(return_value=[])))
    good = SimpleNamespace(model_name='review-model', generate_report=AsyncMock(return_value={'title': 'old', 'report_text': 'old body'}))
    monkeypatch.setattr(router, '_get_ai_service', AsyncMock(return_value=good))
    first = await client.post(f'/api/v1/training/sessions/{sid}/report/generate', json={}, headers=auth_header(token))
    assert first.status_code == 200
    async with test_session_factory() as db:
        original = (await db.execute(select(TrainingReport).where(TrainingReport.session_id == sid))).scalars().one()
        original_snapshot = (original.version, original.report_text, original.input_hash, original.created_at)

    monkeypatch.setattr(router, '_get_ai_service', AsyncMock(side_effect=RuntimeError('controlled provider initialization failure')))
    failed = await client.post(f'/api/v1/training/sessions/{sid}/report/generate', json={'regenerate': True}, headers=auth_header(token))
    assert failed.status_code == 502
    assert '模型服务初始化失败' in failed.json()['detail']
    async with test_session_factory() as db:
        rows = (await db.execute(select(TrainingReport).where(TrainingReport.session_id == sid).order_by(TrainingReport.version))).scalars().all()
        assert [(row.version, row.status) for row in rows] == [(1, 'ready'), (2, 'failed')]
        assert rows[1].model == 'unknown'
        assert rows[1].input_summary['failure_stage'] == 'provider_init'
        assert (rows[0].version, rows[0].report_text, rows[0].input_hash, rows[0].created_at) == original_snapshot

    monkeypatch.setattr(router, '_get_ai_service', AsyncMock(return_value=good))
    retry = await client.post(f'/api/v1/training/sessions/{sid}/report/generate', json={'regenerate': True}, headers=auth_header(token))
    assert retry.status_code == 200
    async with test_session_factory() as db:
        rows = (await db.execute(select(TrainingReport).where(TrainingReport.session_id == sid).order_by(TrainingReport.version))).scalars().all()
        assert [(row.version, row.status) for row in rows] == [(1, 'ready'), (2, 'failed'), (3, 'ready')]


@pytest.mark.asyncio
async def test_provider_init_failure_stream_is_unavailable_not_blocked(client, monkeypatch, test_session_factory):
    from modules.ai_text import router
    from modules.ai_text.schemas import CopilotChatRequest

    monkeypatch.setattr(router, '_retrieve', AsyncMock(return_value=[]))
    monkeypatch.setattr('core.database.get_session_factory', lambda: test_session_factory)
    fail = AsyncMock(side_effect=RuntimeError('controlled unavailable provider'))
    monkeypatch.setattr(router.SystemService, 'build_llm_provider', fail)
    token = await _admin_token(test_session_factory)
    response = await client.post(
        '/api/v1/ai/copilot/chat/stream',
        json={'message': 'Explain a route', 'request_id': 'afix2-provider-error'}, headers=auth_header(token),
    )
    assert response.status_code == 200
    events = [json.loads(frame[6:]) for frame in response.text.splitlines() if frame.startswith('data: ')]
    assert any(event.get('code') == 'provider_unavailable' for event in events)
    assert any(event.get('status') == 'failed' for event in events)
    assert not any(event.get('status') == 'blocked_environment' for event in events)
    assert fail.await_count == 1


@pytest.mark.asyncio
async def test_blocked_environment_still_short_circuits_provider_failure(client, test_session_factory, monkeypatch):
    from modules.ai_text import router
    from modules.ai_text.schemas import CopilotChatRequest

    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token)
    sid = await _session(client, token, lab_id)
    async with test_session_factory() as db:
        assert (await db.get(TrainingSession, sid)) is not None
    monkeypatch.setattr(router, '_retrieve', AsyncMock(return_value=[]))

    blocked_policy = {
        'lab_scoped': True, 'allow_draft': False, 'allow_model': False,
        'reason': '当前实验没有可信的环境绑定信息，不能生成现场可执行配置。',
        'note': '', 'safe_text': '环境未核验，已停止生成现场配置。只读核对：display ospf peer',
        'content_warning': '',
    }
    monkeypatch.setattr(router, '_lab_draft_policy', AsyncMock(return_value=blocked_policy))
    monkeypatch.setattr('core.database.get_session_factory', lambda: test_session_factory)
    provider = AsyncMock(side_effect=RuntimeError('must not be called'))
    monkeypatch.setattr(router.SystemService, 'build_llm_provider', provider)
    response = await client.post(
        '/api/v1/ai/copilot/chat/stream',
        json={'message': 'give config', 'request_id': 'afix2-blocked', 'lab_id': lab_id, 'lab_session_id': sid},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    events = [json.loads(frame[6:]) for frame in response.text.splitlines() if frame.startswith('data: ')]
    assert any(event.get('type') == 'token' for event in events)
    assert any(event.get('status') == 'blocked_environment' for event in events)
    assert not any(event.get('code') == 'provider_unavailable' for event in events)
    provider.assert_not_awaited()
