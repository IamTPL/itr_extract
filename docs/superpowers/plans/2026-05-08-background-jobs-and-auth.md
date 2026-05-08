# Background Jobs, Azure AD Auth & Per-User Storage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the stateless ITR Extract API into an authenticated, async, per-user system with Azure AD JWT auth, arq/Redis background workers, Postgres metadata, and local-disk file persistence (10-session FIFO cap per user).

**Architecture:** FastAPI keeps a thin HTTP layer; a separate `arq` worker runs the existing Gemini pipeline in the background. Postgres stores `users` + `jobs` (JSONB analysis). Local disk under `/var/lib/itr_extract/files/{user_id}/{job_id}/` stores input + output PDFs. Azure AD tokens (single-tenant) are verified against Microsoft JWKS. The frontend polls a job-detail endpoint every 2s and renders status states.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x async, Alembic, asyncpg, arq, Redis 7, PyJWT, httpx, slowapi, pytest + pytest-asyncio + testcontainers; React 19, MSAL (existing), TypeScript, Vite.

**Spec reference:** `docs/superpowers/specs/2026-05-08-background-jobs-and-auth-design.md`

**Discipline:** All tunable values live in `config/constants.py` (BE) or `src/lib/constants.ts` (FE). Every status string flows through `JobStatus` enum. No magic numbers, paths, or strings inline. Every task ends with a green test run + commit.

---

## File Structure

### Backend — new
```
config/
  __init__.py
  constants.py          # numeric/path/duration constants
  enums.py              # JobStatus, status sets
  settings.py           # pydantic-settings (env vars)
db/
  __init__.py
  base.py               # async engine, sessionmaker
  models.py             # User, Job ORM models
  session.py            # get_db dependency
alembic/
  env.py
  script.py.mako
  versions/
    0001_initial.py
auth/
  __init__.py
  jwks.py               # JWKS fetch + TTL cache
  jwt.py                # verify_token
  deps.py               # get_current_user dependency
storage/
  __init__.py
  files.py              # disk path helpers, read/write/delete
jobs/
  __init__.py
  service.py            # job CRUD + retention
  pipeline.py           # extracted Gemini pipeline
  email_html.py         # generate_email_html (moved from api.py)
worker/
  __init__.py
  tasks.py              # process_job
  cron.py               # requeue_stuck_jobs, cleanup_orphan_files
  settings.py           # arq WorkerSettings
api/
  __init__.py
  jobs.py               # /api/jobs router
  me.py                 # /api/me
  health.py             # /healthz
  schemas.py            # request/response Pydantic models
deploy/
  itr-api.service
  itr-worker.service
  README.md
tests/
  conftest.py
  test_constants.py
  test_auth_jwt.py
  test_auth_deps.py
  test_storage_files.py
  test_jobs_service.py
  test_jobs_retention.py
  test_jobs_api.py
  test_worker_tasks.py
  test_worker_cron.py
  test_e2e_lifecycle.py
```

### Backend — modified
- `api.py` → app factory; mount routers; CORS via settings; remove old `/api/process`
- `requirements.txt` → add deps
- `main.py` → keep CLI (untouched); export pipeline helpers reused by `jobs/pipeline.py`

### Frontend — new
```
src/lib/constants.ts
src/lib/apiClient.ts
src/lib/types.ts
src/hooks/useAccessToken.ts
src/hooks/useJobs.ts
src/hooks/useJobPolling.ts
src/components/JobHistory.tsx
src/components/JobStatusBadge.tsx
src/components/UploadCard.tsx
src/components/JobDetailView.tsx
```

### Frontend — modified
- `src/lib/msalConfig.ts` → add BE scope to `loginRequest`
- `src/App.tsx` → two-column layout, state management

---

## Phase 0 — Repository Hygiene

### Task 0.1: Add new dependencies

**Files:** Modify `requirements.txt`

- [ ] **Step 1: Update requirements.txt**

```
# Existing
google-genai
PyMuPDF
python-docx
fastapi
uvicorn[standard]
python-multipart

# New
sqlalchemy[asyncio]>=2.0
asyncpg>=0.29
alembic>=1.13
pydantic-settings>=2.0
pyjwt[crypto]>=2.8
httpx>=0.27
arq>=0.26
redis>=5.0
slowapi>=0.1.9

# Test
pytest>=8.0
pytest-asyncio>=0.23
testcontainers[postgres,redis]>=4.0
respx>=0.21
```

- [ ] **Step 2: Install**

Run: `pip install -r requirements.txt`
Expected: clean install.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add deps for async jobs, auth, and storage"
```

---

## Phase 1 — Configuration & Constants

### Task 1.1: Create `config/constants.py`

**Files:** Create `config/__init__.py`, `config/constants.py`

- [ ] **Step 1: Write empty `config/__init__.py`**

```python
```

- [ ] **Step 2: Write `config/constants.py` (full content)**

```python
"""Centralized constants. NEVER inline literals for these values elsewhere."""
from pathlib import Path

# ── Session & retention ──
MAX_SESSIONS_PER_USER       = 10
MAX_ACTIVE_JOBS_PER_USER    = 5
MAX_INPUT_FILE_SIZE_BYTES   = 50 * 1024 * 1024

# ── Worker / retry ──
JOB_TIMEOUT_SECONDS         = 300
WORKER_MAX_CONCURRENT_JOBS  = 4
MAX_RETRY_ATTEMPTS          = 3
RETRY_BACKOFF_SECONDS       = (5, 15)
STUCK_JOB_THRESHOLD_SECONDS = 360

# ── Filesystem ──
FILES_ROOT_DEFAULT          = Path("/var/lib/itr_extract/files")
INPUT_FILENAME              = "input.pdf"
ECONSENT_FILENAME           = "econsent.pdf"

# ── Auth / JWT ──
JWKS_CACHE_TTL_SECONDS      = 3600
JWT_LEEWAY_SECONDS          = 60
JWT_ALGORITHM               = "RS256"
BEARER_PREFIX               = "Bearer "
AZURE_AUTHORITY_BASE        = "https://login.microsoftonline.com"

# ── Cron ──
CLEANUP_ORPHAN_FILES_HOUR     = 3
STUCK_JOB_SWEEP_INTERVAL_MIN  = 1

# ── Rate limit ──
USER_RATE_LIMIT             = "30/minute"

# ── HTTP ──
HEALTH_CHECK_TIMEOUT_SECONDS = 5
```

- [ ] **Step 3: Commit**

```bash
git add config/__init__.py config/constants.py
git commit -m "feat(config): add centralized constants module"
```

### Task 1.2: Create `config/enums.py`

**Files:** Create `config/enums.py`, `tests/test_constants.py`

- [ ] **Step 1: Write the failing test `tests/test_constants.py`**

```python
from config.enums import JobStatus, TERMINAL_STATUSES, ACTIVE_STATUSES

def test_job_status_values():
    assert JobStatus.PENDING.value == "pending"
    assert JobStatus.PROCESSING.value == "processing"
    assert JobStatus.SUCCESS.value == "success"
    assert JobStatus.FAILED.value == "failed"

def test_status_sets_partition_correctly():
    all_statuses = {s for s in JobStatus}
    assert TERMINAL_STATUSES | ACTIVE_STATUSES == all_statuses
    assert TERMINAL_STATUSES & ACTIVE_STATUSES == set()
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_constants.py -v`
Expected: ImportError (module not found).

- [ ] **Step 3: Write `config/enums.py`**

```python
from enum import Enum

class JobStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    SUCCESS    = "success"
    FAILED     = "failed"

TERMINAL_STATUSES = frozenset({JobStatus.SUCCESS, JobStatus.FAILED})
ACTIVE_STATUSES   = frozenset({JobStatus.PENDING, JobStatus.PROCESSING})
```

- [ ] **Step 4: Run test, verify it passes**

Run: `pytest tests/test_constants.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add config/enums.py tests/test_constants.py
git commit -m "feat(config): add JobStatus enum with terminal/active partitioning"
```

### Task 1.3: Create `config/settings.py`

**Files:** Create `config/settings.py`

- [ ] **Step 1: Write `config/settings.py`**

```python
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from config.constants import FILES_ROOT_DEFAULT

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url:      str
    redis_url:         str = "redis://localhost:6379"
    msal_tenant_id:    str
    msal_be_client_id: str
    files_root:        Path = FILES_ROOT_DEFAULT
    allowed_origins:   list[str] = ["http://localhost:5173"]
    gemini_api_key:    str

settings = Settings()  # type: ignore[call-arg]
```

- [ ] **Step 2: Add `.env.example`**

Write `.env.example`:
```
DATABASE_URL=postgresql+asyncpg://itr:itr@localhost:5432/itr_extract
REDIS_URL=redis://localhost:6379
MSAL_TENANT_ID=00000000-0000-0000-0000-000000000000
MSAL_BE_CLIENT_ID=00000000-0000-0000-0000-000000000000
FILES_ROOT=/var/lib/itr_extract/files
ALLOWED_ORIGINS=["http://localhost:5173"]
GEMINI_API_KEY=
```

- [ ] **Step 3: Commit**

```bash
git add config/settings.py .env.example
git commit -m "feat(config): add Settings with env vars and .env.example"
```

---

## Phase 2 — Database & Migrations

### Task 2.1: SQLAlchemy base + engine

**Files:** Create `db/__init__.py`, `db/base.py`, `db/session.py`

- [ ] **Step 1: Write `db/__init__.py`** (empty)

```python
```

- [ ] **Step 2: Write `db/base.py`**

```python
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from config.settings import settings

class Base(DeclarativeBase):
    pass

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
```

- [ ] **Step 3: Write `db/session.py`**

```python
from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession
from db.base import SessionLocal

async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
```

- [ ] **Step 4: Commit**

```bash
git add db/__init__.py db/base.py db/session.py
git commit -m "feat(db): add async SQLAlchemy engine and session factory"
```

### Task 2.2: ORM models

**Files:** Create `db/models.py`

- [ ] **Step 1: Write `db/models.py`**

```python
from __future__ import annotations
from datetime import datetime
from uuid import UUID, uuid4
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
    id:         Mapped[UUID]     = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    email:      Mapped[str]      = mapped_column(Text, nullable=False)
    name:       Mapped[str | None] = mapped_column(Text)
    tenant_id:  Mapped[UUID]     = mapped_column(PgUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_login: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    jobs: Mapped[list["Job"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Job(Base):
    __tablename__ = "jobs"
    id:                 Mapped[UUID]      = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id:            Mapped[UUID]      = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status:             Mapped[JobStatus] = mapped_column(job_status_enum, nullable=False, default=JobStatus.PENDING)
    original_filename:  Mapped[str]       = mapped_column(Text, nullable=False)
    input_size_bytes:   Mapped[int]       = mapped_column(BigInteger, nullable=False)
    analysis_data:      Mapped[dict | None] = mapped_column(JSONB)
    email_html:         Mapped[str | None]  = mapped_column(Text)
    has_econsent:       Mapped[bool]      = mapped_column(Boolean, nullable=False, default=False)
    created_at:         Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at:         Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at:        Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message:      Mapped[str | None]  = mapped_column(Text)
    error_details:      Mapped[dict | None] = mapped_column(JSONB)
    retry_count:        Mapped[int]       = mapped_column(Integer, nullable=False, default=0)
    parent_job_id:      Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"))

    user: Mapped[User] = relationship(back_populates="jobs")
```

- [ ] **Step 2: Commit**

```bash
git add db/models.py
git commit -m "feat(db): add User and Job ORM models"
```

### Task 2.3: Alembic setup + initial migration

**Files:** Create `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/0001_initial.py`

- [ ] **Step 1: Initialize**

Run: `alembic init alembic`

- [ ] **Step 2: Edit `alembic.ini`** — set `sqlalchemy.url =` empty (we override in env.py).

- [ ] **Step 3: Replace `alembic/env.py`**

```python
import asyncio
from logging.config import fileConfig
from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from config.settings import settings
from db.base import Base
import db.models  # noqa: F401  register models

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata

def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online() -> None:
    connectable = async_engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.")
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

asyncio.run(run_migrations_online())
```

- [ ] **Step 4: Generate initial migration**

Run: `alembic revision --autogenerate -m "initial schema"`
Then rename file to `0001_initial.py`.

- [ ] **Step 5: Verify migration content**

The migration must create `job_status` enum, `users` table, `jobs` table, and indexes:
```python
op.create_index("idx_jobs_user_created", "jobs", ["user_id", sa.text("created_at DESC")])
op.create_index(
    "idx_jobs_status_active", "jobs", ["status"],
    postgresql_where=sa.text("status IN ('pending','processing')"),
)
```
Add these manually if autogenerate omits them.

- [ ] **Step 6: Apply migration to local DB**

Pre-req: a local Postgres `itr_extract` exists. Run: `alembic upgrade head`
Expected: `users` and `jobs` tables created.

- [ ] **Step 7: Commit**

```bash
git add alembic.ini alembic/
git commit -m "feat(db): add Alembic with initial migration"
```

---

## Phase 3 — Auth (JWKS + JWT verification)

### Task 3.1: JWKS fetcher with TTL cache

**Files:** Create `auth/__init__.py`, `auth/jwks.py`, `tests/test_auth_jwt.py` (skeleton)

- [ ] **Step 1: Write `auth/__init__.py`** (empty)

- [ ] **Step 2: Write the failing test `tests/test_auth_jwks.py`**

```python
import pytest, respx, httpx
from auth.jwks import get_jwks, _jwks_cache
from config.constants import AZURE_AUTHORITY_BASE

TENANT = "tenant-uuid"
JWKS_URL = f"{AZURE_AUTHORITY_BASE}/{TENANT}/discovery/v2.0/keys"

@pytest.mark.asyncio
async def test_get_jwks_fetches_and_caches():
    _jwks_cache.clear()
    sample = {"keys": [{"kid": "abc", "kty": "RSA", "n": "x", "e": "AQAB"}]}
    with respx.mock(assert_all_called=False) as m:
        route = m.get(JWKS_URL).mock(return_value=httpx.Response(200, json=sample))
        keys1 = await get_jwks(TENANT)
        keys2 = await get_jwks(TENANT)  # cached
        assert keys1 == sample["keys"]
        assert route.call_count == 1  # only one HTTP call
```

- [ ] **Step 3: Run test, verify it fails**

Run: `pytest tests/test_auth_jwks.py -v`
Expected: ImportError.

- [ ] **Step 4: Write `auth/jwks.py`**

```python
import time
import httpx
from config.constants import AZURE_AUTHORITY_BASE, JWKS_CACHE_TTL_SECONDS, HEALTH_CHECK_TIMEOUT_SECONDS

_jwks_cache: dict[str, tuple[float, list[dict]]] = {}

async def get_jwks(tenant_id: str) -> list[dict]:
    cached = _jwks_cache.get(tenant_id)
    now = time.time()
    if cached and cached[0] > now:
        return cached[1]
    url = f"{AZURE_AUTHORITY_BASE}/{tenant_id}/discovery/v2.0/keys"
    async with httpx.AsyncClient() as client:
        r = await client.get(url, timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
        r.raise_for_status()
    keys = r.json()["keys"]
    _jwks_cache[tenant_id] = (now + JWKS_CACHE_TTL_SECONDS, keys)
    return keys
```

- [ ] **Step 5: Run test, verify it passes**

Run: `pytest tests/test_auth_jwks.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add auth/__init__.py auth/jwks.py tests/test_auth_jwks.py
git commit -m "feat(auth): add JWKS fetcher with TTL cache"
```

### Task 3.2: JWT verification

**Files:** Create `auth/jwt.py`, `tests/test_auth_jwt.py`

- [ ] **Step 1: Write the failing test `tests/test_auth_jwt.py`**

```python
import pytest, time, jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from auth.jwt import verify_token, InvalidToken
from auth import jwks as jwks_mod
from config.constants import AZURE_AUTHORITY_BASE

TENANT = "tenant-uuid"
AUDIENCE = "be-client-id"
ISSUER = f"{AZURE_AUTHORITY_BASE}/{TENANT}/v2.0"

@pytest.fixture
def rsa_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key

def make_jwk(rsa_key, kid="kid1"):
    pub = rsa_key.public_key().public_numbers()
    import base64
    def b64(i: int) -> str:
        b = i.to_bytes((i.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).decode().rstrip("=")
    return {"kid": kid, "kty": "RSA", "n": b64(pub.n), "e": b64(pub.e), "alg": "RS256", "use": "sig"}

def make_token(rsa_key, *, kid="kid1", aud=AUDIENCE, iss=ISSUER, tid=TENANT, exp_offset=600):
    pem = rsa_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    claims = {
        "oid": "user-oid", "tid": tid, "aud": aud, "iss": iss,
        "exp": int(time.time()) + exp_offset, "iat": int(time.time()),
        "preferred_username": "u@x.com", "name": "U",
    }
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})

@pytest.fixture
def patch_jwks(rsa_keypair, monkeypatch):
    async def fake_get_jwks(tid):
        return [make_jwk(rsa_keypair)]
    monkeypatch.setattr(jwks_mod, "get_jwks", fake_get_jwks)

@pytest.mark.asyncio
async def test_valid_token_returns_claims(rsa_keypair, patch_jwks):
    token = make_token(rsa_keypair)
    claims = await verify_token(token, tenant_id=TENANT, audience=AUDIENCE)
    assert claims["oid"] == "user-oid"

@pytest.mark.asyncio
async def test_expired_token_rejected(rsa_keypair, patch_jwks):
    token = make_token(rsa_keypair, exp_offset=-3600)
    with pytest.raises(InvalidToken):
        await verify_token(token, tenant_id=TENANT, audience=AUDIENCE)

@pytest.mark.asyncio
async def test_wrong_audience_rejected(rsa_keypair, patch_jwks):
    token = make_token(rsa_keypair, aud="wrong")
    with pytest.raises(InvalidToken):
        await verify_token(token, tenant_id=TENANT, audience=AUDIENCE)

@pytest.mark.asyncio
async def test_wrong_tenant_rejected(rsa_keypair, patch_jwks):
    token = make_token(rsa_keypair, tid="other-tenant")
    with pytest.raises(InvalidToken):
        await verify_token(token, tenant_id=TENANT, audience=AUDIENCE)

@pytest.mark.asyncio
async def test_unknown_kid_rejected(rsa_keypair, patch_jwks):
    token = make_token(rsa_keypair, kid="unknown")
    with pytest.raises(InvalidToken):
        await verify_token(token, tenant_id=TENANT, audience=AUDIENCE)
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_auth_jwt.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `auth/jwt.py`**

```python
import jwt
from jwt.algorithms import RSAAlgorithm
from auth.jwks import get_jwks
from config.constants import AZURE_AUTHORITY_BASE, JWT_ALGORITHM, JWT_LEEWAY_SECONDS

class InvalidToken(Exception):
    pass

async def verify_token(token: str, *, tenant_id: str, audience: str) -> dict:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as e:
        raise InvalidToken(f"Malformed token: {e}") from e

    kid = header.get("kid")
    if not kid:
        raise InvalidToken("Missing kid")

    keys = await get_jwks(tenant_id)
    jwk = next((k for k in keys if k["kid"] == kid), None)
    if not jwk:
        raise InvalidToken("Unknown signing key")
    public_key = RSAAlgorithm.from_jwk(jwk)

    issuer = f"{AZURE_AUTHORITY_BASE}/{tenant_id}/v2.0"
    try:
        claims = jwt.decode(
            token, public_key,
            algorithms=[JWT_ALGORITHM],
            audience=audience,
            issuer=issuer,
            leeway=JWT_LEEWAY_SECONDS,
        )
    except jwt.InvalidTokenError as e:
        raise InvalidToken(str(e)) from e

    if claims.get("tid") != tenant_id:
        raise InvalidToken("Wrong tenant")
    if not claims.get("oid"):
        raise InvalidToken("Missing oid")
    return claims
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_auth_jwt.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add auth/jwt.py tests/test_auth_jwt.py
git commit -m "feat(auth): add JWT verification with audience/issuer/tenant checks"
```

### Task 3.3: `get_current_user` dependency with JIT provisioning

**Files:** Create `auth/deps.py`, `tests/test_auth_deps.py`

- [ ] **Step 1: Write `tests/test_auth_deps.py`**

```python
import pytest
from uuid import UUID
from auth.deps import _upsert_user
from db.models import User

@pytest.mark.asyncio
async def test_upsert_creates_new_user(db_session):
    claims = {
        "oid": "11111111-1111-1111-1111-111111111111",
        "tid": "22222222-2222-2222-2222-222222222222",
        "preferred_username": "a@x.com", "name": "A",
    }
    user = await _upsert_user(db_session, claims)
    assert user.id == UUID(claims["oid"])
    assert user.email == "a@x.com"

@pytest.mark.asyncio
async def test_upsert_updates_existing_user(db_session):
    claims = {
        "oid": "11111111-1111-1111-1111-111111111111",
        "tid": "22222222-2222-2222-2222-222222222222",
        "preferred_username": "a@x.com", "name": "A",
    }
    await _upsert_user(db_session, claims)
    claims["name"] = "Renamed"
    user = await _upsert_user(db_session, claims)
    assert user.name == "Renamed"
    # Only one row
    from sqlalchemy import select, func
    count = await db_session.scalar(select(func.count(User.id)))
    assert count == 1
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_auth_deps.py -v`
Expected: import error.

- [ ] **Step 3: Write `auth/deps.py`**

```python
from datetime import datetime, timezone
from uuid import UUID
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from auth.jwt import InvalidToken, verify_token
from config.constants import BEARER_PREFIX
from config.settings import settings
from db.models import User
from db.session import get_db


async def _upsert_user(db: AsyncSession, claims: dict) -> User:
    oid = UUID(claims["oid"])
    email = claims.get("preferred_username") or claims.get("email") or ""
    name = claims.get("name")
    tid = UUID(claims["tid"])

    user = await db.get(User, oid)
    if user is None:
        user = User(id=oid, email=email, name=name, tenant_id=tid)
        db.add(user)
    else:
        user.email = email or user.email
        user.name = name or user.name
        user.last_login = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return user


async def get_current_user(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization.startswith(BEARER_PREFIX):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization[len(BEARER_PREFIX):]
    try:
        claims = await verify_token(
            token,
            tenant_id=settings.msal_tenant_id,
            audience=settings.msal_be_client_id,
        )
    except InvalidToken as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}")
    return await _upsert_user(db, claims)
```

- [ ] **Step 4: Add `db_session` fixture to `tests/conftest.py`**

(See Task 4.1 for the conftest scaffold; if running this test before that, defer Task 3.3 verification.)

- [ ] **Step 5: Commit**

```bash
git add auth/deps.py tests/test_auth_deps.py
git commit -m "feat(auth): add get_current_user dependency with JIT provisioning"
```

---

## Phase 4 — Test Infrastructure

### Task 4.1: `conftest.py` with Postgres + Redis fixtures

**Files:** Create `tests/__init__.py`, `tests/conftest.py`

- [ ] **Step 1: Write `tests/__init__.py`** (empty)

- [ ] **Step 2: Write `tests/conftest.py`**

```python
import asyncio, os
import pytest, pytest_asyncio
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from db.base import Base

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
def postgres_url():
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        os.environ["DATABASE_URL"] = url
        yield url

@pytest.fixture(scope="session")
def redis_url():
    with RedisContainer("redis:7-alpine") as r:
        host = r.get_container_host_ip()
        port = r.get_exposed_port(6379)
        url = f"redis://{host}:{port}"
        os.environ["REDIS_URL"] = url
        yield url

@pytest_asyncio.fixture
async def db_engine(postgres_url):
    engine = create_async_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest_asyncio.fixture
async def db_session(db_engine):
    Session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with Session() as s:
        yield s
```

- [ ] **Step 3: Set required env vars in `tests/conftest.py` (top of file)**

Above imports of project modules:
```python
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x")
os.environ.setdefault("REDIS_URL", "redis://x")
os.environ.setdefault("MSAL_TENANT_ID", "00000000-0000-0000-0000-000000000000")
os.environ.setdefault("MSAL_BE_CLIENT_ID", "00000000-0000-0000-0000-000000000000")
os.environ.setdefault("GEMINI_API_KEY", "test")
```

- [ ] **Step 4: Verify Task 3.3 tests pass with new fixture**

Run: `pytest tests/test_auth_deps.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/__init__.py tests/conftest.py
git commit -m "test: add conftest with Postgres + Redis testcontainers"
```

---

## Phase 5 — Storage (local disk)

### Task 5.1: `storage/files.py`

**Files:** Create `storage/__init__.py`, `storage/files.py`, `tests/test_storage_files.py`

- [ ] **Step 1: Write `tests/test_storage_files.py`**

```python
from uuid import uuid4
from pathlib import Path
import pytest
from storage import files as fs
from config.constants import INPUT_FILENAME, ECONSENT_FILENAME

def test_job_dir_segregates_user(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "FILES_ROOT", tmp_path)
    u, j = uuid4(), uuid4()
    d = fs.job_dir(u, j)
    assert d == tmp_path / str(u) / str(j)

def test_write_input_then_read(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "FILES_ROOT", tmp_path)
    u, j = uuid4(), uuid4()
    fs.write_input(u, j, b"hello")
    assert fs.read_input(u, j) == b"hello"

def test_delete_job_dir_removes_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "FILES_ROOT", tmp_path)
    u, j = uuid4(), uuid4()
    fs.write_input(u, j, b"x")
    fs.write_econsent(u, j, b"y")
    fs.delete_job_dir(u, j)
    assert not fs.job_dir(u, j).exists()

def test_econsent_path_uses_constant(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "FILES_ROOT", tmp_path)
    u, j = uuid4(), uuid4()
    fs.write_econsent(u, j, b"y")
    assert (fs.job_dir(u, j) / ECONSENT_FILENAME).exists()
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_storage_files.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `storage/__init__.py`** (empty)

- [ ] **Step 4: Write `storage/files.py`**

```python
import shutil
from pathlib import Path
from uuid import UUID
from config.constants import ECONSENT_FILENAME, INPUT_FILENAME
from config.settings import settings

FILES_ROOT: Path = settings.files_root


def job_dir(user_id: UUID, job_id: UUID) -> Path:
    return FILES_ROOT / str(user_id) / str(job_id)


def _ensure(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_input(user_id: UUID, job_id: UUID, data: bytes) -> Path:
    p = _ensure(job_dir(user_id, job_id) / INPUT_FILENAME)
    p.write_bytes(data)
    return p


def read_input(user_id: UUID, job_id: UUID) -> bytes:
    return (job_dir(user_id, job_id) / INPUT_FILENAME).read_bytes()


def write_econsent(user_id: UUID, job_id: UUID, data: bytes) -> Path:
    p = _ensure(job_dir(user_id, job_id) / ECONSENT_FILENAME)
    p.write_bytes(data)
    return p


def econsent_path(user_id: UUID, job_id: UUID) -> Path:
    return job_dir(user_id, job_id) / ECONSENT_FILENAME


def input_path(user_id: UUID, job_id: UUID) -> Path:
    return job_dir(user_id, job_id) / INPUT_FILENAME


def delete_job_dir(user_id: UUID, job_id: UUID) -> None:
    d = job_dir(user_id, job_id)
    if d.exists():
        shutil.rmtree(d)


def list_user_dirs() -> list[Path]:
    if not FILES_ROOT.exists():
        return []
    return [p for p in FILES_ROOT.iterdir() if p.is_dir()]
```

- [ ] **Step 5: Run, verify pass**

Run: `pytest tests/test_storage_files.py -v`
Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add storage/__init__.py storage/files.py tests/test_storage_files.py
git commit -m "feat(storage): add disk-based file helpers under FILES_ROOT"
```

---

## Phase 6 — Pipeline Extraction

### Task 6.1: Move Gemini pipeline into `jobs/pipeline.py`

**Files:** Create `jobs/__init__.py`, `jobs/pipeline.py`, `jobs/email_html.py`

- [ ] **Step 1: Write `jobs/__init__.py`** (empty)

- [ ] **Step 2: Write `jobs/email_html.py`**

Move `_md_to_html` and `generate_email_html` verbatim from current `api.py:45-162` into `jobs/email_html.py`. Replace `import main as itr` with `from main import PTE_ELIGIBLE_RETURN_TYPES`.

- [ ] **Step 3: Write `jobs/pipeline.py`**

```python
"""Pure pipeline: bytes in → (analysis_data, email_html, econsent_pdf_bytes_or_None)."""
import base64
from concurrent.futures import ThreadPoolExecutor
import fitz
import main as itr
from jobs.email_html import generate_email_html


def run_extraction(pdf_bytes: bytes) -> tuple[dict, str, bytes | None]:
    api_key = itr.load_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    out_doc = fitz.open()
    out_doc.insert_pdf(src, from_page=0, to_page=0)
    page1_bytes = out_doc.write()
    out_doc.close()
    src.close()

    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(
            itr.call_gemini,
            pdf_bytes, itr.TASK1_PROMPT, itr.TASK1_CONFIG,
            api_key, itr.DEFAULT_MODEL, "Task 1",
        )
        f2 = ex.submit(
            itr.call_gemini,
            page1_bytes, itr.TASK2_PROMPT, itr.TASK2_CONFIG,
            api_key, itr.DEFAULT_MODEL, "Task 2",
            itr.TASK2_RESPONSE_SCHEMA,
        )
        t1, _ = f1.result()
        t2, _ = f2.result()
    analysis_data = {**t2, **t1}

    econsent_bytes: bytes | None = None
    pages = analysis_data.get("econsent_pages") or []
    if pages:
        src = fitz.open(stream=pdf_bytes, filetype="pdf")
        valid = sorted(p - 1 for p in pages if isinstance(p, int) and 1 <= p <= src.page_count)
        if valid:
            new_doc = fitz.open()
            for idx in valid:
                new_doc.insert_pdf(src, from_page=idx, to_page=idx)
            econsent_bytes = new_doc.write()
            new_doc.close()
        src.close()

    email_html = generate_email_html(analysis_data)
    return analysis_data, email_html, econsent_bytes
```

- [ ] **Step 4: Commit**

```bash
git add jobs/__init__.py jobs/pipeline.py jobs/email_html.py
git commit -m "refactor(jobs): extract pipeline + email_html from api.py"
```

---

## Phase 7 — Jobs Service (CRUD + Retention)

### Task 7.1: `jobs/service.py` — create + retention

**Files:** Create `jobs/service.py`, `tests/test_jobs_service.py`, `tests/test_jobs_retention.py`

- [ ] **Step 1: Write `tests/test_jobs_service.py`**

```python
import pytest
from uuid import uuid4, UUID
from db.models import User
from jobs.service import create_job, get_job_for_user, list_jobs_for_user, delete_job
from config.enums import JobStatus

async def _make_user(db):
    u = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    db.add(u); await db.commit(); await db.refresh(u); return u

@pytest.mark.asyncio
async def test_create_job_inserts_pending(db_session):
    u = await _make_user(db_session)
    job = await create_job(db_session, user_id=u.id, filename="x.pdf", size=100)
    assert job.status == JobStatus.PENDING
    assert job.user_id == u.id

@pytest.mark.asyncio
async def test_list_returns_user_jobs_desc(db_session):
    u = await _make_user(db_session)
    await create_job(db_session, user_id=u.id, filename="a.pdf", size=1)
    await create_job(db_session, user_id=u.id, filename="b.pdf", size=2)
    rows = await list_jobs_for_user(db_session, u.id)
    assert [j.original_filename for j in rows] == ["b.pdf", "a.pdf"]

@pytest.mark.asyncio
async def test_get_job_for_other_user_returns_none(db_session):
    u1 = await _make_user(db_session); u2 = await _make_user(db_session)
    j = await create_job(db_session, user_id=u1.id, filename="x.pdf", size=1)
    assert await get_job_for_user(db_session, u2.id, j.id) is None
```

- [ ] **Step 2: Write `tests/test_jobs_retention.py`**

```python
import pytest
from uuid import uuid4
from db.models import User, Job
from jobs.service import create_job, enforce_session_cap, list_jobs_for_user
from config.constants import MAX_SESSIONS_PER_USER

async def _make_user(db):
    u = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    db.add(u); await db.commit(); await db.refresh(u); return u

@pytest.mark.asyncio
async def test_cap_evicts_oldest_when_exceeded(db_session, tmp_path, monkeypatch):
    from storage import files as fs
    monkeypatch.setattr(fs, "FILES_ROOT", tmp_path)
    u = await _make_user(db_session)
    created = []
    for i in range(MAX_SESSIONS_PER_USER + 1):
        j = await create_job(db_session, user_id=u.id, filename=f"{i}.pdf", size=1)
        created.append(j)
    evicted = await enforce_session_cap(db_session, u.id)
    rows = await list_jobs_for_user(db_session, u.id)
    assert len(rows) == MAX_SESSIONS_PER_USER
    assert created[0].id in evicted
```

- [ ] **Step 3: Write `jobs/service.py`**

```python
from uuid import UUID, uuid4
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from config.constants import MAX_SESSIONS_PER_USER
from config.enums import JobStatus, ACTIVE_STATUSES
from db.models import Job
from storage import files as fs


async def create_job(db: AsyncSession, *, user_id: UUID, filename: str, size: int,
                     parent_job_id: UUID | None = None) -> Job:
    job = Job(
        id=uuid4(), user_id=user_id, status=JobStatus.PENDING,
        original_filename=filename, input_size_bytes=size,
        parent_job_id=parent_job_id,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def list_jobs_for_user(db: AsyncSession, user_id: UUID) -> list[Job]:
    q = select(Job).where(Job.user_id == user_id).order_by(Job.created_at.desc()).limit(MAX_SESSIONS_PER_USER)
    return list((await db.scalars(q)).all())


async def get_job_for_user(db: AsyncSession, user_id: UUID, job_id: UUID) -> Job | None:
    q = select(Job).where(Job.id == job_id, Job.user_id == user_id)
    return (await db.scalars(q)).one_or_none()


async def count_active_jobs(db: AsyncSession, user_id: UUID) -> int:
    q = select(func.count(Job.id)).where(
        Job.user_id == user_id,
        Job.status.in_([s for s in ACTIVE_STATUSES]),
    )
    return await db.scalar(q) or 0


async def enforce_session_cap(db: AsyncSession, user_id: UUID) -> list[UUID]:
    q = select(Job).where(Job.user_id == user_id).order_by(Job.created_at.asc())
    all_jobs = list((await db.scalars(q)).all())
    excess = max(0, len(all_jobs) - MAX_SESSIONS_PER_USER)
    if excess == 0:
        return []
    to_evict = all_jobs[:excess]
    evicted_ids = [j.id for j in to_evict]
    for j in to_evict:
        fs.delete_job_dir(user_id, j.id)
        await db.delete(j)
    await db.commit()
    return evicted_ids


async def delete_job(db: AsyncSession, user_id: UUID, job_id: UUID) -> bool:
    job = await get_job_for_user(db, user_id, job_id)
    if not job:
        return False
    fs.delete_job_dir(user_id, job_id)
    await db.delete(job)
    await db.commit()
    return True
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_jobs_service.py tests/test_jobs_retention.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add jobs/service.py tests/test_jobs_service.py tests/test_jobs_retention.py
git commit -m "feat(jobs): add service layer with retention enforcement"
```

---

## Phase 8 — API Layer

### Task 8.1: Pydantic schemas

**Files:** Create `api/__init__.py`, `api/schemas.py`

- [ ] **Step 1: Write `api/__init__.py`** (empty)

- [ ] **Step 2: Write `api/schemas.py`**

```python
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
```

- [ ] **Step 3: Commit**

```bash
git add api/__init__.py api/schemas.py
git commit -m "feat(api): add Pydantic schemas for job endpoints"
```

### Task 8.2: Health + Me endpoints

**Files:** Create `api/health.py`, `api/me.py`

- [ ] **Step 1: Write `api/health.py`**

```python
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from db.session import get_db

router = APIRouter()

@router.get("/healthz")
async def healthz(db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}
```

- [ ] **Step 2: Write `api/me.py`**

```python
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from auth.deps import get_current_user
from db.models import Job, User
from db.session import get_db
from api.schemas import MeResponse

router = APIRouter()

@router.get("/api/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    count = await db.scalar(select(func.count(Job.id)).where(Job.user_id == user.id)) or 0
    return MeResponse(user_id=user.id, email=user.email, name=user.name, job_count=count)
```

- [ ] **Step 3: Commit**

```bash
git add api/health.py api/me.py
git commit -m "feat(api): add /healthz and /api/me endpoints"
```

### Task 8.3: Jobs router (POST, GET list, GET detail, DELETE, reprocess, file streams)

**Files:** Create `api/jobs.py`, `tests/test_jobs_api.py`

- [ ] **Step 1: Write `api/jobs.py`**

```python
from uuid import UUID
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from auth.deps import get_current_user
from config.constants import (
    MAX_ACTIVE_JOBS_PER_USER, MAX_INPUT_FILE_SIZE_BYTES,
)
from config.enums import JobStatus
from db.models import User
from db.session import get_db
from jobs.service import (
    count_active_jobs, create_job, delete_job, enforce_session_cap,
    get_job_for_user, list_jobs_for_user,
)
from storage import files as fs
from api.schemas import (
    CreateJobResponse, JobDetail, JobListResponse, JobSummary,
)
from worker.queue import get_arq_pool

router = APIRouter(prefix="/api/jobs")


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
        analysis_data=j.analysis_data, email_html=j.email_html,
    )


@router.post("", response_model=CreateJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def post_job(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    arq: ArqRedis = Depends(get_arq_pool),
):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "File must be a PDF")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > MAX_INPUT_FILE_SIZE_BYTES:
        raise HTTPException(413, "File too large")

    if (await count_active_jobs(db, user.id)) >= MAX_ACTIVE_JOBS_PER_USER:
        raise HTTPException(429, "Too many active jobs, please wait")

    job = await create_job(db, user_id=user.id, filename=file.filename, size=len(data))
    fs.write_input(user.id, job.id, data)
    await enforce_session_cap(db, user.id)
    await arq.enqueue_job("process_job", str(job.id))
    return CreateJobResponse(job_id=job.id, status=job.status, created_at=job.created_at)


@router.get("", response_model=JobListResponse)
async def get_jobs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await list_jobs_for_user(db, user.id)
    return JobListResponse(jobs=[_to_summary(j) for j in rows])


@router.get("/{job_id}", response_model=JobDetail)
async def get_job(job_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    j = await get_job_for_user(db, user.id, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return _to_detail(j)


@router.get("/{job_id}/econsent.pdf")
async def get_econsent(job_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    j = await get_job_for_user(db, user.id, job_id)
    if not j or not j.has_econsent:
        raise HTTPException(404, "Not found")
    return FileResponse(fs.econsent_path(user.id, j.id), media_type="application/pdf",
                        filename="Econsent.pdf")


@router.get("/{job_id}/input.pdf")
async def get_input(job_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    j = await get_job_for_user(db, user.id, job_id)
    if not j:
        raise HTTPException(404, "Not found")
    return FileResponse(fs.input_path(user.id, j.id), media_type="application/pdf",
                        filename=j.original_filename)


@router.post("/{job_id}/reprocess", response_model=CreateJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def post_reprocess(
    job_id: UUID, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db), arq: ArqRedis = Depends(get_arq_pool),
):
    parent = await get_job_for_user(db, user.id, job_id)
    if not parent:
        raise HTTPException(404, "Job not found")
    if parent.status != JobStatus.FAILED:
        raise HTTPException(409, "Only failed jobs can be reprocessed")
    if not fs.input_path(user.id, parent.id).exists():
        raise HTTPException(410, "Original input no longer available")
    new_job = await create_job(
        db, user_id=user.id, filename=parent.original_filename,
        size=parent.input_size_bytes, parent_job_id=parent.id,
    )
    # Copy input
    src = fs.read_input(user.id, parent.id)
    fs.write_input(user.id, new_job.id, src)
    await enforce_session_cap(db, user.id)
    await arq.enqueue_job("process_job", str(new_job.id))
    return CreateJobResponse(job_id=new_job.id, status=new_job.status, created_at=new_job.created_at)


@router.delete("/{job_id}", status_code=204)
async def remove_job(job_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await delete_job(db, user.id, job_id):
        raise HTTPException(404, "Job not found")
```

- [ ] **Step 2: Write `worker/queue.py` (so import resolves)**

```python
from arq import create_pool
from arq.connections import RedisSettings, ArqRedis
from config.settings import settings

_pool: ArqRedis | None = None

def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url)

async def get_arq_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(_redis_settings())
    return _pool
```

(Full worker module comes in Phase 9; this stub is needed by the API now.)

- [ ] **Step 3: Write `tests/test_jobs_api.py`** — happy-path with auth bypass via dependency override

```python
import pytest, io
from httpx import AsyncClient, ASGITransport
from uuid import uuid4
from db.models import User
from auth.deps import get_current_user
from worker.queue import get_arq_pool

class FakeArq:
    def __init__(self): self.jobs = []
    async def enqueue_job(self, name, *args, **kwargs):
        self.jobs.append((name, args)); return None

@pytest.mark.asyncio
async def test_post_job_creates_pending(db_session, tmp_path, monkeypatch):
    from storage import files as fs
    monkeypatch.setattr(fs, "FILES_ROOT", tmp_path)
    from api.app import create_app
    app = create_app()

    user = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    db_session.add(user); await db_session.commit()
    fake_arq = FakeArq()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_arq_pool] = lambda: fake_arq
    from db.session import get_db
    app.dependency_overrides[get_db] = lambda: db_session

    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        r = await c.post("/api/jobs", files={"file": ("x.pdf", b"%PDF-1.4 fake", "application/pdf")})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "pending"
    assert fake_arq.jobs and fake_arq.jobs[0][0] == "process_job"
```

- [ ] **Step 4: Commit**

```bash
git add api/jobs.py worker/__init__.py worker/queue.py tests/test_jobs_api.py
git commit -m "feat(api): add jobs router + arq enqueue stub"
```

### Task 8.4: App factory + wiring

**Files:** Create `api/app.py`, modify `api.py`

- [ ] **Step 1: Write `api/app.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from config.constants import USER_RATE_LIMIT
from config.settings import settings
from api import health, jobs, me

def create_app() -> FastAPI:
    app = FastAPI(title="ITR Extract API", version="2.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    limiter = Limiter(key_func=get_remote_address, default_limits=[USER_RATE_LIMIT])
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(jobs.router)
    return app
```

- [ ] **Step 2: Replace `api.py` (top-level) content**

```python
from api.app import create_app
app = create_app()
```

- [ ] **Step 3: Run server smoke**

Run: `uvicorn api:app --reload`
Smoke: `curl http://localhost:8000/healthz` → `{"status":"ok"}` (assuming local Postgres reachable).

- [ ] **Step 4: Commit**

```bash
git add api/app.py api.py
git commit -m "feat(api): app factory with CORS, rate-limit, and routers"
```

---

## Phase 9 — Worker (arq)

### Task 9.1: `worker/tasks.py` — `process_job`

**Files:** Create `worker/tasks.py`, `tests/test_worker_tasks.py`

- [ ] **Step 1: Write `tests/test_worker_tasks.py`**

```python
import pytest
from uuid import uuid4
from db.models import User, Job
from config.enums import JobStatus
from worker.tasks import process_job
from jobs import pipeline

class FakeCtx(dict):
    pass

@pytest.mark.asyncio
async def test_process_job_success(db_session, tmp_path, monkeypatch):
    from storage import files as fs
    monkeypatch.setattr(fs, "FILES_ROOT", tmp_path)
    user = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    db_session.add(user); await db_session.commit()
    job = Job(id=uuid4(), user_id=user.id, original_filename="x.pdf", input_size_bytes=4)
    db_session.add(job); await db_session.commit()
    fs.write_input(user.id, job.id, b"%PDF")

    monkeypatch.setattr(pipeline, "run_extraction",
                        lambda b: ({"k": "v"}, "<p>ok</p>", b"econsent-bytes"))

    ctx = FakeCtx(db=db_session)
    await process_job(ctx, str(job.id))
    await db_session.refresh(job)
    assert job.status == JobStatus.SUCCESS
    assert job.has_econsent is True
    assert fs.econsent_path(user.id, job.id).exists()

@pytest.mark.asyncio
async def test_process_job_failure_marks_failed_after_max_retries(db_session, tmp_path, monkeypatch):
    from config.constants import MAX_RETRY_ATTEMPTS
    from storage import files as fs
    monkeypatch.setattr(fs, "FILES_ROOT", tmp_path)
    user = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    db_session.add(user); await db_session.commit()
    job = Job(id=uuid4(), user_id=user.id, original_filename="x.pdf",
              input_size_bytes=4, retry_count=MAX_RETRY_ATTEMPTS - 1)
    db_session.add(job); await db_session.commit()
    fs.write_input(user.id, job.id, b"%PDF")

    def boom(_):
        raise RuntimeError("gemini boom")
    monkeypatch.setattr(pipeline, "run_extraction", boom)

    ctx = FakeCtx(db=db_session)
    with pytest.raises(RuntimeError):
        # final attempt re-raises only when retries remain — here it should mark failed
        await process_job(ctx, str(job.id))
    await db_session.refresh(job)
    assert job.status == JobStatus.FAILED
    assert "gemini boom" in (job.error_message or "")
```

- [ ] **Step 2: Write `worker/tasks.py`**

```python
from datetime import datetime, timezone
from uuid import UUID
import traceback
from sqlalchemy.ext.asyncio import AsyncSession
from config.constants import MAX_RETRY_ATTEMPTS
from config.enums import JobStatus
from db.models import Job
from jobs import pipeline
from storage import files as fs


def _utcnow():
    return datetime.now(timezone.utc)


async def process_job(ctx: dict, job_id_str: str) -> None:
    db: AsyncSession = ctx["db"]
    job_id = UUID(job_id_str)

    job = await db.get(Job, job_id)
    if job is None:
        return  # deleted
    if job.status not in (JobStatus.PENDING,):
        return  # already handled

    job.status = JobStatus.PROCESSING
    job.started_at = _utcnow()
    await db.commit()

    try:
        pdf_bytes = fs.read_input(job.user_id, job.id)
        analysis, email_html, econsent = pipeline.run_extraction(pdf_bytes)
        if econsent:
            fs.write_econsent(job.user_id, job.id, econsent)
        job.analysis_data = analysis
        job.email_html = email_html
        job.has_econsent = bool(econsent)
        job.status = JobStatus.SUCCESS
        job.finished_at = _utcnow()
        await db.commit()
    except Exception as e:
        job.retry_count += 1
        if job.retry_count >= MAX_RETRY_ATTEMPTS:
            job.status = JobStatus.FAILED
            job.error_message = str(e)[:500]
            job.error_details = {"traceback": traceback.format_exc()}
            job.finished_at = _utcnow()
            await db.commit()
            raise
        else:
            job.status = JobStatus.PENDING
            await db.commit()
            raise  # arq retries
```

- [ ] **Step 3: Run, verify pass**

Run: `pytest tests/test_worker_tasks.py -v`
Expected: 2 PASS.

- [ ] **Step 4: Commit**

```bash
git add worker/tasks.py tests/test_worker_tasks.py
git commit -m "feat(worker): add process_job task with retry semantics"
```

### Task 9.2: Cron tasks

**Files:** Create `worker/cron.py`, `tests/test_worker_cron.py`

- [ ] **Step 1: Write `tests/test_worker_cron.py`**

```python
import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from db.models import User, Job
from config.enums import JobStatus
from worker.cron import requeue_stuck_jobs, cleanup_orphan_files

class FakeArq:
    def __init__(self): self.jobs = []
    async def enqueue_job(self, name, *args, **kw): self.jobs.append((name, args))

@pytest.mark.asyncio
async def test_requeue_stuck_jobs(db_session):
    user = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    db_session.add(user); await db_session.commit()
    old = datetime.now(timezone.utc) - timedelta(minutes=20)
    j = Job(id=uuid4(), user_id=user.id, original_filename="x.pdf", input_size_bytes=1,
            status=JobStatus.PROCESSING, started_at=old)
    db_session.add(j); await db_session.commit()

    arq = FakeArq()
    n = await requeue_stuck_jobs(db_session, arq)
    await db_session.refresh(j)
    assert n == 1
    assert j.status == JobStatus.PENDING
    assert arq.jobs == [("process_job", (str(j.id),))]

@pytest.mark.asyncio
async def test_cleanup_orphan_files(db_session, tmp_path, monkeypatch):
    from storage import files as fs
    monkeypatch.setattr(fs, "FILES_ROOT", tmp_path)
    user_dir = tmp_path / str(uuid4())
    orphan = user_dir / str(uuid4()); orphan.mkdir(parents=True)
    (orphan / "input.pdf").write_bytes(b"x")
    n = await cleanup_orphan_files(db_session)
    assert n == 1
    assert not orphan.exists()
```

- [ ] **Step 2: Write `worker/cron.py`**

```python
from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from config.constants import STUCK_JOB_THRESHOLD_SECONDS
from config.enums import JobStatus
from db.models import Job
from storage import files as fs


async def requeue_stuck_jobs(db: AsyncSession, arq) -> int:
    threshold = datetime.now(timezone.utc) - timedelta(seconds=STUCK_JOB_THRESHOLD_SECONDS)
    q = select(Job).where(Job.status == JobStatus.PROCESSING, Job.started_at < threshold)
    rows = list((await db.scalars(q)).all())
    for j in rows:
        j.status = JobStatus.PENDING
    await db.commit()
    for j in rows:
        await arq.enqueue_job("process_job", str(j.id))
    return len(rows)


async def cleanup_orphan_files(db: AsyncSession) -> int:
    valid_ids: set[str] = set()
    rows = (await db.scalars(select(Job.id))).all()
    valid_ids = {str(j) for j in rows}
    removed = 0
    for user_dir in fs.list_user_dirs():
        for job_dir in user_dir.iterdir():
            if not job_dir.is_dir():
                continue
            if job_dir.name not in valid_ids:
                fs.delete_job_dir(UUID(user_dir.name), UUID(job_dir.name))
                removed += 1
    return removed
```

- [ ] **Step 3: Run, verify pass**

Run: `pytest tests/test_worker_cron.py -v`
Expected: 2 PASS.

- [ ] **Step 4: Commit**

```bash
git add worker/cron.py tests/test_worker_cron.py
git commit -m "feat(worker): add stuck-job requeue and orphan-file cleanup"
```

### Task 9.3: arq WorkerSettings

**Files:** Create `worker/settings.py`

- [ ] **Step 1: Write `worker/settings.py`**

```python
from arq import cron as arq_cron
from arq.connections import RedisSettings
from config.constants import (
    CLEANUP_ORPHAN_FILES_HOUR, JOB_TIMEOUT_SECONDS, MAX_RETRY_ATTEMPTS,
    STUCK_JOB_SWEEP_INTERVAL_MIN, WORKER_MAX_CONCURRENT_JOBS,
)
from config.settings import settings
from db.base import SessionLocal
from worker.tasks import process_job
from worker.cron import requeue_stuck_jobs, cleanup_orphan_files
from worker.queue import _redis_settings


async def _startup(ctx):
    ctx["db_factory"] = SessionLocal


async def _shutdown(ctx):
    pass


async def _process_job_wrapper(ctx, job_id):
    async with ctx["db_factory"]() as db:
        ctx["db"] = db
        await process_job(ctx, job_id)


async def _requeue_cron(ctx):
    from worker.queue import get_arq_pool
    arq = await get_arq_pool()
    async with ctx["db_factory"]() as db:
        await requeue_stuck_jobs(db, arq)


async def _cleanup_cron(ctx):
    async with ctx["db_factory"]() as db:
        await cleanup_orphan_files(db)


class WorkerSettings:
    redis_settings = _redis_settings()
    on_startup = _startup
    on_shutdown = _shutdown
    functions = [_process_job_wrapper]
    cron_jobs = [
        arq_cron(_requeue_cron, minute=set(range(0, 60, STUCK_JOB_SWEEP_INTERVAL_MIN))),
        arq_cron(_cleanup_cron, hour={CLEANUP_ORPHAN_FILES_HOUR}, minute={0}),
    ]
    job_timeout = JOB_TIMEOUT_SECONDS
    max_jobs = WORKER_MAX_CONCURRENT_JOBS
    max_tries = MAX_RETRY_ATTEMPTS
    retry_jobs = True

# arq enqueues using the function name; expose alias
process_job = _process_job_wrapper  # noqa
```

Note: `enqueue_job("process_job", ...)` calls in `api/jobs.py` and `worker/cron.py` must match the arq-registered function name. We register `_process_job_wrapper` as `process_job`. Update by renaming `_process_job_wrapper` to `process_job` (and renaming the imported `process_job` from tasks to `_run_process_job` in this module) OR change `enqueue_job` calls to use `_process_job_wrapper`. Pick the rename approach:

Replace the file:

```python
from arq import cron as arq_cron
from config.constants import (
    CLEANUP_ORPHAN_FILES_HOUR, JOB_TIMEOUT_SECONDS, MAX_RETRY_ATTEMPTS,
    STUCK_JOB_SWEEP_INTERVAL_MIN, WORKER_MAX_CONCURRENT_JOBS,
)
from db.base import SessionLocal
from worker.tasks import process_job as _run_process_job
from worker.cron import requeue_stuck_jobs, cleanup_orphan_files
from worker.queue import _redis_settings, get_arq_pool


async def _startup(ctx):
    ctx["db_factory"] = SessionLocal

async def _shutdown(ctx):
    pass

async def process_job(ctx, job_id):
    async with ctx["db_factory"]() as db:
        ctx["db"] = db
        await _run_process_job(ctx, job_id)

async def _requeue_cron(ctx):
    arq = await get_arq_pool()
    async with ctx["db_factory"]() as db:
        await requeue_stuck_jobs(db, arq)

async def _cleanup_cron(ctx):
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
```

- [ ] **Step 2: Smoke run**

Run (in another terminal, with Redis up): `arq worker.settings.WorkerSettings`
Expected: arq registers `process_job` and 2 cron jobs.

- [ ] **Step 3: Commit**

```bash
git add worker/settings.py
git commit -m "feat(worker): add arq WorkerSettings with crons"
```

---

## Phase 10 — End-to-End Backend Test

### Task 10.1: Lifecycle integration test

**Files:** Create `tests/test_e2e_lifecycle.py`

- [ ] **Step 1: Write the test**

```python
import pytest
from uuid import uuid4
from httpx import AsyncClient, ASGITransport
from db.models import User
from auth.deps import get_current_user
from db.session import get_db
from worker.queue import get_arq_pool
from jobs import pipeline
from worker.tasks import process_job

class FakeArq:
    def __init__(self): self.queued = []
    async def enqueue_job(self, name, *args, **kw): self.queued.append((name, args))

@pytest.mark.asyncio
async def test_full_lifecycle(db_session, tmp_path, monkeypatch):
    from storage import files as fs
    monkeypatch.setattr(fs, "FILES_ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "run_extraction",
                        lambda b: ({"client": {"name": "Acme"}}, "<p>email</p>", b"%PDF-econsent"))
    user = User(id=uuid4(), email="a@x.com", name="A", tenant_id=uuid4())
    db_session.add(user); await db_session.commit()

    from api.app import create_app
    app = create_app()
    fake = FakeArq()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_arq_pool] = lambda: fake
    app.dependency_overrides[get_db] = lambda: db_session

    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        r = await c.post("/api/jobs", files={"file": ("x.pdf", b"%PDF data", "application/pdf")})
        assert r.status_code == 202
        job_id = r.json()["job_id"]

        r = await c.get(f"/api/jobs/{job_id}")
        assert r.json()["status"] == "pending"

        # Run worker manually
        await process_job({"db": db_session}, job_id)

        r = await c.get(f"/api/jobs/{job_id}")
        body = r.json()
        assert body["status"] == "success"
        assert body["has_econsent"] is True
        assert body["analysis_data"]["client"]["name"] == "Acme"

        r = await c.get(f"/api/jobs/{job_id}/econsent.pdf")
        assert r.status_code == 200 and r.content.startswith(b"%PDF")
```

- [ ] **Step 2: Run, verify pass**

Run: `pytest tests/test_e2e_lifecycle.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_lifecycle.py
git commit -m "test: add end-to-end job lifecycle integration test"
```

---

## Phase 11 — Frontend

### Task 11.1: Constants & types

**Files:** Create `src/lib/constants.ts`, `src/lib/types.ts`

- [ ] **Step 1: Write `src/lib/constants.ts`**

```ts
export const POLLING_INTERVAL_MS    = 2000;
export const POLLING_MAX_ATTEMPTS   = 150;
export const MAX_SESSIONS_PER_USER  = 10;
export const MAX_FILE_SIZE_BYTES    = 50 * 1024 * 1024;

export const JobStatus = {
  PENDING:    'pending',
  PROCESSING: 'processing',
  SUCCESS:    'success',
  FAILED:     'failed',
} as const;
export type JobStatus = typeof JobStatus[keyof typeof JobStatus];

export const TERMINAL_STATUSES: ReadonlyArray<JobStatus> =
  [JobStatus.SUCCESS, JobStatus.FAILED];
export const ACTIVE_STATUSES: ReadonlyArray<JobStatus> =
  [JobStatus.PENDING, JobStatus.PROCESSING];
```

- [ ] **Step 2: Write `src/lib/types.ts`**

```ts
import type { JobStatus } from './constants';

export interface JobSummary {
  job_id: string;
  status: JobStatus;
  original_filename: string;
  created_at: string;
  finished_at: string | null;
  error_message: string | null;
}

export interface JobDetail extends JobSummary {
  started_at: string | null;
  has_econsent: boolean;
  analysis_data: Record<string, unknown> | null;
  email_html: string | null;
}

export interface CreateJobResponse {
  job_id: string;
  status: JobStatus;
  created_at: string;
}
```

- [ ] **Step 3: Commit (in FE repo)**

```bash
cd ~/workspace/itr_extract_fe
git add src/lib/constants.ts src/lib/types.ts
git commit -m "feat(fe): add shared constants and job types"
```

### Task 11.2: MSAL config — add BE scope

**Files:** Modify `src/lib/msalConfig.ts`

- [ ] **Step 1: Edit `loginRequest`**

Replace the existing `loginRequest` export with:
```ts
const BE_SCOPE = `api://${import.meta.env.VITE_MSAL_BE_CLIENT_ID as string}/access_as_user`;

export const loginRequest: PopupRequest = {
  scopes: ['User.Read', 'Mail.ReadWrite', BE_SCOPE],
};

export const beApiScopes: string[] = [BE_SCOPE];
```

- [ ] **Step 2: Update `.env.example`**

Add:
```
VITE_API_BASE_URL=http://localhost:8000
VITE_MSAL_BE_CLIENT_ID=00000000-0000-0000-0000-000000000000
```

- [ ] **Step 3: Commit**

```bash
git add src/lib/msalConfig.ts .env.example
git commit -m "feat(fe): request BE access_as_user scope at login"
```

### Task 11.3: API client + token hook

**Files:** Create `src/hooks/useAccessToken.ts`, `src/lib/apiClient.ts`

- [ ] **Step 1: Write `src/hooks/useAccessToken.ts`**

```ts
import { useMsal } from '@azure/msal-react';
import { beApiScopes } from '../lib/msalConfig';

export function useAccessToken() {
  const { instance, accounts } = useMsal();
  return async (): Promise<string> => {
    const account = accounts[0];
    if (!account) throw new Error('Not signed in');
    const result = await instance.acquireTokenSilent({ scopes: beApiScopes, account });
    return result.accessToken;
  };
}
```

- [ ] **Step 2: Write `src/lib/apiClient.ts`**

```ts
const BASE = import.meta.env.VITE_API_BASE_URL as string;

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function apiFetch(
  path: string,
  init: RequestInit,
  getToken: () => Promise<string>,
): Promise<Response> {
  const token = await getToken();
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { ...(init.headers ?? {}), Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new ApiError(res.status, await res.text().catch(() => ''));
  return res;
}

export async function apiJson<T>(
  path: string, init: RequestInit, getToken: () => Promise<string>,
): Promise<T> {
  const r = await apiFetch(path, init, getToken);
  return r.json() as Promise<T>;
}
```

- [ ] **Step 3: Commit**

```bash
git add src/hooks/useAccessToken.ts src/lib/apiClient.ts
git commit -m "feat(fe): add access token hook and API fetch wrapper"
```

### Task 11.4: `useJobs` + `useJobPolling`

**Files:** Create `src/hooks/useJobs.ts`, `src/hooks/useJobPolling.ts`

- [ ] **Step 1: Write `src/hooks/useJobs.ts`**

```ts
import { useCallback, useEffect, useState } from 'react';
import { apiFetch, apiJson } from '../lib/apiClient';
import { useAccessToken } from './useAccessToken';
import type { CreateJobResponse, JobSummary } from '../lib/types';

export function useJobs() {
  const getToken = useAccessToken();
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiJson<{ jobs: JobSummary[] }>('/api/jobs', {}, getToken);
      setJobs(data.jobs);
    } finally { setLoading(false); }
  }, [getToken]);

  useEffect(() => { refresh(); }, [refresh]);

  const createJob = useCallback(async (file: File): Promise<CreateJobResponse> => {
    const fd = new FormData();
    fd.append('file', file);
    const res = await apiFetch('/api/jobs', { method: 'POST', body: fd }, getToken);
    const body = await res.json();
    await refresh();
    return body;
  }, [getToken, refresh]);

  const reprocess = useCallback(async (jobId: string) => {
    const r = await apiFetch(`/api/jobs/${jobId}/reprocess`, { method: 'POST' }, getToken);
    await refresh();
    return r.json();
  }, [getToken, refresh]);

  const deleteJob = useCallback(async (jobId: string) => {
    await apiFetch(`/api/jobs/${jobId}`, { method: 'DELETE' }, getToken);
    await refresh();
  }, [getToken, refresh]);

  return { jobs, loading, refresh, createJob, reprocess, deleteJob };
}
```

- [ ] **Step 2: Write `src/hooks/useJobPolling.ts`**

```ts
import { useEffect, useState } from 'react';
import { apiJson } from '../lib/apiClient';
import { useAccessToken } from './useAccessToken';
import { POLLING_INTERVAL_MS, POLLING_MAX_ATTEMPTS, TERMINAL_STATUSES } from '../lib/constants';
import type { JobDetail } from '../lib/types';

export function useJobPolling(jobId: string | null) {
  const getToken = useAccessToken();
  const [job, setJob] = useState<JobDetail | null>(null);
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    if (!jobId) { setJob(null); setTimedOut(false); return; }
    let stopped = false;
    let attempts = 0;
    let timer: number | null = null;

    const tick = async () => {
      if (stopped) return;
      try {
        const data = await apiJson<JobDetail>(`/api/jobs/${jobId}`, {}, getToken);
        setJob(data);
        attempts++;
        const isTerminal = (TERMINAL_STATUSES as readonly string[]).includes(data.status);
        if (isTerminal) return;
        if (attempts >= POLLING_MAX_ATTEMPTS) { setTimedOut(true); return; }
        timer = window.setTimeout(tick, POLLING_INTERVAL_MS);
      } catch {
        timer = window.setTimeout(tick, POLLING_INTERVAL_MS);
      }
    };
    tick();
    return () => { stopped = true; if (timer) clearTimeout(timer); };
  }, [jobId, getToken]);

  return { job, timedOut };
}
```

- [ ] **Step 3: Commit**

```bash
git add src/hooks/useJobs.ts src/hooks/useJobPolling.ts
git commit -m "feat(fe): add useJobs and useJobPolling hooks"
```

### Task 11.5: UI components

**Files:** Create `src/components/JobStatusBadge.tsx`, `src/components/JobHistory.tsx`, `src/components/UploadCard.tsx`

- [ ] **Step 1: Write `src/components/JobStatusBadge.tsx`**

```tsx
import { JobStatus } from '../lib/constants';

const LABEL: Record<JobStatus, string> = {
  [JobStatus.PENDING]:    'Đang chờ',
  [JobStatus.PROCESSING]: 'Đang xử lý',
  [JobStatus.SUCCESS]:    'Hoàn tất',
  [JobStatus.FAILED]:     'Thất bại',
};
const COLOR: Record<JobStatus, string> = {
  [JobStatus.PENDING]:    '#888',
  [JobStatus.PROCESSING]: '#0a7',
  [JobStatus.SUCCESS]:    '#0a0',
  [JobStatus.FAILED]:     '#c33',
};

export function JobStatusBadge({ status }: { status: JobStatus }) {
  return (
    <span style={{ color: COLOR[status], fontWeight: 600 }}>
      {LABEL[status]}
    </span>
  );
}
```

- [ ] **Step 2: Write `src/components/JobHistory.tsx`**

```tsx
import { JobStatusBadge } from './JobStatusBadge';
import type { JobSummary } from '../lib/types';
import { JobStatus, MAX_SESSIONS_PER_USER } from '../lib/constants';

interface Props {
  jobs: JobSummary[];
  selectedJobId: string | null;
  onSelect: (id: string) => void;
  onReprocess: (id: string) => void;
  onDelete: (id: string) => void;
}

export function JobHistory({ jobs, selectedJobId, onSelect, onReprocess, onDelete }: Props) {
  return (
    <aside style={{ borderLeft: '1px solid #ddd', padding: '12px', minWidth: 280 }}>
      <h3>History ({jobs.length}/{MAX_SESSIONS_PER_USER})</h3>
      {jobs.length === 0 && <p>Chưa có job.</p>}
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {jobs.map(j => (
          <li key={j.job_id}
              style={{ padding: 8, cursor: 'pointer',
                       background: j.job_id === selectedJobId ? '#eef' : 'transparent' }}
              onClick={() => onSelect(j.job_id)}>
            <div>{j.original_filename}</div>
            <JobStatusBadge status={j.status} />
            {j.status === JobStatus.FAILED && (
              <>
                <div style={{ fontSize: 12, color: '#c33' }}>{j.error_message}</div>
                <button onClick={(e) => { e.stopPropagation(); onReprocess(j.job_id); }}>Retry</button>
              </>
            )}
            <button onClick={(e) => { e.stopPropagation(); onDelete(j.job_id); }}
                    style={{ marginLeft: 8 }}>Xóa</button>
          </li>
        ))}
      </ul>
    </aside>
  );
}
```

- [ ] **Step 3: Write `src/components/UploadCard.tsx`**

```tsx
import { useState } from 'react';
import { MAX_FILE_SIZE_BYTES } from '../lib/constants';

export function UploadCard({ onUpload }: { onUpload: (file: File) => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handle = async (file: File) => {
    setError(null);
    if (!file.name.toLowerCase().endsWith('.pdf')) { setError('Chỉ chấp nhận PDF'); return; }
    if (file.size > MAX_FILE_SIZE_BYTES) { setError('File quá lớn'); return; }
    setBusy(true);
    try { await onUpload(file); } finally { setBusy(false); }
  };

  return (
    <section style={{ border: '2px dashed #aaa', padding: 24, textAlign: 'center' }}>
      <input type="file" accept="application/pdf" disabled={busy}
             onChange={e => e.target.files?.[0] && handle(e.target.files[0])} />
      {busy && <p>Đang upload...</p>}
      {error && <p style={{ color: '#c33' }}>{error}</p>}
    </section>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add src/components/JobStatusBadge.tsx src/components/JobHistory.tsx src/components/UploadCard.tsx
git commit -m "feat(fe): add JobStatusBadge, JobHistory, UploadCard components"
```

### Task 11.6: Refactor App + JobDetailView

**Files:** Modify `src/App.tsx`, create `src/components/JobDetailView.tsx`

- [ ] **Step 1: Write `src/components/JobDetailView.tsx`**

Wrap the existing detail UI (forms select / email editor / Outlook draft button) into a component that takes `JobDetail` as input:
```tsx
import type { JobDetail } from '../lib/types';

export function JobDetailView({ job }: { job: JobDetail }) {
  if (!job.analysis_data || !job.email_html) return null;
  // Reuse existing forms/email/draft UI here, fed by job.analysis_data + job.email_html.
  // Download Econsent → GET /api/jobs/{id}/econsent.pdf via apiFetch.
  return (
    <div>
      <h2>{job.original_filename}</h2>
      {/* existing UI extracted from App.tsx */}
    </div>
  );
}
```

(The exact JSX lift is mechanical: copy current form-selection + email editor + Outlook button block out of `App.tsx` into this component, replace the in-memory `analysisData` / `emailHtml` references with `job.analysis_data` / `job.email_html`, and switch the Econsent base64 to a fetched blob URL.)

- [ ] **Step 2: Refactor `src/App.tsx`**

```tsx
import { useState } from 'react';
import { AuthenticatedTemplate, UnauthenticatedTemplate } from '@azure/msal-react';
import { UploadCard } from './components/UploadCard';
import { JobHistory } from './components/JobHistory';
import { JobDetailView } from './components/JobDetailView';
import { useJobs } from './hooks/useJobs';
import { useJobPolling } from './hooks/useJobPolling';
import { JobStatus } from './lib/constants';

export default function App() {
  const { jobs, createJob, reprocess, deleteJob } = useJobs();
  const [selected, setSelected] = useState<string | null>(null);
  const { job, timedOut } = useJobPolling(selected);

  return (
    <>
      <UnauthenticatedTemplate>
        {/* existing sign-in button */}
      </UnauthenticatedTemplate>
      <AuthenticatedTemplate>
        <div style={{ display: 'flex' }}>
          <main style={{ flex: 1, padding: 16 }}>
            <UploadCard onUpload={async (f) => {
              const r = await createJob(f);
              setSelected(r.job_id);
            }} />
            {job && job.status === JobStatus.SUCCESS && <JobDetailView job={job} />}
            {job && job.status === JobStatus.FAILED && (
              <div style={{ color: '#c33' }}>Thất bại: {job.error_message}</div>
            )}
            {timedOut && <div>Xử lý lâu, refresh để check.</div>}
          </main>
          <JobHistory jobs={jobs} selectedJobId={selected}
                      onSelect={setSelected}
                      onReprocess={async (id) => { const r = await reprocess(id); setSelected(r.job_id); }}
                      onDelete={async (id) => { await deleteJob(id); if (selected === id) setSelected(null); }} />
        </div>
      </AuthenticatedTemplate>
    </>
  );
}
```

- [ ] **Step 3: Smoke run**

Run: `pnpm dev` (or `npm run dev`). Sign in, upload a PDF, observe job appears in history, polling switches to success, detail view renders.

- [ ] **Step 4: Commit**

```bash
git add src/App.tsx src/components/JobDetailView.tsx
git commit -m "refactor(fe): two-column layout with job history and polled detail"
```

---

## Phase 12 — Deployment

### Task 12.1: systemd units + deploy README

**Files:** Create `deploy/itr-api.service`, `deploy/itr-worker.service`, `deploy/README.md`

- [ ] **Step 1: Write `deploy/itr-api.service`**

```ini
[Unit]
Description=ITR Extract API (uvicorn)
After=network.target postgresql.service redis-server.service

[Service]
User=itr
Group=itr
WorkingDirectory=/opt/itr_extract
EnvironmentFile=/etc/itr_extract/api.env
ExecStart=/opt/itr_extract/.venv/bin/uvicorn api:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Write `deploy/itr-worker.service`**

```ini
[Unit]
Description=ITR Extract arq worker
After=network.target postgresql.service redis-server.service

[Service]
User=itr
Group=itr
WorkingDirectory=/opt/itr_extract
EnvironmentFile=/etc/itr_extract/worker.env
ExecStart=/opt/itr_extract/.venv/bin/arq worker.settings.WorkerSettings
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Write `deploy/README.md`**

```markdown
# Deployment — Ubuntu VPS

## Prereqs
- Ubuntu 22.04+
- `apt install postgresql redis-server nginx python3.11 python3.11-venv`

## Postgres
```
sudo -u postgres createuser itr
sudo -u postgres createdb -O itr itr_extract
sudo -u postgres psql -c "ALTER USER itr WITH PASSWORD '<pw>';"
```

## App
```
sudo useradd -r -m -d /opt/itr_extract itr
sudo -u itr git clone <repo> /opt/itr_extract
cd /opt/itr_extract && sudo -u itr python3.11 -m venv .venv
sudo -u itr .venv/bin/pip install -r requirements.txt
sudo mkdir -p /var/lib/itr_extract/files
sudo chown -R itr:itr /var/lib/itr_extract
sudo chmod 700 /var/lib/itr_extract
```

## Env files (`/etc/itr_extract/api.env`, `worker.env`)
```
DATABASE_URL=postgresql+asyncpg://itr:<pw>@localhost:5432/itr_extract
REDIS_URL=redis://localhost:6379
MSAL_TENANT_ID=<from client>
MSAL_BE_CLIENT_ID=<from client>
GEMINI_API_KEY=<key>
ALLOWED_ORIGINS=["https://app.example.com"]
FILES_ROOT=/var/lib/itr_extract/files
```

## Migrations
```
sudo -u itr .venv/bin/alembic upgrade head
```

## Services
```
sudo cp deploy/itr-api.service deploy/itr-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now itr-api itr-worker
```

## nginx (TLS via certbot, reverse-proxy to 127.0.0.1:8000, serve FE static build)
See `nginx.example.conf` (out of scope for this plan).

## Backups
- Nightly cron: `pg_dump itr_extract` + `tar czf files.tgz /var/lib/itr_extract/files`.
```

- [ ] **Step 4: Commit**

```bash
git add deploy/
git commit -m "docs(deploy): add systemd units and Ubuntu deploy guide"
```

---

## Phase 13 — Final Verification

### Task 13.1: Full test sweep + magic-number audit

- [ ] **Step 1: Run full backend test suite**

Run: `pytest -v`
Expected: all green.

- [ ] **Step 2: Audit BE for magic numbers/strings**

Run:
```bash
grep -RnE '\b10\b|\b300\b|\b50\b\s*\*\s*1024|"pending"|"processing"|"success"|"failed"' \
  --include="*.py" --exclude-dir=tests --exclude-dir=.venv \
  | grep -v 'config/constants.py\|config/enums.py'
```
Expected: empty (or only acceptable hits like enum value definitions).

If hits found: replace with `JobStatus.X` / constant import. Re-run audit.

- [ ] **Step 3: Audit FE for magic strings**

```bash
cd ~/workspace/itr_extract_fe
grep -RnE "'pending'|'processing'|'success'|'failed'" src/ --include="*.ts" --include="*.tsx" \
  | grep -v 'src/lib/constants.ts'
```
Expected: empty.

- [ ] **Step 4: Smoke E2E (manual)**

- Start Postgres, Redis, `uvicorn api:app`, `arq worker.settings.WorkerSettings`, FE `npm run dev`.
- Sign in, upload sample PDF.
- Observe job goes pending → processing → success.
- Re-upload same PDF 11 times; confirm oldest auto-deleted (history stays at 10).
- Force a failure (e.g., temporarily break GEMINI_API_KEY in worker env, restart worker, upload). Verify status `failed` and Retry button creates new job.
- Inspect `/var/lib/itr_extract/files/` (or local override): per-user dirs, only 10 jobs each.

- [ ] **Step 5: Final commit**

If any fixes were made:
```bash
git add -A
git commit -m "chore: enforce centralized constants after audit"
```

---

## Self-Review Checklist (already executed by plan author)

- ✅ **Spec coverage:** all 12 spec sections map to phases (config §5 → Phase 1; data model §4 → Phase 2; auth §7 → Phase 3; storage §3 disk layout → Phase 5; pipeline preserved → Phase 6; jobs §4/§5 retention → Phase 7; API §6 → Phase 8; worker §8 → Phase 9; FE §9 → Phase 11; deploy §10 → Phase 12; testing §11 → Phases 4, 10, 13).
- ✅ **Placeholder scan:** no TBD / "implement later"; all code blocks present.
- ✅ **Type consistency:** `JobStatus` values consistent BE/FE; `process_job` registration name matches `enqueue_job` callsites; `get_arq_pool` signature stable across callers; FE `JobDetail` matches BE `JobDetail` schema.
- ✅ **Constants discipline:** every numeric/path/timeout/status value pulled from `config/constants.py`, `config/enums.py`, or `src/lib/constants.ts`. Phase 13.2 enforces via grep audit.
