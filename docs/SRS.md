# Software Requirements Specification — ITR Extract

**Version:** 2.0
**Status:** Active baseline
**Last updated:** 2026-05-08
**Audience:** Engineers, QA, Agentic AI agents working in the codebase

> **Conventions**
> - **MUST** = mandatory; **SHOULD** = recommended; **MAY** = optional.
> - Tất cả con số là source-of-truth — code phải đọc từ `config/constants.py` (BE) hoặc `src/lib/constants.ts` (FE), KHÔNG inline literal.
> - Nếu code mâu thuẫn với SRS, code sai. Update code, không update SRS để khớp.

---

## 1. System overview

| Component | Tech | Cardinality | Notes |
|---|---|---|---|
| Frontend SPA | React 19 + Vite + MSAL | 1 instance per deploy | Static bundle, served via CDN/nginx |
| Backend API | FastAPI (Python 3.12+) | 1+ instances | Stateless, scale horizontal |
| Worker | arq (Redis-backed) | 1+ processes | Stateful queue (Redis), CPU-bound jobs |
| Database | PostgreSQL 16+ | 1 primary | Schema migrations via Alembic |
| Cache/Queue | Redis 7+ | 1 instance | arq queue + JWKS cache (in-memory) |
| Identity provider | Microsoft Entra (Azure AD) | External | Single tenant per deployment |
| AI provider | Google Gemini API | External | Per-call billing |

---

## 2. Functional requirements

### 2.1 Authentication & authorization

| ID | Requirement |
|---|---|
| FR-AUTH-1 | User MUST authenticate via Microsoft Entra OAuth 2.0 PKCE flow trước khi gọi bất kỳ endpoint `/api/*` nào (trừ `/healthz`). |
| FR-AUTH-2 | Frontend MUST sử dụng `loginRedirect` (không popup) — popup flow MSAL v5 không tự đóng đáng tin cậy. |
| FR-AUTH-3 | Backend MUST verify JWT signature qua Microsoft JWKS public keys. JWKS cache TTL = `JWKS_CACHE_TTL_SECONDS` (600s). |
| FR-AUTH-4 | Backend MUST refresh JWKS cache ngay khi gặp `kid` không có trong cache (1 lần retry). |
| FR-AUTH-5 | Backend MUST validate JWT claims: signature, expiry, audience = `MSAL_BE_CLIENT_ID`, leeway = `JWT_LEEWAY_SECONDS` (60s), algorithm = `RS256`. |
| FR-AUTH-6 | Trong production (`environment=production`): MUST validate `tid` (tenant) và `iss` (issuer) khớp `MSAL_TENANT_ID`. |
| FR-AUTH-7 | Trong dev (`MSAL_TENANT_ID` trống): MUST skip tid/iss check, dùng `/common` endpoint, accept ID token thay vì access token. |
| FR-AUTH-8 | User identification: `claims["oid"]` ưu tiên, fallback `claims["sub"]`. Phải parse được thành UUID. |
| FR-AUTH-9 | Backend MUST upsert vào `users` table mỗi request authenticated: insert nếu mới, update `last_login` + email/name nếu đã tồn tại. |
| FR-AUTH-10 | Frontend MUST refresh token âm thầm qua `acquireTokenSilent`. Nếu fail với `InteractionRequiredAuthError` → MUST redirect login. |
| FR-AUTH-11 | Frontend MUST có nút "Sign out" gọi `logoutRedirect` clear sessionStorage. |
| FR-AUTH-12 | App startup MUST fail-fast nếu `environment=production` mà thiếu `MSAL_TENANT_ID`, `MSAL_BE_CLIENT_ID` placeholder, `GEMINI_API_KEY` trống, hoặc `ALLOWED_ORIGINS` chứa localhost. |

### 2.2 Job lifecycle

#### State machine
```
       create_job
PENDING ─────────► PROCESSING ─────────► SUCCESS
   ▲                  │                      
   │                  └─────────► FAILED ────► reprocess → PENDING (new job)
   │                                              │
   └────────── retry (< MAX_RETRY_ATTEMPTS) ──────┘
```

| ID | Requirement |
|---|---|
| FR-JOB-1 | Job states MUST là một trong: `PENDING`, `PROCESSING`, `SUCCESS`, `FAILED`. |
| FR-JOB-2 | Khi tạo, status = `PENDING`. Khi worker pick up, transition `PENDING → PROCESSING` (atomic via DB commit). |
| FR-JOB-3 | Worker phải skip job nếu status đã ≠ `PENDING` (deleted/picked-up race). |
| FR-JOB-4 | Khi success: lưu `analysis_data` (JSONB), `email_html` (Text), `has_econsent` (bool), set `finished_at`. |
| FR-JOB-5 | Khi failed: nếu `retry_count < MAX_RETRY_ATTEMPTS` (3) → status quay về `PENDING`, raise để arq retry. Hết retry → status `FAILED`, lưu `error_message` (≤500 chars), `error_details.traceback`. |
| FR-JOB-6 | Job timeout: arq kill process_job sau `JOB_TIMEOUT_SECONDS` (300s). Mỗi Gemini call có hard cap `_GEMINI_HARD_TIMEOUT_S` (270s). |
| FR-JOB-7 | Worker concurrency: tối đa `WORKER_MAX_CONCURRENT_JOBS` (4) job song song trong 1 worker process. |
| FR-JOB-8 | `process_job` MUST chạy `pipeline.run_extraction` trong thread executor (`run_in_executor`) — KHÔNG block arq event loop. |
| FR-JOB-9 | Cron requeue: mỗi `STUCK_JOB_SWEEP_INTERVAL_MIN` (1 phút), tìm job ở trạng thái PENDING/PROCESSING > `STUCK_JOB_THRESHOLD_SECONDS` (360s) → reset PENDING + re-enqueue. |
| FR-JOB-10 | Cron cleanup: hằng ngày lúc `CLEANUP_ORPHAN_FILES_HOUR` (3 AM server time) — xóa folder không có DB row tương ứng. |

### 2.3 Upload constraints

| ID | Requirement |
|---|---|
| FR-UP-1 | File extension MUST là `.pdf`. Filename là user input, hệ thống không tin cậy MIME type từ client. |
| FR-UP-2 | Size MUST ≤ `MAX_INPUT_FILE_SIZE_BYTES` (50 MB = 52,428,800 bytes). |
| FR-UP-3 | Backend MUST stream theo chunk 1 MiB và bail-out sớm khi vượt size — KHÔNG buffer toàn bộ vào RAM. |
| FR-UP-4 | Empty file (0 bytes) → reject 400. |
| FR-UP-5 | User đã có ≥ `MAX_ACTIVE_JOBS_PER_USER` (5) jobs ở trạng thái active (`PENDING`/`PROCESSING`) → reject 429. Cùng rule cho `/reprocess`. |
| FR-UP-6 | Mỗi user giữ tối đa `MAX_SESSIONS_PER_USER` (10) jobs trong history. Khi tạo mới → eviction job cũ nhất có status terminal (`SUCCESS`/`FAILED`). KHÔNG bao giờ evict job đang active. |
| FR-UP-7 | Filename chứa CR/LF/control chars MUST bị strip trước khi đặt vào `Content-Disposition` header (xem `_safe_download_name` trong api/jobs.py). |

### 2.4 Rate limiting

| ID | Requirement |
|---|---|
| FR-RL-1 | Default per-IP limit `USER_RATE_LIMIT` = 30 requests/minute áp dụng cho tất cả route qua `SlowAPIMiddleware`. |
| FR-RL-2 | `POST /api/jobs` và `POST /api/jobs/{id}/reprocess` siết chặt thêm `UPLOAD_RATE_LIMIT` = 10/minute. |
| FR-RL-3 | Khi vượt limit: 429 `Retry-After` header. |
| FR-RL-4 | Rate limit là defense-in-depth — KHÔNG thay thế per-user quota DB ở FR-UP-5/6. |

### 2.5 PDF processing pipeline

| ID | Requirement |
|---|---|
| FR-PDF-1 | Pipeline gọi 2 Gemini task song song (ThreadPoolExecutor, max 2 workers). |
| FR-PDF-2 | **Task 1 — E-Consent Detection**: input = full PDF, output = list `econsent_pages` (1-indexed) + `econsent_forms[]` (form_number, title, jurisdiction, pages). |
| FR-PDF-3 | **Task 2 — Email Extraction**: input = page 1 (cover letter), output = `tax_year`, `return_type`, `client.{name,email,address}`, `cpa_firm.{name, sharefile_subdomain}`, federal/state outcomes theo 5 pattern (xem 2.6). |
| FR-PDF-4 | Task 1 config: `temperature=0.0, thinking_budget=4096, timeout_s=240`. |
| FR-PDF-5 | Task 2 config: `temperature=0.0, thinking_budget=0, timeout_s=120` + `TASK2_RESPONSE_SCHEMA` enforced. |
| FR-PDF-6 | Mỗi Gemini call có 2 attempt với 30s sleep giữa các retry (cho timeout). |
| FR-PDF-7 | Bất kỳ error nào (timeout, HTTP 4xx/5xx, no candidates, no text, JSON parse fail) MUST `raise RuntimeError(...)`, KHÔNG `sys.exit()` (sẽ kill worker). |
| FR-PDF-8 | E-consent extraction: tách các page chỉ định bằng `fitz` (PyMuPDF), tạo PDF mới chỉ chứa các page đó. Validate page indices nằm trong khoảng `[1, total_pages]`. |
| FR-PDF-9 | Email HTML generation: bulletproof Markdown `**bold**` cho keyword + số tiền, parser convert thành HTML `<strong>`. |

### 2.6 Email outcome patterns

Backend MUST sinh email theo đúng 1 trong 5 pattern, không paraphrase:

| Pattern | Trigger | Template phrase |
|---|---|---|
| **Balance due** | `balance_due > 0` | "Balance due of $X. Please [pay method]..." |
| **Overpayment credited** | `overpayment > 0`, `credited_to_next_year == overpayment` | "Overpayment of $X credited to [next_year] tax." |
| **Refund deposited** | `refund > 0`, no credit | "Refund of $X will be deposited..." |
| **Partial credit + partial refund** | `overpayment > 0`, `credited_to_next_year > 0`, `refund > 0`, `credit + refund == overpayment` | "Overpayment of $X of which $Y credited to [next_year] tax and $Z will be deposited..." |
| **Zero outcome** | All fields ≈ 0 | "No tax is payable with the filing of this return." |

PTE (Pass-Through Entity) payment lines: chỉ render cho `return_type` ∈ {S-Corp 1120S, Partnership 1065}. Whitelist enforce ở code, không tin AI.

### 2.7 API endpoints

| Method | Path | Auth | Rate limit | Description |
|---|---|---|---|---|
| GET | `/healthz` | ❌ | default | Liveness — query `SELECT 1` từ DB |
| GET | `/api/me` | ✅ | default | User info từ JWT claims |
| POST | `/api/jobs` | ✅ | upload (10/min) | Upload PDF, tạo job |
| GET | `/api/jobs` | ✅ | default | List ≤10 jobs gần nhất của user |
| GET | `/api/jobs/{id}` | ✅ | default | Detail 1 job (scoped user.id) |
| GET | `/api/jobs/{id}/input.pdf` | ✅ | default | Download original PDF |
| GET | `/api/jobs/{id}/econsent.pdf` | ✅ | default | Download e-consent PDF (404 nếu `has_econsent=false`) |
| POST | `/api/jobs/{id}/reprocess` | ✅ | upload (10/min) | Tạo job mới từ PDF gốc — chỉ allow nếu parent status=`FAILED` |
| DELETE | `/api/jobs/{id}` | ✅ | default | Xóa job + files. Reject 409 nếu status=`PROCESSING`. |

**Authorization rule:** mọi endpoint `/api/jobs/{id}*` MUST scope theo `user.id` — user A không bao giờ thấy/access job của user B (IDOR prevention).

### 2.8 Storage layout

```
$FILES_ROOT/
└── {user_id}/                    UUID
    └── {job_id}/                 UUID
        ├── input.pdf             original upload
        └── econsent.pdf          generated (chỉ có nếu detect được forms)
```

| ID | Requirement |
|---|---|
| FR-FS-1 | Path computed từ UUID, KHÔNG từ user input → no traversal possible. |
| FR-FS-2 | `delete_job_dir` MUST idempotent (xóa folder không tồn tại không error). |
| FR-FS-3 | `enforce_session_cap` MUST commit DB trước, xóa file sau. File orphan (DB row đã xóa nhưng file còn) sẽ được cron dọn. |
| FR-FS-4 | Worker process_job MUST đọc input.pdf trước khi commit `PROCESSING` status để fail-fast nếu file mất. |

### 2.9 Frontend behavior

| ID | Requirement |
|---|---|
| FR-FE-1 | `useJobs` hook MUST chỉ chạy sau khi `isAuthenticated=true` (component `AuthenticatedApp` mount sau gate). |
| FR-FE-2 | `useJobPolling` MUST exponential backoff khi error: 1×, 2×, 4×, 8× của `POLLING_INTERVAL_MS` (cap 30s). Reset về 0 khi success. |
| FR-FE-3 | Polling MUST stop khi nhận 404 (job đã bị delete). |
| FR-FE-4 | Polling max attempts = `POLLING_MAX_ATTEMPTS` (150) → set `timedOut=true`. |
| FR-FE-5 | Reprocess/Delete buttons MUST disable + show loading state khi đang chạy → chống double-click. |
| FR-FE-6 | Delete MUST hỏi `window.confirm` trước. |
| FR-FE-7 | `email_html` từ BE MUST đi qua `DOMPurify.sanitize` trước khi đặt vào `innerHTML` (cả render và gửi Graph API). |
| FR-FE-8 | Email edit lưu vào localStorage key `itr.email_edit.{job_id}` lúc blur. Restore khi job_id load lại. Clear khi delete job. |
| FR-FE-9 | API errors MUST hiện qua Toast (top-right, auto-dismiss 5s). |
| FR-FE-10 | Token refresh failure (`InteractionRequiredAuthError`) MUST redirect login, không show generic error. |

### 2.10 Microsoft Graph integration

| ID | Requirement |
|---|---|
| FR-GR-1 | Outlook draft create dùng `POST /me/messages` với body sanitize (DOMPurify). |
| FR-GR-2 | Attachment econsent: `@odata.type: #microsoft.graph.fileAttachment`, base64 encoded bytes. |
| FR-GR-3 | Subject template: `{tax_year} Income Tax Return — {client_name}`. |
| FR-GR-4 | Filename attachment cố định: `Econsent.pdf` (không suffix client name — client tự nhận diện qua subject + email body). |
| FR-GR-5 | Token cho Graph API request scope `Mail.ReadWrite` qua `acquireTokenSilent`, fallback `acquireTokenPopup`. |

---

## 3. Non-functional requirements

### 3.1 Performance

| ID | Requirement |
|---|---|
| NFR-P-1 | Upload + queue = phản hồi 202 trong ≤ 1s với PDF 10MB. |
| NFR-P-2 | End-to-end (upload → success) p95 ≤ 90s với PDF ≤ 50 pages. |
| NFR-P-3 | API list/detail p95 ≤ 200ms (excl. polling). |
| NFR-P-4 | DB query plan: list jobs phải dùng index `idx_jobs_user_created`. Active count phải dùng partial index `idx_jobs_status_active`. |

### 3.2 Security

| ID | Requirement |
|---|---|
| NFR-S-1 | All `/api/*` traffic MUST qua HTTPS trong production (TLS 1.2+). |
| NFR-S-2 | Backend set security headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Strict-Transport-Security: max-age=31536000; includeSubDomains`, `CSP: default-src 'none'; frame-ancestors 'none'`, `Permissions-Policy: geolocation=(), camera=(), microphone=()`. |
| NFR-S-3 | CORS `allow_origins` MUST exact-match domain frontend production (no wildcard). |
| NFR-S-4 | Secrets (`GEMINI_API_KEY`, DB password) MUST không log, không xuất hiện trong error response. |
| NFR-S-5 | PDF content KHÔNG bao giờ log. Error chỉ log filename + jobId + size. |
| NFR-S-6 | Filename trong `Content-Disposition` MUST sanitize CR/LF/control chars. |
| NFR-S-7 | DOMPurify sanitize tất cả AI-generated HTML trước khi `innerHTML` hoặc gửi qua Graph API. |
| NFR-S-8 | Per-user quota DB là source of truth, rate limit chỉ là layer phòng thủ thêm. |

### 3.3 Reliability

| ID | Requirement |
|---|---|
| NFR-R-1 | Worker MUST không crash do Gemini error. Errors phải `raise` (job-level fail), không `sys.exit`. |
| NFR-R-2 | Job retry: tối đa 3 lần, exponential backoff `RETRY_BACKOFF_SECONDS` (5s, 15s). |
| NFR-R-3 | Stuck job recovery: cron requeue sau 6 phút stale. |
| NFR-R-4 | DB commit MUST trước file system mutation. Orphan file < orphan DB row (cleanup được). |
| NFR-R-5 | App startup MUST fail-fast với error message rõ nếu config production sai. |

### 3.4 Maintainability

| ID | Requirement |
|---|---|
| NFR-M-1 | Constants MUST centralize trong `config/constants.py` (BE) và `src/lib/constants.ts` (FE). KHÔNG inline literal. |
| NFR-M-2 | Settings MUST đọc qua `get_settings()` (pydantic-settings). KHÔNG `os.environ.get` rải rác. |
| NFR-M-3 | DB schema thay đổi MUST qua Alembic migration với upgrade + downgrade. |
| NFR-M-4 | Type hints bắt buộc cho function signatures Python. TypeScript strict mode bật. |

### 3.5 Observability

| ID | Requirement |
|---|---|
| NFR-O-1 | `/healthz` MUST check DB (Redis check là planned trong P2). |
| NFR-O-2 | Worker log MUST include job_id + duration + status mỗi job. |
| NFR-O-3 | (Planned) Structured JSON logging cho production. |
| NFR-O-4 | (Planned) Metrics endpoint cho Prometheus. |

---

## 4. Data model

```
┌──────────────────────┐         ┌────────────────────────────────┐
│ users                │         │ jobs                           │
├──────────────────────┤         ├────────────────────────────────┤
│ id (PK, UUID)        │◄────────│ user_id (FK CASCADE, UUID)     │
│ email (Text)         │         │ id (PK, UUID)                  │
│ name (Text?)         │         │ status (enum job_status)       │
│ tenant_id (UUID)     │         │ original_filename (Text)       │
│ created_at (TIMESTZ) │         │ input_size_bytes (BigInt)      │
│ last_login (TIMESTZ) │         │ analysis_data (JSONB?)         │
└──────────────────────┘         │ email_html (Text?)             │
                                 │ has_econsent (Bool)            │
                                 │ created_at, started_at,        │
                                 │   finished_at (TIMESTZ?)       │
                                 │ error_message (Text?, ≤500)    │
                                 │ error_details (JSONB?)         │
                                 │ retry_count (Int, default 0)   │
                                 │ parent_job_id (FK SET NULL)    │
                                 └────────────────────────────────┘

ENUM job_status: pending | processing | success | failed

Indexes:
- idx_jobs_user_created  ON jobs(user_id, created_at DESC)
- idx_jobs_status_active ON jobs(status) WHERE status IN ('pending','processing')
```

---

## 5. Configuration matrix

| Variable | Type | Required | Default | Notes |
|---|---|---|---|---|
| `DATABASE_URL` | str | ✅ | — | `postgresql+asyncpg://...` |
| `REDIS_URL` | str | ⚠️ | `redis://localhost:6379` | |
| `MSAL_TENANT_ID` | str | prod only | `""` | Empty = dev permissive |
| `MSAL_BE_CLIENT_ID` | str | ✅ | — | Azure AD app client ID |
| `FILES_ROOT` | path | ⚠️ | `/var/lib/itr_extract/files` | Phải writable |
| `ALLOWED_ORIGINS` | JSON list[str] | ⚠️ | `["http://localhost:5173"]` | Strict match |
| `GEMINI_API_KEY` | str | ✅ | — | aistudio.google.com |
| `ENVIRONMENT` | str | recommend | `development` | Set `production` để bật strict checks |

| Frontend env | | | |
|---|---|---|---|
| `VITE_API_BASE_URL` | str | ✅ | — | Backend URL |
| `VITE_MSAL_CLIENT_ID` | str | ✅ | — | Cùng app reg như BE |
| `VITE_MSAL_BE_CLIENT_ID` | str | ✅ | — | Cùng giá trị `VITE_MSAL_CLIENT_ID` |
| `VITE_MSAL_TENANT_ID` | str | prod only | — | Empty = dev mode |

---

## 6. Error handling

### Standard error response
```json
{ "detail": "<human-readable message>" }
```

| HTTP | Trigger |
|---|---|
| 400 | Invalid input (bad PDF, empty file, missing required field) |
| 401 | Missing/invalid Bearer token |
| 404 | Resource not found OR resource belongs to other user (no leak) |
| 409 | State conflict (delete PROCESSING, reprocess non-FAILED) |
| 410 | Gone (parent job's input.pdf deleted before reprocess) |
| 413 | Payload too large |
| 429 | Rate limit OR per-user quota exceeded |
| 500 | Unhandled (must be logged + alerted) |

### Frontend behavior
- 401 → MSAL refresh; nếu fail → loginRedirect
- 4xx → Toast với detail từ response
- 5xx → Toast generic + log
- Network error → Toast retry hint

---

## 7. Domain glossary

| Term | Meaning |
|---|---|
| **ITR** | Income Tax Return (US federal + state forms) |
| **Cover letter** | Trang đầu tiên của ITR PDF, chứa client info + tax outcome |
| **E-consent form** | Form 8879, 8453, FTB 8453, hoặc tương đương — form authorize CPA e-file thay client. Phải có chữ ký client. |
| **Tax outcome** | Một trong: balance due, refund, overpayment, credit-to-next-year, zero |
| **PTE payment** | Pass-Through Entity tax payment — chỉ áp dụng S-Corp/Partnership |
| **Tenant ID** | Azure AD organization ID |
| **OID** | Object ID Azure AD — định danh user duy nhất trong tenant |
| **Job** | Một lần xử lý 1 PDF từ upload → output |
| **Active job** | Status = pending hoặc processing |
| **Terminal job** | Status = success hoặc failed |
| **Reprocess** | Tạo job MỚI dùng input.pdf của job cũ (không retry in-place) |

---

## 8. References

- [docs/PRD.md](PRD.md) — product vision & users
- [docs/AUDIT_FINAL.md](AUDIT_FINAL.md) — production readiness
- [docs/SETUP_REPORT.md](SETUP_REPORT.md) — setup history
- [README.md](../README.md) — runbook
- [config/constants.py](../config/constants.py) — source of truth cho mọi giới hạn
- [src/lib/constants.ts](../../itr_extract_fe/src/lib/constants.ts) — FE constants (mirror BE)
