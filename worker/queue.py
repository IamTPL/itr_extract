from arq import create_pool
from arq.connections import RedisSettings, ArqRedis
from config.settings import get_settings

_pool: ArqRedis | None = None

def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)

async def get_arq_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(_redis_settings())
    return _pool
