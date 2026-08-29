import fitz

from jobs import facts_validation as fv

LETTER_TEXT = (
    "There is a balance due of $130,828. Make your check payable and mail your "
    "Form 1040-V payment voucher on or before August 26, 2026. "
    "The 2026 Pass-Through Entity Elective Tax Estimate balance due of $10,500 "
    "will be directly withdrawn from your bank account on June 15, 2026. "
    "Due Date California 4/15/26 $ 2,800 refund of $951"
    " There is an overpayment of $67,082, of which $64,175 has been applied to "
    "your 2026 estimated tax. 4/15/26 $ 0"
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


def test_overpayment_total_verbatim_and_note():
    ok = _jur(outcome="refund_or_credit", balance_due=None,
              overpayment={"total": 67082, "credited_next_year": 64175, "refunded": 0})
    out = fv.validate_facts(_analysis([ok]), LETTER_TEXT)
    assert "needs_review" not in out["jurisdictions"][0]

    fabricated = _jur(outcome="refund_or_credit", balance_due=None,
                      overpayment={"total": 67082, "credited_next_year": 64175, "refunded": 2907})
    out = fv.validate_facts(_analysis([fabricated]), LETTER_TEXT)
    assert out["jurisdictions"][0]["needs_review"] is True
    assert out["jurisdictions"][0]["validation_note"] == (
        "Amount $2,907 was not found in the letter."
    )


def test_overpayment_total_not_in_letter_is_flagged():
    hallucinated = _jur(outcome="refund_or_credit", balance_due=None,
                        overpayment={"total": 99999, "credited_next_year": 64175, "refunded": 0})
    out = fv.validate_facts(_analysis([hallucinated]), LETTER_TEXT)
    assert out["jurisdictions"][0]["needs_review"] is True
    assert out["jurisdictions"][0]["validation_note"] == (
        "Amount $99,999 was not found in the letter."
    )


def test_non_numeric_overpayment_amount_flags_instead_of_crashing():
    for op in ({"total": "67082", "credited_next_year": 64175, "refunded": 0},
               {"total": None, "credited_next_year": "64175", "refunded": 0}):
        j = _jur(outcome="refund_or_credit", balance_due=None, overpayment=op)
        out = fv.validate_facts(_analysis([j]), LETTER_TEXT)
        assert out["jurisdictions"][0]["needs_review"] is True
        assert out["jurisdictions"][0]["validation_note"] == (
            "An extracted overpayment amount is not a number."
        )


def test_overpayment_total_less_than_parts_is_flagged():
    bad = _jur(outcome="refund_or_credit", balance_due=None,
               overpayment={"total": 951, "credited_next_year": 951, "refunded": 951})
    out = fv.validate_facts(_analysis([bad]), LETTER_TEXT)
    assert out["jurisdictions"][0]["needs_review"] is True


def test_zero_amount_row_passes_without_verbatim_match():
    e = _pte(amount=0, date="04/15/2026", type="estimated")
    out = fv.validate_facts(_analysis(scheduled=[e]), LETTER_TEXT)
    assert "needs_review" not in out["scheduled_payments"][0]


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


def test_amount_boundary_rejects_substring_of_larger_number():
    letter = "There is a balance due of $2,800."
    j = _jur(balance_due={"amount": 800, "payment_method": "direct_debit",
                          "withdrawal_date": None, "due_date": None})
    out = fv.validate_facts(_analysis([j]), letter)
    assert out["jurisdictions"][0]["needs_review"] is True


def test_amount_boundary_accepts_exact_number_with_punctuation():
    letter = "There is a balance due of $800."
    j = _jur(balance_due={"amount": 800, "payment_method": "direct_debit",
                          "withdrawal_date": None, "due_date": None})
    out = fv.validate_facts(_analysis([j]), letter)
    assert "needs_review" not in out["jurisdictions"][0]
    assert out["needs_review"] is False


def test_letter_text_from_pdf_roundtrip_and_garbage():
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "hello letter")
    text = fv.letter_text_from_pdf(doc.write())
    doc.close()
    assert "hello letter" in text
    assert fv.letter_text_from_pdf(b"not-a-pdf") == ""
