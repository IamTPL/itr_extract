# Fix B — Payment Voucher Extraction (complaint #2 của Marlene/CNY)

**Ngày:** 2026-08-29 · **Base commit:** `aaa2c0a` (Fix A đã commit) · **Trạng thái:** chờ user duyệt spec

## 1. Bối cảnh & mục tiêu

Email Marlene (2026-08-28), ý 2: khi khách trả bằng check, staff cần trang Payment
Voucher (vd Form 1040-V trang 8 của Kramer, in sẵn $130,828) để upload lên portal —
hiện chương trình chỉ tách e-consent (8879/FTB 8879), voucher phải tách tay.

Mục tiêu: Task 1 detect thêm các trang payment voucher → đóng gói `Voucher.pdf`
riêng (KHÔNG trộn vào Econsent.pdf) → FE có panel chọn/tải + option đính kèm
Outlook draft.

## 2. Quyết định đã chốt với user (2026-08-29)

1. **Phạm vi: TẤT CẢ loại voucher** — balance-due (1040-V + state tương đương),
   estimated (1040-ES, 540-ES...), PTE (FTB 3893), LLC (FTB 3522/3536).
2. **Đóng gói: 1 file `voucher.pdf` gộp** (mirror cách `econsent.pdf` gộp form).
3. **Email: CÓ option đính kèm Voucher.pdf vào Outlook draft** (không chỉ download).

## 3. Backend (`itr_extract`)

### 3.1 Prompt Task 1 (`prompts/task1_econsent.txt`)

Thêm task thứ hai "PAYMENT VOUCHER PAGE IDENTIFICATION" cùng cấu trúc với phần
e-consent hiện có:

- Catalog form: Federal 1040-V, 1040-ES; California FTB 3582, 540-ES, FTB 3893
  (PTE), FTB 3522 (LLC annual), FTB 3536 (LLC fee); New York IT-201-V, IT-2105;
  North Carolina D-400V, NC-40; + rule tổng quát: trang có header/title chứa
  "payment voucher" của cơ quan thuế bất kỳ.
- INCLUDE: chỉ trang LÀ voucher thật (mã form in trên trang, khung cắt/mail-in,
  số tiền in sẵn); mọi trang của voucher nhiều trang.
- EXCLUDE: letter/transmittal nhắc tên form; trang instructions ("...payment
  voucher instructions", "Preparer instructions"); trang index; form e-consent
  (đã thuộc task 1a); extension forms.
- Output mở rộng (thêm key mới, giữ nguyên key cũ):

```json
{
  "econsent_pages": [...], "econsent_forms": [...],
  "voucher_pages": [8, 44],
  "voucher_forms": [
    {
      "form_number": "1040-V", "title": "Payment Voucher", "pages": [8],
      "jurisdiction": "Federal",
      "payment_type": "balance_due | estimated | pte | annual | llc_fee | other",
      "amount": 130828 hoặc null,
      "due_date": "MM/DD/YYYY" hoặc null
    }
  ]
}
```

`amount`/`due_date` đọc từ chính trang voucher (in sẵn), nullable — chỉ để FE
hiển thị, KHÔNG dùng cho render email (Task 2 độc lập, không đổi).

### 3.2 Code

| File | Thay đổi |
|---|---|
| `jobs/pipeline.py` | Tách helper `_extract_pages(src_pdf_bytes, pages) -> bytes \| None` dùng chung; `run_extraction` trả 4-tuple `(analysis_data, email_html, econsent_bytes, voucher_bytes)`; cập nhật mọi caller |
| `config/constants.py` | `VOUCHER_FILENAME = "voucher.pdf"` |
| `storage/files.py` | `write_voucher`, `voucher_path` (mirror econsent) |
| `db/models.py` + alembic revision mới | Cột `has_voucher: bool, default False` trên bảng `jobs` |
| `worker/tasks.py` | Lưu voucher + set `has_voucher` (mirror econsent) |
| `api/jobs.py` | `GET /{job_id}/voucher.pdf` (404 nếu `has_voucher=False`); thêm `has_voucher` vào response |
| `api/schemas.py` | `has_voucher: bool` |

`voucher_forms` tự đến FE qua `analysis_data` (JobDetail đã trả nguyên dict) —
không cần endpoint mới. Retention xóa cả thư mục job → không cần sửa.

## 4. Frontend (`itr_extract_fe`)

⚠️ KHÔNG đụng 4 file dirty dev-bypass: `.env.example`, `src/App.tsx`,
`src/hooks/useAccessToken.ts`, `src/lib/msalConfig.ts`. Không commit nếu user
không yêu cầu.

| File | Thay đổi |
|---|---|
| `src/lib/types.ts` | `has_voucher: boolean`; interface `VoucherForm` |
| `src/components/JobDetailView.tsx` | Panel "Payment Vouchers" dưới panel E-consent, mirror UX: checkbox từng form (label = form_number + jurisdiction + amount/due_date nếu có), tải `voucher.pdf` từ BE, bỏ chọn → rebuild client-side bằng `extractPagesFromBuffer` từ `input.pdf` (tái dùng hàm sẵn có), nút Download |
| `src/lib/graphApi.ts` | Tổng quát hóa tham số attachment thành danh sách `{name, contentBytes}[]` (giữ tương thích econsent) |
| Delivery UI | Checkbox "Attach Voucher.pdf" (chỉ hiện khi có voucher); mặc định KHÔNG tick (flow chính của Marlene là upload portal). Mode "One email": đính vào email duy nhất. Mode "Two emails": đính vào email **Summary** (email nói về balance due — voucher đi cùng ngữ cảnh thanh toán; email e-consent giữ nguyên chỉ chứa Econsent.pdf) |

## 5. Test & verification

1. **Unit BE**: storage/api/worker/pipeline mirror các test econsent hiện có
   (mock Gemini trả thêm voucher keys); pipeline helper test tách trang đúng.
2. **Contract Task 1**: mở rộng `tests/test_task1_econsent_contract.py` theo
   pattern hiện có cho shape `voucher_pages`/`voucher_forms`.
3. **Live verification (Gemini thật, 8 samples)**: script kiểm tra detect —
   kỳ vọng grounded từ scan text: Kramer full → 1040-V trang 8 (KHÔNG lấy
   trang 1/5 là letter/instructions), 540-ES trang 44; Yamane → 1040-ES;
   Trevor → voucher PTE; ACCUPUNCTURE/Hong/Im đối chiếu bằng mắt. Sai → tinh
   chỉnh EXCLUDE rules, lặp lại.
4. **Golden suite**: email HTML không đổi (Task 2 untouched) → 114 golden test
   phải vẫn xanh nguyên trạng. Sau khi Fix B chốt, re-capture 38 case để
   `final_analysis.json` có thêm voucher keys (không bắt buộc ngay).
5. **FE**: `npm run build` + typecheck sạch; test tay với Kramer local.
6. Gate chung: `venv/bin/python -m pytest` — không failure MỚI ngoài 2 cái
   pre-existing (docs/TESTING.md §4).

## 6. Rollout

- Deploy BE: `alembic upgrade head` (cột mới default False — job cũ không có
  voucher, đúng ngữ nghĩa; muốn có thì bấm Reprocess).
- Job đang chạy giữa lúc deploy: worker cũ/mới đều ghi được (cột nullable
  default) — không cần downtime.
- FE deploy sau BE (FE đọc `has_voucher`, thiếu field thì coi như false).

## 7. Rủi ro & giảm thiểu

- **Gemini nhầm trang instruction thành voucher**: EXCLUDE rules cụ thể + live
  verification trên 8 samples + staff có checkbox bỏ form sai trên FE (van xả).
- **Task 1 không có API schema** (khác Task 2): giữ nguyên cơ chế hiện tại
  (prompt-defined JSON), pipeline đã chịu được key thiếu (`or []`).
- **4-tuple đổi chữ ký `run_extraction`**: sửa đồng bộ worker + CLI + tests
  trong cùng 1 task để không có trạng thái trung gian gãy.
