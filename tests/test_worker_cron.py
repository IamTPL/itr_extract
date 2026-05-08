import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from db.models import User, Job
from config.enums import JobStatus
from worker.cron import requeue_stuck_jobs, cleanup_orphan_files


class FakeArq:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, name, *args, **kw):
        self.jobs.append((name, args))


@pytest.mark.asyncio
async def test_requeue_stuck_jobs(db_session):
    user = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    db_session.add(user)
    await db_session.commit()
    old = datetime.now(timezone.utc) - timedelta(minutes=20)
    j = Job(id=uuid4(), user_id=user.id, original_filename="x.pdf", input_size_bytes=1,
            status=JobStatus.PROCESSING, started_at=old)
    db_session.add(j)
    await db_session.commit()

    arq = FakeArq()
    n = await requeue_stuck_jobs(db_session, arq)
    await db_session.refresh(j)
    assert n == 1
    assert j.status == JobStatus.PENDING
    assert arq.jobs == [("process_job", (str(j.id),))]


@pytest.mark.asyncio
async def test_cleanup_orphan_files(db_session, tmp_path, monkeypatch):
    from storage import files as fs
    monkeypatch.setattr(fs, "_files_root", lambda: tmp_path)
    orphan = tmp_path / str(uuid4()) / str(uuid4())
    orphan.mkdir(parents=True)
    (orphan / "input.pdf").write_bytes(b"x")
    n = await cleanup_orphan_files(db_session)
    assert n == 1
    assert not orphan.exists()
