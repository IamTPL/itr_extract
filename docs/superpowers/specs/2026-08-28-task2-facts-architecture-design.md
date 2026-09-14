# Task 2 Facts Architecture — Design Spec

**Ngày:** 2026-08-28 · **Trạng thái:** chờ user duyệt · **Phạm vi:** backend `itr_extract`, Task 2 (đọc cover letter → email)

> ⚠️ Quy tắc phiên làm việc: KHÔNG `git add/commit/push` bất kỳ file nào (working tree đang có 3 file
> local-only: `.env.example`, `auth/deps.py`, `config/settings.py`). User tự quyết định thời điểm commit.

## 1. Bối cảnh & vấn đề

Client CNY (email Marlene Ortiz 28/08/2026, sample `samples/Kramer example full pages.pdf`) báo 3 vấn đề;
điều tra ngày 28/08 đã tái hiện được bằng pipeline thật:

1. **Câu balance-due sai khi trả bằng check.** Letter Kramer: *"balance due of $130,828 … Make your check
   payable to the "United States Treasury" and mail your Form 1040-V payment voucher on or before
   August 26, 2026"*. Program in: *"will be withdrawn from your account once your return has been
   processed"*. Root cause: decision box trong `prompts/task2_email.txt` chỉ có 2 nhánh balance-due
   (P1a/P1b — đều "withdrawn"), không có nhánh check/voucher → model bị ép chọn P1a. Lỗi lặp lại 100%.
2. **Cần trích trang Payment Voucher** (1040-V) khi trả bằng check — **ngoài phạm vi spec này** (dự án
   riêng, thuộc Task 1).
3. **Không đọc ANNUAL/ESTIMATED payments nêu bằng câu văn (prose).** Prompt hiện chỉ lấy estimated từ
   bảng schedule; các câu như *"Annual LLC Tax of $800 will be withdrawn on April 15, 2026"* bị bỏ,
   chỉ PTE có rule prose riêng.

Latent bug cùng loại (chưa bị báo nhưng sẽ dính): `jobs/email_html.py:73` hardcode intro bảng estimated
*"will be automatically withdrawn as shown below"* — sai với letter kiểu `House.pdf` (*"If not paying
electronically, mail your payments…"*).

Client xác nhận: letter có nhiều biến thể tự do → vá từng pattern câu là whack-a-mole. Quyết định
(user chốt 28/08): **kiến trúc facts** — Gemini tùy biến ở tầng HIỂU, code cố định ở tầng NÓI.

## 2. Mục tiêu / Non-goals

**Mục tiêu**
- Gemini trả về **sự kiện có cấu trúc** (facts) thay vì câu văn thành phẩm.
- Toàn bộ wording chuẩn CNY chuyển từ prompt về Python (unit-test được, không tốn Gemini call).
- Van xả: ca không nhận dạng được → block `⚠️ NEEDS REVIEW` trong email preview, không bao giờ
  "tự tin nói sai" kiểu bug Kramer.
- Sửa tận gốc vấn đề 1 + 3 + latent bug intro bảng.
- Regression đầy đủ: 8 file `samples/` + toàn bộ job thật client đã chạy trên production.

**Non-goals**
- Voucher extraction (vấn đề 2) — dự án riêng sau.
- Hotfix P1c trên prompt cũ — track riêng, đang chờ client confirm wording; nếu kiến trúc facts xong
  trước thì hotfix bỏ.
- Không đổi FE, API, DB schema, Task 1, auth.

## 3. Kiến trúc

```
PDF → extract_cover_letter_bytes (giữ nguyên)
    → Gemini Task 2 (prompt mới: FACTS ONLY, không viết câu)
    → jobs/facts_validation.py   (verbatim check, dedup, PTE gate, gắn cờ needs_review)
    → jobs/summary_sentences.py  (facts → câu chuẩn CNY, markdown **bold**)
    → jobs/email_html.py (HTML)  +  main.py generate_email_docx (DOCX)  — cùng dùng summary_sentences
```

Nguyên tắc: **model không bao giờ quyết định câu chữ gửi khách; code không bao giờ đoán nội dung letter.**

## 4. Schema Task 2 mới (`schemas.py`)

Top-level **giữ nguyên**: `client`, `cpa_firm`, `tax_year`, `next_year`, `return_type`
(FE đọc `client.name`, `tax_year`, `return_type`, `econsent_forms` — đã verify, không đổi key nào FE dùng).

**Bỏ**: `tax_summary`, `estimated_payments`, `pte_payments`. **Thêm** 2 mảng:

### 4.1 `jurisdictions[]` — kết quả năm hiện tại, mỗi jurisdiction một entry

| Field | Kiểu | Ghi chú |
|---|---|---|
| `jurisdiction_name` | STRING | "Federal", "California", "Oregon Metro Supportive Housing Services"… |
| `state_abbreviation` | STRING\|null | null cho Federal; USPS code, local/regional dùng host state (giữ rule cũ) |
| `display_label` | STRING\|null | như hiện tại, `jobs/tax_labels.py` tái dùng nguyên trạng |
| `outcome` | ENUM | `balance_due` \| `refund_or_credit` \| `no_tax` \| `other` |
| `balance_due` | OBJECT\|null | chỉ khi outcome=balance_due |
| `overpayment` | OBJECT\|null | chỉ khi outcome=refund_or_credit |
| `source_quote` | STRING | câu nguyên văn trong letter (bằng chứng, bắt buộc mọi outcome) |
| `other_note` | STRING\|null | Gemini tóm tắt tiếng Anh đơn giản khi outcome/method = other |

`balance_due` = `{ amount: NUMBER, payment_method: "direct_debit"|"mail_check"|"other",
withdrawal_date: STRING|null (MM/DD/YYYY), due_date: STRING|null (MM/DD/YYYY, cho mail_check
"on or before") }`

`overpayment` = `{ credited_next_year: NUMBER (0 nếu không), refunded: NUMBER (0 nếu không) }`
— phủ cả 3 ca cũ P2/P3/P4; refund thuần = `{credited: 0, refunded: X}`.

### 4.2 `scheduled_payments[]` — MỌI khoản phải trả tương lai (bảng hay prose đều vào đây)

| Field | Kiểu | Ghi chú |
|---|---|---|
| `type` | ENUM | `estimated` \| `annual` \| `pte` \| `other` |
| `jurisdiction` | STRING | "Federal", "California", "North Carolina"… |
| `amount` | NUMBER | |
| `date` | STRING | MM/DD/YYYY |
| `payment_method` | ENUM | `direct_debit` \| `mail_voucher` \| `unspecified` |
| `ordinal` | STRING\|null | chỉ PTE, chỉ khi letter in rõ ("1st"…) — giữ rule + đối chiếu FTB hiện có |
| `source_quote` | STRING | câu/dòng nguyên văn |
| `note` | STRING\|null | mô tả khi type=other |

Đây là chỗ giải quyết vấn đề 3: prose *"Annual LLC Tax of $800 … April 15, 2026"* →
`{type: annual, amount: 800, date: "04/15/2026", …}` mà không cần biết trước wording.

### 4.3 Trường bổ sung do code gắn (không thuộc schema Gemini)

- `needs_review: bool` — pipeline gắn vào `analysis_data` khi có ít nhất 1 mục bị cờ (additive, FE dùng
  sau nếu muốn).

## 5. Renderer — `jobs/summary_sentences.py` (module mới, pure functions)

Bảng map facts → câu (wording GIỮ NGUYÊN VĂN bộ câu client đã duyệt):

| Điều kiện | Câu (markdown bold, code render) |
|---|---|
| balance_due + direct_debit + withdrawal_date=null | P1a: `**Balance due** of **$X**, which will be withdrawn from your account once your return has been processed.` |
| balance_due + direct_debit + withdrawal_date | P1b: `**Balance due** of **$X**, will be withdrawn from account on **{Month Day, Year}**.` |
| balance_due + mail_check | **P1c: `**Balance due** of **$X**, see the voucher on the ShareFile portal, due on or before **{Month Day, Year}**.`** (wording chờ client chốt — xem §12; due_date=null → bỏ vế ", due on or before…") |
| refund_or_credit, credited>0, refunded=0 | P2: `No tax is payable with the filing of this return. **Overpayment** of **$T** of which **$C** credited to {next_year} tax.` (T=C+R) |
| refund_or_credit, credited=0, refunded>0 | P3: `No tax is payable with the filing of this return. **Refund** of **$R** will be deposited to your account.` |
| refund_or_credit, cả hai>0 | P4: P2 + " " + `**Refund** of **$R** will be deposited to your account.` |
| no_tax | P5: `No tax is payable with the filing of this return.` |
| other / validate fail | Van xả §6.4 |

**Bảng estimated** (`type=estimated`): render bảng Payment Date / Federal / State như hiện tại
(gom row theo date; giữ logic has_fed/has_state, format `$X,XXX`). **Câu intro suy từ
`payment_method`** của các row (fix latent bug):
- tất cả `direct_debit` → `{Federal and state…} estimated tax payments will be automatically withdrawn as shown below`
- tất cả `mail_voucher` → `…are due as shown below. If not paying electronically, please mail your payments using the payment vouchers.`
- lẫn lộn / `unspecified` → `…are due as shown below`

**`type=annual` / `type=other`**: câu riêng dưới bảng, cùng section "{next_year} Tax Payment Summary":
`{next_year} {jurisdiction} annual tax payment of **$X** will be automatically withdrawn on **{date}**.`
(direct_debit) / `…is due on **{date}**.` (khác). type=other kèm van xả nếu thiếu note.

**`type=pte`**: 2 câu PTE hiện tại giữ nguyên văn; ordinal render từ field `ordinal`.
`main.py::apply_ftb_first_pte_ordinal` đơn giản hóa: so `amount`+`date` của facts trực tiếp với evidence
FTB Part IV (bỏ cụm regex parse câu `_pte_sentence_evidence`/`_PTE_NO_ORDINAL_RE`).

DOCX (`main.py::generate_email_docx`) và HTML (`jobs/email_html.py`) cùng gọi module này —
xóa logic câu trùng lặp ở cả hai nơi.

## 6. Validation & van xả — `jobs/facts_validation.py` (module mới)

Chạy trong `jobs/pipeline.py` ngay sau khi Gemini trả JSON, TRƯỚC renderer:

1. **Verbatim check (chống bịa):** mọi `amount` phải xuất hiện trong text trang Letter (so chuỗi đã
   normalize: bỏ `$`, giữ dấu phẩy — "130,828" phải tìm thấy; số bảng như "2,800" tương tự). Mọi `date`
   match một trong các dạng trong letter ("April 15, 2026", "4/15/26", "4/15/2026"…). Fail → gắn cờ mục đó.
2. **Dedup:** hai entry `scheduled_payments` trùng (jurisdiction, amount, date) → giữ một (ưu tiên type
   cụ thể hơn `other`; nếu 1 estimated + 1 pte cùng amount+date thì GIỮ CẢ HAI — PTE là khoản riêng
   hợp lệ, chỉ dedup khi cùng type hoặc một bên là other).
3. **PTE gate theo `return_type`:** giữ nguyên rule code-side hiện tại (drop `type=pte` nếu return_type
   ∉ {S-Corp, Partnership}).
4. **Van xả:** entry có cờ / `outcome=other` / `payment_method=other` → renderer chèn block:
   `<div style="background:#FFF3CD;border:1px solid #E0A800;…">⚠️ NEEDS REVIEW — {other_note của Gemini}.
   Letter says: "{source_quote}"</div>` tại đúng vị trí dòng đó. Staff sửa trong ô preview (đã editable)
   trước khi Create Draft. Đồng thời set `needs_review=true`.

## 7. Prompt mới (`prompts/task2_email.txt` viết lại)

- Giữ: role CPA, scope rules (chỉ dùng thông tin trong letter, null khi thiếu), display_label rules,
  quy tắc normalize date MM/DD/YYYY, PTE eligibility + "ordinal chỉ khi in rõ".
- **Bỏ toàn bộ**: SENTENCE PATTERNS P1–P5, quy tắc P1a-vs-P1b, NORMALIZE câu, các mục self-verification
  về pattern câu.
- **Thêm**: định nghĩa 2 mảng facts (§4) với hướng dẫn nhận diện `outcome`/`payment_method`/`type`;
  yêu cầu `source_quote` nguyên văn; quy tắc "one entry per actual payment — câu giới thiệu bảng
  ('in accordance with the schedule below') KHÔNG phải payment riêng".
- **Worked examples** (nguồn từ letter thật trong `samples/`): ① Yamane (overpayment credited + refund CA
  + bảng estimate Fed direct-debit), ② House (P1b 2 bang + refund + bảng estimate mail-voucher),
  ③ Kramer (mail_check + due date, CA no_tax), ④ Trevor (S-Corp: no_tax Fed, P1a CA, bảng estimate CA,
  PTE), ⑤ synthetic LLC (annual $800 + estimated fee prose + PTE — minh họa type=annual từ prose).
- Self-verification mới: mọi amount/date có trong letter; mỗi payment một entry; PTE đúng eligibility;
  source_quote là trích nguyên văn.

## 8. Files thay đổi

| File | Loại | Nội dung |
|---|---|---|
| `prompts/task2_email.txt` | rewrite | §7 |
| `schemas.py` | rewrite phần TASK2 | §4 |
| `jobs/summary_sentences.py` | MỚI | §5 |
| `jobs/facts_validation.py` | MỚI | §6 |
| `jobs/email_html.py` | sửa | render từ facts qua summary_sentences; giữ khung email/ShareFile |
| `main.py` | sửa | generate_email_docx dùng summary_sentences; apply_ftb_first_pte_ordinal so facts; xóa regex parse câu PTE |
| `jobs/pipeline.py` | sửa | hook facts_validation sau Gemini, gắn needs_review |
| `tests/test_task2_email_contract.py` | rewrite | contract schema facts + worked examples |
| `tests/test_email_rendering.py` | rewrite | render từ facts |
| `tests/test_summary_sentences.py` | MỚI | unit từng nhánh template |
| `tests/test_facts_validation.py` | MỚI | verbatim/dedup/gate/cờ |

**Không đụng:** `auth/deps.py`, `config/settings.py`, `.env.example` (3 file dirty local-only) ·
`prompts/task1_econsent.txt` · `api/` · `db/` (JSONB schemaless, không migration) · `jobs/tax_labels.py`
(tái dùng) · FE (`itr_extract_fe`) · deploy/.

**Backward compat:** job cũ serve `email_html` đã render lưu trong DB — không re-render bao giờ →
không bị ảnh hưởng. `analysis_data` cũ giữ nguyên trong DB (chỉ job mới có shape mới; FE không đọc
các field đổi shape).

## 9. Test plan

### 9.1 Unit + contract (TDD, không tốn Gemini)
- `test_summary_sentences.py`: một test/nhánh — P1a, P1b, P1c (có/không due_date), P2, P3, P4, P5,
  van xả, intro bảng 3 biến thể, annual sentence, PTE ordinal, format tiền.
- `test_facts_validation.py`: verbatim pass/fail, các ca dedup (kể cả "PTE trùng amount+date với
  estimated thì giữ"), PTE gate, needs_review propagation.
- Contract: worked examples ↔ schema facts (giữ cơ chế `_assert_matches_schema` hiện có).

### 9.2 Regression local — 8 file `samples/`
1. **Trước khi sửa**: chạy pipeline hiện tại trên cả 8 file, lưu baseline JSON + HTML
   (Kramer + Trevor đã chụp 28/08, còn 6 file).
2. Sau khi sửa: chạy lại, sinh bảng diff từng file.
3. **Catalog diff chủ đích (chỉ được phép khác đúng những điểm này):**
   - 2 file Kramer: federal → P1c (hết "will be withdrawn" sai).
   - House: intro bảng estimated đổi từ "will be automatically withdrawn" sang biến thể trung tính
     (letter House không khẳng định auto-debit → `unspecified`/`mail_voucher`) — fix latent bug.
   - Mọi câu P1a/P1b/P2–P5, bảng estimated, PTE (kể cả "1st" của Trevor) giữ nguyên ngữ nghĩa.
   - Không file nào có cờ ⚠️.
   Diff ngoài catalog = FAIL → điều tra trước khi đi tiếp.

### 9.3 Regression production — job thật client đã chạy (yêu cầu user 28/08)
Server lưu `input.pdf` theo job (`storage/files.py::write_input`; retention = 10 job gần nhất/user —
usage hiện thấp nên kỳ vọng còn đủ; ~7 job thật tính đến 04/08). PDF thật chứa SSN → **không rời server**.

Quy trình (mỗi bước read-only với production, cần user cấp quyền SSH hoặc chạy cùng):
0. **Inventory** (read-only): đếm job `done`, liệt kê `input.pdf` còn trên disk, kích thước
   (mở rộng từ `deploy/checklog.sh`). *Ghi chú 28/08: lệnh SSH bị permission classifier chặn trong
   phiên này — bước 0 chạy khi user approve.*
1. Copy working tree đã refactor lên `/tmp/itr_facts_regression/` trên server (KHÔNG đụng
   `/opt/itr_extract` đang chạy).
2. Với từng job còn `input.pdf`: chạy `jobs.pipeline.run_extraction()` bằng chính interpreter sẵn có
   `PYTHONPATH=/tmp/itr_facts_regression /opt/itr_extract/.venv/bin/python` + key từ `worker.env`
   (pattern đã dùng 27/08 khi test key: không ghi DB, không cần login, ~17s/job; khả thi vì refactor
   không thêm dependency mới).
3. So kết quả mới với `analysis_data` + `email_html` đã lưu trong DB của chính job đó:
   script trích (outcome, amounts, dates, method, số dòng estimated, PTE) từ CẢ HAI phía → so semantic;
   kèm diff text câu chữ để user duyệt bằng mắt (wording mới chuẩn hóa có thể lệch nhẹ chính tả cũ).
4. Bảng tổng hợp per-job: PASS / diff-chủ-đích (theo catalog §9.2) / FAIL.
5. Xóa `/tmp/itr_facts_regression/` + verify 5 services vẫn active (checklog).

Chi phí: ~7 Gemini call (~2–5 cent/call). Điều kiện dừng: bất kỳ FAIL nào ngoài catalog → dừng, điều tra,
không deploy.

### 9.4 Tiêu chí hoàn thành
- Toàn bộ pytest xanh; regression local 8/8 khớp catalog; regression production 100% job PASS hoặc
  diff-chủ-đích; user duyệt bảng diff; KHÔNG commit — bàn giao working tree + bảng kết quả.

## 10. Rollout

1. Implement theo plan (writing-plans, TDD) trên working tree — không commit.
2. Regression local → user duyệt bảng diff.
3. Regression production (§9.3) → user duyệt.
4. User tự commit/push và deploy theo `deploy/deploy_tutorial.md` §2 (nhớ checklist dev-bypass:
   server không có `DEV_AUTH_BYPASS=true`).

## 11. Rủi ro & giảm thiểu

| Rủi ro | Giảm thiểu |
|---|---|
| Gemini điền enum sai (method/outcome/type) | Nhiệm vụ phân loại dễ hơn viết câu; worked examples phủ 5 dạng thật; verbatim check chặn số bịa; van xả đỡ ca mơ hồ |
| Đếm trùng prose + bảng | Rule "one entry per payment" trong prompt + dedup code-side (§6.2); test Trevor/ACCUPUNCTURE trong regression |
| Wording mới lệch kỳ vọng client | Bộ câu giữ nguyên văn đã duyệt; P1c chờ client chốt (§12) |
| Ảnh hưởng job production cũ | Không có — email_html cũ lưu sẵn trong DB, không re-render (§8) |
| Regression production đụng hệ thống sống | Mọi bước read-only với DB/`/opt`; chạy ở `/tmp`; verify services sau khi xong |

## 12. Câu hỏi mở

1. **Wording P1c** — client đang confirm "Client Portal" vs "ShareFile portal" (khuyến nghị:
   "on the ShareFile portal"). Chặn việc chốt text template P1c, KHÔNG chặn implement phần còn lại
   (đổi 1 hằng số).
2. Sample letter thật có ANNUAL/estimated prose từ client — nice-to-have để thêm regression case;
   kiến trúc facts không phụ thuộc (worked example ⑤ synthetic đảm nhiệm).
