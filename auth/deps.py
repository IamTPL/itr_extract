from datetime import datetime, timezone
from uuid import UUID
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from auth.jwt import InvalidToken, verify_token
from config.constants import BEARER_PREFIX
from config.settings import get_settings
from db.models import User
from db.session import get_db


# Tenant ID giả cho personal accounts khi token không có `tid` (rất hiếm).
# Tất cả personal Microsoft accounts đều thuộc tenant "consumers" này theo Microsoft.
_CONSUMERS_TENANT_ID = UUID("9188040d-6c67-4c5b-b112-36a304b66dad")


async def _upsert_user(db: AsyncSession, claims: dict) -> User:
    # `oid` là object ID Azure AD; một số token cũ/edge case dùng `sub` thay thế.
    raw_oid = claims.get("oid") or claims.get("sub")
    if not raw_oid:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Token missing required identity claim (oid/sub)",
        )
    try:
        oid = UUID(raw_oid)
    except (ValueError, TypeError):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Token identity claim is not a valid UUID",
        )

    raw_tid = claims.get("tid")
    try:
        tid = UUID(raw_tid) if raw_tid else _CONSUMERS_TENANT_ID
    except (ValueError, TypeError):
        tid = _CONSUMERS_TENANT_ID

    email = claims.get("preferred_username") or claims.get("email") or ""
    name = claims.get("name")

    user = await db.get(User, oid)
    if user is None:
        user = User(id=oid, email=email, name=name, tenant_id=tid)
        db.add(user)
    else:
        user.email = email or user.email
        user.name = name or user.name
        user.last_login = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return user


async def get_current_user(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization.startswith(BEARER_PREFIX):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization[len(BEARER_PREFIX):]
    settings = get_settings()

    # Dev mode: MSAL_TENANT_ID chưa set → dùng "common" endpoint, bỏ issuer/tid check
    # Production: enforce tenant cụ thể
    tenant_id = settings.msal_tenant_id or "common"
    # ID token (dev) và access token (prod) đều có aud = msal_be_client_id
    audience = settings.msal_be_client_id

    try:
        claims = await verify_token(token, tenant_id=tenant_id, audience=audience)
    except InvalidToken as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}")
    return await _upsert_user(db, claims)
