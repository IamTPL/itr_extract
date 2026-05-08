from arq import cron as arq_cron
from config.constants import (
    CLEANUP_ORPHAN_FILES_HOUR,
    JOB_TIMEOUT_SECONDS,
    MAX_RETRY_ATTEMPTS,
    STUCK_JOB_SWEEP_INTERVAL_MIN,
    WORKER_MAX_CONCURRENT_JOBS,
)
from db.base import SessionLocal
from worker.tasks import process_job as _run_process_job
from worker.cron import requeue_stuck_jobs, cleanup_orphan_files
from worker.queue import _redis_settings, get_arq_pool


async def _startup(ctx: dict) -> None:
    ctx["db_factory"] = SessionLocal


async def _shutdown(ctx: dict) -> None:
    pass


async def process_job(ctx: dict, job_id: str) -> None:
    async with ctx["db_factory"]() as db:
        ctx["db"] = db
        await _run_process_job(ctx, job_id)


async def _requeue_cron(ctx: dict) -> None:
    arq = await get_arq_pool()
    async with ctx["db_factory"]() as db:
        await requeue_stuck_jobs(db, arq)


async def _cleanup_cron(ctx: dict) -> None:
    async with ctx["db_factory"]() as db:
        await cleanup_orphan_files(db)


class WorkerSettings:
    redis_settings = _redis_settings()
    on_startup = _startup
    on_shutdown = _shutdown
    functions = [process_job]
    cron_jobs = [
        arq_cron(_requeue_cron, minute=set(range(0, 60, STUCK_JOB_SWEEP_INTERVAL_MIN))),
        arq_cron(_cleanup_cron, hour={CLEANUP_ORPHAN_FILES_HOUR}, minute={0}),
    ]
    job_timeout = JOB_TIMEOUT_SECONDS
    max_jobs = WORKER_MAX_CONCURRENT_JOBS
    max_tries = MAX_RETRY_ATTEMPTS
    retry_jobs = True
