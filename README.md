# ITR Extract — Backend

Hệ thống xử lý PDF Income Tax Return (ITR) tự động bằng Gemini AI:
1. Detect & extract các trang **e-consent** → PDF
2. Extract dữ liệu cover letter và sinh **email template** (DOCX/HTML) gửi cho client

Backend là REST API (FastAPI) + background worker (arq + Redis) + PostgreSQL, với auth qua Microsoft Entra (Azure AD). Frontend riêng ở repo [`itr_extract_fe`](../itr_extract_fe/).

---

## Tech stack

| | |
|---|---|
| API | FastAPI (Python 3.12+) |
| Worker | arq (Redis-backed queue) |
| DB | PostgreSQL 16+ với SQLAlchemy 2.x async + Alembic migrations |
| Queue | Redis 7+ |
| Auth | Microsoft Entra (Azure AD) JWT bearer tokens |
| AI | Google Gemini API |

Luồng:
```
Frontend (React + MSAL)
   │ POST /api/jobs với PDF + Bearer token
   ▼
FastAPI ── verify JWT ── create Job row ── enqueue ─┐
   │                                                ▼
   │                                              Redis
   │                                                │
   ▼                                                ▼
PostgreSQL <── update status ── arq worker ── Gemini API
                                    │
                                    ▼
                              FILES_ROOT/{user}/{job}/
                              (input.pdf, output files)
```

---

## Prerequisites

- **Python 3.12+**
- **PostgreSQL 16+** chạy local (hoặc Docker)
- **Redis 7+** chạy local
- **Google Gemini API key** — [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
- **Azure AD App Registration** — xem [phần Azure AD setup](#azure-ad-setup) bên dưới
- (Khuyến nghị) WSL2 hoặc Linux native — chưa test trên Windows native

---

## Quick start (TL;DR)

```bash
# 1. Clone & vào project
cd itr_extract

# 2. Tạo Python venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Cài DB
sudo systemctl start postgresql redis-server
psql -U postgres -h 127.0.0.1 -c 'CREATE DATABASE itr_extract;'

# 4. Cấu hình
cp .env.example .env
# → mở .env, điền DATABASE_URL (password postgres), GEMINI_API_KEY,
#   MSAL_BE_CLIENT_ID (lấy từ Azure AD app registration)

# 5. Tạo storage folder
mkdir -p storage_data

# 6. Chạy migrations
alembic upgrade head

# 7. Chạy API + worker (mỗi lệnh ở 1 terminal riêng)
uvicorn api.app:create_app --factory --reload --port 8000
arq worker.settings.WorkerSettings
```

API sẵn sàng tại `http://localhost:8000`. Tiếp theo set up frontend (xem [itr_extract_fe/README.md](../itr_extract_fe/README.md)).

---

## Detailed setup

### 1. Python virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> ⚠️ Ubuntu 23.04+ chặn `pip install` global với lỗi `externally-managed-environment`. Bắt buộc dùng venv.

### 2. PostgreSQL

**Cài và chạy:**
```bash
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
```

**Set password cho user `postgres` (lần đầu):**
```bash
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'your_password';"
```

**Tạo database:**
```bash
PGPASSWORD=your_password psql -U postgres -h 127.0.0.1 -c 'CREATE DATABASE itr_extract;'
```

### 3. Redis

```bash
sudo apt install redis-server
sudo systemctl start redis-server
redis-cli ping  # → PONG
```

### 4. Cấu hình `.env`

```bash
cp .env.example .env
```

Mở `.env` và điền:

| Var | Dev | Production |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:PASS@127.0.0.1:5432/itr_extract?ssl=disable` | DSN production DB |
| `REDIS_URL` | `redis://localhost:6379` | Redis production URL |
| `MSAL_TENANT_ID` | **để trống** (dev permissive mode) | tenant ID của khách hàng |
| `MSAL_BE_CLIENT_ID` | client ID của Azure AD app | client ID của Azure AD app |
| `FILES_ROOT` | `./storage_data` | `/var/lib/itr_extract/files` (writable) |
| `ALLOWED_ORIGINS` | `["http://localhost:5173"]` | `["https://your-frontend.com"]` |
| `GEMINI_API_KEY` | API key từ aistudio.google.com | API key |

> 💡 **Tại sao để trống `MSAL_TENANT_ID` trong dev?** Khi trống, backend dùng `/common` endpoint của Azure AD và bỏ qua tenant/issuer check, cho phép login bằng personal Microsoft account (outlook/hotmail) để test. **Không bao giờ deploy mode này lên public** vì nó accept token từ bất kỳ Microsoft account nào. Xem [docs/SETUP_REPORT.md](docs/SETUP_REPORT.md#issue-3-dev-mode-auth-quá-lỏng-security-note) để hiểu rõ.

### 5. Database migrations

```bash
alembic upgrade head
```

Kiểm tra:
```bash
PGPASSWORD=$YOUR_PASS psql -U postgres -h 127.0.0.1 -d itr_extract -c '\dt'
# Phải thấy: alembic_version, jobs, users
```

### 6. Storage folder

```bash
mkdir -p storage_data
```

(Đã gitignored. Path khớp với `FILES_ROOT` trong `.env`.)

---

## Azure AD setup

Cần một **App Registration** trong Azure Portal. Cùng một app phục vụ cả frontend (SPA) và backend (custom API).

### Tạo app registration (1 lần)

1. [portal.azure.com](https://portal.azure.com) → **Microsoft Entra ID** → **App registrations** → **New registration**
2. **Name:** `ITR Extract` (tùy ý)
3. **Supported account types:** chọn theo môi trường
   - Dev/test với personal account: **Accounts in any organizational directory and personal Microsoft accounts**
   - Production cho khách hàng: **Accounts in this organizational directory only**
4. **Redirect URI:** Single-page application (SPA), `http://localhost:5173` (cho dev)
5. → **Register**, copy **Application (client) ID** → đó là `MSAL_BE_CLIENT_ID` / `VITE_MSAL_CLIENT_ID`

### Expose API scope

Vẫn ở App Registration vừa tạo:

1. **Expose an API** → **Set** Application ID URI (Azure tự gợi ý `api://{client_id}`)
2. **Add a scope:**
   - Name: `access_as_user`
   - Who can consent: **Admins and users**
   - Display name: `Access ITR Extract API`
   - Description: `Allows the app to access ITR Extract API on behalf of the user`
   - State: **Enabled**

### API permissions (Microsoft Graph)

Vẫn ở App Registration:

1. **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated**
2. Add: `User.Read`, `Mail.ReadWrite`
3. (Production) **Grant admin consent** — chỉ admin của tenant làm được

### Redirect URIs cần đăng ký

| Môi trường | Redirect URI |
|---|---|
| Dev | `http://localhost:5173` |
| Production | `https://your-frontend-domain.com` |

---

## Running

Hai process chạy song song (mỗi cái 1 terminal):

```bash
# Terminal 1 — API server
source venv/bin/activate
uvicorn api.app:create_app --factory --reload --port 8000
```

```bash
# Terminal 2 — Background worker
source venv/bin/activate
arq worker.settings.WorkerSettings
```

> ⚠️ **Khi đổi `.env`, phải restart cả hai.** `--reload` của uvicorn chỉ watch code, không reload `.env`. arq worker không có `--reload`.

### Health check

```bash
curl http://localhost:8000/healthz
# → {"status": "ok"}
```

---

## Switching to production

Sau khi setup dev xong, chuyển sang production chỉ cần **2 bước**:

### Bước 1: Cập nhật Azure AD

- IT admin của khách hàng grant admin consent cho `User.Read`, `Mail.ReadWrite`, `access_as_user`
- Thêm production redirect URI vào app registration: `https://your-frontend-domain.com`
- Lấy **Tenant ID** của tổ chức khách hàng

### Bước 2: Cập nhật `.env`

**Backend `.env`:**
```diff
-MSAL_TENANT_ID=
+MSAL_TENANT_ID=<tenant-id-của-khách-hàng>
+ALLOWED_ORIGINS=["https://your-frontend-domain.com"]
+FILES_ROOT=/var/lib/itr_extract/files
```

**Frontend `.env`:**
```diff
+VITE_MSAL_TENANT_ID=<tenant-id-của-khách-hàng>
+VITE_API_BASE_URL=https://your-backend-domain.com
```

Khi `MSAL_TENANT_ID` được set, backend tự động:
- Strict tenant check (chỉ accept token có `tid` khớp)
- Validate issuer chuẩn
- Verify audience là custom BE scope

Khi `VITE_MSAL_TENANT_ID` được set, frontend tự động:
- `authority` chuyển từ `/common` → `/{tenant-id}`
- `loginRequest` thêm BE_SCOPE để consent ngay khi login
- `useAccessToken` trả về access token chuẩn (không phải ID token)

**Không cần đổi code** — cơ chế switch hoàn toàn dựa vào env vars.

---

## Project structure

```
itr_extract/
├── api/                    FastAPI app
│   ├── app.py              create_app() factory
│   ├── jobs.py             POST/GET /api/jobs endpoints
│   ├── me.py               GET /api/me
│   ├── health.py           GET /healthz
│   └── schemas.py          Pydantic request/response models
├── auth/                   JWT verification
│   ├── deps.py             FastAPI dependency `get_current_user`
│   ├── jwt.py              verify_token() — JWKS-based JWT validation
│   └── jwks.py             JWKS fetch + cache
├── config/
│   ├── settings.py         Pydantic-settings (đọc .env)
│   └── constants.py        Hằng số (timeouts, limits, paths)
├── db/
│   ├── base.py             SQLAlchemy engine + Base
│   ├── models.py           User, Job ORM models
│   └── session.py          AsyncSession dependency
├── jobs/                   Job orchestration logic
├── storage/
│   └── files.py            FILES_ROOT layout (input.pdf, outputs)
├── worker/                 arq worker
│   ├── settings.py         WorkerSettings — entry point cho arq
│   ├── tasks.py            process_job() — logic chính xử lý PDF
│   ├── cron.py             Cron jobs (requeue stuck, cleanup)
│   └── queue.py            enqueue helpers
├── alembic/                DB migrations
│   └── versions/0001_initial.py
├── prompts/                Gemini prompts (Task 1, Task 2)
├── docs/
│   ├── SETUP_REPORT.md     Báo cáo chi tiết setup + issues
│   ├── architecture.md     Thiết kế Task 2 (legacy)
│   └── superpowers/        Plans & specs (legacy)
├── main.py                 CLI standalone (legacy, không dùng trong web flow)
└── samples/                Sample PDFs (gitignored)
```

---

## Troubleshooting

| Triệu chứng | Nguyên nhân | Fix |
|---|---|---|
| `command alembic not found` | Chưa activate venv | `source venv/bin/activate` |
| `externally-managed-environment` khi pip install | Ubuntu chặn pip system | Tạo venv (`python3 -m venv venv`) |
| `getaddrinfo` failure khi connect DB | asyncpg mặc định bật SSL | Thêm `?ssl=disable` vào DATABASE_URL hoặc đảm bảo `connect_args={"ssl": False}` (đã set sẵn) |
| `DuplicateObjectError: type "job_status" already exists` | Migration enum bị tạo 2 lần | Đã fix trong `0001_initial.py` (dùng `postgresql.ENUM(create_type=False)`). Nếu vẫn lỗi: DROP DATABASE rồi tạo lại |
| uvicorn `Attribute "app" not found` | `app` là factory function | Dùng `--factory api.app:create_app` |
| arq `No module named workers` | Tên module là `worker` (số ít) | `arq worker.settings.WorkerSettings` |
| API trả 401 `Invalid token: Not enough segments` | FE gửi opaque token thay vì JWT | Verify FE dùng đúng `useAccessToken` (idToken trong dev, accessToken trong prod) |
| API trả 401 `Invalid token: Wrong tenant` | `MSAL_TENANT_ID` set sai trong dev | Để TRỐNG `MSAL_TENANT_ID` trong dev mode |
| Worker fail `FileNotFoundError /var/lib/itr_extract/...` | Worker chạy trước khi đổi FILES_ROOT | Restart arq worker |
| Job đang chờ mãi (pending) | Worker không chạy hoặc bị stuck | Check worker terminal; xóa job và upload lại; hoặc đợi cron requeue (~6 phút) |

Chi tiết toàn bộ vấn đề đã gặp + fix: [docs/SETUP_REPORT.md](docs/SETUP_REPORT.md)

---

## API endpoints

| Method | Path | Mô tả |
|---|---|---|
| GET | `/healthz` | Health check (no auth) |
| GET | `/api/me` | User profile từ JWT claims |
| POST | `/api/jobs` | Upload PDF, tạo job (multipart `file`) |
| GET | `/api/jobs` | List jobs của user hiện tại |
| GET | `/api/jobs/{id}` | Chi tiết 1 job |
| POST | `/api/jobs/{id}/reprocess` | Tạo job mới từ PDF của job cũ |
| DELETE | `/api/jobs/{id}` | Xóa job + files |

Tất cả endpoint `/api/*` yêu cầu header `Authorization: Bearer <jwt>`.

---

## Tests

```bash
source venv/bin/activate
pytest
```

---

## License

MIT (xem [LICENSE](LICENSE))
