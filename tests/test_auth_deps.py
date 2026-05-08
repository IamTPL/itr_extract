import pytest
from uuid import UUID
from auth.deps import _upsert_user
from db.models import User

@pytest.mark.asyncio
async def test_upsert_creates_new_user(db_session):
    claims = {
        "oid": "11111111-1111-1111-1111-111111111111",
        "tid": "22222222-2222-2222-2222-222222222222",
        "preferred_username": "a@x.com", "name": "A",
    }
    user = await _upsert_user(db_session, claims)
    assert user.id == UUID(claims["oid"])
    assert user.email == "a@x.com"

@pytest.mark.asyncio
async def test_upsert_updates_existing_user(db_session):
    claims = {
        "oid": "11111111-1111-1111-1111-111111111111",
        "tid": "22222222-2222-2222-2222-222222222222",
        "preferred_username": "a@x.com", "name": "A",
    }
    await _upsert_user(db_session, claims)
    claims["name"] = "Renamed"
    user = await _upsert_user(db_session, claims)
    assert user.name == "Renamed"
    from sqlalchemy import select, func
    count = await db_session.scalar(select(func.count(User.id)))
    assert count == 1
