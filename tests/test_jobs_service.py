import pytest
from uuid import uuid4, UUID
from db.models import User, Job
from jobs.service import create_job, get_job_for_user, list_jobs_for_user, delete_job
from config.enums import JobStatus


async def _make_user(db):
    u = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_create_job_inserts_pending(db_session):
    u = await _make_user(db_session)
    job = await create_job(db_session, user_id=u.id, filename="x.pdf", size=100)
    assert job.status == JobStatus.PENDING
    assert job.user_id == u.id


@pytest.mark.asyncio
async def test_list_returns_user_jobs_desc(db_session):
    u = await _make_user(db_session)
    await create_job(db_session, user_id=u.id, filename="a.pdf", size=1)
    await create_job(db_session, user_id=u.id, filename="b.pdf", size=2)
    rows = await list_jobs_for_user(db_session, u.id)
    assert [j.original_filename for j in rows] == ["b.pdf", "a.pdf"]


@pytest.mark.asyncio
async def test_get_job_for_other_user_returns_none(db_session):
    u1 = await _make_user(db_session)
    u2 = await _make_user(db_session)
    j = await create_job(db_session, user_id=u1.id, filename="x.pdf", size=1)
    assert await get_job_for_user(db_session, u2.id, j.id) is None
