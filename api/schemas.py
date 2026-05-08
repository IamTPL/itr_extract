from datetime import datetime
from uuid import UUID
from pydantic import BaseModel
from config.enums import JobStatus

class JobSummary(BaseModel):
    job_id: UUID
    status: JobStatus
    original_filename: str
    created_at: datetime
    finished_at: datetime | None
    error_message: str | None

class JobDetail(JobSummary):
    started_at: datetime | None
    has_econsent: bool
    analysis_data: dict | None
    email_html: str | None

class JobListResponse(BaseModel):
    jobs: list[JobSummary]

class CreateJobResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    created_at: datetime

class MeResponse(BaseModel):
    user_id: UUID
    email: str
    name: str | None
    job_count: int
