# Fix B — Payment Voucher Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Task 1 detect trang payment voucher → đóng gói `voucher.pdf` riêng → API + FE panel + option đính kèm Outlook draft.

**Architecture:** Nhân bản flow e-consent hiện có end-to-end (prompt → pipeline tách trang → storage/DB/API → FE panel). Task 2 (email) KHÔNG đụng.

**Tech Stack:** FastAPI + SQLAlchemy/alembic + PyMuPDF (BE); React 19 + TS + pdf-lib (FE, repo riêng `~/WorkSpace/itr_extract_fe`).

**Spec:** `docs/superpowers/specs/2026-08-29-voucher-extraction-design.md`

## Global Constraints

- KHÔNG `git add/commit/push` ở cả 2 repo — user tự commit. Base BE = commit `aaa2c0a`.
- KHÔNG đụng file dev-bypass: BE `.env.example`, `auth/deps.py`, `config/settings.py`; FE `.env.example`, `src/App.tsx`, `src/hooks/useAccessToken.ts`, `src/lib/msalConfig.ts`.
- Gate test: `venv/bin/python -m pytest` — không failure MỚI ngoài 2 pre-existing (docs/TESTING.md §4). 114 golden test phải xanh NGUYÊN TRẠNG (Task 2 untouched).
- Mirror pattern e-consent sát nhất có thể; style/comment tiếng Việt như code hiện có.
- Key JSON mới của Task 1: `voucher_pages: list[int]`, `voucher_forms: list[dict]` — pipeline phải chịu được key thiếu (`or []`).

---

### Task 1 — BE plumbing: constants, storage, DB+alembic, pipeline 4-tuple, worker, API

**Files:**
- Modify: `config/constants.py` (cạnh `ECONSENT_FILENAME`, dòng 19): thêm `VOUCHER_FILENAME = "voucher.pdf"`
- Modify: `storage/files.py`: thêm `write_voucher(user_id, job_id, data) -> Path` và `voucher_path(user_id, job_id) -> Path` — mirror y hệt `write_econsent`/`econsent_path` (dùng `VOUCHER_FILENAME`)
- Modify: `db/models.py:38` vùng `has_econsent`: thêm `has_voucher: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())` (khớp convention cột has_econsent trong 0001 — đọc file migration cũ để lấy đúng kiểu server_default)
- Create: `alembic/versions/0002_add_has_voucher.py` — `op.add_column("jobs", sa.Column("has_voucher", sa.Boolean(), nullable=False, server_default=sa.false()))`; `down_revision` = revision id THẬT đọc từ `alembic/versions/0001_initial.py`; downgrade = drop column
- Modify: `jobs/pipeline.py`:
  ```python
  def _extract_pages(pdf_bytes: bytes, pages) -> bytes | None:
      pages = [p for p in pages or [] if isinstance(p, int)]
      if not pages:
          return None
      src = fitz.open(stream=pdf_bytes, filetype="pdf")
      try:
          valid = sorted(p - 1 for p in pages if 1 <= p <= src.page_count)
          if not valid:
              return None
          new_doc = fitz.open()
          for idx in valid:
              new_doc.insert_pdf(src, from_page=idx, to_page=idx)
          data = new_doc.write()
          new_doc.close()
          return data
      finally:
          src.close()
  ```
  `run_extraction` dùng helper cho CẢ econsent lẫn voucher, trả `(analysis_data, email_html, econsent_bytes, voucher_bytes)`; cập nhật docstring dòng 1.
- Modify callers của `run_extraction` (grep xác nhận đủ): `worker/tasks.py:38` (unpack 4 giá trị; sau `write_econsent` thêm `if voucher: fs.write_voucher(...)`; cạnh `job.has_econsent` thêm `job.has_voucher = bool(voucher)`), `regression_out/run_task2_regression.py:19` (`data, html, _econsent, _voucher = ...`)
- Modify: `api/jobs.py`: endpoint mới mirror `get_econsent` (dòng 110–123): `GET /{job_id}/voucher.pdf`, check `j.has_voucher`, `filename="Voucher.pdf"`; grep MỌI chỗ dùng `has_econsent` trong `api/` (dòng 46 `_to_detail`/list row) và thêm `has_voucher` song song
- Modify: `api/schemas.py:16` vùng `has_econsent`: thêm `has_voucher: bool` vào đúng các model đang có `has_econsent`
- Test: `tests/test_storage_files.py` (mirror test econsent cho voucher), `tests/test_pipeline.py` (unpack 4-tuple ở 3 chỗ + test mới `_extract_pages`/voucher bytes với mock gemini trả `voucher_pages`), `tests/test_worker_tasks.py` (mock trả 4-tuple; assert `has_voucher` + write_voucher được gọi), `tests/test_e2e_lifecycle.py:25` (mock 4-tuple), `tests/test_jobs_api.py` (mirror test econsent endpoint: 200 khi has_voucher, 404 khi không)

**Interfaces:**
- Produces: `run_extraction(pdf_bytes) -> tuple[dict, str, bytes | None, bytes | None]`; `fs.write_voucher/voucher_path`; `Job.has_voucher`; `GET /api/jobs/{id}/voucher.pdf`.
- Consumes: key `voucher_pages` trong analysis_data (Task 2 của plan này tạo ra từ prompt — code phải chạy đúng khi key CHƯA tồn tại: voucher_bytes=None).

**Steps:**
- [ ] Viết test fail trước cho storage/pipeline/worker/api (mirror test econsent tương ứng)
- [ ] Implement theo danh sách trên
- [ ] `venv/bin/python -m pytest` — không failure mới; alembic revision import sạch (`venv/bin/python -c "import alembic..."` hoặc pytest đã cover)

### Task 2 — Prompt Task 1 + contract tests

**Files:**
- Modify: `prompts/task1_econsent.txt` — thêm section "TASK B — PAYMENT VOUCHER PAGE IDENTIFICATION" sau phần e-consent, format/giọng văn y hệt phần hiện có; GIỮ NGUYÊN từng chữ phần e-consent (contract test cũ assert nguyên văn)
- Modify: `tests/test_task1_econsent_contract.py` — test mới assert prompt chứa catalog voucher + response format có `voucher_pages`/`voucher_forms`

**Nội dung section mới (theo spec §3.1):**
- Catalog: Federal `1040-V`, `1040-ES`; California `FTB 3582`, `540-ES`, `FTB 3893 (PTE)`, `FTB 3522 (LLC annual)`, `FTB 3536 (LLC fee)`; New York `IT-201-V`, `IT-2105`; North Carolina `D-400V`, `NC-40`; rule tổng quát: trang là payment voucher chính thức của cơ quan thuế bất kỳ (header/title chứa "payment voucher").
- INCLUDE: chỉ trang LÀ voucher slip thật (form number in trên trang, khung cắt gửi bưu điện, amount in sẵn); mọi trang của voucher nhiều trang.
- EXCLUDE: letter nhắc tên form; trang instructions/worksheet của preparer; index; e-consent forms (thuộc task A); extension forms; trang "Record of estimated tax payments".
- RESPONSE FORMAT: mở rộng JSON hiện có với `voucher_pages` + `voucher_forms[{form_number,title,pages,jurisdiction,payment_type∈{balance_due,estimated,pte,annual,llc_fee,other},amount:number|null,due_date:"MM/DD/YYYY"|null}]`; nói rõ trả `[]` khi không có voucher.

**Steps:** test fail → sửa prompt → pytest xanh (kể cả các contract test cũ).

### Task 3 — Live verification với Gemini thật (8 samples)

Script one-off tại scratchpad (KHÔNG bỏ vào repo): với từng `samples/*.pdf`, gọi `itr.call_gemini(pdf_bytes, itr.TASK1_PROMPT, itr.TASK1_CONFIG, api_key, itr.DEFAULT_MODEL, "Task 1")`, in `econsent_pages/econsent_forms/voucher_pages/voucher_forms`.

Kỳ vọng grounded (đối chiếu, sai thì đọc trang PDF bằng fitz để adjudicate):
- `Kramer example full pages`: voucher CÓ trang 8 (1040-V, $130,828); KHÔNG có trang 1, 5 (letter/instructions); trang 44 (540-ES) — đọc trang thật để phán đúng/sai.
- `Kramer Example ITR` (bản ngắn): scan text chỉ thấy 1040-V ở trang 1 (letter) → nhiều khả năng KHÔNG có voucher page thật; xác nhận bằng mắt.
- `Yamane`: trang 4 có chữ 1040-ES — đọc trang thật xem là voucher slip hay chỉ instructions.
- `Trevor`: "Payment Voucher" trang 2, 9 — phân loại thật (PTE 3893?).
- `House`: chỉ letter nhắc voucher → kỳ vọng KHÔNG detect trang nào.
- `Im` trang 22, `Hong`/`ACCUPUNCTURE` — đối chiếu bằng mắt.
- Bất biến: econsent_pages/forms KHÔNG đổi so với trước (Kramer full: 7 + 30).

Nếu Gemini lấy nhầm trang instructions/letter → chỉnh EXCLUDE rules trong prompt (quay lại Task 2), lặp tối đa 3 vòng. Ghi report vào workspace SDD.

### Task 4 — FE (repo `~/WorkSpace/itr_extract_fe`)

**Files:**
- Modify: `src/lib/types.ts` — `has_voucher: boolean` cạnh `has_econsent` (dòng 14); interface `VoucherForm { form_number: string; title: string; pages: number[]; jurisdiction: string; payment_type?: string; amount?: number | null; due_date?: string | null }`
- Modify: `src/lib/graphApi.ts` — tổng quát tham số attachment đơn (`econsentB64`, `econsentFileName`) thành `attachments: { name: string; contentBytes: string }[]`; cập nhật mọi call site
- Modify: `src/components/JobDetailView.tsx`:
  - Đọc `voucher_forms` từ `analysisData` (mirror `econsent_forms` dòng 192)
  - Panel "Payment Vouchers" NGAY DƯỚI panel E-consent, mirror UX: checkbox từng form (label: form_number + jurisdiction, phụ đề title + trang + amount/due_date nếu có), fetch `/api/jobs/{id}/voucher.pdf` khi `job.has_voucher`, bỏ chọn form → rebuild bằng `extractPagesFromBuffer` từ `input.pdf` (hàm sẵn có dòng ~175), nút Download `Voucher.pdf`
  - Delivery: checkbox "Attach Voucher.pdf" (chỉ render khi có voucher; default KHÔNG tick). Mode combined: đính vào email duy nhất. Mode separate: đính vào email **Summary** (email e-consent giữ nguyên)
- KHÔNG đụng 4 file dirty (Global Constraints).

**Steps:** implement → `npm run build` (hoặc script typecheck của repo) sạch → mô tả test tay (Kramer local) trong report.

### Task 5 — Gate cuối + review toàn diff

- [ ] BE: `venv/bin/python -m pytest` full — không failure mới; golden 114 xanh nguyên trạng
- [ ] FE: build sạch
- [ ] Review toàn diff 2 repo (BE vs `aaa2c0a`, FE vs HEAD, loại file dev-bypass) bằng reviewer model mạnh nhất
- [ ] Cập nhật `docs/TESTING.md` nếu cần (mục nào đổi thì chạy gì — thêm dòng cho prompt Task 1/voucher)
