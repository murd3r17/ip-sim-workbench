"""SQLAlchemy异步引擎与会话管理"""
from pathlib import Path
from urllib.parse import quote_plus
from sqlalchemy import event, inspect

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from core.config import get_settings


class Base(DeclarativeBase):
    pass


# 使用模块级别的变量，而不是全局变量
_engine = None
_session_factory = None

# 仓库根目录（backend/ 的上一级），sqlite 默认落盘位置用它
REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_database_url(settings=None) -> str:
    """解析实际使用的数据库连接串。

    优先级：DB_URL（完整覆盖）> DB_BACKEND=sqlite（最小运行模式）> MySQL 组装。
    DB_BACKEND=sqlite 让"没装 MySQL 的机器"也能跑起来（测试套件本来就全跑 SQLite）。
    """
    settings = settings or get_settings()
    override = (getattr(settings, "db_url", "") or "").strip()
    if override:
        return override
    backend = (getattr(settings, "db_backend", "mysql") or "mysql").strip().lower()
    if backend == "sqlite":
        raw_path = (getattr(settings, "db_sqlite_path", "") or "").strip()
        db_file = Path(raw_path) if raw_path else (REPO_ROOT / ".runtime" / "sim_workspace.db")
        db_file = db_file.expanduser()
        db_file.parent.mkdir(parents=True, exist_ok=True)
        # 统一用 POSIX 风格分隔符，Windows 盘符也能被 sqlite URL 正确解析
        return f"sqlite+aiosqlite:///{db_file.as_posix()}"
    encoded_password = quote_plus(settings.db_password)
    return (
        f"mysql+aiomysql://{settings.db_user}:{encoded_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )


def is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite")


def get_engine():
    """获取数据库引擎"""
    global _engine
    return _engine


def get_session_factory():
    """获取会话工厂"""
    global _session_factory
    return _session_factory


def _import_all_models() -> None:
    """导入全部模型，保证 Base.metadata 完整（create_all 用）。"""
    import modules.auth.models  # noqa: F401
    import modules.device.models  # noqa: F401
    import modules.deploy.models  # noqa: F401
    import modules.monitor.models  # noqa: F401
    import modules.training.models  # noqa: F401
    import modules.ai_text.models  # noqa: F401
    import modules.system.models  # noqa: F401
    import modules.trust.models  # noqa: F401


async def init_db():
    """初始化数据库连接池"""
    global _engine, _session_factory
    settings = get_settings()
    url = resolve_database_url(settings)

    kwargs: dict = {"echo": settings.debug, "pool_pre_ping": True}
    if is_sqlite_url(url):
        # sqlite 不接受 pool_size/max_overflow；aiosqlite 需要放开线程检查
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_recycle=settings.db_pool_recycle,
        )

    _engine = create_async_engine(url, **kwargs)
    if is_sqlite_url(url):
        @event.listens_for(_engine.sync_engine, "connect")
        def enable_foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    # Only an empty store is initialized automatically. Existing stores require
    # the explicit, backed-up bootstrap path, for SQLite and MySQL alike.
    auto_create = bool(settings.db_auto_create) or is_sqlite_url(url)
    from core.migrations import assert_schema_ready, upgrade_connection
    def ensure_schema(connection):
        if not inspect(connection).get_table_names() and auto_create:
            upgrade_connection(connection)
        assert_schema_ready(connection)
    try:
        async with _engine.begin() as conn:
            await conn.run_sync(ensure_schema)
    except Exception:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        raise
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

    return _engine, _session_factory


async def close_db():
    """关闭数据库连接池"""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
    _session_factory = None


async def get_async_session():
    """FastAPI依赖注入：获取数据库会话"""
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()")
    async with factory() as session:
        try:
            yield session
        finally:
            await session.close()
