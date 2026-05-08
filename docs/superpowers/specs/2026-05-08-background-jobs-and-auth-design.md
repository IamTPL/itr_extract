# ITR Extract — Background Jobs, Auth & Per-User Storage

**Date:** 2026-05-08
**Status:** Approved (brainstorming complete)
**Scope:** Add async job processing, Azure AD authentication, and per-user persistence to a currently stateless FastAPI + React app.

---

## 1. Problem Statement

The current system has two limitations:

1. **No background processing.** `POST /api/process` runs the Gemini pipeline synchronously. Large PDFs risk frontend timeout; users have no visibility into progress; transient Gemini failures surface as hard errors with no retry.
2. **No per-user persistence.** Backend is stateless and unauthenticated. The frontend has Azure MSAL login, but its tokens are never sent to (or verified by) the backend, so there is no concept of "user identity" server-side and no way to store results per user.

This spec addresses both: introduce async job execution with status tracking, authenticate the backend via Azure AD JWTs, and persist jobs (metadata in Postgres, files on local disk) per user with a 10-session-per-user retention cap.

---

## 2. Goals & Non-Goals

### Goals
- Asynchronous PDF processing with `pending` → `processing` → `success`/`failed` lifecycle, exposed via REST polling.
- Backend authentication using Azure AD (single-tenant) JWTs validated against Microsoft JWKS.
- Per-user job history (max 10 sessions/user, FIFO auto-eviction).
- Manual re-process for failed jobs; automatic retry (up to 3 attempts) for transient errors.
- Centralized constants for all tunable values (statuses, limits, timeouts, paths).

### Non-Goals
- Multi-tenant support (single tenant only; configurable via env).
- Real-time push (WebSocket/SSE) — polling is sufficient at this scale.
- Object storage (S3/R2) — local disk only for v1.
- Username/password auth — Microsoft OAuth only.
- Horizontal scaling beyond a single VPS.

---

## 3. Architecture Overview

```
┌─────────────┐                    ┌──────────────────────────────────┐
│   FE        │                    │           VPS (Ubuntu)           │
│ React+MSAL  │                    │                                  │
│             │   HTTPS + JWT      │  ┌──────────┐    ┌─────────────┐ │
│             ├───────────────────>│  │ FastAPI  │───>│  Postgres   │ │
│             │                    │  │  (BE)    │    │ users/jobs  │ │
│             │<───────────────────┤  └────┬─────┘    └─────────────┘ │
│             │  job_id + status   │       │ enqueue                  │
└─────────────┘                    │       ▼                          │
                                   │  ┌──────────┐    ┌─────────────┐ │
                                   │  │  Redis   │<───│ arq Worker  │ │
                                   │  └──────────┘    └──────┬──────┘ │
                                   │                         │        │
                                   │                  ┌──────▼──────┐ │
                                   │                  │ Local Disk  │ │
                                   │                  │ /var/lib/   │ │
                                   │                  │ itr_extract │ │
                                   │                  └─────────────┘ │
                                   └──────────────────────────────────┘
```

**Four systemd services:** `itr-api` (uvicorn), `itr-worker` (arq), `redis`, `postgresql`.

**Disk layout:**
```
/var/lib/itr_extract/files/{user_id}/{job_id}/
  ├── input.pdf       (original upload)
  └── econsent.pdf    (output, only on success when applicable)
```

---

## 4. Data Model

### 4.1 `users`
| Column      | Type          | Notes                                  |
|-------------|---------------|----------------------------------------|
| id          | UUID PK       | Equals Azure AD `oid` claim            |
| email       | TEXT NOT NULL | From `preferred_username`/`email`      |
| name        | TEXT          | From `name`                            |
| tenant_id   | UUID NOT NULL | From `tid`                             |
| created_at  | TIMESTAMPTZ   | DEFAULT NOW()                          |
| last_login  | TIMESTAMPTZ   | Updated on each authenticated request  |

### 4.2 `jobs`
| Column            | Type                  | Notes                                            |
|-------------------|-----------------------|--------------------------------------------------|
| id                | UUID PK               | DEFAULT gen_random_uuid()                        |
| user_id           | UUID FK CASCADE       | → `users.id`                                     |
| status            | `job_status` ENUM     | pending / processing / success / failed          |
| original_filename | TEXT NOT NULL         | e.g., `ITR_2024.pdf`                             |
| input_size_bytes  | BIGINT NOT NULL       |                                                  |
| analysis_data     | JSONB                 | NULL until success                               |
| email_html        | TEXT                  | NULL until success                               |
| has_econsent      | BOOLEAN               | DEFAULT FALSE; reflects existence of econsent.pdf|
| created_at        | TIMESTAMPTZ           | DEFAULT NOW()                                    |
| started_at        | TIMESTAMPTZ           | When worker begins                               |
| finished_at       | TIMESTAMPTZ           | On terminal state                                |
| error_message     | TEXT                  | User-facing summary                              |
| error_details     | JSONB                 | Stack trace, debug info                          |
| retry_count       | INTEGER               | DEFAULT 0                                        |
| parent_job_id     | UUID FK SET NULL      | Lineage for re-processed jobs                    |

**Indexes:**
- `idx_jobs_user_created` on `(user_id, created_at DESC)` — for history list
- `idx_jobs_status` on `(status)` WHERE status IN ('pending','processing') — for stuck-job sweeper

**Retention enforcement (10 sessions / user):** within the same transaction as INSERT of new job, delete oldest jobs (by `created_at ASC`) until count ≤ `MAX_SESSIONS_PER_USER`. Files for deleted jobs are removed best-effort post-commit; a nightly cron sweeps any orphans.

---

## 5. Constants & Configuration

**All tunable values MUST be defined as named constants in dedicated modules — no inline literals.**

### 5.1 Backend (`config/constants.py`)
```python
# Session & retention
MAX_SESSIONS_PER_USER          = 10
MAX_ACTIVE_JOBS_PER_USER       = 5      # concurrent pending+processing
MAX_INPUT_FILE_SIZE_BYTES      = 50 * 1024 * 1024

# Worker / retry
JOB_TIMEOUT_SECONDS            = 300
WORKER_MAX_CONCURRENT_JOBS     = 4
MAX_RETRY_ATTEMPTS             = 3      # initial + 2 retries
RETRY_BACKOFF_SECONDS          = (5, 15)
STUCK_JOB_THRESHOLD_SECONDS    = 360    # processing > 6 min → requeue

# Paths
FILES_ROOT                     = Path("/var/lib/itr_extract/files")
INPUT_FILENAME                 = "input.pdf"
ECONSENT_FILENAME              = "econsent.pdf"

# Auth / JWT
JWKS_CACHE_TTL_SECONDS         = 3600
JWT_LEEWAY_SECONDS             = 60
JWT_ALGORITHM                  = "RS256"

# Cron
CLEANUP_ORPHAN_FILES_HOUR      = 3
STUCK_JOB_SWEEP_INTERVAL_MIN   = 1
```

### 5.2 Backend (`config/enums.py`)
```python
class JobStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    SUCCESS    = "success"
    FAILED     = "failed"

TERMINAL_STATUSES   = frozenset({JobStatus.SUCCESS, JobStatus.FAILED})
ACTIVE_STATUSES     = frozenset({JobStatus.PENDING, JobStatus.PROCESSING})
```

### 5.3 Backend (env vars, loaded via Pydantic Settings)
```
DATABASE_URL
REDIS_URL
MSAL_TENANT_ID
MSAL_BE_CLIENT_ID
FILES_ROOT_OVERRIDE        (optional, for tests)
ALLOWED_ORIGINS            (CORS)
```

### 5.4 Frontend (`src/lib/constants.ts`)
```ts
export const POLLING_INTERVAL_MS    = 2000;
export const POLLING_MAX_ATTEMPTS   = 150;   // 5 min safety stop
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
```

**Rule:** any future PR adding magic numbers/strings related to limits, statuses, paths, or timeouts must add them here, not inline.

---

## 6. API Surface

All endpoints (except `/healthz`) require `Authorization: Bearer <JWT>`.

| Method | Path                              | Purpose                                            |
|--------|-----------------------------------|----------------------------------------------------|
| POST   | `/api/jobs`                       | Create job (multipart PDF). Returns 202 + job_id   |
| GET    | `/api/jobs`                       | List user's jobs (max 10, sorted DESC)             |
| GET    | `/api/jobs/{id}`                  | Job detail (used by FE polling)                    |
| GET    | `/api/jobs/{id}/econsent.pdf`     | Stream output PDF                                  |
| GET    | `/api/jobs/{id}/input.pdf`        | Stream original input PDF                          |
| POST   | `/api/jobs/{id}/reprocess`        | Re-run a failed job → creates new job              |
| DELETE | `/api/jobs/{id}`                  | Delete job + associated files                      |
| GET    | `/api/me`                         | Current user info + job count                      |
| GET    | `/healthz`                        | Public health check (DB + Redis)                   |

**Authorization rule:** any reference to a `job_id` not owned by the authenticated user returns 404 (not 403) to avoid revealing existence.

**Polling contract:** FE polls `GET /api/jobs/{id}` every `POLLING_INTERVAL_MS` until status is terminal or `POLLING_MAX_ATTEMPTS` is reached.

---

## 7. Authentication

### 7.1 Azure AD setup (client IT)
- **App 1 (FE, SPA):** existing — adds BE scope to `loginRequest`.
- **App 2 (BE, Web API):** new. Exposes scope `api://<BE_CLIENT_ID>/access_as_user`. Pre-authorize App 1.

### 7.2 Token validation pipeline (BE)
1. Extract Bearer token from `Authorization` header.
2. Read `kid` from JWT header.
3. Fetch JWKS from `https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys`, cached for `JWKS_CACHE_TTL_SECONDS`.
4. Verify signature (RS256), `aud == MSAL_BE_CLIENT_ID`, `iss == https://login.microsoftonline.com/{TENANT_ID}/v2.0`, `exp` (with `JWT_LEEWAY_SECONDS`), and `tid == MSAL_TENANT_ID`.
5. Resolve user via JIT provisioning: upsert `users` row keyed by `oid`; refresh `last_login`, `email`, `name`.

### 7.3 Defense in depth
- HTTPS enforced via nginx + Let's Encrypt.
- CORS restricted to FE origin (`ALLOWED_ORIGINS`).
- Rate limiting via slowapi: 30 req/min/user; max `MAX_ACTIVE_JOBS_PER_USER` concurrent active jobs.
- Authorization header redacted in all logs.

---

## 8. Worker Pipeline (arq)

### 8.1 Task: `process_job(job_id)`
1. Begin tx → `SELECT … FOR UPDATE` job; bail if missing or already non-pending.
2. Set `status = processing`, `started_at = now()`.
3. Read `input.pdf` from disk.
4. Run existing extraction pipeline (preserved from `main.py` — Task 1 + Task 2 in parallel).
5. On success: write `econsent.pdf` if applicable; persist `analysis_data`, `email_html`, `has_econsent`; set `status = success`, `finished_at`.
6. On exception: increment `retry_count`. If `< MAX_RETRY_ATTEMPTS - 1` → re-raise (arq retries with backoff). Else → set `status = failed`, capture `error_message` + `error_details`, `finished_at`.

### 8.2 Cron tasks
- **`requeue_stuck_jobs`** (every `STUCK_JOB_SWEEP_INTERVAL_MIN`): jobs in `processing` for > `STUCK_JOB_THRESHOLD_SECONDS` → reset to `pending` and re-enqueue (covers worker crashes).
- **`cleanup_orphan_files`** (daily at `CLEANUP_ORPHAN_FILES_HOUR`): scan `FILES_ROOT`; remove directories whose `job_id` no longer exists in DB.

### 8.3 Resilience matrix
| Scenario                    | Behavior                                              |
|-----------------------------|-------------------------------------------------------|
| Worker crash mid-job        | systemd restart; stuck-job sweeper requeues          |
| Gemini timeout / 5xx        | arq retry up to `MAX_RETRY_ATTEMPTS`                  |
| Redis down                  | `POST /api/jobs` → 503; FE shows service unavailable  |
| User deletes job mid-process| Worker checks existence on each transition; no-ops    |
| File read error             | Counts as exception; retried per policy               |

---

## 9. Frontend Changes

### 9.1 New/modified files
```
src/
  lib/
    apiClient.ts             NEW   fetch wrapper, attaches Bearer token
    constants.ts             NEW   shared constants/enums
    msalConfig.ts            EDIT  add BE scope to loginRequest
  hooks/
    useAccessToken.ts        NEW   acquireTokenSilent for BE scope
    useJobs.ts               NEW   list / create / delete / reprocess
    useJobPolling.ts         NEW   2s poll until terminal
  components/
    JobHistory.tsx           NEW   sidebar list (max 10)
    JobStatusBadge.tsx       NEW
    UploadCard.tsx           NEW   extracted from App.tsx
    JobDetailView.tsx        REFACTOR  current detail UI, fed by job
  App.tsx                    REFACTOR  two-column layout + state
```

### 9.2 UX states
| Status      | Display                                | Action          |
|-------------|----------------------------------------|-----------------|
| pending     | spinner + "Đang chờ..."               | (none)          |
| processing  | spinner + "Đang xử lý..."             | (none)          |
| success     | green check + "Hoàn tất"              | open detail     |
| failed      | red x + sanitized `error_message`     | [Retry] button  |
| timeout     | warning + "Refresh để check"          | [Refresh]       |

### 9.3 New env vars (FE)
```
VITE_API_BASE_URL
VITE_MSAL_BE_CLIENT_ID
```

---

## 10. Deployment (VPS Ubuntu)

- **systemd units:** `itr-api.service`, `itr-worker.service` (both `Restart=always`).
- **Postgres + Redis:** packaged installs, bound to localhost.
- **nginx:** TLS termination, reverse proxy to uvicorn, serves FE static build.
- **File permissions:** `FILES_ROOT` owned by service user, mode `0700`.
- **Backups:** nightly `pg_dump` + `tar` of `FILES_ROOT` (out of scope for code, documented in README).

---

## 11. Testing Strategy

- **Unit:** JWT verification (valid, expired, wrong audience, wrong tenant, malformed). Constants importable & used everywhere (lint rule / grep audit).
- **Integration:** end-to-end job lifecycle against a real Postgres + Redis (testcontainers). Retention cap, retry, stuck-job requeue, re-process lineage.
- **Auth e2e:** mock JWKS server; assert 401 on bad tokens; assert JIT user creation; assert 404 cross-user access.
- **FE:** polling stops on terminal state and at attempt cap; retry button posts to reprocess endpoint.

---

## 12. Open Questions / Future Work
- Migrate file storage to object storage (R2/MinIO) when multi-instance scaling is needed.
- Replace polling with SSE if poll volume becomes a concern.
- Add admin endpoint to list all users / disk usage.
- Pre-signed download URLs once object storage is adopted.
