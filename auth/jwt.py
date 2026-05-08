import jwt
from jwt.algorithms import RSAAlgorithm
from auth.jwks import get_jwks
from config.constants import AZURE_AUTHORITY_BASE, JWT_ALGORITHM, JWT_LEEWAY_SECONDS

class InvalidToken(Exception):
    pass

async def verify_token(token: str, *, tenant_id: str, audience: str) -> dict:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as e:
        raise InvalidToken(f"Malformed token: {e}") from e

    kid = header.get("kid")
    if not kid:
        raise InvalidToken("Missing kid")

    keys = await get_jwks(tenant_id)
    jwk = next((k for k in keys if k["kid"] == kid), None)
    if not jwk:
        # Có thể Microsoft vừa rotate key, force refresh cache rồi thử lại 1 lần.
        keys = await get_jwks(tenant_id, force_refresh=True)
        jwk = next((k for k in keys if k["kid"] == kid), None)
        if not jwk:
            raise InvalidToken("Unknown signing key")
    public_key = RSAAlgorithm.from_jwk(jwk)

    decode_kwargs: dict = {
        "algorithms": [JWT_ALGORITHM],
        "audience": audience,
        "leeway": JWT_LEEWAY_SECONDS,
    }
    # "common" endpoint: issuer is tenant-specific so we can't pre-compute it
    if tenant_id != "common":
        decode_kwargs["issuer"] = f"{AZURE_AUTHORITY_BASE}/{tenant_id}/v2.0"

    try:
        claims = jwt.decode(token, public_key, **decode_kwargs)
    except jwt.InvalidTokenError as e:
        raise InvalidToken(str(e)) from e

    if tenant_id != "common" and claims.get("tid") != tenant_id:
        raise InvalidToken("Wrong tenant")
    if not claims.get("oid"):
        raise InvalidToken("Missing oid")
    return claims
