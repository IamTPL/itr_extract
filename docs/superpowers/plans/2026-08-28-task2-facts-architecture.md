# Task 2 Facts Architecture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chuyển Task 2 từ "Gemini viết câu theo pattern cứng" sang "Gemini extract facts, code render câu chuẩn CNY + validate + van xả ⚠️" — sửa tận gốc bug Kramer (mail-check bị dịch thành auto-withdrawal) và bug bỏ sót ANNUAL/ESTIMATED prose payments.

**Architecture:** Gemini trả về `jurisdictions[]` + `scheduled_payments[]` (facts + source_quote). `jobs/facts_validation.py` kiểm chứng verbatim/dedup/gate và gắn `needs_review`. `jobs/summary_sentences.py` là nguồn wording duy nhất, dùng chung cho email HTML (`jobs/email_html.py`) và DOCX (`main.py`).

**Tech Stack:** Python 3.11, FastAPI/arq (không đổi), PyMuPDF (fitz), Gemini structured output (OpenAPI-subset schema), pytest.

**Spec:** `docs/superpowers/specs/2026-08-28-task2-facts-architecture-design.md`

## Global Constraints

- **NGHIÊM CẤM `git add` / `git commit` / `git push`** — mọi task kết thúc ở working tree + pytest xanh. User tự commit sau. (Working tree đang có 3 file local-only chưa được phép lên prod.)
- **Không sửa 3 file dirty:** `.env.example`, `auth/deps.py`, `config/settings.py`. (Lưu ý: `config/constants.py` là file KHÁC và sạch — Task 2 được sửa nó.)
- **Không thêm dependency mới** vào `requirements.txt`.
- Chạy Python/pytest bằng venv của repo: `venv/bin/python`, `venv/bin/python -m pytest`.
- Câu chữ gửi khách (tiếng Anh) phải dùng **đúng nguyên văn** chuỗi trong plan này — không paraphrase. Wording P1c nằm ở hằng số `P1C_PORTAL_PHRASE` (đang chờ client chốt "ShareFile portal" vs "Client Portal" — mặc định ShareFile).
- Thư mục `regression_out/` là untracked, KHÔNG bao giờ được commit.
- Tuân thủ `CLAUDE.md` gốc repo (surgical changes; chỉ xóa symbol do chính thay đổi này làm unused).
- Task 0 (baseline) và Task 9/10 (regression) gọi Gemini thật — cần `GEMINI_API_KEY` trong `.env` (đã có sẵn local).

---

### Task 0: Chụp baseline 8 samples bằng code HIỆN TẠI

Phải chạy **trước mọi thay đổi code** — đây là mốc so sánh của Task 9.

**Files:**
- Create: `regression_out/run_task2_regression.py`
- Create (output): `regression_out/baseline/*.json`, `regression_out/baseline/*.html`

**Interfaces:**
- Produces: baseline dir cho Task 9; script được tái dùng nguyên trạng sau refactor (nó chỉ gọi `run_extraction`).

- [ ] **Step 1: Xác nhận working tree chưa bị sửa ngoài 3 file dirty đã biết**

Run: `git status --short`
Expected: chỉ ` M .env.example`, ` M auth/deps.py`, ` M config/settings.py` (+ dòng `??` cho docs/specs/plans mới nếu có).

- [ ] **Step 2: Viết script**

```python
# regression_out/run_task2_regression.py
"""Chạy pipeline trên toàn bộ samples/ và lưu JSON + HTML per file.

Dùng:  venv/bin/python regression_out/run_task2_regression.py regression_out/baseline
Gọi Gemini thật (~17s + vài cent mỗi file). Không ghi DB.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from jobs.pipeline import run_extraction  # noqa: E402


def main() -> None:
    outdir = pathlib.Path(sys.argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    for pdf in sorted(pathlib.Path("samples").glob("*.pdf")):
        data, html, _econsent = run_extraction(pdf.read_bytes())
        stem = pdf.stem.replace(" ", "_").replace(",", "")
        (outdir / f"{stem}.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False)
        )
        (outdir / f"{stem}.html").write_text(html)
        print(f"done: {pdf.name}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Chạy baseline**

Run: `venv/bin/python regression_out/run_task2_regression.py regression_out/baseline`
Expected: 8 dòng `done:`, thư mục baseline có 16 file (8 json + 8 html).

- [ ] **Step 4: Xác nhận baseline ghi lại đúng bug hiện tại**

Run: `grep -l "withdrawn from your account" regression_out/baseline/Kramer_example_full_pages.html`
Expected: in ra tên file (bug Kramer có mặt trong baseline — đây là điều sẽ đổi sau refactor).

---

### Task 1: `jobs/summary_sentences.py` — renderer thuần (nguồn wording duy nhất)

**Files:**
- Create: `jobs/summary_sentences.py`
- Test: `tests/test_summary_sentences.py`

**Interfaces:**
- Consumes: không phụ thuộc module nội bộ nào (chỉ stdlib `datetime`).
- Produces (Task 5, 6, 7, 8 dùng đúng các tên/chữ ký này):
  - `P1C_PORTAL_PHRASE: str`
  - `format_amount(value) -> str`
  - `format_long_date(value) -> str`
  - `is_federal(name) -> bool`
  - `review_note(item: dict) -> str`
  - `jurisdiction_sentence(j: dict, next_year: str) -> str | None` — `None` ⇒ caller chèn review block
  - `estimated_entries(scheduled: list | None) -> list[dict]`
  - `estimated_rows(entries: list[dict]) -> list[dict]` — `[{"date","federal","state"}]`
  - `estimated_intro(entries: list[dict]) -> str`
  - `scheduled_sentence(e: dict, next_year: str) -> str | None` — cho `type` annual/pte; `None` ⇒ review block

- [ ] **Step 1: Viết test fail**

```python
# tests/test_summary_sentences.py
from jobs import summary_sentences as ss


def _bd(amount, method, withdrawal_date=None, due_date=None):
    return {
        "jurisdiction_name": "Federal",
        "outcome": "balance_due",
        "balance_due": {
            "amount": amount,
            "payment_method": method,
            "withdrawal_date": withdrawal_date,
            "due_date": due_date,
        },
        "overpayment": None,
        "source_quote": "q",
        "other_note": None,
    }


def test_p1a_direct_debit_no_date():
    assert ss.jurisdiction_sentence(_bd(1341, "direct_debit"), "2026") == (
        "**Balance due** of **$1,341**, which will be withdrawn from your "
        "account once your return has been processed."
    )


def test_p1b_direct_debit_with_date():
    assert ss.jurisdiction_sentence(
        _bd(14917, "direct_debit", withdrawal_date="04/15/2026"), "2026"
    ) == "**Balance due** of **$14,917**, will be withdrawn from account on **April 15, 2026**."


def test_p1c_mail_check_with_due_date():
    assert ss.jurisdiction_sentence(
        _bd(130828, "mail_check", due_date="08/26/2026"), "2026"
    ) == (
        "**Balance due** of **$130,828**, see the voucher on the ShareFile "
        "portal, due on or before **August 26, 2026**."
    )


def test_p1c_mail_check_without_due_date():
    assert ss.jurisdiction_sentence(_bd(500, "mail_check"), "2026") == (
        "**Balance due** of **$500**, see the voucher on the ShareFile portal."
    )


def test_balance_due_other_method_returns_none():
    assert ss.jurisdiction_sentence(_bd(500, "other"), "2026") is None


def _rc(credited, refunded):
    return {
        "jurisdiction_name": "Federal",
        "outcome": "refund_or_credit",
        "balance_due": None,
        "overpayment": {"credited_next_year": credited, "refunded": refunded},
        "source_quote": "q",
        "other_note": None,
    }


def test_p2_fully_credited():
    assert ss.jurisdiction_sentence(_rc(3597, 0), "2026") == (
        "No tax is payable with the filing of this return. **Overpayment** of "
        "**$3,597** of which **$3,597** credited to 2026 tax."
    )


def test_p3_pure_refund():
    assert ss.jurisdiction_sentence(_rc(0, 2052), "2026") == (
        "No tax is payable with the filing of this return. **Refund** of "
        "**$2,052** will be deposited to your account."
    )


def test_p4_split():
    assert ss.jurisdiction_sentence(_rc(1000, 500), "2026") == (
        "No tax is payable with the filing of this return. **Overpayment** of "
        "**$1,500** of which **$1,000** credited to 2026 tax. **Refund** of "
        "**$500** will be deposited to your account."
    )


def test_p5_no_tax():
    j = {"jurisdiction_name": "California", "outcome": "no_tax",
         "balance_due": None, "overpayment": None,
         "source_quote": "No tax is payable", "other_note": None}
    assert ss.jurisdiction_sentence(j, "2026") == (
        "No tax is payable with the filing of this return."
    )


def test_outcome_other_and_flagged_return_none():
    j = {"jurisdiction_name": "Federal", "outcome": "other",
         "balance_due": None, "overpayment": None,
         "source_quote": "q", "other_note": "pay by money order"}
    assert ss.jurisdiction_sentence(j, "2026") is None
    flagged = _bd(100, "direct_debit")
    flagged["needs_review"] = True
    assert ss.jurisdiction_sentence(flagged, "2026") is None


def test_review_note_with_and_without_quote():
    assert ss.review_note({"other_note": "pay by money order",
                           "source_quote": "Mail a money order"}) == (
        '⚠️ NEEDS REVIEW — pay by money order Letter says: "Mail a money order"'
    )
    assert ss.review_note({}) == (
        "⚠️ NEEDS REVIEW — Unrecognized case — please write this line manually."
    )


def _est(jur, amount, date, method="direct_debit"):
    return {"type": "estimated", "jurisdiction": jur, "amount": amount,
            "date": date, "payment_method": method, "ordinal": None,
            "source_quote": "q", "note": None}


def test_estimated_rows_group_by_date_in_order():
    entries = [_est("Federal", 5600, "04/15/2026"),
               _est("North Carolina", 500, "04/15/2026"),
               _est("Federal", 5600, "06/15/2026")]
    assert ss.estimated_rows(entries) == [
        {"date": "04/15/2026", "federal": 5600, "state": 500},
        {"date": "06/15/2026", "federal": 5600, "state": 0},
    ]


def test_estimated_intro_variants():
    debit = [_est("Federal", 1, "04/15/2026"), _est("California", 1, "04/15/2026")]
    assert ss.estimated_intro(debit) == (
        "Federal and state estimated tax payments will be automatically "
        "withdrawn as shown below"
    )
    voucher = [_est("Federal", 1, "04/15/2026", method="mail_voucher")]
    assert ss.estimated_intro(voucher) == (
        "Federal estimated tax payments are due as shown below. If not paying "
        "electronically, please mail your payments using the payment vouchers."
    )
    mixed = [_est("California", 1, "04/15/2026", method="unspecified")]
    assert ss.estimated_intro(mixed) == (
        "State estimated tax payments are due as shown below"
    )


def test_annual_sentence():
    e = {"type": "annual", "jurisdiction": "California", "amount": 800,
         "date": "04/15/2026", "payment_method": "direct_debit",
         "ordinal": None, "source_quote": "q", "note": None}
    assert ss.scheduled_sentence(e, "2026") == (
        "2026 California annual tax payment of **$800** will be automatically "
        "withdrawn on **April 15, 2026**."
    )
    e2 = {**e, "payment_method": "unspecified"}
    assert ss.scheduled_sentence(e2, "2026") == (
        "2026 California annual tax payment of **$800** is due on **April 15, 2026**."
    )


def test_pte_sentence_with_and_without_ordinal():
    e = {"type": "pte", "jurisdiction": "California", "amount": 10500,
         "date": "06/15/2026", "payment_method": "direct_debit",
         "ordinal": None, "source_quote": "q", "note": None}
    assert ss.scheduled_sentence(e, "2026") == (
        "2026 PTE tax payment of **$10,500** will be automatically withdrawn "
        "on **June 15, 2026**."
    )
    assert ss.scheduled_sentence({**e, "ordinal": "1st"}, "2026") == (
        "2026 1st PTE tax payment of **$10,500** will be automatically "
        "withdrawn on **June 15, 2026**."
    )


def test_scheduled_other_or_flagged_returns_none():
    other = {"type": "other", "jurisdiction": "California", "amount": 1,
             "date": "04/15/2026", "payment_method": "unspecified",
             "ordinal": None, "source_quote": "q", "note": "?"}
    assert ss.scheduled_sentence(other, "2026") is None
    flagged = {"type": "pte", "amount": 1, "date": "04/15/2026",
               "payment_method": "direct_debit", "needs_review": True}
    assert ss.scheduled_sentence(flagged, "2026") is None


def test_formatters():
    assert ss.format_amount(130828) == "$130,828"
    assert ss.format_amount(130828.0) == "$130,828"
    assert ss.format_amount(12.5) == "$12.50"
    assert ss.format_long_date("08/26/2026") == "August 26, 2026"
    assert ss.format_long_date("bad") == "bad"
    assert ss.is_federal("Federal") and ss.is_federal(" federal ")
    assert not ss.is_federal("California") and not ss.is_federal(None)
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `venv/bin/python -m pytest tests/test_summary_sentences.py -q`
Expected: FAIL/ERROR `ModuleNotFoundError: No module named 'jobs.summary_sentences'`.

- [ ] **Step 3: Implement**

```python
# jobs/summary_sentences.py
"""Facts → câu chuẩn CNY. Nguồn wording DUY NHẤT cho email HTML và DOCX.

Mọi hàm đều pure: dict facts vào, chuỗi markdown ra (**bold** được tầng render
đổi thành <strong>/bold-run). Trả về None nghĩa là "không có câu an toàn" —
caller phải chèn review block (review_note) thay vì đoán.
"""
from datetime import datetime

# Chờ client chốt wording cuối ("ShareFile portal" vs "Client Portal") — đổi 1 dòng này.
P1C_PORTAL_PHRASE = "see the voucher on the ShareFile portal"

_NO_TAX = "No tax is payable with the filing of this return."


def format_amount(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == int(number):
        return f"${int(number):,}"
    return f"${number:,.2f}"


def format_long_date(value) -> str:
    try:
        dt = datetime.strptime(str(value), "%m/%d/%Y")
    except (TypeError, ValueError):
        return str(value)
    return f"{dt:%B} {dt.day}, {dt.year}"


def is_federal(name) -> bool:
    return isinstance(name, str) and name.strip().casefold() == "federal"


def review_note(item: dict) -> str:
    note = (
        item.get("other_note")
        or item.get("note")
        or "Unrecognized case — please write this line manually."
    )
    text = f"⚠️ NEEDS REVIEW — {note}"
    quote = item.get("source_quote")
    if quote:
        text += f' Letter says: "{quote}"'
    return text


def jurisdiction_sentence(j: dict, next_year: str) -> str | None:
    if j.get("needs_review"):
        return None
    outcome = j.get("outcome")
    if outcome == "no_tax":
        return _NO_TAX
    if outcome == "balance_due":
        return _balance_due_sentence(j.get("balance_due") or {})
    if outcome == "refund_or_credit":
        return _refund_or_credit_sentence(j.get("overpayment") or {}, next_year)
    return None


def _balance_due_sentence(bd: dict) -> str | None:
    amount = bd.get("amount")
    if amount is None:
        return None
    amt = format_amount(amount)
    method = bd.get("payment_method")
    if method == "direct_debit":
        withdrawal_date = bd.get("withdrawal_date")
        if withdrawal_date:
            return (
                f"**Balance due** of **{amt}**, will be withdrawn from account "
                f"on **{format_long_date(withdrawal_date)}**."
            )
        return (
            f"**Balance due** of **{amt}**, which will be withdrawn from your "
            "account once your return has been processed."
        )
    if method == "mail_check":
        sentence = f"**Balance due** of **{amt}**, {P1C_PORTAL_PHRASE}"
        due_date = bd.get("due_date")
        if due_date:
            sentence += f", due on or before **{format_long_date(due_date)}**"
        return sentence + "."
    return None


def _refund_or_credit_sentence(op: dict, next_year: str) -> str | None:
    credited = op.get("credited_next_year") or 0
    refunded = op.get("refunded") or 0
    refund_part = (
        f"**Refund** of **{format_amount(refunded)}** will be deposited to your account."
    )
    if credited > 0:
        total = format_amount(credited + refunded)
        sentence = (
            f"{_NO_TAX} **Overpayment** of **{total}** of which "
            f"**{format_amount(credited)}** credited to {next_year} tax."
        )
        if refunded > 0:
            sentence += f" {refund_part}"
        return sentence
    if refunded > 0:
        return f"{_NO_TAX} {refund_part}"
    return None


def estimated_entries(scheduled) -> list[dict]:
    return [
        e for e in (scheduled or [])
        if isinstance(e, dict) and e.get("type") == "estimated" and not e.get("needs_review")
    ]


def estimated_rows(entries: list[dict]) -> list[dict]:
    rows: dict[str, dict] = {}
    for e in entries:
        date = str(e.get("date", ""))
        row = rows.setdefault(date, {"date": date, "federal": 0, "state": 0})
        key = "federal" if is_federal(e.get("jurisdiction")) else "state"
        row[key] += e.get("amount") or 0
    return list(rows.values())


def estimated_intro(entries: list[dict]) -> str:
    has_fed = any(
        is_federal(e.get("jurisdiction")) and (e.get("amount") or 0) > 0 for e in entries
    )
    has_state = any(
        not is_federal(e.get("jurisdiction")) and (e.get("amount") or 0) > 0 for e in entries
    )
    if has_fed and has_state:
        subject = "Federal and state estimated tax payments"
    elif has_fed:
        subject = "Federal estimated tax payments"
    else:
        subject = "State estimated tax payments"
    methods = {e.get("payment_method") for e in entries}
    if methods == {"direct_debit"}:
        return f"{subject} will be automatically withdrawn as shown below"
    if methods == {"mail_voucher"}:
        return (
            f"{subject} are due as shown below. If not paying electronically, "
            "please mail your payments using the payment vouchers."
        )
    return f"{subject} are due as shown below"


def scheduled_sentence(e: dict, next_year: str) -> str | None:
    if e.get("needs_review"):
        return None
    kind = e.get("type")
    amount, date = e.get("amount"), e.get("date")
    if amount is None or not date:
        return None
    amt, long_date = format_amount(amount), format_long_date(date)
    debit = e.get("payment_method") == "direct_debit"
    if kind == "annual":
        jurisdiction = (e.get("jurisdiction") or "").strip()
        head = f"{next_year} {jurisdiction} annual tax payment of **{amt}**" if jurisdiction \
            else f"{next_year} annual tax payment of **{amt}**"
        if debit:
            return f"{head} will be automatically withdrawn on **{long_date}**."
        return f"{head} is due on **{long_date}**."
    if kind == "pte":
        ordinal = e.get("ordinal")
        label = (
            f"{next_year} {ordinal} PTE tax payment" if ordinal else f"{next_year} PTE tax payment"
        )
        if debit:
            return f"{label} of **{amt}** will be automatically withdrawn on **{long_date}**."
        return f"{label} of **{amt}** is due on **{long_date}**."
    return None
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `venv/bin/python -m pytest tests/test_summary_sentences.py -q`
Expected: tất cả PASS.

- [ ] **Step 5: Chạy full suite xác nhận không vỡ gì**

Run: `venv/bin/python -m pytest -q`
Expected: xanh như trước task (module mới chưa ai import).

---

### Task 2: `jobs/facts_validation.py` — verbatim check, dedup, PTE gate, needs_review

**Files:**
- Modify: `config/constants.py` (thêm `PTE_ELIGIBLE_RETURN_TYPES`)
- Modify: `main.py:67` (định nghĩa set → import từ constants, giữ nguyên tên để `jobs/email_html.py` import cũ vẫn chạy)
- Create: `jobs/facts_validation.py`
- Test: `tests/test_facts_validation.py`

**Interfaces:**
- Consumes: `config.constants.PTE_ELIGIBLE_RETURN_TYPES` (di chuyển tại task này — TRÁNH vòng import main ↔ jobs vì Task 8 cho `main.py` import module này).
- Produces:
  - `letter_text_from_pdf(pdf_bytes) -> str` (lỗi/PDF hỏng → `""`)
  - `validate_facts(analysis: dict, letter_text: str) -> dict` — trả bản sao: PTE gate, dedup `scheduled_payments`, gắn `needs_review: True` per-item khi fail, luôn set top-level `analysis["needs_review"]: bool`; **bảo toàn mọi key khác** (passthrough).

- [ ] **Step 1: Di chuyển hằng số**

Trong `config/constants.py` thêm (cuối file):

```python
# Loại return được phép có PTE elective tax (dùng bởi validation + renderer).
PTE_ELIGIBLE_RETURN_TYPES = {"S-Corporation (1120S)", "Partnership (1065)"}
```

Trong `main.py`, thay dòng 67 `PTE_ELIGIBLE_RETURN_TYPES = {...}` bằng:

```python
from config.constants import PTE_ELIGIBLE_RETURN_TYPES  # noqa: F401 (re-export cho jobs.email_html)
```

Run: `venv/bin/python -m pytest -q` → Expected: xanh (import path cũ `from main import PTE_ELIGIBLE_RETURN_TYPES` vẫn hoạt động).

- [ ] **Step 2: Viết test fail**

```python
# tests/test_facts_validation.py
import fitz

from jobs import facts_validation as fv

LETTER_TEXT = (
    "There is a balance due of $130,828. Make your check payable and mail your "
    "Form 1040-V payment voucher on or before August 26, 2026. "
    "The 2026 Pass-Through Entity Elective Tax Estimate balance due of $10,500 "
    "will be directly withdrawn from your bank account on June 15, 2026. "
    "Due Date California 4/15/26 $ 2,800 refund of $951"
)


def _jur(**over):
    j = {"jurisdiction_name": "Federal", "state_abbreviation": None,
         "display_label": None, "outcome": "balance_due",
         "balance_due": {"amount": 130828, "payment_method": "mail_check",
                         "withdrawal_date": None, "due_date": "08/26/2026"},
         "overpayment": None, "source_quote": "q", "other_note": None}
    j.update(over)
    return j


def _pte(amount=10500, date="06/15/2026", **over):
    e = {"type": "pte", "jurisdiction": "California", "amount": amount,
         "date": date, "payment_method": "direct_debit", "ordinal": None,
         "source_quote": "q", "note": None}
    e.update(over)
    return e


def _analysis(jurisdictions=None, scheduled=None, return_type="S-Corporation (1120S)"):
    return {"return_type": return_type, "extra_key": "preserved",
            "jurisdictions": jurisdictions or [], "scheduled_payments": scheduled or []}


def test_valid_facts_pass_and_preserve_keys():
    out = fv.validate_facts(_analysis([_jur()], [_pte()]), LETTER_TEXT)
    assert out["needs_review"] is False
    assert out["extra_key"] == "preserved"
    assert "needs_review" not in out["jurisdictions"][0]
    assert "needs_review" not in out["scheduled_payments"][0]


def test_amount_not_in_letter_is_flagged():
    j = _jur(balance_due={"amount": 999999, "payment_method": "mail_check",
                          "withdrawal_date": None, "due_date": None})
    out = fv.validate_facts(_analysis([j]), LETTER_TEXT)
    assert out["jurisdictions"][0]["needs_review"] is True
    assert out["needs_review"] is True


def test_date_not_in_letter_is_flagged():
    j = _jur(balance_due={"amount": 130828, "payment_method": "mail_check",
                          "withdrawal_date": None, "due_date": "12/31/2027"})
    out = fv.validate_facts(_analysis([j]), LETTER_TEXT)
    assert out["jurisdictions"][0]["needs_review"] is True


def test_two_digit_year_table_date_matches():
    e = _pte(amount=2800, date="04/15/2026", type="estimated")
    out = fv.validate_facts(_analysis(scheduled=[e]), LETTER_TEXT)
    assert out["needs_review"] is False


def test_outcome_other_and_bad_method_flagged():
    out = fv.validate_facts(
        _analysis([_jur(outcome="other"),
                   _jur(balance_due={"amount": 130828, "payment_method": "other",
                                     "withdrawal_date": None, "due_date": None})]),
        LETTER_TEXT,
    )
    assert [j["needs_review"] for j in out["jurisdictions"]] == [True, True]


def test_refund_or_credit_rules():
    ok = _jur(outcome="refund_or_credit", balance_due=None,
              overpayment={"credited_next_year": 0, "refunded": 951})
    zero = _jur(outcome="refund_or_credit", balance_due=None,
                overpayment={"credited_next_year": 0, "refunded": 0})
    out = fv.validate_facts(_analysis([ok, zero]), LETTER_TEXT)
    assert "needs_review" not in out["jurisdictions"][0]
    assert out["jurisdictions"][1]["needs_review"] is True


def test_pte_gate_drops_pte_for_individual_return():
    out = fv.validate_facts(
        _analysis(scheduled=[_pte()], return_type="Individual (1040)"), LETTER_TEXT
    )
    assert out["scheduled_payments"] == []


def test_dedup_same_type_and_other_loses_to_specific():
    dup = [_pte(), _pte(), _pte(type="other", note="dup"),
           _pte(type="estimated", amount=2800, date="04/15/2026")]
    out = fv.validate_facts(_analysis(scheduled=dup), LETTER_TEXT)
    kinds = [e["type"] for e in out["scheduled_payments"]]
    assert kinds == ["pte", "estimated"]


def test_pte_and_estimated_same_amount_date_both_kept():
    pair = [_pte(), _pte(type="estimated")]
    out = fv.validate_facts(_analysis(scheduled=pair), LETTER_TEXT)
    assert [e["type"] for e in out["scheduled_payments"]] == ["pte", "estimated"]


def test_scheduled_type_other_is_flagged_not_dropped():
    e = _pte(type="other", note="unknown payment")
    out = fv.validate_facts(_analysis(scheduled=[e]), LETTER_TEXT)
    assert out["scheduled_payments"][0]["needs_review"] is True


def test_letter_text_from_pdf_roundtrip_and_garbage():
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "hello letter")
    text = fv.letter_text_from_pdf(doc.write())
    doc.close()
    assert "hello letter" in text
    assert fv.letter_text_from_pdf(b"not-a-pdf") == ""
```

- [ ] **Step 3: Chạy test, xác nhận fail**

Run: `venv/bin/python -m pytest tests/test_facts_validation.py -q`
Expected: FAIL `ModuleNotFoundError: No module named 'jobs.facts_validation'`.

- [ ] **Step 4: Implement**

```python
# jobs/facts_validation.py
"""Kiểm chứng facts Gemini trước khi render: chống bịa số/ngày, đếm trùng, gate PTE.

Nguyên tắc: không bao giờ lặng lẽ sửa nội dung — mục nào không kiểm chứng được
thì gắn needs_review=True để renderer chèn block ⚠️ cho staff xử lý.
"""
import re

import fitz

from config.constants import PTE_ELIGIBLE_RETURN_TYPES

_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_VALID_OUTCOMES = {"no_tax", "balance_due", "refund_or_credit"}
_VALID_SCHEDULED_TYPES = {"estimated", "annual", "pte"}


def letter_text_from_pdf(pdf_bytes) -> str:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return ""
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def _amount_in_text(amount, text: str) -> bool:
    try:
        number = float(amount)
    except (TypeError, ValueError):
        return False
    candidates = {f"{number:,.0f}", f"{number:,.2f}", f"{number:.0f}", f"{number:.2f}"}
    return any(c in text for c in candidates)


def _date_in_text(value, text: str) -> bool:
    match = _DATE_RE.match(str(value or ""))
    if not match:
        return False
    month, day, year = int(match.group(1)), int(match.group(2)), match.group(3)
    if not 1 <= month <= 12:
        return False
    short_year = year[2:]
    candidates = {
        f"{_MONTHS[month - 1]} {day}, {year}",
        f"{month}/{day}/{year}", f"{month:02d}/{day:02d}/{year}",
        f"{month}/{day}/{short_year}", f"{month:02d}/{day:02d}/{short_year}",
    }
    lowered = text.casefold()
    return any(c.casefold() in lowered for c in candidates)


def _jurisdiction_needs_review(j: dict, text: str) -> bool:
    outcome = j.get("outcome")
    if outcome not in _VALID_OUTCOMES:
        return True
    if outcome == "no_tax":
        return False
    if outcome == "balance_due":
        bd = j.get("balance_due")
        if not isinstance(bd, dict) or bd.get("amount") is None:
            return True
        if bd.get("payment_method") not in ("direct_debit", "mail_check"):
            return True
        if not _amount_in_text(bd["amount"], text):
            return True
        for key in ("withdrawal_date", "due_date"):
            value = bd.get(key)
            if value and not _date_in_text(value, text):
                return True
        return False
    op = j.get("overpayment")  # refund_or_credit
    if not isinstance(op, dict):
        return True
    credited = op.get("credited_next_year") or 0
    refunded = op.get("refunded") or 0
    if credited <= 0 and refunded <= 0:
        return True
    for value in (credited, refunded):
        if value > 0 and not _amount_in_text(value, text):
            return True
    return False


def _scheduled_needs_review(e: dict, text: str) -> bool:
    if e.get("type") not in _VALID_SCHEDULED_TYPES:
        return True
    if e.get("amount") is None or not e.get("date"):
        return True
    if not _amount_in_text(e["amount"], text):
        return True
    if not _date_in_text(e["date"], text):
        return True
    return False


def _dedup_scheduled(entries: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for e in entries:
        key = (e.get("jurisdiction"), e.get("amount"), e.get("date"))
        replaced = False
        duplicate = False
        for index, existing in enumerate(kept):
            if (existing.get("jurisdiction"), existing.get("amount"),
                    existing.get("date")) != key:
                continue
            same_type = existing.get("type") == e.get("type")
            one_is_other = "other" in (existing.get("type"), e.get("type"))
            if not (same_type or one_is_other):
                continue  # ví dụ pte vs estimated cùng số — hai khoản thật, giữ cả hai
            duplicate = True
            if existing.get("type") == "other" and e.get("type") != "other":
                kept[index] = e  # ưu tiên type cụ thể hơn "other"
                replaced = True
            break
        if not duplicate and not replaced:
            kept.append(e)
    return kept


def validate_facts(analysis: dict, letter_text: str) -> dict:
    if not isinstance(analysis, dict):
        return analysis
    result = dict(analysis)
    flagged = False

    jurisdictions = []
    for raw in result.get("jurisdictions") or []:
        if not isinstance(raw, dict):
            continue
        j = dict(raw)
        if _jurisdiction_needs_review(j, letter_text):
            j["needs_review"] = True
            flagged = True
        jurisdictions.append(j)
    result["jurisdictions"] = jurisdictions

    scheduled = [dict(e) for e in result.get("scheduled_payments") or []
                 if isinstance(e, dict)]
    if result.get("return_type") not in PTE_ELIGIBLE_RETURN_TYPES:
        scheduled = [e for e in scheduled if e.get("type") != "pte"]
    scheduled = _dedup_scheduled(scheduled)
    for e in scheduled:
        if _scheduled_needs_review(e, letter_text):
            e["needs_review"] = True
            flagged = True
    result["scheduled_payments"] = scheduled

    result["needs_review"] = flagged
    return result
```

- [ ] **Step 5: Chạy test module + full suite**

Run: `venv/bin/python -m pytest tests/test_facts_validation.py -q && venv/bin/python -m pytest -q`
Expected: tất cả PASS.

---

### Task 3: `schemas.py` — TASK2_RESPONSE_SCHEMA mới

**Files:**
- Modify: `schemas.py` (thay toàn bộ TASK2_RESPONSE_SCHEMA; giữ docstring đầu file, cập nhật ghi chú design)

**Interfaces:**
- Produces: `TASK2_RESPONSE_SCHEMA` shape facts — Task 4 (prompt) và Task 5 (contract test) phải khớp từng field. Quy ước Gemini: type UPPERCASE, mọi property nằm trong `required`, enum KHÔNG kết hợp nullable.

- [ ] **Step 1: Thay schema**

```python
# ── Task 2: client cover-letter FACTS extraction ─────────────────────────────
TASK2_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "required": [
        "client", "cpa_firm", "tax_year", "next_year",
        "return_type", "jurisdictions", "scheduled_payments",
    ],
    "properties": {
        "client": {
            "type": "OBJECT",
            "required": ["name"],
            "properties": {"name": {"type": "STRING", "nullable": True}},
        },
        "cpa_firm": {
            "type": "OBJECT",
            "required": ["name", "sharefile_subdomain"],
            "properties": {
                "name": {"type": "STRING", "nullable": True},
                "sharefile_subdomain": {"type": "STRING", "nullable": True},
            },
        },
        "tax_year":  {"type": "STRING", "nullable": True},
        "next_year": {"type": "STRING", "nullable": True},
        "return_type": {
            "type": "STRING",
            "enum": [
                "Individual (1040)",
                "S-Corporation (1120S)",
                "C-Corporation (1120)",
                "Partnership (1065)",
                "Trust/Estate (1041)",
                "Non-Profit (990)",
            ],
        },
        "jurisdictions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "required": [
                    "jurisdiction_name", "state_abbreviation", "display_label",
                    "outcome", "balance_due", "overpayment",
                    "source_quote", "other_note",
                ],
                "properties": {
                    "jurisdiction_name":  {"type": "STRING"},
                    "state_abbreviation": {"type": "STRING", "nullable": True},
                    "display_label":      {"type": "STRING", "nullable": True},
                    "outcome": {
                        "type": "STRING",
                        "enum": ["balance_due", "refund_or_credit", "no_tax", "other"],
                    },
                    "balance_due": {
                        "type": "OBJECT",
                        "nullable": True,
                        "required": ["amount", "payment_method", "withdrawal_date", "due_date"],
                        "properties": {
                            "amount": {"type": "NUMBER"},
                            "payment_method": {
                                "type": "STRING",
                                "enum": ["direct_debit", "mail_check", "other"],
                            },
                            "withdrawal_date": {"type": "STRING", "nullable": True},
                            "due_date":        {"type": "STRING", "nullable": True},
                        },
                    },
                    "overpayment": {
                        "type": "OBJECT",
                        "nullable": True,
                        "required": ["credited_next_year", "refunded"],
                        "properties": {
                            "credited_next_year": {"type": "NUMBER"},
                            "refunded":           {"type": "NUMBER"},
                        },
                    },
                    "source_quote": {"type": "STRING"},
                    "other_note":   {"type": "STRING", "nullable": True},
                },
            },
        },
        "scheduled_payments": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "required": [
                    "type", "jurisdiction", "amount", "date",
                    "payment_method", "ordinal", "source_quote", "note",
                ],
                "properties": {
                    "type": {
                        "type": "STRING",
                        "enum": ["estimated", "annual", "pte", "other"],
                    },
                    "jurisdiction": {"type": "STRING"},
                    "amount":       {"type": "NUMBER"},
                    "date":         {"type": "STRING"},
                    "payment_method": {
                        "type": "STRING",
                        "enum": ["direct_debit", "mail_voucher", "unspecified"],
                    },
                    "ordinal":      {"type": "STRING", "nullable": True},
                    "source_quote": {"type": "STRING"},
                    "note":         {"type": "STRING", "nullable": True},
                },
            },
        },
    },
}
```

Cập nhật docstring đầu file: thay bullet "estimated_payments... Set missing to 0" và "tax_summary..." bằng:

```
  • jurisdictions/scheduled_payments — facts-only (không có câu văn); mọi enum
    KHÔNG nullable (enum + nullable không ổn định trên preview models);
    object con balance_due/overpayment nullable ở cấp ngoài.
```

- [ ] **Step 2: Sanity import**

Run: `venv/bin/python -c "from schemas import TASK2_RESPONSE_SCHEMA; print(sorted(TASK2_RESPONSE_SCHEMA['properties']))"`
Expected: in danh sách key có `jurisdictions`, `scheduled_payments`, không có `tax_summary`.

- [ ] **Step 3: Chạy full suite — ghi nhận các test fail CHỦ ĐÍCH**

Run: `venv/bin/python -m pytest -q`
Expected: `tests/test_task2_email_contract.py` FAIL (schema đổi — Task 5 sửa). Các file khác vẫn xanh. Nếu file khác fail → dừng, điều tra.

---

### Task 4: Viết lại `prompts/task2_email.txt` (facts-only)

**Files:**
- Modify: `prompts/task2_email.txt` (thay TOÀN BỘ nội dung bằng text dưới)

**Interfaces:**
- Produces: worked examples định dạng `EXPECTED OUTPUT:` + JSON indent 2-space (regex contract test hiện có phụ thuộc format này). JSON các example phải khớp schema Task 3 từng field.

- [ ] **Step 1: Thay toàn bộ nội dung file bằng:**

```text
You are a senior U.S. Certified Public Accountant (CPA) with 20+ years of experience preparing
federal, multi-state, and local/regional income tax returns. You are reading a CLIENT COVER
(TRANSMITTAL) LETTER that summarizes the outcome of a finalized tax return. The PDF you receive
contains one or more pages from the bookmarked Letter section, or the first PDF page when that
bookmark is unavailable. It contains nothing else.

Your job: extract STRUCTURED FACTS ONLY. You never write client-facing sentences — application
code renders the notification email from your facts. Accuracy and verbatim evidence beat fluency.

═══════════════════════════════════════════════════════════════════
ABSOLUTE SCOPE RULES
═══════════════════════════════════════════════════════════════════
• Use ONLY information literally present in the letter. Never invent amounts, dates, or jurisdictions.
• If a field is not present in the letter, return null (or [] for arrays, 0 for a missing
  overpayment side).
• Ignore intermediate calculations (ACA premium tax credit reconciliation, depreciation,
  K-1 distribution instructions, signature blocks, preparer notes).
• Every entry carries "source_quote": the deciding sentence(s) copied VERBATIM from the letter.

═══════════════════════════════════════════════════════════════════
OUTPUT JSON SCHEMA (strict)
═══════════════════════════════════════════════════════════════════
{
  "client": { "name": "string — as printed in salutation/address block" },
  "cpa_firm": {
    "name": "string — firm letterhead",
    "sharefile_subdomain": "string — lowercase alphanumeric, derived from firm name (e.g. 'CNY LLP' → 'cnyllp')"
  },
  "tax_year":   "string — 4-digit year of the return (e.g. '2025')",
  "next_year":  "string — tax_year + 1 (e.g. '2026')",
  "return_type": "Individual (1040)" | "S-Corporation (1120S)" | "C-Corporation (1120)" | "Partnership (1065)" | "Trust/Estate (1041)" | "Non-Profit (990)",
  "jurisdictions": [ { ...see JURISDICTIONS... } ],
  "scheduled_payments": [ { ...see SCHEDULED PAYMENTS... } ]
}

═══════════════════════════════════════════════════════════════════
JURISDICTIONS — current-year outcome, one entry per taxing jurisdiction
═══════════════════════════════════════════════════════════════════
One entry per jurisdiction the letter reports an outcome for (Federal + each state, local, or
regional tax), in letter order. Fields:

• "jurisdiction_name": "Federal", or the full state/local/regional name
  (e.g. "California", "Oregon Metro Supportive Housing Services").
• "state_abbreviation": null for Federal; otherwise the host state's USPS 2-letter code.
• "display_label": null for Federal and for an ordinary state tax; for a local or regional tax,
  a concise complete client-facing heading without a trailing colon (e.g. "OR Metro Income Tax").
  A state plus a local/regional tax is NOT a multi-state return.
• "outcome" — decide per jurisdiction:
    – "no_tax": the letter says no tax is payable and reports no balance due, overpayment, or refund.
    – "balance_due": the letter states a balance due of $X.
    – "refund_or_credit": the letter states an overpayment and/or a refund.
    – "other": anything else (unusual arrangement you cannot classify) → explain in "other_note".
• "balance_due" (object, only when outcome = "balance_due", else null):
    – "amount": number (no $ or commas).
    – "payment_method":
        · "direct_debit" — letter says the balance will be withdrawn/debited from a bank account.
        · "mail_check"   — letter says to make/mail a check or money order and/or mail a payment
                           voucher (e.g. Form 1040-V).
        · "other"        — any other or unclear arrangement → explain in "other_note".
    – "withdrawal_date": MM/DD/YYYY when the letter gives an explicit calendar date next to the
      withdrawal phrase; null when it only says "once the return has been processed" or gives no date.
    – "due_date": MM/DD/YYYY for mail_check when the letter says "on or before {date}"; else null.
• "overpayment" (object, only when outcome = "refund_or_credit", else null):
    – "credited_next_year": amount applied/credited to next year's estimated tax (0 if none).
    – "refunded": amount refunded/deposited to the client's account (0 if none).
    CRITICAL: "Overpayment credited" (no money returned) ≠ "Refund deposited" (money returned).
    A split disposition sets both sides.
• "source_quote": verbatim sentence(s) that decided outcome + amounts.
• "other_note": one plain-English sentence describing the situation when outcome or
  payment_method is "other"; else null.

═══════════════════════════════════════════════════════════════════
SCHEDULED PAYMENTS — every FUTURE payment the letter mentions
═══════════════════════════════════════════════════════════════════
One entry per individual future payment, whether it appears in a payment schedule TABLE or in a
PROSE sentence, in letter order. Fields:

• "type":
    – "estimated": quarterly estimated tax payments or estimated fee installments.
    – "annual":    a fixed annual tax (e.g. "California Annual LLC Tax of $800").
    – "pte":       Pass-Through Entity Elective Tax payments.
    – "other":     a future payment that fits none of the above → describe in "note".
• "jurisdiction": "Federal" or the state name the payment belongs to.
• "amount": number. • "date": MM/DD/YYYY (normalize "4/15/26" → "04/15/2026", "1/15/27" → "01/15/2027").
• "payment_method":
    – "direct_debit": the letter says these payments will be withdrawn/debited from a bank account.
    – "mail_voucher": the letter directs mailing payments with vouchers as the payment method.
    – "unspecified": the letter does not state a single method (e.g. offers electronic OR mail).
  A sentence introducing a schedule applies its method to every row of that schedule.
• "ordinal": ONLY for pte, ONLY when the letter explicitly prints it ("1st"/"first" → "1st");
  otherwise null. NEVER infer an ordinal from the number of PTE entries.
• "source_quote": the verbatim sentence, or for a table row a compact quote of the row
  (e.g. "4/15/26 $ 2,800"). • "note": required description when type = "other"; else null.

Rules:
• A table row with amounts in two jurisdiction columns = TWO entries with the same date.
• A totals row of a schedule table is NOT a payment — never create an entry for it.
• An intro sentence that merely refers to the schedule ("...in accordance with the payment
  schedule below") is NOT an additional payment — never create a separate entry for it.
• PTE entries: only for S-Corporation (1120S) and Partnership (1065) returns, and only when the
  letter EXPLICITLY mentions a "Pass-Through Entity Elective Tax" payment with both an amount AND
  a date. For all other return types, never emit type "pte".

═══════════════════════════════════════════════════════════════════
NEGATIVE CONSTRAINTS — DO NOT
═══════════════════════════════════════════════════════════════════
✗ Fabricate any amount, date, jurisdiction, or PTE ordinal not present in the letter.
✗ Include ACA premium tax credit, depreciation, K-1 notices, or preparer instructions.
✗ Emit PTE entries for non-passthrough returns, or infer PTE from an unlabeled dollar figure.
✗ Turn schedule intro sentences or totals rows into payments.
✗ Paraphrase inside source_quote — it must be verbatim letter text.

═══════════════════════════════════════════════════════════════════
SELF-VERIFICATION (perform before final output)
═══════════════════════════════════════════════════════════════════
1. Every amount and date in my output appears literally in the letter. ✓
2. Every jurisdictions entry has exactly one outcome, matching object (balance_due XOR
   overpayment XOR neither), and a verbatim source_quote. ✓
3. Every future payment in the letter (table AND prose) has exactly one scheduled_payments
   entry; no entry exists for intro sentences or totals rows. ✓
4. All dates use MM/DD/YYYY. ✓
5. PTE eligibility and ordinal rules respected. ✓

═══════════════════════════════════════════════════════════════════
WORKED EXAMPLE 1 — Individual, Federal credit + State refund + Federal estimates (direct debit)
═══════════════════════════════════════════════════════════════════
LETTER EXCERPT:
  "CNY LLP ... Dear EXAMPLE CLIENT: Your 2025 Federal Individual Income Tax return ... No tax is
   payable with the filing of this return. There is an overpayment of $3,597, of which $3,597 has
   been applied to your 2026 estimated tax. Your 2025 California Individual Income Tax Return ...
   No tax is payable with the filing of this return. The refund of $2,052 will be directly
   deposited into your checking account. Your 2026 estimated tax payment schedule is listed below.
   Your Federal estimated tax payments will be directly withdrawn from your bank account in
   accordance with the IRS payment schedule. Due Date Federal 4/15/26 $10,000 6/15/26 10,000
   9/15/26 10,000 1/15/27 10,000 ---------- $40,000"

EXPECTED OUTPUT:
  {
    "client": {"name": "EXAMPLE CLIENT"},
    "cpa_firm": {"name": "CNY LLP", "sharefile_subdomain": "cnyllp"},
    "tax_year": "2025", "next_year": "2026", "return_type": "Individual (1040)",
    "jurisdictions": [
      {"jurisdiction_name": "Federal", "state_abbreviation": null, "display_label": null,
       "outcome": "refund_or_credit", "balance_due": null,
       "overpayment": {"credited_next_year": 3597, "refunded": 0},
       "source_quote": "There is an overpayment of $3,597, of which $3,597 has been applied to your 2026 estimated tax.",
       "other_note": null},
      {"jurisdiction_name": "California", "state_abbreviation": "CA", "display_label": null,
       "outcome": "refund_or_credit", "balance_due": null,
       "overpayment": {"credited_next_year": 0, "refunded": 2052},
       "source_quote": "The refund of $2,052 will be directly deposited into your checking account.",
       "other_note": null}
    ],
    "scheduled_payments": [
      {"type": "estimated", "jurisdiction": "Federal", "amount": 10000, "date": "04/15/2026",
       "payment_method": "direct_debit", "ordinal": null, "source_quote": "4/15/26 $10,000", "note": null},
      {"type": "estimated", "jurisdiction": "Federal", "amount": 10000, "date": "06/15/2026",
       "payment_method": "direct_debit", "ordinal": null, "source_quote": "6/15/26 10,000", "note": null},
      {"type": "estimated", "jurisdiction": "Federal", "amount": 10000, "date": "09/15/2026",
       "payment_method": "direct_debit", "ordinal": null, "source_quote": "9/15/26 10,000", "note": null},
      {"type": "estimated", "jurisdiction": "Federal", "amount": 10000, "date": "01/15/2027",
       "payment_method": "direct_debit", "ordinal": null, "source_quote": "1/15/27 10,000", "note": null}
    ]
  }

═══════════════════════════════════════════════════════════════════
WORKED EXAMPLE 2 — Individual, multi-state, withdrawal dates + estimates without a single method
═══════════════════════════════════════════════════════════════════
LETTER EXCERPT:
  "Your 2025 Federal Individual Income Tax return ... There is a balance due of $14,917. The
   balance due will be directly withdrawn from your bank account on April 15, 2026. Your 2025
   California Individual Income Tax Return ... There is a balance due of $29. The balance due will
   be directly withdrawn from your bank account on April 15, 2026. Your 2025 North Carolina
   Individual Income Tax Return ... No tax is payable with the filing of this return. The refund
   of $95 will be deposited directly into your bank account. Your 2026 estimated tax payment
   schedule is listed below. If not paying electronically, mail your payments to the address shown
   on your estimated tax payment vouchers. Due Date Federal North Carolina 4/15/26 $5,600 $500
   6/15/26 5,600 500"

EXPECTED OUTPUT:
  {
    "client": {"name": "EXAMPLE CLIENT"},
    "cpa_firm": {"name": "CNY LLP", "sharefile_subdomain": "cnyllp"},
    "tax_year": "2025", "next_year": "2026", "return_type": "Individual (1040)",
    "jurisdictions": [
      {"jurisdiction_name": "Federal", "state_abbreviation": null, "display_label": null,
       "outcome": "balance_due",
       "balance_due": {"amount": 14917, "payment_method": "direct_debit",
                       "withdrawal_date": "04/15/2026", "due_date": null},
       "overpayment": null,
       "source_quote": "There is a balance due of $14,917. The balance due will be directly withdrawn from your bank account on April 15, 2026.",
       "other_note": null},
      {"jurisdiction_name": "California", "state_abbreviation": "CA", "display_label": null,
       "outcome": "balance_due",
       "balance_due": {"amount": 29, "payment_method": "direct_debit",
                       "withdrawal_date": "04/15/2026", "due_date": null},
       "overpayment": null,
       "source_quote": "There is a balance due of $29. The balance due will be directly withdrawn from your bank account on April 15, 2026.",
       "other_note": null},
      {"jurisdiction_name": "North Carolina", "state_abbreviation": "NC", "display_label": null,
       "outcome": "refund_or_credit", "balance_due": null,
       "overpayment": {"credited_next_year": 0, "refunded": 95},
       "source_quote": "The refund of $95 will be deposited directly into your bank account.",
       "other_note": null}
    ],
    "scheduled_payments": [
      {"type": "estimated", "jurisdiction": "Federal", "amount": 5600, "date": "04/15/2026",
       "payment_method": "unspecified", "ordinal": null, "source_quote": "4/15/26 $5,600 $500", "note": null},
      {"type": "estimated", "jurisdiction": "North Carolina", "amount": 500, "date": "04/15/2026",
       "payment_method": "unspecified", "ordinal": null, "source_quote": "4/15/26 $5,600 $500", "note": null},
      {"type": "estimated", "jurisdiction": "Federal", "amount": 5600, "date": "06/15/2026",
       "payment_method": "unspecified", "ordinal": null, "source_quote": "6/15/26 5,600 500", "note": null},
      {"type": "estimated", "jurisdiction": "North Carolina", "amount": 500, "date": "06/15/2026",
       "payment_method": "unspecified", "ordinal": null, "source_quote": "6/15/26 5,600 500", "note": null}
    ]
  }

═══════════════════════════════════════════════════════════════════
WORKED EXAMPLE 3 — Individual, balance due paid by MAILED CHECK with 1040-V voucher
═══════════════════════════════════════════════════════════════════
LETTER EXCERPT:
  "Your 2025 Federal Individual Income Tax return will be electronically filed ... There is a
   balance due of $130,828. Make your check payable to the "United States Treasury" and mail your
   Form 1040-V payment voucher on or before August 26, 2026 to: INTERNAL REVENUE SERVICE ...
   Your 2025 California Individual Income Tax Return ... No tax is payable with the filing of
   this return."

EXPECTED OUTPUT:
  {
    "client": {"name": "EXAMPLE CLIENT"},
    "cpa_firm": {"name": "CNY LLP", "sharefile_subdomain": "cnyllp"},
    "tax_year": "2025", "next_year": "2026", "return_type": "Individual (1040)",
    "jurisdictions": [
      {"jurisdiction_name": "Federal", "state_abbreviation": null, "display_label": null,
       "outcome": "balance_due",
       "balance_due": {"amount": 130828, "payment_method": "mail_check",
                       "withdrawal_date": null, "due_date": "08/26/2026"},
       "overpayment": null,
       "source_quote": "There is a balance due of $130,828. Make your check payable to the \"United States Treasury\" and mail your Form 1040-V payment voucher on or before August 26, 2026",
       "other_note": null},
      {"jurisdiction_name": "California", "state_abbreviation": "CA", "display_label": null,
       "outcome": "no_tax", "balance_due": null, "overpayment": null,
       "source_quote": "No tax is payable with the filing of this return.",
       "other_note": null}
    ],
    "scheduled_payments": []
  }

═══════════════════════════════════════════════════════════════════
WORKED EXAMPLE 4 — S-Corporation: CA balance due (debit, no date), CA estimates table, PTE
═══════════════════════════════════════════════════════════════════
LETTER EXCERPT:
  "Your 2025 Federal S Corporation Income Tax return ... No tax is payable with the filing of this
   return. Your 2025 California S Corporation Income Tax Return ... There is a balance due of
   $1,341 which will be withdrawn from the taxpayer's bank account once the Franchise Tax Board
   has processed the return. Your 2026 California estimated tax payments will be directly
   withdrawn from your bank account in accordance with the payment schedule below. The 2026
   Pass-Through Entity Elective Tax Estimate balance due of $10,500 will be directly withdrawn
   from your bank account on June 15, 2026. Your estimated tax schedule for 2026 is listed below:
   Due Date California 4/15/26 $800 6/15/26 800 12/15/26 700 ---------- $2,300"

EXPECTED OUTPUT:
  {
    "client": {"name": "EXAMPLE CLIENT"},
    "cpa_firm": {"name": "CNY LLP", "sharefile_subdomain": "cnyllp"},
    "tax_year": "2025", "next_year": "2026", "return_type": "S-Corporation (1120S)",
    "jurisdictions": [
      {"jurisdiction_name": "Federal", "state_abbreviation": null, "display_label": null,
       "outcome": "no_tax", "balance_due": null, "overpayment": null,
       "source_quote": "No tax is payable with the filing of this return.",
       "other_note": null},
      {"jurisdiction_name": "California", "state_abbreviation": "CA", "display_label": null,
       "outcome": "balance_due",
       "balance_due": {"amount": 1341, "payment_method": "direct_debit",
                       "withdrawal_date": null, "due_date": null},
       "overpayment": null,
       "source_quote": "There is a balance due of $1,341 which will be withdrawn from the taxpayer's bank account once the Franchise Tax Board has processed the return.",
       "other_note": null}
    ],
    "scheduled_payments": [
      {"type": "estimated", "jurisdiction": "California", "amount": 800, "date": "04/15/2026",
       "payment_method": "direct_debit", "ordinal": null, "source_quote": "4/15/26 $800", "note": null},
      {"type": "estimated", "jurisdiction": "California", "amount": 800, "date": "06/15/2026",
       "payment_method": "direct_debit", "ordinal": null, "source_quote": "6/15/26 800", "note": null},
      {"type": "estimated", "jurisdiction": "California", "amount": 700, "date": "12/15/2026",
       "payment_method": "direct_debit", "ordinal": null, "source_quote": "12/15/26 700", "note": null},
      {"type": "pte", "jurisdiction": "California", "amount": 10500, "date": "06/15/2026",
       "payment_method": "direct_debit", "ordinal": null,
       "source_quote": "The 2026 Pass-Through Entity Elective Tax Estimate balance due of $10,500 will be directly withdrawn from your bank account on June 15, 2026.",
       "note": null}
    ]
  }

═══════════════════════════════════════════════════════════════════
WORKED EXAMPLE 5 — Partnership (LLC): ANNUAL tax + estimated fee stated in PROSE + PTE
═══════════════════════════════════════════════════════════════════
LETTER EXCERPT:
  "Your 2025 Federal Partnership Income Tax return ... No tax is payable with the filing of this
   return. Your 2025 California Partnership Income Tax Return ... No tax is payable with the
   filing of this return. Your 2026 California Annual LLC Tax of $800 will be directly withdrawn
   from your bank account on April 15, 2026. The 2026 California Estimated LLC Fee of $2,500 will
   be directly withdrawn from your bank account on June 15, 2026. The 2026 Pass-Through Entity
   Elective Tax Estimate of $10,500 will be directly withdrawn from your bank account on
   June 15, 2026."

EXPECTED OUTPUT:
  {
    "client": {"name": "EXAMPLE CLIENT"},
    "cpa_firm": {"name": "CNY LLP", "sharefile_subdomain": "cnyllp"},
    "tax_year": "2025", "next_year": "2026", "return_type": "Partnership (1065)",
    "jurisdictions": [
      {"jurisdiction_name": "Federal", "state_abbreviation": null, "display_label": null,
       "outcome": "no_tax", "balance_due": null, "overpayment": null,
       "source_quote": "No tax is payable with the filing of this return.",
       "other_note": null},
      {"jurisdiction_name": "California", "state_abbreviation": "CA", "display_label": null,
       "outcome": "no_tax", "balance_due": null, "overpayment": null,
       "source_quote": "No tax is payable with the filing of this return.",
       "other_note": null}
    ],
    "scheduled_payments": [
      {"type": "annual", "jurisdiction": "California", "amount": 800, "date": "04/15/2026",
       "payment_method": "direct_debit", "ordinal": null,
       "source_quote": "Your 2026 California Annual LLC Tax of $800 will be directly withdrawn from your bank account on April 15, 2026.",
       "note": null},
      {"type": "estimated", "jurisdiction": "California", "amount": 2500, "date": "06/15/2026",
       "payment_method": "direct_debit", "ordinal": null,
       "source_quote": "The 2026 California Estimated LLC Fee of $2,500 will be directly withdrawn from your bank account on June 15, 2026.",
       "note": null},
      {"type": "pte", "jurisdiction": "California", "amount": 10500, "date": "06/15/2026",
       "payment_method": "direct_debit", "ordinal": null,
       "source_quote": "The 2026 Pass-Through Entity Elective Tax Estimate of $10,500 will be directly withdrawn from your bank account on June 15, 2026.",
       "note": null}
    ]
  }

Return ONLY the JSON object — no markdown fences, no commentary.
```

- [ ] **Step 2: Sanity đọc lại**

Run: `grep -c "EXPECTED OUTPUT:" prompts/task2_email.txt`
Expected: `5`. Và `grep -c "P1a\|federal_sentence\|state_sentences" prompts/task2_email.txt` → `0`.

---

### Task 5: Viết lại `tests/test_task2_email_contract.py` — khóa prompt ↔ schema ↔ renderer

**Files:**
- Modify: `tests/test_task2_email_contract.py` (thay toàn bộ nội dung)

**Interfaces:**
- Consumes: `TASK2_RESPONSE_SCHEMA` (Task 3), prompt (Task 4), `summary_sentences` (Task 1), `facts_validation.validate_facts` (Task 2).

- [ ] **Step 1: Thay nội dung file** — GIỮ nguyên helper `_assert_matches_schema` và `_worked_example_outputs` hiện có (copy từ file cũ, không sửa logic), thay các test bằng:

```python
def test_schema_top_level_contract():
    props = set(TASK2_RESPONSE_SCHEMA["properties"])
    assert {"jurisdictions", "scheduled_payments"} <= props
    assert "tax_summary" not in props and "estimated_payments" not in props


def test_enums_are_not_nullable():
    def walk(schema, path="$"):
        if isinstance(schema, dict):
            if "enum" in schema:
                assert schema.get("nullable") is not True, path
            for key, child in schema.items():
                walk(child, f"{path}.{key}")
        elif isinstance(schema, list):
            for index, child in enumerate(schema):
                walk(child, f"{path}[{index}]")
    walk(TASK2_RESPONSE_SCHEMA)


def test_worked_examples_match_schema():
    prompt = PROMPT_PATH.read_text()
    examples = _worked_example_outputs(prompt)
    assert len(examples) == 5
    for index, example in enumerate(examples):
        _assert_matches_schema(example, TASK2_RESPONSE_SCHEMA, f"example[{index}]")


def test_worked_examples_cover_decision_space():
    examples = _worked_example_outputs(PROMPT_PATH.read_text())
    methods = {j["balance_due"]["payment_method"]
               for e in examples for j in e["jurisdictions"] if j["balance_due"]}
    assert {"direct_debit", "mail_check"} <= methods
    kinds = {p["type"] for e in examples for p in e["scheduled_payments"]}
    assert {"estimated", "annual", "pte"} <= kinds


def test_worked_examples_render_cleanly():
    """Mỗi example phải render trọn vẹn bằng renderer thật — không mục nào rơi vào van xả."""
    from jobs import summary_sentences as ss

    for example in _worked_example_outputs(PROMPT_PATH.read_text()):
        next_year = example["next_year"]
        for j in example["jurisdictions"]:
            assert ss.jurisdiction_sentence(j, next_year) is not None, j
        for e in example["scheduled_payments"]:
            if e["type"] != "estimated":
                assert ss.scheduled_sentence(e, next_year) is not None, e


def test_kramer_example_produces_p1c():
    from jobs import summary_sentences as ss

    examples = _worked_example_outputs(PROMPT_PATH.read_text())
    kramer_fed = examples[2]["jurisdictions"][0]
    sentence = ss.jurisdiction_sentence(kramer_fed, "2026")
    assert sentence == (
        "**Balance due** of **$130,828**, see the voucher on the ShareFile "
        "portal, due on or before **August 26, 2026**."
    )
```

Đầu file giữ imports: `import json`, `import re`, `from pathlib import Path`, `from schemas import TASK2_RESPONSE_SCHEMA`, `PROMPT_PATH = Path("prompts/task2_email.txt")`.

- [ ] **Step 2: Chạy contract tests**

Run: `venv/bin/python -m pytest tests/test_task2_email_contract.py -q`
Expected: PASS toàn bộ. Fail nào ở đây = prompt/schema/renderer lệch nhau — sửa NGUỒN lệch (thường là JSON example trong prompt), không nới test.

---

### Task 6: Viết lại `jobs/email_html.py` + `tests/test_email_rendering.py`

**Files:**
- Modify: `jobs/email_html.py`
- Modify: `tests/test_email_rendering.py` (thay fixtures shape cũ bằng facts; GIỮ nguyên intent từng test)

**Interfaces:**
- Consumes: toàn bộ API `summary_sentences` (Task 1), `resolve_tax_summary_labels` (giữ nguyên — adapter key: truyền `state_name = jurisdiction_name`), `INVOICE_BRAND_NAME`.
- Produces: `generate_email_html(data: dict) -> str` (chữ ký KHÔNG đổi — worker/pipeline/FE không biết gì thay đổi).

- [ ] **Step 1: Viết lại `tests/test_email_rendering.py` trước (TDD).** Fixture builders dùng chung:

```python
def _jur(name, abbr=None, label=None, outcome="no_tax", balance_due=None,
         overpayment=None, quote="q", note=None, **extra):
    return {"jurisdiction_name": name, "state_abbreviation": abbr,
            "display_label": label, "outcome": outcome,
            "balance_due": balance_due, "overpayment": overpayment,
            "source_quote": quote, "other_note": note, **extra}


def _sched(kind, jur, amount, date, method="direct_debit", ordinal=None, **extra):
    return {"type": kind, "jurisdiction": jur, "amount": amount, "date": date,
            "payment_method": method, "ordinal": ordinal,
            "source_quote": "q", "note": None, **extra}


def _data(jurisdictions, scheduled=(), return_type="Individual (1040)", firm=None):
    return {"client": {"name": "C"}, "cpa_firm": firm or {"name": "CNY LLP",
            "sharefile_subdomain": "cnyllp"}, "tax_year": "2025",
            "next_year": "2026", "return_type": return_type,
            "jurisdictions": list(jurisdictions),
            "scheduled_payments": list(scheduled)}
```

Mapping test cũ → mới (giữ nguyên tên test và assertion labels/escape, chỉ đổi fixture sang facts):
- `test_html_combines_cny_brand_and_correct_im_labels` → 3 jurisdiction Im-style: Federal refund 8647, Oregon refund 7447, OR Metro (label "OR Metro Income Tax") refund 349; assert các dòng `Federal Income Tax:`, `State Income Tax:`… như file cũ.
- 2 test firm-object + 1 firm-name (dòng 102–137): giữ nguyên logic, fixture `_data`.
- 2 test escape (139–183): display_label chứa HTML + quote chứa `<script>` trong review block — assert đã escape, `**bold**` thành `<strong>`.
- `test_html_single_state_and_true_multi_state_keep_legacy_labels`: 1 state → `State Income Tax:`; 2 states (CA+NC) → `CA State Income Tax:`/`NC State Income Tax:`.
- `test_html_accupuncture_estimates_and_pte_remain_unchanged` → fixture Trevor-style (Task 4 example 4) + `ordinal="1st"`; assert intro direct-debit, 3 dòng bảng, câu PTE `2026 1st PTE tax payment of <strong>$10,500</strong>…`.
- DOCX tests (275+) chuyển sang Task 7.

Thêm test MỚI (viết đầy đủ):

```python
def test_html_kramer_p1c_and_no_tax():
    data = _data([
        _jur("Federal", outcome="balance_due",
             balance_due={"amount": 130828, "payment_method": "mail_check",
                          "withdrawal_date": None, "due_date": "08/26/2026"}),
        _jur("California", abbr="CA"),
    ])
    html = generate_email_html(data)
    assert ("Federal Income Tax: <strong>Balance due</strong> of "
            "<strong>$130,828</strong>, see the voucher on the ShareFile "
            "portal, due on or before <strong>August 26, 2026</strong>.") in html
    assert "withdrawn from your account" not in html
    assert "State Income Tax: No tax is payable with the filing of this return." in html


def test_html_review_block_for_flagged_jurisdiction():
    data = _data([_jur("Federal", outcome="other",
                       note="Client must pay by money order",
                       quote="Mail a money order to...")])
    html = generate_email_html(data)
    assert "NEEDS REVIEW" in html and "Client must pay by money order" in html
    assert "Mail a money order to..." in html
    assert 'background:#fff3cd' in html


def test_html_house_style_estimates_neutral_intro():
    data = _data([_jur("Federal")],
                 [_sched("estimated", "Federal", 5600, "04/15/2026", method="unspecified"),
                  _sched("estimated", "North Carolina", 500, "04/15/2026", method="unspecified")])
    html = generate_email_html(data)
    assert "Federal and state estimated tax payments are due as shown below" in html
    assert "automatically withdrawn as shown below" not in html


def test_html_annual_prose_payment_rendered():
    data = _data([_jur("Federal")],
                 [_sched("annual", "California", 800, "04/15/2026")],
                 return_type="Partnership (1065)")
    html = generate_email_html(data)
    assert ("2026 California annual tax payment of <strong>$800</strong> will "
            "be automatically withdrawn on <strong>April 15, 2026</strong>.") in html
```

- [ ] **Step 2: Chạy, xác nhận fail**

Run: `venv/bin/python -m pytest tests/test_email_rendering.py -q`
Expected: FAIL hàng loạt (renderer còn shape cũ).

- [ ] **Step 3: Viết lại `generate_email_html`** — giữ khung email hiện tại (Dear Client / intro ShareFile / E-file para / heading Tax Payment Summary / heading năm sau / Instructions / closing, style inline y hệt), thay phần thân:

```python
from jobs import summary_sentences as ss

def _review_div(prefix: str, item: dict) -> str:
    body = escape(f"{prefix}{ss.review_note(item)}") if prefix else escape(ss.review_note(item))
    return ('<div style="background:#fff3cd;border:1px solid #e0a800;'
            'border-radius:4px;padding:8px 12px;margin:0 0 10px 0;">'
            f"{body}</div>")

# Trong generate_email_html(data):
jurisdictions = data.get("jurisdictions", []) or []
scheduled = data.get("scheduled_payments", []) or []
federal = next((j for j in jurisdictions if ss.is_federal(j.get("jurisdiction_name"))), None)
states = [j for j in jurisdictions if j is not federal]

# ── Current year ──
if federal is not None:
    sentence = ss.jurisdiction_sentence(federal, next_year)
    if sentence is None:
        lines.append(_review_div("Federal Income Tax: ", federal))
    else:
        lines.append(f'{p}Federal Income Tax: {_md_to_html(sentence)}</p>')
labels = resolve_tax_summary_labels(
    [{**j, "state_name": j.get("jurisdiction_name")} for j in states]
)
for j, label in zip(states, labels):
    sentence = ss.jurisdiction_sentence(j, next_year)
    if sentence is None:
        lines.append(_review_div(f"{label}: ", j))
    else:
        lines.append(f'{p}{escape(label)}: {_md_to_html(sentence)}</p>')

# ── Next year ──
est = ss.estimated_entries(scheduled)
others = [e for e in scheduled if e.get("type") != "estimated" or e.get("needs_review")]
if est or others:
    lines.append(f'<p style="margin:16px 0 8px 0;"><strong>{escaped_next_year} Tax Payment Summary</strong></p>')
if est:
    lines.append(f'{p}{escape(ss.estimated_intro(est))}</p>')
    rows = ss.estimated_rows(est)
    has_fed = any(r["federal"] for r in rows)
    has_state = any(r["state"] for r in rows)
    # bảng: header Payment Date / Federal? / State? + ss.format_amount cho ô ≠ 0, "—" cho 0
    # (giữ nguyên style td/th inline hiện tại)
for e in others:
    sentence = ss.scheduled_sentence(e, next_year)
    lines.append(_review_div("", e) if sentence is None
                 else f'{p}{_md_to_html(sentence)}</p>')
```

Xóa các phần của code cũ mà thay đổi này làm chết: đọc `tax_summary`/`estimated_payments`/`pte_payments`, import `PTE_ELIGIBLE_RETURN_TYPES` từ main nếu không còn dùng (gate đã nằm ở validation). KHÔNG sửa gì khác.

- [ ] **Step 4: Chạy test module + full suite trừ 2 file chưa port**

Run: `venv/bin/python -m pytest tests/test_email_rendering.py tests/test_summary_sentences.py tests/test_facts_validation.py tests/test_task2_email_contract.py tests/test_tax_labels.py -q`
Expected: PASS. (`test_main.py`, `tests/test_pipeline.py` sẽ xanh sau Task 7–8.)

---

### Task 7: `main.py` — PTE ordinal trên facts + DOCX render từ facts

**Files:**
- Modify: `main.py` — `apply_ftb_first_pte_ordinal` (dòng ~434–474), `generate_email_docx` (đọc kỹ dòng ~504–760 trước khi sửa), CLI `main()` (hook validate — xem Step 3)
- Modify: `test_main.py` (fixtures sang facts)

**Interfaces:**
- Consumes: `summary_sentences` (Task 1), `facts_validation` (Task 2), `_ftb_first_pte_evidence`/`_normalized_amount`/`_normalized_date` (GIỮ NGUYÊN — main.py:340–419).
- Produces: `apply_ftb_first_pte_ordinal(pdf_bytes, task2_data) -> dict` (chữ ký không đổi; nay set `ordinal="1st"` trên entry pte của `scheduled_payments`).

- [ ] **Step 1: Đọc trước** `main.py:504-760` (helpers DOCX + generate_email_docx + main()) — xác định helper markdown-bold→run hiện có (dùng lại y nguyên, không tự viết mới).

- [ ] **Step 2: Viết lại `apply_ftb_first_pte_ordinal`:**

```python
def apply_ftb_first_pte_ordinal(pdf_bytes, task2_data):
    """Set ordinal='1st' on the single PTE facts entry matching filled FTB Part IV evidence."""
    if not isinstance(task2_data, dict):
        return task2_data
    result = dict(task2_data)
    if result.get("return_type") not in PTE_ELIGIBLE_RETURN_TYPES:
        return result
    payments = result.get("scheduled_payments")
    if not isinstance(payments, list):
        return result
    pte_indexes = [
        index for index, entry in enumerate(payments)
        if isinstance(entry, dict) and entry.get("type") == "pte"
    ]
    if not pte_indexes:
        return result

    evidence = _ftb_first_pte_evidence(pdf_bytes)
    if len(evidence) != 1:
        return result
    expected_amount, expected_date = next(iter(evidence))

    matching = [
        index for index in pte_indexes
        if _normalized_amount(str(payments[index].get("amount"))) == expected_amount
        and _normalized_date(str(payments[index].get("date"))) == expected_date
    ]
    if len(matching) != 1:
        return result
    target = matching[0]
    if payments[target].get("ordinal"):
        return result
    updated = [dict(entry) if isinstance(entry, dict) else entry for entry in payments]
    updated[target]["ordinal"] = "1st"
    result["scheduled_payments"] = updated
    return result
```

Xóa `_pte_sentence_evidence` và `_PTE_NO_ORDINAL_RE` NẾU grep xác nhận không còn nơi nào dùng (`grep -rn "_pte_sentence_evidence\|_PTE_NO_ORDINAL_RE" --include="*.py" .`); regex/normalizer khác giữ nguyên.

- [ ] **Step 3: Port `generate_email_docx` + CLI.** Thân DOCX render đúng cấu trúc Task 6 (federal → states+labels → estimated intro+bảng → annual/pte sentences → review paragraphs), thay `<div>` vàng bằng paragraph text `review_note(item)` (bold). CLI `main()`: sau `call_gemini` Task 2 →

```python
from jobs.facts_validation import letter_text_from_pdf, validate_facts
# ...trong main(), sau khi có task2_data và cover_letter_bytes:
task2_data = validate_facts(task2_data, letter_text_from_pdf(cover_letter_bytes))
task2_data = apply_ftb_first_pte_ordinal(pdf_bytes, task2_data)
```

(import đặt đầu file; KHÔNG có vòng import vì `facts_validation` chỉ import `config.constants` — đã lo ở Task 2.)

- [ ] **Step 4: Cập nhật `test_main.py`** — mọi fixture `pte_payments=[{"sentence": ...}]` → `scheduled_payments=[_pte-facts]`; test ordinal: evidence khớp → `ordinal == "1st"`, evidence lệch/2 entry trùng → giữ `None`; test docx im/hong (từ test_email_rendering cũ dòng 275+) chuyển fixture facts, assertion text giữ nguyên intent.

- [ ] **Step 5: Chạy**

Run: `venv/bin/python -m pytest test_main.py tests/ -q --ignore=tests/test_pipeline.py`
Expected: PASS toàn bộ.

---

### Task 8: `jobs/pipeline.py` hook validation + cập nhật `tests/test_pipeline.py` — full suite xanh

**Files:**
- Modify: `jobs/pipeline.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `validate_facts`, `letter_text_from_pdf` (Task 2); `apply_ftb_first_pte_ordinal` (Task 7).
- Produces: `run_extraction` trả `analysis_data` có `needs_review` (bool) — worker lưu JSONB nguyên trạng, không đổi gì thêm.

- [ ] **Step 1: Sửa pipeline** — trong `run_extraction`, thay dòng `t2 = itr.apply_ftb_first_pte_ordinal(pdf_bytes, t2)` bằng:

```python
from jobs.facts_validation import letter_text_from_pdf, validate_facts
# ... (import đầu file)
t2 = validate_facts(t2, letter_text_from_pdf(cover_letter_bytes))
t2 = itr.apply_ftb_first_pte_ordinal(pdf_bytes, t2)
```

(Thứ tự: validate/dedup/gate TRƯỚC, ordinal SAU — ordinal chỉ chạy trên facts đã sạch.)

- [ ] **Step 2: Cập nhật `tests/test_pipeline.py`:**
  - Test 2 (`test_run_extraction_applies_full_pdf_pte_evidence_before_render`): fixture `task2_data` đổi `pte_payments` → `scheduled_payments: [{"type": "pte", "jurisdiction": "California", "amount": 1, "date": "06/15/2026", "payment_method": "direct_debit", "ordinal": None, "source_quote": "q", "note": None}]`; assertion `calls == [(full_pdf, task2_data)]` đổi thành:

```python
    assert calls[0][0] == full_pdf
    assert calls[0][1]["return_type"] == "S-Corporation (1120S)"
    assert calls[0][1]["needs_review"] is True  # letter bytes giả → verbatim check flag
```

  - Test 3 (CLI): fixture Task 2 tương tự (`scheduled_payments` thay `pte_payments`); assertion passthrough giữ nguyên.
  - Test 1 giữ nguyên (shape-agnostic).

- [ ] **Step 3: FULL suite**

Run: `venv/bin/python -m pytest -q`
Expected: PASS 100%. Đây là gate của toàn bộ phần code.

---

### Task 9: Regression local 8 samples + báo cáo diff — CHECKPOINT USER

**Files:**
- Create: `regression_out/compare_task2_regression.py`
- Create (output): `regression_out/after/*`, `regression_out/report.md`

- [ ] **Step 1: Viết script so sánh**

```python
# regression_out/compare_task2_regression.py
"""So sánh baseline vs after: diff text HTML đã normalize + chênh lệch tập số tiền.

Dùng: venv/bin/python regression_out/compare_task2_regression.py \
        regression_out/baseline regression_out/after regression_out/report.md
"""
import difflib
import pathlib
import re
import sys


def html_lines(path: pathlib.Path) -> list[str]:
    text = re.sub(r"<[^>]+>", "\n", path.read_text())
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return [line for line in lines if line]


def amounts(lines: list[str]) -> set[str]:
    return set(re.findall(r"\$[\d,]+(?:\.\d{2})?", " ".join(lines)))


def main() -> None:
    base, after, out = (pathlib.Path(a) for a in sys.argv[1:4])
    report: list[str] = ["# Task 2 facts — regression report\n"]
    for base_html in sorted(base.glob("*.html")):
        after_html = after / base_html.name
        report.append(f"\n{'=' * 80}\n## {base_html.stem}\n")
        if not after_html.exists():
            report.append("**MISSING** trong after/")
            continue
        old, new = html_lines(base_html), html_lines(after_html)
        diff = list(difflib.unified_diff(old, new, "baseline", "after", lineterm=""))
        report.append("(không có khác biệt text)" if not diff else "```diff\n" + "\n".join(diff) + "\n```")
        gone, added = amounts(old) - amounts(new), amounts(new) - amounts(old)
        if gone or added:
            report.append(f"\n**AMOUNTS** mất: {sorted(gone)} — thêm: {sorted(added)}")
        if any("NEEDS REVIEW" in line for line in new):
            report.append("\n**⚠️ CÓ REVIEW BLOCK** — theo catalog phải là 0 với 8 samples")
    out.write_text("\n".join(report))
    print(f"report: {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Chạy after + compare**

Run:
```bash
venv/bin/python regression_out/run_task2_regression.py regression_out/after
venv/bin/python regression_out/compare_task2_regression.py regression_out/baseline regression_out/after regression_out/report.md
```
Expected: 8 `done:` + report.md.

- [ ] **Step 3: Đối chiếu report với catalog diff chủ đích (spec §9.2):**
  - 2 file Kramer: federal → câu P1c (`see the voucher on the ShareFile portal, due on or before August 26, 2026`), KHÔNG còn "withdrawn from your account".
  - House: intro bảng → "…are due as shown below" (mất "automatically withdrawn").
  - Trevor + ACCUPUNCTURE: bảng estimate + câu PTE (Trevor có "1st") giữ nguyên ngữ nghĩa; KHÔNG double-count.
  - Hong/Im/Yamane: không khác biệt ngữ nghĩa (chấp nhận khác biệt thuần chính tả nếu baseline vốn lệch pattern — ghi chú lại từng chỗ).
  - Không file nào có "NEEDS REVIEW"; tập AMOUNTS không mất số nào.
  Bất kỳ diff ngoài catalog → DỪNG, điều tra (systematic-debugging), không sang Task 10.

- [ ] **Step 4: CHECKPOINT — trình report.md cho user duyệt. Chỉ tiếp tục khi user OK.**

---

### Task 10: Regression production (~7 job thật) — GATED, cần user cấp quyền SSH

> Mọi lệnh dưới đây cần user approve (phiên 28/08 classifier đã chặn SSH). PDF thật KHÔNG rời server. KHÔNG đụng `/opt/itr_extract` và DB (chỉ SELECT).

- [ ] **Step 0: Inventory read-only** (mở rộng `deploy/checklog.sh`): đếm job `done`, liệt kê `input.pdf` còn trên disk (`FILES_ROOT` từ `/etc/itr_extract/api.env`), xuất danh sách `<user_id>/<job_id>`.
- [ ] **Step 1: Đưa code lên chỗ tạm:** `rsync -a --exclude venv --exclude .git --exclude regression_out . ubuntu@35.174.254.48:/tmp/itr_facts_regression/` (dùng key `~/.ssh/CNY_Key.pem`).
- [ ] **Step 2: Chạy pipeline mới per job trên server** (script one-off đặt tại `/tmp/itr_facts_regression/prod_regression.py` — viết tại chỗ theo mẫu):

```python
# /tmp/itr_facts_regression/prod_regression.py — chạy TRÊN SERVER
# PYTHONPATH=/tmp/itr_facts_regression /opt/itr_extract/.venv/bin/python prod_regression.py <files_root>
# (nạp env: set -a; . /etc/itr_extract/worker.env; set +a  — TRƯỚC khi chạy)
import json, pathlib, sys
from jobs.pipeline import run_extraction

files_root = pathlib.Path(sys.argv[1])
out = pathlib.Path("/tmp/itr_facts_regression/prod_after"); out.mkdir(exist_ok=True)
for input_pdf in sorted(files_root.glob("*/*/input.pdf")):
    job_id = input_pdf.parent.name
    data, html, _ = run_extraction(input_pdf.read_bytes())
    (out / f"{job_id}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    (out / f"{job_id}.html").write_text(html)
    print("done:", job_id)
```

- [ ] **Step 3: So với output cũ trong DB:** export per-job `analysis_data`+`email_html` (psql `\copy` sang `/tmp/itr_facts_regression/prod_baseline/`), rồi chạy `compare_task2_regression.py` (copy lên cùng rsync) trên server cho từng cặp html.
- [ ] **Step 4: Đem về CHỈ report** (`scp .../report.md`), trình user: mỗi job phải PASS hoặc diff-chủ-đích theo catalog. FAIL ngoài catalog → dừng, điều tra.
- [ ] **Step 5: Dọn dẹp:** `rm -rf /tmp/itr_facts_regression` trên server; chạy `bash deploy/checklog.sh` xác nhận 5 services active. Bàn giao: user tự quyết commit + deploy (`deploy/deploy_tutorial.md` §2, nhớ checklist DEV_AUTH_BYPASS).

---

## Self-review đã thực hiện (2026-08-28)

- Spec coverage: §4→Task 3, §5→Task 1+6+7, §6→Task 2, §7→Task 4+5, §8→Task 6–8, §9.1→Task 1–8, §9.2→Task 0+9, §9.3→Task 10. Đủ.
- Type consistency: field names (`jurisdiction_name`, `credited_next_year`, `scheduled_payments`…) thống nhất Task 1↔2↔3↔4↔5↔6↔7↔8; chữ ký `generate_email_html(data)->str` và `apply_ftb_first_pte_ordinal(pdf_bytes, dict)->dict` không đổi so với callers.
- Wording: mọi chuỗi client-facing xuất hiện nguyên văn trong test Task 1/5/6 — không chỗ nào "viết câu tương tự".
