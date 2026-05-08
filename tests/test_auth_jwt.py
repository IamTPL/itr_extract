import pytest
import time
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from auth.jwt import verify_token, InvalidToken
import auth.jwt as jwt_mod
from config.constants import AZURE_AUTHORITY_BASE

TENANT = "tenant-uuid"
AUDIENCE = "be-client-id"
ISSUER = f"{AZURE_AUTHORITY_BASE}/{TENANT}/v2.0"

@pytest.fixture
def rsa_keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)

def make_jwk(rsa_key, kid="kid1"):
    import base64
    pub = rsa_key.public_key().public_numbers()
    def b64(i: int) -> str:
        b = i.to_bytes((i.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).decode().rstrip("=")
    return {"kid": kid, "kty": "RSA", "n": b64(pub.n), "e": b64(pub.e), "alg": "RS256", "use": "sig"}

def make_token(rsa_key, *, kid="kid1", aud=AUDIENCE, iss=ISSUER, tid=TENANT, exp_offset=600):
    pem = rsa_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    claims = {
        "oid": "user-oid", "tid": tid, "aud": aud, "iss": iss,
        "exp": int(time.time()) + exp_offset, "iat": int(time.time()),
        "preferred_username": "u@x.com", "name": "U",
    }
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})

@pytest.fixture
def patch_jwks(rsa_keypair, monkeypatch):
    async def fake_get_jwks(tid):
        return [make_jwk(rsa_keypair)]
    monkeypatch.setattr(jwt_mod, "get_jwks", fake_get_jwks)

@pytest.mark.asyncio
async def test_valid_token_returns_claims(rsa_keypair, patch_jwks):
    token = make_token(rsa_keypair)
    claims = await verify_token(token, tenant_id=TENANT, audience=AUDIENCE)
    assert claims["oid"] == "user-oid"

@pytest.mark.asyncio
async def test_expired_token_rejected(rsa_keypair, patch_jwks):
    token = make_token(rsa_keypair, exp_offset=-3600)
    with pytest.raises(InvalidToken):
        await verify_token(token, tenant_id=TENANT, audience=AUDIENCE)

@pytest.mark.asyncio
async def test_wrong_audience_rejected(rsa_keypair, patch_jwks):
    token = make_token(rsa_keypair, aud="wrong")
    with pytest.raises(InvalidToken):
        await verify_token(token, tenant_id=TENANT, audience=AUDIENCE)

@pytest.mark.asyncio
async def test_wrong_tenant_rejected(rsa_keypair, patch_jwks):
    token = make_token(rsa_keypair, tid="other-tenant")
    with pytest.raises(InvalidToken):
        await verify_token(token, tenant_id=TENANT, audience=AUDIENCE)

@pytest.mark.asyncio
async def test_unknown_kid_rejected(rsa_keypair, patch_jwks):
    token = make_token(rsa_keypair, kid="unknown")
    with pytest.raises(InvalidToken):
        await verify_token(token, tenant_id=TENANT, audience=AUDIENCE)
