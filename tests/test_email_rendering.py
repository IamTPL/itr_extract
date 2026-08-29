import copy
import re

import pytest

from jobs.email_html import generate_email_html


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


def _im_data():
    return _data([
        _jur("Federal", outcome="refund_or_credit", overpayment={"refunded": 8647}),
        _jur("Oregon", abbr="OR", outcome="refund_or_credit", overpayment={"refunded": 7447}),
        _jur("Oregon Metro Supportive Housing Services", abbr="OR",
             label="OR Metro Income Tax", outcome="refund_or_credit",
             overpayment={"refunded": 349}),
    ])


def test_html_combines_cny_brand_and_correct_im_labels():
    html = generate_email_html(_im_data())

    federal_line = (
        "Federal Income Tax: No tax is payable with the filing of this return. "
        "<strong>Refund</strong> of <strong>$8,647</strong> will be deposited to your account."
    )
    state_line = (
        "State Income Tax: No tax is payable with the filing of this return. "
        "<strong>Refund</strong> of <strong>$7,447</strong> will be deposited to your account."
    )
    metro_line = (
        "OR Metro Income Tax: No tax is payable with the filing of this return. "
        "<strong>Refund</strong> of <strong>$349</strong> will be deposited to your account."
    )

    assert "Your 2025 Income Tax Return and CNY invoice are now available" in html
    assert federal_line in html
    assert state_line in html
    assert metro_line in html
    assert html.index(federal_line) < html.index(state_line) < html.index(metro_line)
    assert "OR State Income Tax" not in html
    assert "Income Tax Income Tax" not in html
    assert "OR Metro Income Tax::" not in html
    assert "Enter &ldquo;cnyllp&rdquo; as the subdomain" in html


@pytest.mark.parametrize("firm", ["CNY LLP", "ABC LLP", None, ""])
def test_html_invoice_brand_is_global_and_does_not_mutate_input(firm):
    data = _data([], firm={"name": firm, "sharefile_subdomain": "cnyllp"})
    before = copy.deepcopy(data)

    html = generate_email_html(data)

    assert "Your 2025 Income Tax Return and CNY invoice are now available" in html
    assert "CNY LLP invoice" not in html
    assert "ABC LLP invoice" not in html
    assert "incoive" not in html
    assert data == before


@pytest.mark.parametrize("firm_value", ["missing", None])
def test_html_handles_missing_firm_object(firm_value):
    data = _data([])
    if firm_value == "missing":
        data.pop("cpa_firm")
    else:
        data["cpa_firm"] = None

    html = generate_email_html(data)

    assert "CNY invoice" in html
    assert "Enter the firm subdomain" in html


def test_html_handles_firm_object_without_name():
    data = _data([])
    data["cpa_firm"].pop("name")

    html = generate_email_html(data)

    assert "CNY invoice" in html
    assert "Enter &ldquo;cnyllp&rdquo; as the subdomain" in html


def test_html_escapes_model_produced_display_label():
    data = _data([
        _jur("Local", abbr="OR", label="A&B <Local> Income Tax",
             outcome="refund_or_credit", overpayment={"refunded": 1}),
    ])

    html = generate_email_html(data)

    assert "A&amp;B &lt;Local&gt; Income Tax:" in html
    assert "A&B <Local> Income Tax:" not in html


def test_html_escapes_all_dynamic_text_without_losing_markdown_bold():
    data = _data(
        [_jur("Federal", outcome="other", note="<svg onload=alert(3)>",
              quote="<script>alert(2)</script>")],
        [
            _sched("estimated", "Federal", 1, "<a href=evil>04/15/2026</a>", method="unspecified"),
            _sched("annual", "<script>alert(1)</script>&Co", 800, "04/15/2026"),
        ],
    )
    data["tax_year"] = "<img src=x onerror=alert(1)>"
    data["cpa_firm"]["sharefile_subdomain"] = "x</li><script>alert(2)</script>"

    html = generate_email_html(data)

    assert "<img" not in html
    assert "<script" not in html
    assert "<svg" not in html
    assert "<a href=evil" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "x&lt;/li&gt;&lt;script&gt;alert(2)&lt;/script&gt;" in html
    assert "&lt;svg onload=alert(3)&gt;" in html
    assert "&lt;a href=evil&gt;04/15/2026&lt;/a&gt;" in html
    # Same _md_to_html() call: escaping a malicious substring must not stop
    # an adjacent **bold** marker from still converting to <strong>. (tax_year
    # above is deliberately non-numeric, so next_year derives to "" here —
    # the assertion starts after that empty prefix rather than hardcoding it.)
    assert (
        "&lt;script&gt;alert(1)&lt;/script&gt;&amp;Co annual tax payment of "
        "<strong>$800</strong> will be automatically withdrawn on "
        "<strong>April 15, 2026</strong>."
    ) in html


def test_html_single_state_and_true_multi_state_keep_legacy_labels():
    single = _data([
        _jur("California", abbr="CA", outcome="refund_or_credit", overpayment={"refunded": 297}),
    ])
    multi = _data([
        _jur("California", abbr="CA", outcome="balance_due",
             balance_due={"amount": 29, "payment_method": "direct_debit",
                          "withdrawal_date": None, "due_date": None}),
        _jur("North Carolina", abbr="NC", outcome="refund_or_credit", overpayment={"refunded": 95}),
    ])

    single_html = generate_email_html(single)
    multi_html = generate_email_html(multi)

    assert "State Income Tax:" in single_html
    assert "CA State Income Tax:" not in single_html
    assert "CA State Income Tax:" in multi_html
    assert "NC State Income Tax:" in multi_html


def _accupuncture_data():
    return _data(
        [
            _jur("Federal"),
            _jur("California", abbr="CA", outcome="balance_due",
                 balance_due={"amount": 1341, "payment_method": "direct_debit",
                              "withdrawal_date": None, "due_date": None}),
        ],
        [
            _sched("estimated", "California", 800, "04/15/2026"),
            _sched("estimated", "California", 800, "06/15/2026"),
            _sched("estimated", "California", 700, "12/15/2026"),
            _sched("pte", "California", 10500, "06/15/2026", ordinal="1st"),
        ],
        return_type="S-Corporation (1120S)",
    )


def test_html_accupuncture_estimates_and_pte_remain_unchanged():
    html = generate_email_html(_accupuncture_data())

    assert "State Income Tax:" in html
    assert "will be automatically withdrawn as shown below" in html
    assert "$800" in html
    assert "$700" in html
    assert (
        "2026 1st PTE tax payment of <strong>$10,500</strong> will be "
        "automatically withdrawn on <strong>June 15, 2026</strong>."
    ) in html


def test_html_kramer_p1c_and_no_tax():
    data = _data([
        _jur("Federal", outcome="balance_due",
             balance_due={"amount": 130828, "payment_method": "mail_check",
                          "withdrawal_date": None, "due_date": "08/26/2026"}),
        _jur("California", abbr="CA"),
    ])
    html = generate_email_html(data)
    assert ("Federal Income Tax: <strong>Balance due</strong> of "
            "<strong>$130,828</strong>, see the voucher on the Client "
            "Portal, due on or before <strong>August 26, 2026</strong>.") in html
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


def test_html_zero_amount_schedule_rows_kept_with_dash():
    data = _data([_jur("Federal")],
                 [_sched("estimated", "Federal", 0, "04/15/2026"),
                  _sched("estimated", "Federal", 0, "06/15/2026"),
                  _sched("estimated", "Federal", 85015, "09/15/2026"),
                  _sched("estimated", "California", 12193, "09/15/2026")])
    html = generate_email_html(data)
    rows = re.findall(r"<tr>(.*?)</tr>", html, flags=re.S)
    row_0415 = next(r for r in rows if "04/15/2026" in r)
    row_0615 = next(r for r in rows if "06/15/2026" in r)
    row_0915 = next(r for r in rows if "09/15/2026" in r)
    assert row_0415.count(">—</td>") == 2
    assert row_0615.count(">—</td>") == 2
    assert ">$85,015</td>" in row_0915
    assert ">$12,193</td>" in row_0915


def test_html_overpayment_prints_stated_total():
    data = _data([_jur("Federal", outcome="refund_or_credit",
                       overpayment={"total": 67082, "credited_next_year": 64175, "refunded": 0})])
    html = generate_email_html(data)
    assert ("<strong>Overpayment</strong> of <strong>$67,082</strong> of which "
            "<strong>$64,175</strong> credited to 2026 tax.") in html
