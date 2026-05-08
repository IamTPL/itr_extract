import pytest
from uuid import uuid4
from db.models import User, Job
from config.enums import JobStatus
from config.constants import MAX_RETRY_ATTEMPTS
from worker.tasks import process_job
from jobs import pipeline


class FakeCtx(dict):
    pass


@pytest.mark.asyncio
async def test_process_job_success(db_session, tmp_path, monkeypatch):
    from storage import files as fs
    monkeypatch.setattr(fs, "_files_root", lambda: tmp_path)
    monkeypatch.setattr(pipeline, "run_extraction",
                        lambda b: ({"k": "v"}, "<p>ok</p>", b"econsent-bytes"))
    user = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    db_session.add(user)
    await db_session.commit()
    job = Job(id=uuid4(), user_id=user.id, original_filename="x.pdf", input_size_bytes=4)
    db_session.add(job)
    await db_session.commit()
    fs.write_input(user.id, job.id, b"%PDF")

    ctx = FakeCtx(db=db_session)
    await process_job(ctx, str(job.id))
    await db_session.refresh(job)
    assert job.status == JobStatus.SUCCESS
    assert job.has_econsent is True
    assert fs.econsent_path(user.id, job.id).exists()


@pytest.mark.asyncio
async def test_process_job_final_retry_marks_failed(db_session, tmp_path, monkeypatch):
    from storage import files as fs
    monkeypatch.setattr(fs, "_files_root", lambda: tmp_path)

    def boom(_):
        raise RuntimeError("boom")

    monkeypatch.setattr(pipeline, "run_extraction", boom)
    user = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    db_session.add(user)
    await db_session.commit()
    # Set retry_count to MAX - 1 so next failure is final
    job = Job(id=uuid4(), user_id=user.id, original_filename="x.pdf",
              input_size_bytes=4, retry_count=MAX_RETRY_ATTEMPTS - 1)
    db_session.add(job)
    await db_session.commit()
    fs.write_input(user.id, job.id, b"%PDF")

    ctx = FakeCtx(db=db_session)
    # Final attempt — should NOT re-raise, should mark failed
    await process_job(ctx, str(job.id))
    await db_session.refresh(job)
    assert job.status == JobStatus.FAILED
    assert "boom" in (job.error_message or "")
