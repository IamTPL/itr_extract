from __future__ import annotations
from datetime import datetime
from uuid import UUID, uuid4
import sqlalchemy as sa
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID, ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from config.enums import JobStatus
from db.base import Base

job_status_enum = PgEnum(
    JobStatus,
    name="job_status",
    values_callable=lambda e: [m.value for m in e],
)


class User(Base):
    __tablename__ = "users"
    id:         Mapped[UUID]       = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    email:      Mapped[str]        = mapped_column(Text, nullable=False)
    name:       Mapped[str | None] = mapped_column(Text)
    tenant_id:  Mapped[UUID]       = mapped_column(PgUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_login: Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    jobs: Mapped[list["Job"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Job(Base):
    __tablename__ = "jobs"
    id:                Mapped[UUID]        = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id:           Mapped[UUID]        = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status:            Mapped[JobStatus]   = mapped_column(job_status_enum, nullable=False, default=JobStatus.PENDING)
    original_filename: Mapped[str]         = mapped_column(Text, nullable=False)
    input_size_bytes:  Mapped[int]         = mapped_column(BigInteger, nullable=False)
    analysis_data:     Mapped[dict | None] = mapped_column(JSONB)
    email_html:        Mapped[str | None]  = mapped_column(Text)
    has_econsent:      Mapped[bool]        = mapped_column(Boolean, nullable=False, default=False)
    has_voucher:       Mapped[bool]        = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
    created_at:        Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at:        Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at:       Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message:     Mapped[str | None]  = mapped_column(Text)
    error_details:     Mapped[dict | None] = mapped_column(JSONB)
    retry_count:       Mapped[int]         = mapped_column(Integer, nullable=False, default=0)
    parent_job_id:     Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"))

    user: Mapped[User] = relationship(back_populates="jobs")
