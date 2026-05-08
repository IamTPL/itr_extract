import time
import httpx
from config.constants import AZURE_AUTHORITY_BASE, JWKS_CACHE_TTL_SECONDS, HEALTH_CHECK_TIMEOUT_SECONDS

_jwks_cache: dict[str, tuple[float, list[dict]]] = {}


async def _fetch_jwks(tenant_id: str) -> list[dict]:
    # "common" resolves keys for both personal and work accounts
    url = f"{AZURE_AUTHORITY_BASE}/{tenant_id}/discovery/v2.0/keys"
    async with httpx.AsyncClient() as client:
        r = await client.get(url, timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
        r.raise_for_status()
    keys = r.json()["keys"]
    _jwks_cache[tenant_id] = (time.time() + JWKS_CACHE_TTL_SECONDS, keys)
    return keys


async def get_jwks(tenant_id: str, *, force_refresh: bool = False) -> list[dict]:
    if not force_refresh:
        cached = _jwks_cache.get(tenant_id)
        if cached and cached[0] > time.time():
            return cached[1]
    return await _fetch_jwks(tenant_id)
