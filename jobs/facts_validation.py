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


def _valid_amount_boundary(text: str, start: int, end: int) -> bool:
    """True nếu match [start:end) không phải là substring của số lớn hơn."""
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    if before in "0123456789,":
        return False
    if before == "." and start > 1 and text[start - 2].isdigit():
        return False  # part thập phân, vd "50" trong "800.50"
    if after.isdigit():
        return False
    if after in ".," and end + 1 < len(text) and text[end + 1].isdigit():
        return False  # vd "800" trong "800,000" hoặc "2" trong "2.800"
    return True


def _amount_in_text(amount, text: str) -> bool:
    try:
        number = float(amount)
    except (TypeError, ValueError):
        return False
    candidates = {f"{number:,.0f}", f"{number:,.2f}", f"{number:.0f}", f"{number:.2f}"}
    for candidate in candidates:
        start = 0
        while True:
            idx = text.find(candidate, start)
            if idx == -1:
                break
            if _valid_amount_boundary(text, idx, idx + len(candidate)):
                return True
            start = idx + 1
    return False


def _amount_reason(value) -> str:
    try:
        return f"Amount ${float(value):,.0f} was not found in the letter."
    except (TypeError, ValueError):
        return "An extracted amount was not found in the letter."


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


def _jurisdiction_needs_review(j: dict, text: str) -> str | None:
    outcome = j.get("outcome")
    if outcome not in _VALID_OUTCOMES:
        return "Unrecognized outcome."
    if outcome == "no_tax":
        return None
    if outcome == "balance_due":
        bd = j.get("balance_due")
        if not isinstance(bd, dict) or bd.get("amount") is None:
            return "Balance-due details are missing."
        if bd.get("payment_method") not in ("direct_debit", "mail_check"):
            return "Unrecognized payment method."
        if not _amount_in_text(bd["amount"], text):
            return _amount_reason(bd["amount"])
        for key in ("withdrawal_date", "due_date"):
            value = bd.get(key)
            if value and not _date_in_text(value, text):
                return f"Date {value} was not found in the letter."
        return None
    op = j.get("overpayment")  # refund_or_credit
    if not isinstance(op, dict):
        return "Overpayment details are missing."
    credited = op.get("credited_next_year") or 0
    refunded = op.get("refunded") or 0
    total = op.get("total")
    for value in (credited, refunded, total):
        if value is not None and not isinstance(value, (int, float)):
            return "An extracted overpayment amount is not a number."
    if credited <= 0 and refunded <= 0:
        return "No credited or refunded amount was extracted."
    for value in (credited, refunded):
        if value > 0 and not _amount_in_text(value, text):
            return _amount_reason(value)
    if total:
        if not _amount_in_text(total, text):
            return _amount_reason(total)
        if total < credited + refunded:
            return "Stated overpayment total is less than credited plus refunded."
    return None


def _scheduled_needs_review(e: dict, text: str) -> str | None:
    if e.get("type") not in _VALID_SCHEDULED_TYPES:
        return "Unrecognized payment type."
    amount = e.get("amount")
    if amount is None or not e.get("date"):
        return "Amount or date is missing."
    if amount and not _amount_in_text(amount, text):
        return _amount_reason(amount)
    if not _date_in_text(e["date"], text):
        return f"Date {e['date']} was not found in the letter."
    return None


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
        reason = _jurisdiction_needs_review(j, letter_text)
        if reason:
            j["needs_review"] = True
            j["validation_note"] = reason
            flagged = True
        jurisdictions.append(j)
    result["jurisdictions"] = jurisdictions

    scheduled = [dict(e) for e in result.get("scheduled_payments") or []
                 if isinstance(e, dict)]
    if result.get("return_type") not in PTE_ELIGIBLE_RETURN_TYPES:
        scheduled = [e for e in scheduled if e.get("type") != "pte"]
    scheduled = _dedup_scheduled(scheduled)
    for e in scheduled:
        reason = _scheduled_needs_review(e, letter_text)
        if reason:
            e["needs_review"] = True
            e["validation_note"] = reason
            flagged = True
    result["scheduled_payments"] = scheduled

    result["needs_review"] = flagged
    return result
