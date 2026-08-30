import asyncio
from datetime import datetime, timezone
from uuid import UUID
import traceback
from sqlalchemy.ext.asyncio import AsyncSession
from config.constants import MAX_RETRY_ATTEMPTS
from config.enums import JobStatus
from db.models import Job
from jobs import pipeline
from storage import files as fs


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def process_job(ctx: dict, job_id_str: str) -> None:
    db: AsyncSession = ctx["db"]
    job_id = UUID(job_id_str)

    job = await db.get(Job, job_id)
    if job is None:
        return  # deleted mid-queue
    if job.status not in (JobStatus.PENDING,):
        return  # already handled

    job.status = JobStatus.PROCESSING
    job.started_at = _utcnow()
    await db.commit()

    try:
        pdf_bytes = fs.read_input(job.user_id, job.id)
        # `run_extraction` là CPU-bound + sync I/O (Gemini, fitz). Phải chạy
        # trong thread executor để KHÔNG block arq event loop — nếu không, các
        # job khác đang queue + cron (requeue, cleanup) sẽ bị stall đến vài phút.
        loop = asyncio.get_running_loop()
        analysis, email_html, econsent, voucher = await loop.run_in_executor(
            None, pipeline.run_extraction, pdf_bytes,
        )
        if econsent:
            fs.write_econsent(job.user_id, job.id, econsent)
        if voucher:
            fs.write_voucher(job.user_id, job.id, voucher)
        job.analysis_data = analysis
        job.email_html = email_html
        job.has_econsent = bool(econsent)
        job.has_voucher = bool(voucher)
        job.status = JobStatus.SUCCESS
        job.finished_at = _utcnow()
        await db.commit()
    except Exception as e:
        await db.refresh(job)  # refresh to get latest retry_count
        job.retry_count += 1
        if job.retry_count >= MAX_RETRY_ATTEMPTS:
            job.status = JobStatus.FAILED
            job.error_message = str(e)[:500]
            job.error_details = {"traceback": traceback.format_exc()}
            job.finished_at = _utcnow()
            await db.commit()
        else:
            job.status = JobStatus.PENDING
            await db.commit()
            raise  # arq retries
