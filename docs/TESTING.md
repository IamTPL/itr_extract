# TESTING — hướng dẫn test cho người & agent (Claude Code, v.v.)

> **TL;DR:** trước khi kết luận một thay đổi là xong, chạy:
>
> ```bash
> venv/bin/python -m pytest
> ```
>
> Gate = **không có failure MỚI**. Có đúng 2 failure pre-existing đã biết (xem §4) — không phải lỗi của bạn, không tự sửa.

## 1. Ba tầng test

| Tầng | Ở đâu | Cần gì | Khi nào chạy |
|---|---|---|---|
| **Unit / contract** | `tests/*.py` (trừ golden) | Docker (testcontainers cho vài file) | Luôn luôn |
| **Golden regression** | `tests/test_golden_cases.py` + fixtures `tests/golden/cases/` | Fixture local (không commit — máy không có thì module tự skip) | Luôn luôn (chạy chung trong pytest, offline, <1s) |
| **Live regression (Gemini)** | `regression_out/run_task2_regression.py` + `compare_task2_regression.py` | GEMINI_API_KEY, tốn phí + ~17s/file | CHỈ khi đổi `prompts/task2_email.txt`, `schemas.py`, hoặc model Gemini |

## 2. Golden regression là gì

Đóng băng output **đã được xác nhận đúng** (2026-08-29) cho:

- 8 file trong `samples/` (case `sample_*`)
- 30 job thật trên production (case `prod_*` — đặt tên theo 8 ký tự đầu job id)

Mỗi case dir gồm:

| File | Vai trò |
|---|---|
| `raw_facts.json` | INPUT — Task 2 thô từ Gemini, TRƯỚC validation |
| `letter.txt` | INPUT — text của transmittal letter |
| `final_analysis.json` | INPUT render — analysis_data đầy đủ (sau validation + ordinal FTB + Task 1) |
| `validated_facts.json` | GOLDEN — output kỳ vọng của `validate_facts` |
| `expected_email.html` | GOLDEN — HTML email kỳ vọng |
| `meta.json` | Nguồn gốc + ngày capture |

Mỗi case chạy 3 test: validation golden, render golden, và consistency check
(final_analysis phải khớp validated_facts ngoài phần `ordinal`).

Lưu ý đặc biệt: golden của `prod_87422abf` LÀ block ⚠️ NEEDS REVIEW — letter đó
tự mâu thuẫn (total $2,210 < credited $2,209 + refunded $30), van xả hoạt động
đúng thiết kế. Đừng "sửa" nó thành câu render bình thường (chi tiết: meta.json
của case đó).

**Test chạy offline hoàn toàn** — không gọi Gemini, không cần PDF, không cần server.

Bộ suite đã được **mutation-check** (2026-08-29): 5 mutation cố ý (đổi wording P1c,
revert bug intro, bỏ check total, tắt HTML escape, bỏ digit-boundary guard) — 4 bị
golden bắt ngay đúng case kỳ vọng; 1 (digit-boundary) được tầng unit test
`tests/test_facts_validation.py` bắt, đúng phân tầng thiết kế.

## 3. Đổi logic xong thì làm gì?

| Bạn vừa đổi | Việc cần làm |
|---|---|
| Wording / render (`jobs/summary_sentences.py`, `jobs/email_html.py`, `jobs/tax_labels.py`) | `pytest` → golden fail đúng các case bị ảnh hưởng. Đọc diff, xác nhận đúng chủ đích, rồi `UPDATE_GOLDENS=1 venv/bin/python -m pytest tests/test_golden_cases.py` và chạy lại pytest lần cuối. Đưa diff golden cho user review. |
| Validation (`jobs/facts_validation.py`) | Như trên. Nếu sau UPDATE_GOLDENS mà test `test_final_analysis_consistent_with_validated` fail → fixture `final_analysis.json` đã cũ so với logic mới → **re-capture** case đó (§5), đừng sửa tay. |
| Prompt Task 2 / schema Gemini (`prompts/task2_email.txt`, `schemas.py`) | Golden fixtures cũ không còn đại diện cho output prompt mới. Chạy live regression (§6) so baseline, xác nhận diff, rồi **re-capture toàn bộ fixture** (§5). |
| Pipeline / ordinal (`jobs/pipeline.py`, `apply_ftb_first_pte_ordinal` trong `main.py`) | `pytest` — `tests/test_pipeline.py` + `test_main.py` cover; golden render vẫn chạy bình thường. |
| Chỗ khác (API, auth, storage, worker) | `pytest` là đủ. |

⚠️ KHÔNG BAO GIỜ sửa tay nội dung file golden để "cho test xanh" — golden chỉ được
thay bằng `UPDATE_GOLDENS=1` (kèm diff cho user review) hoặc re-capture.

## 4. 2 failure pre-existing (tính đến 2026-08-29)

- `tests/test_auth_jwt.py::test_unknown_kid_rejected`
- `tests/test_jobs_retention.py::test_cap_evicts_oldest_when_exceeded`

Tồn tại từ trước refactor facts-architecture, nằm ngoài scope. Đừng sửa chúng
trong lúc làm việc khác; gate luôn là "không có failure MỚI ngoài 2 cái này".

## 5. Tạo lại fixture (capture)

Fixture chứa dữ liệu client (tên, số tiền, nội dung letter) → nằm trong
`.gitignore`, **không commit**. Capture gọi Gemini thật (temperature 0).

**Local samples (8 case):**

```bash
venv/bin/python tests/golden/capture_golden.py --outdir tests/golden/cases --samples-dir samples
```

**Production (30 case)** — PDF client KHÔNG rời server; làm trên server rồi chỉ
mang JSON/TXT/HTML về:

1. Lấy danh sách job id: `grep '^## ' regression_out/prod_report.md`.
2. Đóng tarball code working tree (exclude `.env*`, `.git`, `venv`, `samples`,
   `storage_data`, `regression_out`, `tests/golden/cases`, `*.pdf` — verify
   tarball sạch trước khi scp), đưa lên `/tmp` trên server.
3. Trên server: `set -a; source /etc/itr_extract/api.env; set +a` (env prod nằm
   ở đây, KHÔNG phải /opt/itr_extract/.env), tìm `input.pdf` của từng job tại
   `<files_root>/<user_id>/<job_id>/input.pdf` (job bị retention xóa → extract
   từ backup `/var/backups/itr_extract/files-*.tgz` vào /tmp — cần `sudo -n`
   để đọc backup), rồi chạy:
   ```bash
   /opt/itr_extract/.venv/bin/python <code>/tests/golden/capture_golden.py \
       --outdir /tmp/<out>/cases "prod_<id8>=<đường dẫn input.pdf>" ...
   ```
4. Tar `cases/` (verify không dính `.pdf`), scp về, giải nén vào
   `tests/golden/cases/`, **dọn sạch /tmp trên server**.
5. Sau khi capture: so `expected_email.html` mới với bản cũ / catalog đã verify
   trước khi tin — capture chỉ đóng băng, không tự chứng minh đúng.

## 6. Live regression (khi đổi prompt/schema)

```bash
venv/bin/python regression_out/run_task2_regression.py regression_out/<nhãn-mới>
venv/bin/python regression_out/compare_task2_regression.py \
    regression_out/after_fix2 regression_out/<nhãn-mới> regression_out/report_<nhãn>.md
```

Đọc report: mọi diff phải giải thích được và được user duyệt. Với production
dùng quy trình §5 (spec gốc: `docs/superpowers/specs/2026-08-28-task2-facts-architecture-design.md` §9.3).

## 7. Quy tắc chung

- KHÔNG commit fixture golden, PDF, hay bất cứ gì chứa dữ liệu client.
- KHÔNG tự ý `git add/commit/push` — user tự commit (xem CLAUDE.md).
- Test mới cho logic mới: viết theo pattern có sẵn trong `tests/`.
