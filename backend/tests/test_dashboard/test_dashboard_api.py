"""首页运维指挥中心聚合接口测试。"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, update, text

from core.security import create_access_token
from modules.auth.models import AuditLog, User, UserRole
from modules.deploy.models import ChangeLevel, DeployStatus, DeployTask
from modules.device.models import (
    Device,
    DeviceStatus,
    DeviceType,
    DeviceVendor,
    Topology,
    TopologyLink,
    TopologyType,
)
from modules.monitor.models import Alarm, AlarmStatus
from modules.system.models import BackgroundTask, SystemConfig, TaskStatus
from modules.dashboard.service import DashboardService


@pytest.mark.asyncio
async def test_dashboard_sorts_mixed_persisted_timezones_without_changing_history(test_session_factory):
    async with test_session_factory() as db:
        user=User(username='d09-zone-admin',hashed_password='unused',role=UserRole.ADMIN)
        topology=Topology(name='d09-zone',topology_type=TopologyType.MAIN,status='active')
        db.add_all([user,topology]);await db.flush()
        device=Device(hostname='d09-zone-R1',mgmt_ip='198.51.100.29',device_type=DeviceType.ROUTER,vendor=DeviceVendor.HUAWEI,topology_id=topology.id)
        db.add(device);await db.flush()
        deploys=[DeployTask(device_id=device.id,operator_id=user.id,config_content='description D09-TZ',status=DeployStatus.PENDING,created_at=datetime(2026,11,7,10,m)) for m in [0,30,45]]
        db.add_all(deploys);await db.flush();deploy_ids=[row.id for row in deploys]
        await db.execute(text('UPDATE deploy_task SET created_at=:stamp WHERE id=:id'),{'stamp':'2026-11-07 18:30:00+08:00','id':deploy_ids[1]})
        await db.execute(text('UPDATE deploy_task SET created_at=:stamp WHERE id=:id'),{'stamp':'2026-11-07 10:45:00+00:00','id':deploy_ids[2]})
        rows=[BackgroundTask(task_type='d09-time',task_name=name,status=TaskStatus.PENDING,created_at=datetime(2026,11,7,10,minute)) for name,minute in [('older-naive',0),('newer-offset',30),('newest-utc',45)]]
        db.add_all(rows);await db.flush()
        await db.execute(text('UPDATE background_task SET created_at=:stamp WHERE id=:id'),{'stamp':'2026-11-07 18:30:00+08:00','id':rows[1].id})
        await db.execute(text('UPDATE background_task SET created_at=:stamp WHERE id=:id'),{'stamp':'2026-11-07 10:45:00+00:00','id':rows[2].id})
        await db.commit()
    async with test_session_factory() as db:
        summary=await DashboardService.get_summary(db)
        names=[x['name'] for x in summary['tasks']['items'] if x['kind']=='d09-time']
        assert names==['newest-utc','newer-offset','older-naive']
        assert [x['id'] for x in summary['approvals']]==deploy_ids
        persisted=(await db.execute(text('SELECT created_at FROM background_task WHERE task_name=:name'),{'name':'newer-offset'})).scalar()
        assert persisted=='2026-11-07 18:30:00+08:00'


@pytest.mark.asyncio
async def test_dashboard_requires_authentication(client):
    response = await client.get("/api/v1/dashboard/summary")

    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_dashboard_summary_aggregates_operational_state(
    client, test_session_factory
):
    now = datetime.now(timezone.utc)
    async with test_session_factory() as db:
        await db.execute(update(Topology).values(status="inactive"))
        user = User(
            username="dashboard-admin",
            hashed_password="not-used-by-dashboard-tests",
            display_name="Dashboard Admin",
            role=UserRole.ADMIN,
        )
        db.add(user)
        await db.flush()

        topology = Topology(
            name="Dashboard Test Topology",
            topology_type=TopologyType.MAIN,
            status="active",
        )
        db.add(topology)
        await db.flush()

        online = Device(
            hostname="dashboard-online",
            mgmt_ip="198.51.100.10",
            device_type=DeviceType.ROUTER,
            vendor=DeviceVendor.HUAWEI,
            status=DeviceStatus.ONLINE,
            topology_id=topology.id,
            network_role="core",
        )
        offline = Device(
            hostname="dashboard-offline",
            mgmt_ip="198.51.100.11",
            device_type=DeviceType.SWITCH_L3,
            vendor=DeviceVendor.HUAWEI,
            status=DeviceStatus.OFFLINE,
            topology_id=topology.id,
            network_role="access",
        )
        db.add_all([online, offline])
        await db.flush()

        db.add_all([
            TopologyLink(
                topology_id=topology.id,
                source_device_id=online.id,
                source_interface="GE0/0/1",
                target_device_id=offline.id,
                target_interface="GE0/0/1",
                status="down",
            ),
            DeployTask(
                device_id=offline.id,
                config_content="interface GE0/0/1",
                status=DeployStatus.PENDING,
                change_level=ChangeLevel.HIGH_RISK,
                operator_id=user.id,
                verify_diff="interface GE0/0/1: expected up, actual down",
                created_at=now,
            ),
            BackgroundTask(
                task_type="inspection",
                task_name="Dashboard inspection task",
                status=TaskStatus.RUNNING,
                progress=50,
                created_at=now,
            ),
            BackgroundTask(
                task_type="ai",
                task_name="Dashboard AI task",
                status=TaskStatus.PENDING,
                created_at=now,
            ),
            Alarm(
                device_id=offline.id,
                alarm_type="device_offline",
                severity="critical",
                message="Dashboard test alarm",
                status=AlarmStatus.FIRED,
                fired_at=now,
            ),
            AuditLog(
                user_id=user.id,
                username=user.username,
                module="device",
                action="health_check",
                resource_type="device",
                resource_id=str(offline.id),
                result="success",
                created_at=now,
            ),
        ])
        await db.commit()

    token = create_access_token(user.id, user.username, user.role.value)
    response = await client.get(
        "/api/v1/dashboard/summary",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["devices"]["total"] >= 2
    assert data["devices"]["online"] >= 1
    assert data["devices"]["ssh_reachable"] == data["devices"]["online"]
    assert data["devices"]["offline"] >= 1
    assert data["topology"]["name"] == "Dashboard Test Topology"
    assert data["topology"]["device_count"] == 2
    assert data["topology"]["link_count"] == 1
    assert {node["hostname"] for node in data["topology"]["nodes"]} == {
        "dashboard-online",
        "dashboard-offline",
    }
    assert data["tasks"]["pending"] >= 1
    task_kinds = {item["kind"] for item in data["tasks"]["items"]}
    assert {"deploy", "inspection", "ai"} <= task_kinds
    assert data["tasks"]["with_diff"] >= 1
    assert any(
        item["kind"] == "deploy" and item["has_diff"]
        for item in data["tasks"]["items"]
    )
    assert data["alarms"]["active"] >= 1
    assert data["alarms"]["items"][0]["device_name"] == "dashboard-offline"
    assert data["risks"]["pending_approval"] >= 1
    assert all(item["recommendation"] for item in data["risks"]["items"])
    assert data["services"]["knowledge"]["status"] in {
        "healthy",
        "unavailable",
        "not_configured",
        "configured",
    }
    assert data["services"]["database"]["status"] in {"healthy", "unhealthy"}
    assert data["activity"][0]["action"] == "health_check"
    assert data["monitor_scheduler_enabled"] is False


@pytest.mark.asyncio
async def test_dashboard_task_counts_are_not_limited_to_visible_items(
    test_session_factory,
):
    async with test_session_factory() as db:
        db.add_all([
            BackgroundTask(
                task_type="dashboard-test",
                task_name=f"Dashboard task {index}",
                status=TaskStatus.PENDING,
            )
            for index in range(11)
        ])
        await db.commit()

        summary = await DashboardService.get_summary(db)

    assert summary["tasks"]["pending"] >= 11
    assert len(summary["tasks"]["items"]) <= 10


@pytest.mark.asyncio
async def test_dashboard_llm_config_source_matches_health_semantics(test_session_factory):
    """A6：DB 里没有 llm.* 覆盖行时，summary 的 config_source 必须是 env。

    此前 dashboard 硬编码 "system_config"，与 core/health.py（按 DB 实际行数判断）口径不一致，
    首页会把"全部来自 .env"的配置显示成"来自系统配置"。
    """
    from modules.system.service import SystemService

    async with test_session_factory() as db:
        await db.execute(delete(SystemConfig).where(SystemConfig.config_key.like("llm.%")))
        await db.commit()

        summary = await DashboardService.get_summary(db)
        assert summary["services"]["llm"]["config_source"] == "env"
        assert await SystemService.get_llm_config_source(db) == "env"

        db.add(SystemConfig(config_key="llm.model", config_value="deepseek-chat", description="test"))
        await db.commit()

        summary = await DashboardService.get_summary(db)
        assert summary["services"]["llm"]["config_source"] == "system_config"


@pytest.mark.asyncio
async def test_dashboard_summary_exposes_published_topology_layout(test_session_factory):
    async with test_session_factory() as db:
        await db.execute(update(Topology).values(status="inactive"))
        topology = Topology(name="Published Layout", topology_type=TopologyType.MAIN, status="active")
        db.add(topology)
        await db.flush()
        device = Device(
            hostname="published-layout-device",
            mgmt_ip="198.51.100.250",
            device_type=DeviceType.ROUTER,
            vendor=DeviceVendor.HUAWEI,
            status=DeviceStatus.UNKNOWN,
            topology_id=topology.id,
        )
        db.add(device)
        await db.flush()
        db.add(SystemConfig(
            config_key=f"topology:{topology.id}:layout:published",
            config_value=f'{{"{device.id}": {{"x": 0.25, "y": 0.5}}}}',
        ))
        await db.commit()

        summary = await DashboardService.get_summary(db)

    assert summary["topology"]["published_positions"] == {
        str(device.id): {"x": 0.25, "y": 0.5}
    }


@pytest.fixture
def local_knowledge_without_remote_credentials(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from core.config import Settings

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "routing.md").write_text("# OSPF\nOSPF neighbors exchange routing information.", encoding="utf-8")
    (corpus / "switching.md").write_text("# VLAN\nVLAN separates broadcast domains.", encoding="utf-8")
    settings = Settings(
        _env_file=None, knowledge_provider="local", knowledge_corpus_dir=str(corpus),
        knowledge_base_url="", knowledge_api_key="", knowledge_dataset_id="", knowledge_workspace_id="",
        rag_jwt_token="", rag_password="", llm_base_url="", llm_model="",
    )
    for module in ("modules.dashboard.service", "modules.system.service", "core.health",
                   "modules.knowledge.service", "modules.knowledge.local_provider"):
        monkeypatch.setattr(f"{module}.get_settings", lambda: settings)
    monkeypatch.setattr("modules.knowledge.local_provider.DEFAULT_STORAGE_DIR", tmp_path / "uploads")
    monkeypatch.setattr("core.health._SIDE_HEALTH_CACHE", {})
    monkeypatch.setattr("core.llm_provider.create_llm_provider", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("core.llm_provider.cached_llm_health_check", AsyncMock(return_value=False))


@pytest.mark.asyncio
async def test_dashboard_local_knowledge_uses_real_health_without_remote_credentials(
    test_session_factory, local_knowledge_without_remote_credentials,
):
    from modules.knowledge.service import KnowledgeService

    health = await KnowledgeService.from_settings().health_check()
    assert health["available"] is True
    assert health["document_count"] == 2
    async with test_session_factory() as db:
        summary = await DashboardService.get_summary(db)
    knowledge = summary["services"]["knowledge"]
    assert knowledge["provider"] == "local"
    assert knowledge["status"] == "healthy"
    assert knowledge["available"] == health["available"]
    assert knowledge["document_count"] == health["document_count"]


@pytest.mark.asyncio
async def test_dashboard_local_knowledge_health_failure_stays_unavailable(
    test_session_factory, local_knowledge_without_remote_credentials, monkeypatch,
):
    from unittest.mock import AsyncMock

    failed_probe = AsyncMock(side_effect=RuntimeError("isolated local index failure"))
    monkeypatch.setattr("modules.knowledge.local_provider.LocalKnowledgeProvider.health_check", failed_probe)
    async with test_session_factory() as db:
        summary = await DashboardService.get_summary(db)
    knowledge = summary["services"]["knowledge"]
    assert knowledge["status"] == "unavailable"
    assert knowledge["available"] is False
    assert knowledge["document_count"] == 0
    failed_probe.assert_awaited_once()
