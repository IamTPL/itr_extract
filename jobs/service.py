from uuid import UUID, uuid4
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from config.constants import MAX_SESSIONS_PER_USER
from config.enums import JobStatus, ACTIVE_STATUSES
from db.models import Job
from storage import files as fs


async def create_job(db: AsyncSession, *, user_id: UUID, filename: str, size: int,
                     parent_job_id: UUID | None = None) -> Job:
    job = Job(
        id=uuid4(), user_id=user_id, status=JobStatus.PENDING,
        original_filename=filename, input_size_bytes=size,
        parent_job_id=parent_job_id,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def list_jobs_for_user(db: AsyncSession, user_id: UUID) -> list[Job]:
    q = (
        select(Job)
        .where(Job.user_id == user_id)
        .order_by(Job.created_at.desc())
        .limit(MAX_SESSIONS_PER_USER)
    )
    return list((await db.scalars(q)).all())


async def get_job_for_user(db: AsyncSession, user_id: UUID, job_id: UUID) -> Job | None:
    q = select(Job).where(Job.id == job_id, Job.user_id == user_id)
    return (await db.scalars(q)).one_or_none()


async def count_active_jobs(db: AsyncSession, user_id: UUID) -> int:
    q = select(func.count(Job.id)).where(
        Job.user_id == user_id,
        Job.status.in_([s.value for s in ACTIVE_STATUSES]),
    )
    return await db.scalar(q) or 0


async def enforce_session_cap(db: AsyncSession, user_id: UUID) -> list[UUID]:
    q = select(Job).where(Job.user_id == user_id).order_by(Job.created_at.asc())
    all_jobs = list((await db.scalars(q)).all())
    excess = max(0, len(all_jobs) - MAX_SESSIONS_PER_USER)
    if excess == 0:
        return []
    to_evict = all_jobs[:excess]
    evicted_ids = [j.id for j in to_evict]
    for j in to_evict:
        fs.delete_job_dir(user_id, j.id)
        await db.delete(j)
    await db.commit()
    return evicted_ids


async def delete_job(db: AsyncSession, user_id: UUID, job_id: UUID) -> bool:
    job = await get_job_for_user(db, user_id, job_id)
    if not job:
        return False
    fs.delete_job_dir(user_id, job_id)
    await db.delete(job)
    await db.commit()
    return True
