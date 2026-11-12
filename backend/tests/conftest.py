"""公共测试fixtures"""
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from httpx import AsyncClient, ASGITransport

from core.database import Base, get_async_session

# 导入所有模型以确保Base.metadata包含所有表
from modules.auth.models import User, AuditLog, UserRole
from modules.device.models import Device, Topology, TopologyLink, TopologyVersion, TopologyRuntimeCheck, DeviceStatus, DeviceType, DeviceVendor, TopologyType
from modules.deploy.models import DeployTask, ConfigTemplate, ConfigVersion, DeployStatus, ChangeLevel
from modules.monitor.models import MetricRecord, Alarm, AlarmStatus, MetricType, MonitorJob
from modules.training.models import TrainingLab, TrainingSession, FaultInjection, OperationLog, LabStatus
from modules.ai_text.models import AILog, CopilotConversation  # noqa: F401
from modules.system.models import SystemConfig, BackgroundTask
from modules.trust.models import EnvironmentProfile, ReadOnlyObservation  # noqa: F401


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """创建SQLite测试数据库引擎 - StaticPool确保所有连接共享同一内存数据库"""
    from sqlalchemy import event

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # 打开外键约束：SQLite 默认关闭，导致"删设备撞外键"这类缺陷测不出来
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """每个用例前清空内存限流桶，避免测试间累计触发 429（生产限流逻辑不变）。"""
    from core.rate_limiter import _limiter
    _limiter._requests.clear()
    yield
    _limiter._requests.clear()


@pytest_asyncio.fixture(autouse=True)
async def _reset_settings_cache():
    """每个用例前清掉 get_settings 缓存。

    client 夹具里 monkeypatch 了环境变量并 cache_clear，但只对用了 client 的用例生效；
    其它用例可能拿到上一个用例缓存的 Settings（跨用例污染）。
    """
    from core.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def test_session_factory(test_engine):
    """创建测试session工厂"""
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def client(test_engine, test_session_factory, monkeypatch):
    """创建测试客户端，覆盖数据库依赖"""
    import core.database as db_module
    db_module._engine = test_engine
    db_module._session_factory = test_session_factory

    # The mocked database is SQLite; lifespan checks must not require local MySQL credentials.
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    monkeypatch.setenv("DB_URL", "")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing-only-32chars!")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "480")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5:7b")
    # 显式清空 key：否则部分用例可能真的去连本机 Ollama（测试不应依赖外部服务）
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("KNOWLEDGE_API_KEY", "")

    from core.config import get_settings
    get_settings.cache_clear()

    async def fake_init_db():
        db_module._engine = test_engine
        db_module._session_factory = test_session_factory
        return test_engine, test_session_factory

    async def fake_close_db():
        # The session-scoped in-memory engine is disposed by test_engine.
        return None

    # 覆盖数据库依赖
    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    from main import app
    monkeypatch.setattr("main.settings", get_settings())
    monkeypatch.setattr("main.init_db", fake_init_db)
    monkeypatch.setattr("main.close_db", fake_close_db)
    monkeypatch.setattr("main.start_monitor_scheduler", lambda: None)
    monkeypatch.setattr("main.shutdown_monitor_scheduler", lambda: None)
    app.dependency_overrides[get_async_session] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    # 清表：内存库是 session 级共享的，用例之间不清会互相污染
    # （此前只能靠"宽松断言"（如 >= 1）来容忍脏数据，掩盖了真实的数量/排序问题）
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest.fixture
def mock_env(monkeypatch):
    """设置测试环境变量"""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_MAX_TOKENS", "2048")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.3")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing-only-32chars!")


@pytest.fixture
def mock_provider():
    """模拟LLM Provider"""
    provider = AsyncMock()
    provider.__class__.__name__ = "MockProvider"
    provider.name = "MockProvider"
    return provider


@pytest.fixture
def mock_db():
    """模拟数据库session"""
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def sample_cli_response():
    """LLM返回的CLI命令示例"""
    return '{"commands": ["sysname CoreRouter01"], "explanation": "修改设备主机名", "warnings": []}'


@pytest.fixture
def sample_validate_response():
    """LLM返回的带多命令的CLI示例"""
    return json.dumps({
        "commands": [
            "interface GigabitEthernet0/0/1",
            "ip address 192.168.1.1 255.255.255.0",
        ],
        "explanation": "配置接口IP地址",
        "warnings": [],
    })
