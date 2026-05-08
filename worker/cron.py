from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from config.constants import STUCK_JOB_THRESHOLD_SECONDS
from config.enums import JobStatus
from db.models import Job
from storage import files as fs


async def requeue_stuck_jobs(db: AsyncSession, arq) -> int:
    threshold = datetime.now(timezone.utc) - timedelta(seconds=STUCK_JOB_THRESHOLD_SECONDS)
    q = select(Job).where(Job.status == JobStatus.PROCESSING, Job.started_at < threshold)
    rows = list((await db.scalars(q)).all())
    for j in rows:
        j.status = JobStatus.PENDING
    await db.commit()
    for j in rows:
        await arq.enqueue_job("process_job", str(j.id))
    return len(rows)


async def cleanup_orphan_files(db: AsyncSession) -> int:
    valid_ids: set[str] = {str(j) for j in (await db.scalars(select(Job.id))).all()}
    removed = 0
    for user_dir in fs.list_user_dirs():
        if not user_dir.is_dir():
            continue
        for job_dir in user_dir.iterdir():
            if not job_dir.is_dir():
                continue
            if job_dir.name not in valid_ids:
                try:
                    fs.delete_job_dir(UUID(user_dir.name), UUID(job_dir.name))
                    removed += 1
                except (ValueError, Exception):
                    pass
    return removed
