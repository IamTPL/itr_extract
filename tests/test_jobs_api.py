import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from db.models import User, Job
from auth.deps import get_current_user
from db.session import get_db
from worker.queue import get_arq_pool
from config.enums import JobStatus
from datetime import datetime, timezone


class FakeArq:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, name, *args, **kwargs):
        self.jobs.append((name, args))
        return None


class FakeDb:
    """Minimal AsyncSession stub: count_active_jobs returns 0, create_job inserts a job."""

    def __init__(self):
        self._added = []
        self._job = None

    def add(self, obj):
        self._added.append(obj)
        if isinstance(obj, Job):
            self._job = obj

    async def commit(self):
        pass

    async def refresh(self, obj):
        # Populate server_default fields that the DB would normally set
        if isinstance(obj, Job) and obj.created_at is None:
            obj.created_at = datetime.now(timezone.utc)

    async def scalar(self, _query):
        return 0  # count_active_jobs → 0 active jobs

    async def scalars(self, _query):
        result = MagicMock()
        result.all.return_value = []
        return result

    async def delete(self, _obj):
        pass


@pytest.mark.asyncio
async def test_post_job_creates_pending(tmp_path, monkeypatch):
    from storage import files as fs
    monkeypatch.setattr(fs, "_files_root", lambda: tmp_path)

    from api.app import create_app
    app = create_app()

    user = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    fake_arq = FakeArq()
    fake_db = FakeDb()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_arq_pool] = lambda: fake_arq
    app.dependency_overrides[get_db] = lambda: fake_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/jobs",
            files={"file": ("x.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "pending"
    assert fake_arq.jobs and fake_arq.jobs[0][0] == "process_job"


@pytest.mark.asyncio
async def test_post_job_rejects_non_pdf(tmp_path, monkeypatch):
    from api.app import create_app
    app = create_app()
    user = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_arq_pool] = lambda: FakeArq()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/jobs",
            files={"file": ("x.txt", b"not a pdf", "text/plain")},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_get_voucher_pdf_200_when_has_voucher(db_session, tmp_path, monkeypatch):
    from storage import files as fs
    monkeypatch.setattr(fs, "_files_root", lambda: tmp_path)

    user = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    db_session.add(user)
    await db_session.commit()
    job = Job(id=uuid4(), user_id=user.id, original_filename="x.pdf", input_size_bytes=4, has_voucher=True)
    db_session.add(job)
    await db_session.commit()
    fs.write_voucher(user.id, job.id, b"%PDF-voucher")

    from api.app import create_app
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_arq_pool] = lambda: FakeArq()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/api/jobs/{job.id}/voucher.pdf")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_get_voucher_pdf_404_when_no_voucher(db_session, tmp_path, monkeypatch):
    from storage import files as fs
    monkeypatch.setattr(fs, "_files_root", lambda: tmp_path)

    user = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    db_session.add(user)
    await db_session.commit()
    job = Job(id=uuid4(), user_id=user.id, original_filename="x.pdf", input_size_bytes=4)
    db_session.add(job)
    await db_session.commit()

    from api.app import create_app
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_arq_pool] = lambda: FakeArq()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/api/jobs/{job.id}/voucher.pdf")
    assert r.status_code == 404
