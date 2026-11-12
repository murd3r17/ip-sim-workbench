import os
from logging.config import fileConfig
from urllib.parse import quote_plus

from alembic import context
from sqlalchemy import engine_from_config, pool

from core.config import get_settings
from core.database import Base, _import_all_models

# Keep cold CLI metadata identical to application/bootstrap metadata.
_import_all_models()

config = context.config
if config.config_file_name is not None and not config.attributes.get("connection"):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    override = os.environ.get("ALEMBIC_URL")
    if override:
        return override
    settings = get_settings()
    from core.database import resolve_database_url
    resolved = resolve_database_url(settings)
    if resolved.startswith("sqlite"):
        # Alembic 走同步引擎
        return resolved.replace("+aiosqlite", "")
    name = (
        os.environ.get("ALEMBIC_DB_NAME")
        or context.get_x_argument(as_dictionary=True).get("db")
        or settings.db_name
    )
    password = quote_plus(settings.db_password)
    return (
        f"mysql+pymysql://{settings.db_user}:{password}"
        f"@{settings.db_host}:{settings.db_port}/{name}"
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    existing_connection = config.attributes.get("connection")
    if existing_connection is not None:
        context.configure(connection=existing_connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
