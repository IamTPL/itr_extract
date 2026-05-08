import asyncio
import os

# Set all required env vars BEFORE importing project modules
# (get_settings() is lru_cache'd — must be set before first call)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://placeholder")
os.environ.setdefault("REDIS_URL", "redis://placeholder")
os.environ.setdefault("MSAL_TENANT_ID", "00000000-0000-0000-0000-000000000000")
os.environ.setdefault("MSAL_BE_CLIENT_ID", "00000000-0000-0000-0000-000000000000")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from db.base import Base


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def postgres_url():
    with PostgresContainer("postgres:16-alpine") as pg:
        # testcontainers returns psycopg2 URL, convert to asyncpg
        url = pg.get_connection_url().replace("psycopg2", "asyncpg").replace("postgresql://", "postgresql+asyncpg://")
        # Override the cached settings so DB session uses real test DB
        os.environ["DATABASE_URL"] = url
        from config.settings import get_settings
        get_settings.cache_clear()
        yield url


@pytest.fixture(scope="session")
def redis_url():
    with RedisContainer("redis:7-alpine") as r:
        host = r.get_container_host_ip()
        port = r.get_exposed_port(6379)
        url = f"redis://{host}:{port}"
        os.environ["REDIS_URL"] = url
        from config.settings import get_settings
        get_settings.cache_clear()
        yield url


@pytest_asyncio.fixture
async def db_engine(postgres_url):
    engine = create_async_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    Session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with Session() as s:
        yield s
