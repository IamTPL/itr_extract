import asyncio
import os
from logging.config import fileConfig
from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Must set env vars before importing project modules
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("MSAL_TENANT_ID", "x")
os.environ.setdefault("MSAL_BE_CLIENT_ID", "x")
os.environ.setdefault("GEMINI_API_KEY", "x")

from config.settings import get_settings
from db.base import Base
import db.models  # noqa: F401  registers models with Base.metadata

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


asyncio.run(run_migrations_online())
