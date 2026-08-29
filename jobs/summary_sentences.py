"""Facts → câu chuẩn CNY. Nguồn wording DUY NHẤT cho email HTML và DOCX.

Mọi hàm đều pure: dict facts vào, chuỗi markdown ra (**bold** được tầng render
đổi thành <strong>/bold-run). Trả về None nghĩa là "không có câu an toàn" —
caller phải chèn review block (review_note) thay vì đoán.
"""
from datetime import datetime

# Chờ client chốt wording cuối ("ShareFile portal" vs "Client Portal") — đổi 1 dòng này.
P1C_PORTAL_PHRASE = "see the voucher on the Client Portal"

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
        or item.get("validation_note")
        or "Unrecognized case — please write this line manually."
    )
    note_text = note[:-1] if note.endswith(".") else note
    text = f"⚠️ NEEDS REVIEW — {note_text}."
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
        stated_total = op.get("total")
        total = format_amount(stated_total if stated_total else credited + refunded)
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
