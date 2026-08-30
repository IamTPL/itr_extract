from uuid import UUID
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from auth.deps import get_current_user
from config.constants import MAX_ACTIVE_JOBS_PER_USER, MAX_INPUT_FILE_SIZE_BYTES, UPLOAD_RATE_LIMIT
from config.enums import JobStatus
from db.models import User
from db.session import get_db
from jobs.service import (
    count_active_jobs, create_job, delete_job, enforce_session_cap,
    get_job_for_user, JobBusyError, list_jobs_for_user,
)
from storage import files as fs
from api.limiter import limiter
from api.schemas import CreateJobResponse, JobDetail, JobListResponse, JobSummary
from worker.queue import get_arq_pool

router = APIRouter(prefix="/api/jobs")


def _safe_download_name(raw: str, fallback: str = "file.pdf") -> str:
    """Strip CR/LF + control chars khỏi filename trước khi đặt vào
    Content-Disposition header — tránh header injection.
    """
    if not raw:
        return fallback
    cleaned = "".join(c for c in raw if c.isprintable() and c not in '"\r\n')
    cleaned = cleaned.strip()[:200]  # cap length
    return cleaned or fallback


def _to_summary(j) -> JobSummary:
    return JobSummary(
        job_id=j.id, status=j.status, original_filename=j.original_filename,
        created_at=j.created_at, finished_at=j.finished_at,
        error_message=j.error_message,
    )


def _to_detail(j) -> JobDetail:
    return JobDetail(
        job_id=j.id, status=j.status, original_filename=j.original_filename,
        created_at=j.created_at, started_at=j.started_at, finished_at=j.finished_at,
        error_message=j.error_message, has_econsent=j.has_econsent,
        has_voucher=j.has_voucher,
        analysis_data=j.analysis_data, email_html=j.email_html,
    )


_UPLOAD_CHUNK_SIZE = 1 << 20  # 1 MiB


@router.post("", response_model=CreateJobResponse, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(UPLOAD_RATE_LIMIT)
async def post_job(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    arq: ArqRedis = Depends(get_arq_pool),
):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "File must be a PDF")

    # Pre-check active jobs trước khi đọc file để fail-fast
    if (await count_active_jobs(db, user.id)) >= MAX_ACTIVE_JOBS_PER_USER:
        raise HTTPException(429, "Too many active jobs, please wait")

    # Stream từng chunk + bail sớm khi vượt size → tránh OOM
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_INPUT_FILE_SIZE_BYTES:
            raise HTTPException(413, "File too large")
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(400, "Empty file")

    data = b"".join(chunks)
    job = await create_job(db, user_id=user.id, filename=file.filename, size=total)
    fs.write_input(user.id, job.id, data)
    await enforce_session_cap(db, user.id)
    await arq.enqueue_job("process_job", str(job.id))
    return CreateJobResponse(job_id=job.id, status=job.status, created_at=job.created_at)


@router.get("", response_model=JobListResponse)
async def get_jobs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await list_jobs_for_user(db, user.id)
    return JobListResponse(jobs=[_to_summary(j) for j in rows])


@router.get("/{job_id}", response_model=JobDetail)
async def get_job(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    j = await get_job_for_user(db, user.id, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return _to_detail(j)


@router.get("/{job_id}/econsent.pdf")
async def get_econsent(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    j = await get_job_for_user(db, user.id, job_id)
    if not j or not j.has_econsent:
        raise HTTPException(404, "Not found")
    return FileResponse(
        fs.econsent_path(user.id, j.id),
        media_type="application/pdf",
        filename="Econsent.pdf",
    )


@router.get("/{job_id}/voucher.pdf")
async def get_voucher(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    j = await get_job_for_user(db, user.id, job_id)
    if not j or not j.has_voucher:
        raise HTTPException(404, "Not found")
    return FileResponse(
        fs.voucher_path(user.id, j.id),
        media_type="application/pdf",
        filename="Voucher.pdf",
    )


@router.get("/{job_id}/input.pdf")
async def get_input(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    j = await get_job_for_user(db, user.id, job_id)
    if not j:
        raise HTTPException(404, "Not found")
    return FileResponse(
        fs.input_path(user.id, j.id),
        media_type="application/pdf",
        filename=_safe_download_name(j.original_filename),
    )


@router.post("/{job_id}/reprocess", response_model=CreateJobResponse, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(UPLOAD_RATE_LIMIT)
async def post_reprocess(
    request: Request,
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    arq: ArqRedis = Depends(get_arq_pool),
):
    parent = await get_job_for_user(db, user.id, job_id)
    if not parent:
        raise HTTPException(404, "Job not found")
    if parent.status != JobStatus.FAILED:
        raise HTTPException(409, "Only failed jobs can be reprocessed")
    if not fs.input_path(user.id, parent.id).exists():
        raise HTTPException(410, "Original input no longer available")
    # Same quota check như upload — chống bypass MAX_ACTIVE_JOBS_PER_USER
    if (await count_active_jobs(db, user.id)) >= MAX_ACTIVE_JOBS_PER_USER:
        raise HTTPException(429, "Too many active jobs, please wait")
    new_job = await create_job(
        db, user_id=user.id, filename=parent.original_filename,
        size=parent.input_size_bytes, parent_job_id=parent.id,
    )
    src = fs.read_input(user.id, parent.id)
    fs.write_input(user.id, new_job.id, src)
    await enforce_session_cap(db, user.id)
    await arq.enqueue_job("process_job", str(new_job.id))
    return CreateJobResponse(job_id=new_job.id, status=new_job.status, created_at=new_job.created_at)


@router.delete("/{job_id}", status_code=204)
async def remove_job(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        deleted = await delete_job(db, user.id, job_id)
    except JobBusyError as e:
        raise HTTPException(409, str(e))
    if not deleted:
        raise HTTPException(404, "Job not found")
