from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from config.settings import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _make_session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


engine = _make_engine()
SessionLocal = _make_session_factory(engine)
