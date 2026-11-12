"""Fresh minimal seeds appear on the dashboard without changing existing topology choices."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import Settings
from core.database import Base
from modules.auth.models import User, UserRole
from modules.dashboard.service import DashboardService
from modules.device.models import Device, Topology, TopologyLink, TopologyType
from modules.system.models import SystemConfig


@pytest_asyncio.fixture
async def fresh_seed(monkeypatch):
    # The entry point normally loads local dotenv files and initializes a database.
    # Replace both before importing/running it; this fixture owns an empty memory DB.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_args, **_kwargs: False)
    path = Path(__file__).resolve().parents[1] / "scripts/seed_sim_devices.py"
    spec = importlib.util.spec_from_file_location("isolated_sim_seed", path)
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add(User(username="isolated-seed-owner", hashed_password="synthetic-unused-hash", role=UserRole.ADMIN))
        await db.commit()
    monkeypatch.setattr(seed, "init_db", AsyncMock())
    monkeypatch.setattr(seed, "close_db", AsyncMock())
    monkeypatch.setattr(seed, "get_session_factory", lambda: factory)
    settings = Settings(_env_file=None, llm_base_url="", llm_model="", knowledge_base_url="", knowledge_api_key="")
    monkeypatch.setattr("core.config.get_settings", lambda: settings)
    monkeypatch.setattr("modules.dashboard.service.get_settings", lambda: settings)
    monkeypatch.setattr("core.llm_provider.create_llm_provider", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("core.llm_provider.cached_llm_health_check", AsyncMock(return_value=False))
    monkeypatch.setattr("core.health.get_knowledge_health_cached", AsyncMock(return_value={"status": "unavailable"}))
    try:
        yield seed, factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_fresh_sim_seed_exposes_six_nodes_and_five_links_on_dashboard(fresh_seed):
    seed, factory = fresh_seed
    async with factory() as db:
        assert (await db.scalar(select(func.count()).select_from(Topology))) == 0
    assert await seed.main() == 0
    async with factory() as db:
        summary = await DashboardService.get_summary(db)
        topology = summary["topology"]
        assert topology is not None
        assert topology["name"] == seed.TOPOLOGY_NAME
        assert topology["device_count"] == len(topology["nodes"]) == 6
        assert topology["link_count"] == len(topology["links"]) == 5
        assert {node["hostname"] for node in topology["nodes"]} == {item[0] for item in seed.DEVICE_PLAN}
        assert (await db.get(Topology, topology["id"])).topology_type == TopologyType.MAIN


@pytest.mark.asyncio
async def test_new_sim_topology_stays_lab_when_an_active_main_already_exists(fresh_seed):
    seed, factory = fresh_seed
    async with factory() as db:
        existing = Topology(name="Existing user main", topology_type=TopologyType.MAIN, status="active")
        db.add(existing)
        await db.commit()
        existing_id = existing.id
    assert await seed.main() == 0
    assert await seed.main() == 0
    async with factory() as db:
        assert (await db.get(Topology, existing_id)).topology_type == TopologyType.MAIN
        simulated = (await db.execute(select(Topology).where(Topology.name == seed.TOPOLOGY_NAME))).scalar_one()
        assert simulated.topology_type == TopologyType.LAB
        assert await db.scalar(select(func.count()).select_from(Device)) == 6
        assert await db.scalar(select(func.count()).select_from(TopologyLink)) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_type", [TopologyType.MAIN, TopologyType.LAB])
async def test_repeat_seed_preserves_existing_type_and_published_layout(fresh_seed, existing_type):
    seed, factory = fresh_seed
    async with factory() as db:
        existing = Topology(name=seed.TOPOLOGY_NAME, topology_type=existing_type, status="active")
        db.add(existing)
        await db.commit()
        topology_id = existing.id
    assert await seed.main() == 0
    async with factory() as db:
        device_id = await db.scalar(select(Device.id).order_by(Device.id).limit(1))
        key = f"topology:{topology_id}:layout:published"
        layout = json.dumps({str(device_id): {"x": 0.25, "y": 0.75}})
        db.add(SystemConfig(config_key=key, config_value=layout))
        await db.commit()
    assert await seed.main() == 0
    async with factory() as db:
        topology = await db.get(Topology, topology_id)
        assert topology.topology_type == existing_type
        assert topology.status == "active"
        assert await db.scalar(select(SystemConfig.config_value).where(SystemConfig.config_key == key)) == layout
        assert await db.scalar(select(func.count()).select_from(Device)) == 6
        assert await db.scalar(select(func.count()).select_from(TopologyLink)) == 5


@pytest.mark.asyncio
async def test_inactive_main_does_not_hide_a_new_sim_topology(fresh_seed):
    seed, factory = fresh_seed
    async with factory() as db:
        db.add(Topology(name="Archived main", topology_type=TopologyType.MAIN, status="inactive"))
        await db.commit()
    assert await seed.main() == 0
    async with factory() as db:
        summary = await DashboardService.get_summary(db)
        assert summary["topology"]["name"] == seed.TOPOLOGY_NAME
