import pytest
from uuid import uuid4
from httpx import AsyncClient, ASGITransport
from db.models import User
from auth.deps import get_current_user
from worker.queue import get_arq_pool
from worker.tasks import process_job
from jobs import pipeline


class FakeArq:
    def __init__(self):
        self.queued = []

    async def enqueue_job(self, name, *args, **kw):
        self.queued.append((name, args))
        return None


@pytest.mark.asyncio
async def test_full_lifecycle(db_session, tmp_path, monkeypatch):
    from storage import files as fs
    monkeypatch.setattr(fs, "_files_root", lambda: tmp_path)
    monkeypatch.setattr(
        pipeline, "run_extraction",
        lambda b: ({"client": {"name": "Acme"}}, "<p>email</p>", b"%PDF-econsent")
    )

    user = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    db_session.add(user)
    await db_session.commit()

    from api.app import create_app
    from db.session import get_db

    app = create_app()
    fake = FakeArq()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_arq_pool] = lambda: fake
    app.dependency_overrides[get_db] = lambda: db_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 1. Create job
        r = await c.post(
            "/api/jobs",
            files={"file": ("x.pdf", b"%PDF-1.4 data", "application/pdf")},
        )
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]

        # 2. Status is pending
        r = await c.get(f"/api/jobs/{job_id}")
        assert r.json()["status"] == "pending"

        # 3. Run worker manually
        await process_job({"db": db_session}, job_id)

        # 4. Status is success
        r = await c.get(f"/api/jobs/{job_id}")
        body = r.json()
        assert body["status"] == "success", body
        assert body["has_econsent"] is True
        assert body["analysis_data"]["client"]["name"] == "Acme"
        assert body["email_html"] == "<p>email</p>"

        # 5. Econsent PDF available
        r = await c.get(f"/api/jobs/{job_id}/econsent.pdf")
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF")
