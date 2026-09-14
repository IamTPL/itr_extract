# UI Workbench Phase 1 — Design Spec

- **Ngày:** 2026-07-14
- **Trạng thái:** Spec đã chốt theo quyết định của anh Long · **chờ approve implementation plan** trước khi code
- **Repo áp dụng:** `itr_extract_fe` (React + TS + Vite). Backend `itr_extract` **không thay đổi** trong Phase 1.
- **Mockup tham chiếu:** `itr_extract/docs/ui-proposals/option-c-workbench.html` (bản v2)

## 1. Quyết định đã chốt (14/07/2026)

| Câu hỏi | Quyết định |
|---|---|
| Hướng thiết kế | **C · Workbench** — 3 khoang: hàng đợi · nội dung · checklist soát |
| Mức checklist "Verify extracted figures" | **Mức 2** — checkbox theo dõi tiến độ soát, **không khoá** nút gửi |
| Phạm vi backend | **Phase 1 thuần frontend** — 0 thay đổi API/pipeline/schema |

Hệ quả đã thống nhất (trung thực với API hiện có):

- Không có % tiến độ thật (API chỉ có `pending/processing/success/failed`) → progress theo **thời gian trôi so với thời lượng trung bình** các job trước.
- Không hiển thị cost ($) — pipeline hiện không persist token_usage (`jobs/pipeline.py` vứt usage).
- Không có tham chiếu trang nguồn per-figure — link "letter (PDF)" mở `input.pdf` chung.
- Không có "Season total" / thống kê vượt quá danh sách job đang giữ (retention xoá job cũ).

## 2. Mục tiêu & phi mục tiêu

**Mục tiêu Phase 1**

1. Kế toán viên soát mọi con số AI trích xuất ở dạng **bảng cấu trúc** thay vì dò trong đoạn văn email.
2. Một màn hình duy nhất cho toàn bộ luồng review → không cuộn tìm, hành động chính cố định một chỗ.
3. Trạng thái xử lý "sống" (timer + mô tả 2 task) thay cho chấm vàng tĩnh.
4. Hàng đợi tử tế: nhóm ngày, tìm kiếm, lọc, multi-upload.
5. Nhận diện thương hiệu + dark mode + nền tảng a11y.

**Phi mục tiêu (Phase 1)**

- Không gating nút gửi (Mức 3), không "send anyway" flow.
- Không % per-task, không console log xử lý, không processing theater (Phase 2+).
- Không render nội dung thumbnail trang PDF (placeholder CSS + số trang; render thật cần pdf.js — dependency nặng, để sau).
- Không thay đổi backend, kể cả field mới. Không thêm endpoint.
- Không đổi luồng auth/MSAL, không đổi cơ chế polling.

## 3. Kiến trúc UI

```
AppShell
├── TopBar: brand · Stepper(Upload→Extract→Review→Send) · stats(Today/Queue/Review) · avatar/sign-out
├── QueuePane (trái, 252px)
│   ├── UploadStrip (drop nhiều file, tối đa 5, tuần tự POST)
│   ├── FilterChips (All/Review/Sent/Failed) + search
│   ├── JobList (nhóm Today/Yesterday/…, pill trạng thái)
│   └── QueueFooter (History n/20 + mini bars từ list)
├── WorkPane (giữa)
│   ├── ClientHeader (tên, chips 1120S/TY/jurisdictions, meta pages·58s)
│   ├── Tabs: Client email · E-consent (n) · Extracted JSON
│   ├── EconsentCards (toggle include — logic hiện có giữ nguyên)
│   └── EmailCard (toolbar B/I/Undo · Saved chip · Reset · contentEditable + DOMPurify)
└── VerifyPane (phải, 336px)
    ├── VerifyHeader (progress k/n)
    ├── VerifyList (item: label · amount · date · link letter (PDF) · checkbox)
    └── SendBlock (To · attachment summary · Create Outlook Draft — luôn enabled · dòng nhắc nếu còn mục chưa tick)
```

- Trạng thái `processing`: WorkPane giữa hiển thị ProcessingCard (timer + est) + skeleton checklist.
- Dưới 1100px: VerifyPane thu thành bottom-sheet (toggle).

## 4. Data mapping — 100% từ API hiện có

| UI | Nguồn |
|---|---|
| Queue, nhóm ngày, search, filter, mini bars | `GET /api/jobs` (client-side) |
| Stepper | `status` + localStorage `itr.sent.{job_id}` (set khi tạo draft thành công) |
| Client chips, tax year, return type | `analysis_data` |
| "processed in 58s" | `finished_at - started_at` |
| Checklist: estimated payments | `analysis_data.estimated_payments` (đã structured) |
| Checklist: balance due / refund / PTE | Parse từ `federal_sentence`, `state_sentences[].sentence`, `pte_payments[].sentence` (xem §5) |
| "38 pages" | `pdf-lib.getPageCount()` — chỉ hiển thị khi input buffer đã được tải cho việc khác; không fetch riêng chỉ để đếm |
| E-consent cards | `analysis_data.econsent_forms` (form_number, title, jurisdiction, pages) |
| Email preview | `email_html` (sanitize DOMPurify như hiện tại) |
| Stats Today/Queue/Review | Đếm client-side từ jobs list |

## 5. Figure parser (lib thuần, có unit test)

Input: `analysis_data` → Output: `VerifyItem[]`:

```ts
interface VerifyItem {
  id: string;          // ổn định: `${kind}:${index}` — key cho localStorage
  label: string;       // "Federal balance due", "Estimated tax Q3 2026", …
  sublabel: string;    // jurisdiction / mô tả ngắn
  amount: number|null; // null nếu không parse được
  amountRaw: string|null; // chuỗi gốc "$12,450"
  direction: 'due'|'refund'|'info';
  date: string|null;   // chuẩn hoá MM/DD/YYYY nếu có
  sourceSentence: string; // câu gốc — luôn giữ để fallback hiển thị
}
```

Quy tắc:

1. `return_type`, `tax_year` → 2 item `info` cố định.
2. `estimated_payments[]` → mỗi phần tử 1 item, amount = federal + state, sublabel "Fed $x + {state} $y".
3. Câu văn (federal/state/PTE): amount = regex `\$[\d,]+(\.\d{1,2})?` **ưu tiên đoạn trong \*\*bold\*\***; date = `Month D, YYYY` | `MM/DD/YYYY`; direction từ keyword (`balance due|owe` → due; `refund|overpayment` → refund).
4. **Fallback bắt buộc:** parse thất bại (0 hoặc ≥2 amount không phân định) → item vẫn render với `sourceSentence` nguyên văn, amount ẩn — **không bao giờ chặn UI vì parse fail**.
5. Email cross-highlight: hover/chọn item → tìm `amountRaw` trong preview, wrap `<mark>` tạm (remove khi blur). Không tìm thấy → bỏ qua im lặng.

Trạng thái tick: localStorage `itr.verify.{job_id}` = `{ [itemId]: true }`. Đổi job hoặc reprocess (job_id mới) → checklist trống lại (đúng mong muốn).

## 6. Processing UI (không % giả)

- `elapsed = now - started_at` (fallback `created_at`).
- `typical = median(finished_at - started_at của các job SUCCESS trong list)`; list rỗng → 60s.
- Bar width = `min(elapsed/typical, 0.95)`, nhãn "elapsed 0:23 · typical ~60s", copy "Task 1 + Task 2 running in parallel".
- `elapsed > 2×typical` → thêm dòng "Taking longer than usual" + nút Refresh (tái dùng logic `timedOut` hiện có).

## 7. Theming & type

Token CSS theo mockup C: nền `#F5F6F8`, panel `#FFF`, ink `#1A2333`, line `#E3E7EE`, accent cobalt `#1E56D6` (dark: `#5F8CF0` — đã validate), verified `#15803D`, attention `#B45309`, due-red `#B91C1C`. Dark mode: `prefers-color-scheme` + toggle tay (localStorage), token-level override. Type: Segoe UI stack, base 12.5px; số liệu `Cascadia Mono/Consolas` + `tabular-nums`. Logo: SVG nội bộ (bỏ hotlink wikimedia). Motion 120–150ms, tôn trọng `prefers-reduced-motion`.

## 8. Hotkeys (Phase 1 tối thiểu)

`J/K` chuyển item checklist · `V` tick item đang chọn · `E` focus email editor. **Không** bind Enter-to-send (rủi ro gửi nhầm). Tắt khi focus nằm trong input/contentEditable.

## 9. Ràng buộc hiệu năng (giữ key value)

- **0 thay đổi pipeline/backend** → thời gian xử lý mỗi hồ sơ giữ nguyên.
- Không thêm dependency runtime mới (parser regex thuần; toolbar dùng `document.execCommand` với feature-detect, ẩn nút nếu không hỗ trợ). Dev-dependency mới duy nhất: **vitest** cho parser tests.
- Polling giữ nhịp hiện có; stats/filter/search đều client-side trên dữ liệu đã tải.
- Bundle: không pdf.js; placeholder thumbnail bằng CSS.

## 10. Acceptance criteria

1. Mở job SUCCESS bất kỳ: checklist hiện đủ item từ `analysis_data`; câu không parse được vẫn hiện nguyên văn.
2. Tick/untick lưu qua reload (localStorage per job); nút draft **luôn** bấm được; còn mục chưa tick → hiện dòng nhắc cam.
3. Job processing: bar chạy theo elapsed/typical; quá 2× → dòng "taking longer" + Refresh.
4. Upload 3 file cùng lúc → 3 job tuần tự xuất hiện trong queue, không 429.
5. Search/filter/nhóm ngày hoạt động trên list; xoá có confirm; reprocess giữ hành vi cũ.
6. Email: sửa → chip "Saved"; Reset → về `email_html` gốc; draft Outlook nhận đúng HTML đã sửa (hành vi hiện có không đổi).
7. Dark/light theo OS + toggle; axe không lỗi contrast mức AA cho text chính.
8. `npm run build` xanh; vitest parser pass; không import thư viện runtime mới.

## 11. Tham chiếu

- Mockup: `docs/ui-proposals/option-c-workbench.html` (v2) · so sánh: `docs/ui-proposals/index.html`
- FE hiện tại: `src/App.tsx`, `src/components/{UploadCard,JobHistory,JobDetailView,JobStatusBadge}.tsx`, `src/index.css`
- Backend đọc để xác nhận scope (không sửa): `api/schemas.py`, `jobs/pipeline.py`, `worker/tasks.py`, `schemas.py`
