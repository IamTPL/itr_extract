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
        "**Balance due** of **$130,828**, see the voucher on the Client "
        "Portal, due on or before **August 26, 2026**."
    )


def test_p1c_mail_check_without_due_date():
    assert ss.jurisdiction_sentence(_bd(500, "mail_check"), "2026") == (
        "**Balance due** of **$500**, see the voucher on the Client Portal."
    )


def test_balance_due_other_method_returns_none():
    assert ss.jurisdiction_sentence(_bd(500, "other"), "2026") is None


def _rc(credited, refunded, total=None):
    return {
        "jurisdiction_name": "Federal",
        "outcome": "refund_or_credit",
        "balance_due": None,
        "overpayment": {"total": total, "credited_next_year": credited, "refunded": refunded},
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


def test_p2_with_stated_total_greater_than_credited():
    assert ss.jurisdiction_sentence(_rc(64175, 0, total=67082), "2026") == (
        "No tax is payable with the filing of this return. **Overpayment** of "
        "**$67,082** of which **$64,175** credited to 2026 tax."
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
        '⚠️ NEEDS REVIEW — pay by money order. Letter says: "Mail a money order"'
    )
    assert ss.review_note({}) == (
        "⚠️ NEEDS REVIEW — Unrecognized case — please write this line manually."
    )


def test_review_note_uses_validation_note_before_fallback():
    assert ss.review_note({"validation_note": "Amount $423 was not found in the letter.",
                           "source_quote": "q"}) == (
        '⚠️ NEEDS REVIEW — Amount $423 was not found in the letter. Letter says: "q"'
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


def test_zero_amount_rows_survive_to_estimated_rows():
    scheduled = [_est("Federal", 0, "04/15/2026"),
                 _est("Federal", 0, "06/15/2026"),
                 _est("Federal", 85015, "09/15/2026")]
    entries = ss.estimated_entries(scheduled)
    assert len(entries) == 3
    assert ss.estimated_rows(entries) == [
        {"date": "04/15/2026", "federal": 0, "state": 0},
        {"date": "06/15/2026", "federal": 0, "state": 0},
        {"date": "09/15/2026", "federal": 85015, "state": 0},
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
