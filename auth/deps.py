from datetime import datetime, timezone
from uuid import UUID
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from auth.jwt import InvalidToken, verify_token
from config.constants import BEARER_PREFIX
from config.settings import get_settings
from db.models import User
from db.session import get_db


async def _upsert_user(db: AsyncSession, claims: dict) -> User:
    oid = UUID(claims["oid"])
    email = claims.get("preferred_username") or claims.get("email") or ""
    name = claims.get("name")
    tid = UUID(claims["tid"])

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
    try:
        claims = await verify_token(
            token,
            tenant_id=get_settings().msal_tenant_id,
            audience=get_settings().msal_be_client_id,
        )
    except InvalidToken as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}")
    return await _upsert_user(db, claims)
