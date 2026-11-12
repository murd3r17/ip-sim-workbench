"""V7-A A-fix AF-05/AF-06/AF-07：迁移保护、快照溯源、并发与恢复。"""
import asyncio
import json
import shutil
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import Base
from core.security import create_access_token, hash_password
from modules.training.lab_content import CONTENT_VERSION, system_lab_fingerprint
from modules.training.models import TrainingLab, TrainingReport, TrainingSession
from tests.test_training.test_v7a_state_and_reports import _admin_token, _lab, _session, auth_header


async def _engine_factory(tmp_path, name="afix.db"):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / name).as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed_lab(factory, *, title, description, objectives, time_limit=60):
    from modules.auth.models import User, UserRole
    from modules.device.models import Topology, TopologyType

    async with factory() as db:
        suffix = uuid.uuid4().hex[:8]
        owner = User(username=f"afix-{suffix}", hashed_password="x", role=UserRole.ADMIN)
        topo = Topology(name=f"afix-topo-{suffix}", topology_type=TopologyType.LAB, status="active")
        db.add_all([owner, topo])
        await db.flush()
        lab = TrainingLab(
            title=title, description=description, topology_id=topo.id, instructor_id=owner.id,
            objectives=objectives, time_limit_minutes=time_limit, status="ready",
        )
        db.add(lab)
        await db.commit()
        return lab.id


@pytest.mark.asyncio
async def test_migration_requires_whole_row_match_and_is_idempotent(tmp_path, monkeypatch):
    from scripts import migrate_training_content_v7a as migrator

    engine, factory = await _engine_factory(tmp_path)
    monkeypatch.setattr(migrator, "init_db", AsyncMock(return_value=(engine, factory)))
    monkeypatch.setattr(migrator, "close_db", AsyncMock())
    monkeypatch.setattr(migrator, "get_session_factory", lambda: factory)
    legacy_objectives = [{"id": 1, "name": "old"}]
    fingerprint = system_lab_fingerprint(
        description="旧描述", time_limit_minutes=60, is_sandbox=False, objectives=legacy_objectives
    )
    monkeypatch.setattr(migrator, "known_legacy_fingerprints", lambda: {"OSPF 单区域基础实验完整版": {fingerprint}})

    clean_id = await _seed_lab(
        factory, title="OSPF 单区域基础实验完整版", description="旧描述", objectives=legacy_objectives
    )
    edited_id = await _seed_lab(
        factory, title="OSPF 单区域基础实验完整版", description="USER_EDITED_DESCRIPTION",
        objectives=legacy_objectives, time_limit=77,
    )
    dry = await migrator.migrate(True)
    assert dry["updated_count"] == 1
    async with factory() as db:
        assert (await db.get(TrainingLab, clean_id)).content_version is None

    first = await migrator.migrate(False)
    assert first["updated_count"] == 1
    assert any(item["id"] == edited_id for item in first["skipped_user_modified"] + first["skipped_same_title"])
    assert any("description" in item.get("differences_from_target", []) for item in first["skipped_user_modified"] + first["skipped_same_title"])
    async with factory() as db:
        clean = await db.get(TrainingLab, clean_id)
        edited = await db.get(TrainingLab, edited_id)
        assert clean.content_version == CONTENT_VERSION
        assert clean.objectives != legacy_objectives
        assert edited.description == "USER_EDITED_DESCRIPTION"
        assert edited.time_limit_minutes == 77
        assert edited.content_version is None

    second = await migrator.migrate(False)
    assert second["updated_count"] == 0
    assert second["already_current"][0]["id"] == clean_id
    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_failure_rolls_back_and_backup_can_be_restored(tmp_path, monkeypatch):
    from scripts import migrate_training_content_v7a as migrator

    engine, factory = await _engine_factory(tmp_path, "recovery.db")
    db_path = tmp_path / "recovery.db"
    pre_copy = tmp_path / "pre-migration.db"
    monkeypatch.setattr(migrator, "init_db", AsyncMock(return_value=(engine, factory)))
    monkeypatch.setattr(migrator, "close_db", AsyncMock())
    monkeypatch.setattr(migrator, "get_session_factory", lambda: factory)
    legacy_objectives = [{"id": 1, "name": "old"}]
    fingerprint = system_lab_fingerprint(
        description="旧描述", time_limit_minutes=60, is_sandbox=False, objectives=legacy_objectives
    )
    monkeypatch.setattr(migrator, "known_legacy_fingerprints", lambda: {"OSPF 单区域基础实验完整版": {fingerprint}})
    first_id = await _seed_lab(factory, title="OSPF 单区域基础实验完整版", description="旧描述", objectives=legacy_objectives)
    await _seed_lab(factory, title="OSPF 单区域基础实验精简版", description="旧描述", objectives=legacy_objectives)
    # 精简版也用同一指纹，确保失败发生在第二条更新之后
    monkeypatch.setattr(
        migrator, "known_legacy_fingerprints",
        lambda: {"OSPF 单区域基础实验完整版": {fingerprint}, "OSPF 单区域基础实验精简版": {fingerprint}},
    )
    shutil.copy2(db_path, pre_copy)  # 迁移前真实备份
    backup = tmp_path / "backup.json"
    result = await migrator.migrate(False, backup_path=str(backup), fail_after=1)
    assert result["failure"]["rolled_back"] is True
    assert result["updated"] == []
    assert len(json.loads(backup.read_text(encoding="utf-8"))["rows"]) >= 2
    async with factory() as db:
        assert (await db.get(TrainingLab, first_id)).content_version is None

    restored_path = tmp_path / "restored.db"
    shutil.copy2(pre_copy, restored_path)
    restore_engine = create_async_engine(f"sqlite+aiosqlite:///{restored_path.as_posix()}")
    restore_factory = async_sessionmaker(restore_engine, expire_on_commit=False)
    async with restore_factory() as db:
        restored = (await db.execute(select(TrainingLab))).scalars().all()
        assert restored and all(lab.content_version is None for lab in restored)
    await restore_engine.dispose()
    await engine.dispose()


@pytest.mark.asyncio
async def test_report_uses_session_snapshot_and_records_model_provenance(client, test_session_factory, monkeypatch):
    from modules.training import router

    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token, objectives=[{"id": 1, "name": "ORIGINAL_SESSION_OBJECTIVE"}])
    sid = await _session(client, token, lab_id)
    async with test_session_factory() as db:
        lab = await db.get(TrainingLab, lab_id)
        lab.objectives = [{"id": 1, "name": "LATER_EDITED_OBJECTIVE"}]
        await db.commit()
    ai = SimpleNamespace(
        model_name="provider-model-x",
        generate_report=AsyncMock(return_value={"title": "review", "report_text": "review body"}),
    )
    monkeypatch.setattr(router, "_get_ai_service", AsyncMock(return_value=ai))
    monkeypatch.setattr(router, "_get_knowledge_service", lambda: SimpleNamespace(search=AsyncMock(return_value=[])))
    response = await client.post(
        f"/api/v1/training/sessions/{sid}/report/generate", json={}, headers=auth_header(token)
    )
    assert response.status_code == 200
    prompt = ai.generate_report.call_args.kwargs["source_text"]
    assert "ORIGINAL_SESSION_OBJECTIVE" in prompt
    assert "LATER_EDITED_OBJECTIVE" not in prompt
    async with test_session_factory() as db:
        rows = (await db.execute(select(TrainingReport).where(TrainingReport.session_id == sid))).scalars().all()
        assert len(rows) == 1
        assert rows[0].model == "provider-model-x"
        assert rows[0].input_summary["content_source"] == "session_snapshot"


@pytest.mark.asyncio
async def test_hint_uses_snapshot_and_verified_environment(client, test_session_factory, monkeypatch):
    from modules.training import router

    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token, objectives=[{"id": 1, "name": "ORIGINAL_SESSION_OBJECTIVE"}])
    async with test_session_factory() as db:
        lab = await db.get(TrainingLab, lab_id)
        lab.environment_spec = {"requires_binding": True, "binding_status": "verified", "devices": [{"role": "R1"}]}
        await db.commit()
    sid = await _session(client, token, lab_id)
    async with test_session_factory() as db:
        lab = await db.get(TrainingLab, lab_id)
        lab.objectives = [{"id": 1, "name": "LATER_EDITED_OBJECTIVE"}]
        await db.commit()
    ai = SimpleNamespace(
        model_name="provider-model-x",
        coach_training=AsyncMock(return_value={"summary": "ok", "next_steps": ["核对接口"], "coach_text": "coach"}),
    )
    monkeypatch.setattr(router, "_get_ai_service", AsyncMock(return_value=ai))
    monkeypatch.setattr(router, "_get_knowledge_service", lambda: SimpleNamespace(search=AsyncMock(return_value=[])))
    response = await client.get(f"/api/v1/training/sessions/{sid}/hint", headers=auth_header(token))
    assert response.status_code == 200
    data = response.json()
    scenario = ai.coach_training.call_args.kwargs["scenario"]
    assert "ORIGINAL_SESSION_OBJECTIVE" in scenario
    assert "LATER_EDITED_OBJECTIVE" not in scenario
    assert data["config_blocked"] is False
    assert data["content_source"] == "session_snapshot"


@pytest.mark.asyncio
async def test_legacy_session_without_snapshot_is_marked_unknown(client, test_session_factory, monkeypatch):
    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token, objectives=[{"id": 1, "name": "CURRENT_LAB_OBJECTIVE"}])
    sid = await _session(client, token, lab_id)
    async with test_session_factory() as db:
        session = await db.get(TrainingSession, sid)
        session.content_snapshot = None
        lab = await db.get(TrainingLab, lab_id)
        lab.content_version = CONTENT_VERSION
        await db.commit()
    detail = await client.get(f"/api/v1/training/sessions/{sid}", headers=auth_header(token))
    assert detail.json()["content_source"] == "legacy_unknown"
    assert "无法证明" in detail.json()["content_warning"]
    hint = await client.get(f"/api/v1/training/sessions/{sid}/hint", headers=auth_header(token))
    assert hint.json()["config_blocked"] is True
    assert "CURRENT_LAB_OBJECTIVE" not in hint.json()["coach_text"]


@pytest.mark.asyncio
async def test_mode_facts_reflect_settings_and_snapshot(client, test_session_factory, monkeypatch):
    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token)
    from modules.training import mode_facts as facts_module

    monkeypatch.setattr(
        facts_module, "get_settings",
        lambda: SimpleNamespace(device_mode="sim", deploy_simulate_only=True),
    )
    listing = await client.get("/api/v1/training/labs", headers=auth_header(token))
    row = next(item for item in listing.json() if item["id"] == lab_id)
    assert row["mode_facts"]["device_mode"] == "sim"
    assert row["mode_facts"]["deploy_mode"] == "simulated"
    sid = await _session(client, token, lab_id)

    monkeypatch.setattr(
        facts_module, "get_settings",
        lambda: SimpleNamespace(device_mode="ssh", deploy_simulate_only=True),
    )
    detail = await client.get(f"/api/v1/training/sessions/{sid}", headers=auth_header(token))
    facts = detail.json()["mode_facts"]
    # 会话快照固定开始时的模拟事实，不随当前设置翻转
    assert detail.json()["mode_source"] == "session_snapshot"
    assert facts["device_mode"] == "sim"
    assert facts["webssh_write_risk"] == "none"

    new_list = await client.get("/api/v1/training/labs", headers=auth_header(token))
    new_row = next(item for item in new_list.json() if item["id"] == lab_id)
    assert new_row["mode_facts"]["device_mode"] == "ssh"
    assert new_row["mode_facts"]["deploy_mode"] == "simulated"
    assert new_row["mode_facts"]["webssh_write_risk"] == "possible"
    assert "WebSSH" in new_row["mode_facts"]["summary"]

    monkeypatch.setattr(
        facts_module, "get_settings",
        lambda: SimpleNamespace(device_mode="ssh", deploy_simulate_only=False),
    )
    real_list = await client.get("/api/v1/training/labs", headers=auth_header(token))
    real_row = next(item for item in real_list.json() if item["id"] == lab_id)
    assert real_row["mode_facts"]["deploy_mode"] == "real"
    assert "真实下发" in real_row["mode_facts"]["summary"]


@pytest.mark.asyncio
async def test_historical_session_without_mode_snapshot_is_unknown(client, test_session_factory, monkeypatch):
    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token)
    sid = await _session(client, token, lab_id)
    async with test_session_factory() as db:
        session = await db.get(TrainingSession, sid)
        session.mode_snapshot = None
        await db.commit()
    detail = await client.get(f"/api/v1/training/sessions/{sid}", headers=auth_header(token))
    assert detail.json()["mode_source"] == "unknown_history"
    assert detail.json()["mode_facts"]["device_mode"] == "unknown"
    assert detail.json()["mode_facts"]["webssh_write_risk"] == "unknown"


@pytest.mark.asyncio
async def test_concurrent_report_generation_uses_one_model_call_for_same_key(client, test_session_factory, monkeypatch):
    from modules.training import router

    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token)
    sid = await _session(client, token, lab_id)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def slow_report(**kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return {"title": "t", "summary": "s", "report_text": f"body-{calls}"}

    ai = SimpleNamespace(model_name="provider-model-x", generate_report=slow_report)
    monkeypatch.setattr(router, "_get_ai_service", AsyncMock(return_value=ai))
    monkeypatch.setattr(router, "_get_knowledge_service", lambda: SimpleNamespace(search=AsyncMock(return_value=[])))

    first = asyncio.create_task(client.post(
        f"/api/v1/training/sessions/{sid}/report/generate",
        json={"idempotency_key": "same-key"}, headers=auth_header(token),
    ))
    await asyncio.wait_for(entered.wait(), 2)
    second = asyncio.create_task(client.post(
        f"/api/v1/training/sessions/{sid}/report/generate",
        json={"idempotency_key": "same-key"}, headers=auth_header(token),
    ))
    await asyncio.sleep(0.05)
    release.set()
    responses = await asyncio.gather(first, second)
    assert all(r.status_code == 200 for r in responses)
    versions = [r.json()["report"]["version"] for r in responses]
    assert versions[0] == 1
    assert calls == 1
    async with test_session_factory() as db:
        rows = (await db.execute(select(TrainingReport).where(TrainingReport.session_id == sid))).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_generation_survives_session_completed_and_new_session(client, test_session_factory, monkeypatch):
    from modules.training import router

    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token)
    first_sid = await _session(client, token, lab_id)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def slow_report(**kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return {"title": "t", "summary": "s", "report_text": "late body"}

    ai = SimpleNamespace(model_name="provider-model-x", generate_report=slow_report)
    monkeypatch.setattr(router, "_get_ai_service", AsyncMock(return_value=ai))
    monkeypatch.setattr(router, "_get_knowledge_service", lambda: SimpleNamespace(search=AsyncMock(return_value=[])))

    task = asyncio.create_task(client.post(
        f"/api/v1/training/sessions/{first_sid}/report/generate", json={}, headers=auth_header(token)
    ))
    await asyncio.wait_for(entered.wait(), 2)
    # 生成过程中结束原会话并新开另一个会话
    await client.post(f"/api/v1/training/sessions/{first_sid}/complete", headers=auth_header(token))
    second_sid = await _session(client, token, lab_id)
    release.set()
    response = await task
    assert response.status_code == 200
    assert response.json()["session_id"] == first_sid
    async with test_session_factory() as db:
        first_rows = (await db.execute(select(TrainingReport).where(TrainingReport.session_id == first_sid))).scalars().all()
        second_rows = (await db.execute(select(TrainingReport).where(TrainingReport.session_id == second_sid))).scalars().all()
        assert len(first_rows) == 1
        assert second_rows == []
        assert first_rows[0].report_text == "late body"
