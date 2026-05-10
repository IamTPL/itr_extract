# ITR Extract

## 1. Vấn đề & Giải pháp

|               |                                                                                                                                                                                                                  |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Bài toán**  | CPA firms ở Mỹ phải xử lý hàng trăm hồ sơ ITR mỗi mùa thuế. Mỗi hồ sơ: đọc cover letter → soạn email summary → tách e-consent → đính kèm Outlook draft. Tổng ~15 phút/hồ sơ, dễ sai khi paraphrase outcome thuế. |
| **Giải pháp** | Web app upload PDF → backend dùng AI (Gemini) extract → frontend cho user review/edit → tạo Outlook draft qua Microsoft Graph API. Toàn bộ workflow <2 phút.                                                     |
| **Đo lường**  | Thời gian: 15min → <2min. Accuracy: ≥95% match với CPA review. Không thay phần mềm tax prep, chỉ là layer post-processing.                                                                                       |

---

## 2. Kiến trúc tổng quan (C4 Level 1 — Context)

```
                    ┌──────────────────────┐
                    │   CPA Staff (User)   │
                    │  Microsoft 365 acc   │
                    └──────────┬───────────┘
                               │ Web browser
                               ▼
        ┌────────────────────────────────────────┐
        │       ITR Extract Web App              │
        │   (Frontend + Backend + Worker + DB)   │
        └──────┬───────────────┬──────────┬──────┘
               │               │          │
               ▼               ▼          ▼
   ┌────────────────┐  ┌─────────────┐  ┌──────────────────┐
   │ Microsoft Entra│  │ Google      │  │ Microsoft Graph  │
   │ (Azure AD)     │  │ Gemini API  │  │ /me/messages     │
   │                │  │             │  │                  │
   │ - Login        │  │ - PDF       │  │ - Tạo Outlook    │
   │ - JWT verify   │  │   analysis  │  │   draft          │
   └────────────────┘  └─────────────┘  └──────────────────┘
```

**3 dependency bên ngoài:**

- **Microsoft Entra** (auth/identity) — không tốn tiền, dùng tier miễn phí của khách hàng
- **Google Gemini** (AI) — trả tiền per call
- **Microsoft Graph** (Outlook integration) — không tốn tiền, dùng quota M365 của user

---

## 3. Components (C4 Level 2 — Containers)

```
┌─────────────────────────────────────────────────────────────────┐
│                       Browser (CPA's laptop)                    │
│   ┌────────────────────────────────────────────────────────┐    │
│   │  Frontend SPA (React + TypeScript)                     │    │
│   │  - Login UI / Job history / Email editor               │    │
│   │  - Microsoft Authentication Library (MSAL.js)          │    │
│   └────────────────────────────────────────────────────────┘    │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTPS + JWT bearer
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Server (1 VPS hoặc cluster)               │
│                                                                 │
│   ┌──────────────┐   enqueue    ┌────────────────┐              │
│   │  Backend API │ ───────────► │  Redis Queue   │              │
│   │  (FastAPI)   │              │                │              │
│   │              │ ◄──── status │  - Job IDs     │              │
│   │  - JWT verify│   poll       │  - Cron jobs   │              │
│   │  - Job CRUD  │              └────────┬───────┘              │
│   │  - Rate limit│                       │ pull job             │
│   └──────┬───────┘                       ▼                      │
│          │                       ┌────────────────┐             │
│          │                       │  Worker        │             │
│          │                       │  (arq + Python)│             │
│          │                       │                │             │
│          ▼                       │  - Call Gemini │             │
│   ┌──────────────┐               │  - PDF process │             │
│   │  PostgreSQL  │ ◄──────────── │  - Save result │             │
│   │              │   write       └────────┬───────┘             │
│   │  - users     │                        │                     │
│   │  - jobs      │                        ▼                     │
│   └──────────────┘               ┌────────────────┐             │
│                                  │ Local Disk     │             │
│                                  │ /var/lib/...   │             │
│                                  │  - input.pdf   │             │
│                                  │  - econsent.pdf│             │
│                                  └────────────────┘             │
└─────────────────────────────────────────────────────────────────┘
```

| Container    | Tech                   | Vai trò                                       | Số instance                    |
| ------------ | ---------------------- | --------------------------------------------- | ------------------------------ |
| Frontend SPA | React 19 + Vite + MSAL | UI cho user                                   | Static files trên CDN/nginx    |
| Backend API  | FastAPI (Python 3.12)  | REST endpoints, auth, validation              | 1+ (scale ngang được)          |
| Worker       | arq (Redis-backed)     | Xử lý PDF nặng (Gemini call) trong background | 1+                             |
| Database     | PostgreSQL 16          | Lưu users + jobs metadata                     | 1 (production cần replication) |
| Queue/Cache  | Redis 7                | Queue cho worker + JWKS cache                 | 1                              |
| Storage      | Local disk hoặc S3     | Lưu PDF gốc + e-consent xuất ra               | Depends on deploy              |

---

## 4. 3 luồng nghiệp vụ chính

### Luồng A — Login (1 lần / session)

```
User click "Sign in"
   ↓
Frontend → Microsoft login page
   ↓
User chọn account, nhập password (Microsoft xử lý)
   ↓
Microsoft redirect về app với auth code
   ↓
Frontend đổi code → JWT (id token / access token)
   ↓
Lưu vào sessionStorage (chỉ tab này, đóng tab = logout)
   ↓
Render UI app
```

### Luồng B — Upload + Extract (chính, ~60s)

```
User upload PDF
   ↓
Frontend gửi POST /api/jobs với JWT + file
   ↓
Backend: verify JWT → check size <50MB → tạo Job row (PENDING)
   ↓
Backend lưu file vào /var/lib/itr_extract/files/{user}/{job}/input.pdf
   ↓
Backend enqueue vào Redis → trả 202 cho frontend
   ↓
[Frontend bắt đầu polling GET /api/jobs/{id} mỗi 2s]
   ↓
Worker pull job từ Redis
   ↓
Worker đọc file → gọi Gemini Task 1 (e-consent) + Task 2 (email) song song
   ↓
Worker generate email HTML + tách e-consent PDF
   ↓
Worker update Job status = SUCCESS, lưu analysis_data vào DB
   ↓
Frontend polling thấy SUCCESS → render kết quả
```

### Luồng C — Tạo Outlook Draft

```
User chọn forms cần đính kèm + nhập email người nhận
   ↓
Frontend dùng pdf-lib tách lại đúng các page user chọn
   ↓
Frontend gọi Microsoft Graph /me/messages với:
   - Subject: "{tax_year} Income Tax Return — {client_name}"
   - Body: HTML email (đã sanitize qua DOMPurify)
   - Attachment: Econsent.pdf (base64)
   ↓
Microsoft tạo draft trong mailbox của user
   ↓
Frontend hiện link "Open draft in Outlook" → user mở Outlook gửi đi
```

---

## 5. Tính năng quan trọng

| Tính năng                         | Mô tả                                                                         | Status  |
| --------------------------------- | ----------------------------------------------------------------------------- | ------- |
| **Microsoft 365 SSO**             | Login một lần, dùng account công ty                                           | ✅ Done |
| **Multi-user với job history**    | Mỗi user có lịch sử riêng, scope per user                                     | ✅ Done |
| **AI extract 5 outcome patterns** | Balance due / Refund / Overpayment credited / Mixed / Zero — không paraphrase | ✅ Done |
| **E-consent form selection**      | User chọn forms cụ thể (8879, 8453, FTB...)                                   | ✅ Done |
| **Editable email preview**        | User edit inline trước khi tạo draft, lưu localStorage                        | ✅ Done |
| **Reprocess failed job**          | Khi Gemini lỗi, click 1 nút retry                                             | ✅ Done |
| **Quota & rate limit**            | Max 5 active jobs/user, 10 history, 50MB/file                                 | ✅ Done |
| **Auto-cleanup stuck job**        | Cron requeue jobs stuck >6 phút, dọn file orphan                              | ✅ Done |
| **Production-grade auth**         | JWT verify với JWKS, rate limit per IP, security headers                      | ✅ Done |

---

## 6. Tech stack & lý do chọn

| Component        | Tech                                 | Tại sao                                                                 |
| ---------------- | ------------------------------------ | ----------------------------------------------------------------------- |
| Frontend         | React 19 + TypeScript + Vite         | Standard SPA stack, type-safe, ecosystem MSAL có sẵn                    |
| Auth             | Microsoft MSAL                       | Customer dùng M365 → đỡ tạo password riêng, SSO native                  |
| Backend          | FastAPI (Python)                     | Async I/O tốt, type hints, OpenAPI tự sinh, ecosystem AI mạnh           |
| Worker           | arq (Redis)                          | Lightweight (vs Celery), async-native, Python pure                      |
| DB               | PostgreSQL 16                        | JSONB cho analysis_data, ACID, tooling chuẩn                            |
| AI               | Google Gemini 3                      | Cheap (vs GPT-4), 1M context (cho PDF lớn), structured output           |
| Mail integration | Microsoft Graph API                  | Native với M365, không cần SMTP setup                                   |
| PDF              | PyMuPDF (server) + pdf-lib (browser) | Server: extract pages nhanh; Browser: re-extract khi user đổi selection |

---

## 7. Effort breakdown

| Phase                    | Nội dung                                                | Effort                       |
| ------------------------ | ------------------------------------------------------- | ---------------------------- |
| **V1** (legacy)          | CLI standalone, single PDF in/out                       | 1-2 tuần                     |
| **V2** (current)         | Web app: auth, async jobs, history, Mail draft, full UI | ~4-6 tuần                    |
| **Production hardening** | Rate limit, audit, monitoring, ops docs                 | ~1 tuần (đã chuẩn bị 1 phần) |

---
