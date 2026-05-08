import pytest
from uuid import uuid4
from db.models import User, Job
from jobs.service import create_job, enforce_session_cap, list_jobs_for_user
from config.constants import MAX_SESSIONS_PER_USER


async def _make_user(db):
    u = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_cap_evicts_oldest_when_exceeded(db_session, tmp_path, monkeypatch):
    from storage import files as fs
    monkeypatch.setattr(fs, "_files_root", lambda: tmp_path)
    u = await _make_user(db_session)
    created = []
    for i in range(MAX_SESSIONS_PER_USER + 1):
        j = await create_job(db_session, user_id=u.id, filename=f"{i}.pdf", size=1)
        created.append(j)
    evicted_ids = await enforce_session_cap(db_session, u.id)
    rows = await list_jobs_for_user(db_session, u.id)
    assert len(rows) == MAX_SESSIONS_PER_USER
    assert created[0].id in evicted_ids


@pytest.mark.asyncio
async def test_cap_no_eviction_under_limit(db_session, tmp_path, monkeypatch):
    from storage import files as fs
    monkeypatch.setattr(fs, "_files_root", lambda: tmp_path)
    u = await _make_user(db_session)
    for i in range(MAX_SESSIONS_PER_USER):
        await create_job(db_session, user_id=u.id, filename=f"{i}.pdf", size=1)
    evicted = await enforce_session_cap(db_session, u.id)
    assert evicted == []
