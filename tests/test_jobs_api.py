import pytest
from httpx import AsyncClient, ASGITransport
from uuid import uuid4
from db.models import User
from auth.deps import get_current_user
from db.session import get_db
from worker.queue import get_arq_pool


class FakeArq:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, name, *args, **kwargs):
        self.jobs.append((name, args))
        return None


@pytest.mark.asyncio
async def test_post_job_creates_pending(tmp_path, monkeypatch):
    from storage import files as fs
    monkeypatch.setattr(fs, "_files_root", lambda: tmp_path)

    from api.app import create_app
    app = create_app()

    user = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    fake_arq = FakeArq()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_arq_pool] = lambda: fake_arq

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
