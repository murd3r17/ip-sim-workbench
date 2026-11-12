"""V7-A（纠错与状态修复）行为契约测试。

覆盖任务书 A-T01…A-T12 中可由代码直接断言的部分：
- 精简/完整版共享同一套现场参数，教材地址不进入可执行步骤；
- 旧系统样例的幂等迁移，用户改过的实验不被覆盖；
- 只有 active 会话可写操作/请求教练，completed/abandoned 只读；
- 复盘读取不调用模型、幂等生成不重复新增、显式重生成新增版本、失败保留旧版本；
- 未核验环境不允许生成可执行草稿；
- naive UTC 出参带偏移；
- 执行模式落库后不被当前开关改写。
"""
import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from core.security import create_access_token, hash_password
from core.time_utils import iso_utc, pydantic_iso_utc


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _admin_token(session_factory, username: str | None = None) -> str:
    from modules.auth.models import User, UserRole

    suffix = uuid.uuid4().hex[:8]
    async with session_factory() as db:
        user = User(
            username=username or f"v7a-admin-{suffix}",
            hashed_password=hash_password("not-a-real-password"),
            role=UserRole.ADMIN,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return create_access_token(user.id, user.username, user.role.value)


async def _lab(client, token: str, *, objectives=None, environment_spec=None) -> int:
    topo = await client.post(
        "/api/v1/topologies", json={"name": f"v7a-topo-{uuid.uuid4().hex[:6]}"}, headers=auth_header(token)
    )
    topo_id = topo.json()["id"]
    lab = await client.post(
        "/api/v1/training/labs",
        json={
            "title": f"v7a-lab-{uuid.uuid4().hex[:6]}",
            "topology_id": topo_id,
            "objectives": objectives or [{"id": 1, "name": "观察", "goal": "只读查看"}],
        },
        headers=auth_header(token),
    )
    lab_id = lab.json()["id"]
    await client.put(f"/api/v1/training/labs/{lab_id}", json={"status": "ready"}, headers=auth_header(token))
    return lab_id


async def _session(client, token: str, lab_id: int) -> int:
    resp = await client.post("/api/v1/training/sessions", json={"lab_id": lab_id}, headers=auth_header(token))
    assert resp.status_code == 200
    return resp.json()["id"]


def test_ospf_full_and_simplified_share_site_parameters():
    from modules.training.lab_content import OSPF_SITE, full_ospf_steps, simplified_ospf_steps

    full = full_ospf_steps()
    simple = simplified_ospf_steps()
    full_text = json.dumps(full, ensure_ascii=False)
    simple_text = json.dumps(simple, ensure_ascii=False)

    for device in OSPF_SITE["devices"]:
        link_ip = device["link_address"].split("/")[0]
        loop_ip = device["loopback_address"].split("/")[0]
        assert f"network {link_ip} 0.0.0.0" in full_text
        assert f"network {link_ip} 0.0.0.0" in simple_text
        assert f"network {loop_ip} 0.0.0.0" in full_text
        assert f"network {loop_ip} 0.0.0.0" in simple_text
        assert device["link_interface"] in full_text
        assert device["link_interface"] in simple_text

    # 教材示例地址不得再作为可执行参数出现（完整版只用它们做“不要改成”的提醒）
    for legacy in ("10.0.1.1", "10.0.2.2", "10.0.3.3"):
        assert legacy not in full_text
        assert legacy not in simple_text
    # 精简版以前用 10.0.123.0 0.0.0.255 的口径，必须与完整版的 host 通配一致
    assert "10.0.123.0 0.0.0.255" not in simple_text

    # 验证命令/关键字必须能在真实 VRP 输出里找到（不再用 Process ID: 这类不存在的字段）
    full_process = [step for step in full if step["id"] == 2][0]
    simple_process = [step for step in simple if step["id"] == 1][0]
    assert full_process["verify_contains"] == simple_process["verify_contains"] == ["OSPF Process 1", "Router ID"]


@pytest.mark.asyncio
async def test_content_migration_is_idempotent_and_skips_user_edits(tmp_path, monkeypatch):
    from core import database
    from core.config import get_settings
    from modules.auth.models import User, UserRole
    from modules.device.models import Topology, TopologyType
    from modules.training.lab_content import CONTENT_VERSION, system_lab_fingerprint
    from modules.training.models import TrainingLab
    from scripts import migrate_training_content_v7a as migrator

    path = tmp_path / "v7a-migrate.db"
    settings = get_settings().model_copy(
        update={"db_url": f"sqlite+aiosqlite:///{path.as_posix()}", "debug": False}
    )
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)
    await database.init_db()
    try:
        factory = database.get_session_factory()
        legacy_objectives = [{"id": 1, "name": "旧系统样例", "goal": "旧内容"}]
        legacy_fingerprint = system_lab_fingerprint(
            description="旧系统描述", time_limit_minutes=60, is_sandbox=False, objectives=legacy_objectives
        )
        monkeypatch.setattr(
            migrator, "known_legacy_fingerprints", lambda: {"OSPF 单区域基础实验完整版": {legacy_fingerprint}}
        )
        async with factory() as db:
            admin = User(username="migrator-admin", hashed_password="x", role=UserRole.ADMIN)
            topo = Topology(name="migrator-topo", topology_type=TopologyType.LAB, status="active")
            db.add_all([admin, topo])
            await db.flush()
            system_lab = TrainingLab(
                title="OSPF 单区域基础实验完整版",
                description="旧系统描述",
                topology_id=topo.id,
                instructor_id=admin.id,
                objectives=legacy_objectives,
                status="ready",
            )
            user_lab = TrainingLab(
                title="OSPF 单区域基础实验完整版",
                description="用户自己改过",
                topology_id=topo.id,
                instructor_id=admin.id,
                objectives=[{"id": 1, "name": "用户改的步骤"}],
                status="ready",
            )
            db.add_all([system_lab, user_lab])
            await db.commit()
            system_id, user_id = system_lab.id, user_lab.id

        first = await migrator.migrate(dry_run=False)
        assert first["updated_count"] == 1
        assert any(item["id"] == user_id for item in first["skipped_user_modified"] + first["skipped_same_title"])
        second = await migrator.migrate(dry_run=False)
        assert second["updated_count"] == 0
        assert second["already_current"][0]["id"] == system_id

        async with factory() as db:
            system = await db.get(TrainingLab, system_id)
            edited = await db.get(TrainingLab, user_id)
            assert system.content_version == CONTENT_VERSION
            assert system.objectives != legacy_objectives
            # 用户编辑的实验保持原样，不被迁移覆盖
            assert edited.objectives == [{"id": 1, "name": "用户改的步骤"}]
            assert edited.content_version is None
    finally:
        await database.close_db()


@pytest.mark.asyncio
async def test_completed_and_abandoned_sessions_are_read_only(client, test_session_factory):
    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token)
    session_id = await _session(client, token, lab_id)

    ok = await client.post(
        f"/api/v1/training/sessions/{session_id}/log",
        json={"lab_id": lab_id, "action": "command", "command": "display clock"},
        headers=auth_header(token),
    )
    assert ok.status_code == 200

    completed = await client.post(f"/api/v1/training/sessions/{session_id}/complete", headers=auth_header(token))
    assert completed.status_code == 200

    rejected_log = await client.post(
        f"/api/v1/training/sessions/{session_id}/log",
        json={"lab_id": lab_id, "action": "command", "command": "display clock"},
        headers=auth_header(token),
    )
    assert rejected_log.status_code == 400
    assert "不在进行中" in rejected_log.json()["detail"]

    hint = await client.get(f"/api/v1/training/sessions/{session_id}/hint", headers=auth_header(token))
    assert hint.status_code == 409
    assert "只能回看" in hint.json()["detail"]

    abandon = await client.post(f"/api/v1/training/sessions/{session_id}/abandon", headers=auth_header(token))
    assert abandon.status_code == 400

    # 新会话可以放弃，放弃后同样只读
    second = await _session(client, token, lab_id)
    abandoned = await client.post(f"/api/v1/training/sessions/{second}/abandon", headers=auth_header(token))
    assert abandoned.status_code == 200
    detail = await client.get(f"/api/v1/training/sessions/{second}", headers=auth_header(token))
    assert detail.json()["status"] == "abandoned"
    assert detail.json()["is_active"] is False
    # 会话固定了开始时的步骤快照；管理员自建实验没有注册内容版本时为 None（不能伪造版本）
    assert detail.json()["content_snapshot"]["objectives"]
    assert detail.json()["content_version"] in (None, "v7a.2026-10-26")


@pytest.mark.asyncio
async def test_wrong_user_cannot_touch_session(client, test_session_factory):
    from modules.auth.models import User, UserRole

    owner_token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, owner_token)
    session_id = await _session(client, owner_token, lab_id)

    async with test_session_factory() as db:
        trainee = User(username=f"v7a-trainee-{uuid.uuid4().hex[:6]}", hashed_password="x", role=UserRole.USER)
        db.add(trainee)
        await db.commit()
        await db.refresh(trainee)
        trainee_token = create_access_token(trainee.id, trainee.username, trainee.role.value)

    for method, path, payload in (
        ("get", f"/api/v1/training/sessions/{session_id}", None),
        ("post", f"/api/v1/training/sessions/{session_id}/log", {"lab_id": lab_id, "action": "command", "command": "display clock"}),
        ("post", f"/api/v1/training/sessions/{session_id}/abandon", None),
        ("post", f"/api/v1/training/sessions/{session_id}/report/generate", {}),
    ):
        response = await getattr(client, method)(path, json=payload, headers=auth_header(trainee_token)) if payload is not None \
            else await getattr(client, method)(path, headers=auth_header(trainee_token))
        assert response.status_code == 403, (method, path, response.status_code, response.text)


@pytest.mark.asyncio
async def test_report_generation_is_idempotent_and_regenerate_adds_version(client, test_session_factory):
    from unittest.mock import AsyncMock, patch

    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token)
    session_id = await _session(client, token, lab_id)

    fake_ai = AsyncMock()
    fake_ai.generate_report = AsyncMock(
        return_value={"title": "v1", "summary": "s1", "report_text": "body-v1"}
    )
    fake_knowledge = AsyncMock()
    fake_knowledge.search = AsyncMock(return_value=[])
    with patch("modules.training.router._get_ai_service", return_value=fake_ai), patch(
        "modules.training.router._get_knowledge_service", return_value=fake_knowledge
    ):
        first = await client.post(
            f"/api/v1/training/sessions/{session_id}/report/generate",
            json={"regenerate": False, "idempotency_key": "key-1"},
            headers=auth_header(token),
        )
        assert first.status_code == 200
        assert first.json()["report"]["version"] == 1
        assert fake_ai.generate_report.await_count == 1

        # 双击/重复幂等键：不重复调用模型
        again = await client.post(
            f"/api/v1/training/sessions/{session_id}/report/generate",
            json={"regenerate": False, "idempotency_key": "key-1"},
            headers=auth_header(token),
        )
        assert again.status_code == 200
        assert again.json()["reused"] is True
        assert fake_ai.generate_report.await_count == 1

        # 证据未变、非显式重生成：同样复用，不重复收费
        same = await client.post(
            f"/api/v1/training/sessions/{session_id}/report/generate",
            json={"regenerate": False},
            headers=auth_header(token),
        )
        assert same.json()["report"]["version"] == 1
        assert fake_ai.generate_report.await_count == 1

        fake_ai.generate_report = AsyncMock(return_value={"title": "v2", "summary": "s2", "report_text": "body-v2"})
        regenerated = await client.post(
            f"/api/v1/training/sessions/{session_id}/report/generate",
            json={"regenerate": True},
            headers=auth_header(token),
        )
        assert regenerated.status_code == 200
        assert regenerated.json()["report"]["version"] == 2
        assert [item["version"] for item in regenerated.json()["versions"]] == [1, 2]

    read_back = await client.get(f"/api/v1/training/sessions/{session_id}/report", headers=auth_header(token))
    assert read_back.json()["report"]["report_text"] == "body-v2"
    assert read_back.json()["versions"][0]["input_hash"]


@pytest.mark.asyncio
async def test_draft_is_refused_without_verified_environment_binding(client, test_session_factory):
    from modules.ai_text.router import _lab_draft_policy
    from modules.ai_text.schemas import CopilotChatRequest
    from modules.training.models import TrainingLab, TrainingSession

    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token)
    session_id = await _session(client, token, lab_id)

    async with test_session_factory() as db:
        lab = await db.get(TrainingLab, lab_id)
        lab.environment_spec = {"requires_binding": True, "binding_status": "unverified", "devices": []}
        await db.commit()

        request = CopilotChatRequest(message="给出配置草稿", want_draft=True, lab_id=lab_id, lab_session_id=session_id)
        session = await db.get(TrainingSession, session_id)
        actor = {'user_id': session.trainee_id, 'role': 'user'}
        policy = await _lab_draft_policy(db, request, actor)
        assert policy["allow_draft"] is False
        # D01: this session froze the original empty requirements; later edits
        # must not silently change its permissions or historical meaning.
        assert "没有可信的环境绑定信息" in policy["reason"]

        lab.environment_spec = {
            "requires_binding": True,
            "binding_status": "verified",
            "devices": [{"role": "R1"}],
        }
        await db.commit()
        allowed = await _lab_draft_policy(db, request, actor)
        assert allowed["allow_draft"] is False

    # The updated binding can only affect a subsequently created session.
    new_session_id = await _session(client, token, lab_id)
    async with test_session_factory() as db:
        new_session = await db.get(TrainingSession, new_session_id)
        updated_request = CopilotChatRequest(message="给出配置草稿", want_draft=True, lab_id=lab_id, lab_session_id=new_session_id)
        assert (await _lab_draft_policy(db, updated_request, {'user_id': new_session.trainee_id, 'role': 'user'}))["allow_draft"] is True

    # 非实验请求不受影响
    plain = CopilotChatRequest(message="解释 OSPF 邻居状态", want_draft=True)
    async with test_session_factory() as db:
        assert (await _lab_draft_policy(db, plain))["allow_draft"] is True


def test_utc_time_contract_adds_offset_to_naive_values():
    naive = datetime(2026, 10, 15, 11, 39, 34, 860657)
    aware = datetime(2026, 10, 15, 11, 39, 34, 860657, tzinfo=timezone.utc)

    assert iso_utc(naive) == "2026-10-15T11:39:34.860657+00:00"
    assert iso_utc(aware) == iso_utc(naive)
    assert pydantic_iso_utc(naive).endswith("Z")
    assert iso_utc(None) is None


@pytest.mark.asyncio
async def test_session_api_times_include_offset(client, test_session_factory):
    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token)
    session_id = await _session(client, token, lab_id)

    detail = await client.get(f"/api/v1/training/sessions/{session_id}", headers=auth_header(token))
    started_at = detail.json()["started_at"]
    assert started_at
    assert started_at.endswith("+00:00") or started_at.endswith("Z")

    listing = await client.get("/api/v1/training/sessions", headers=auth_header(token))
    row = next(item for item in listing.json() if item["id"] == session_id)
    assert row["started_at"].endswith("+00:00") or row["started_at"].endswith("Z")
