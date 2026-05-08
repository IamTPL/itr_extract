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
        raise InvalidToken("Unknown signing key")
    public_key = RSAAlgorithm.from_jwk(jwk)

    issuer = f"{AZURE_AUTHORITY_BASE}/{tenant_id}/v2.0"
    try:
        claims = jwt.decode(
            token, public_key,
            algorithms=[JWT_ALGORITHM],
            audience=audience,
            issuer=issuer,
            leeway=JWT_LEEWAY_SECONDS,
        )
    except jwt.InvalidTokenError as e:
        raise InvalidToken(str(e)) from e

    if claims.get("tid") != tenant_id:
        raise InvalidToken("Wrong tenant")
    if not claims.get("oid"):
        raise InvalidToken("Missing oid")
    return claims
