import pytest
import httpx
import respx
from auth.jwks import get_jwks, _jwks_cache
from config.constants import AZURE_AUTHORITY_BASE

TENANT = "tenant-uuid"
JWKS_URL = f"{AZURE_AUTHORITY_BASE}/{TENANT}/discovery/v2.0/keys"

@pytest.mark.asyncio
async def test_get_jwks_fetches_and_caches():
    _jwks_cache.clear()
    sample = {"keys": [{"kid": "abc", "kty": "RSA", "n": "x", "e": "AQAB"}]}
    with respx.mock(assert_all_called=False) as m:
        route = m.get(JWKS_URL).mock(return_value=httpx.Response(200, json=sample))
        keys1 = await get_jwks(TENANT)
        keys2 = await get_jwks(TENANT)
        assert keys1 == sample["keys"]
        assert route.call_count == 1
