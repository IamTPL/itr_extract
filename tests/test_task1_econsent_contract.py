import json
import re
from pathlib import Path


PROMPT_PATH = Path("prompts/task1_econsent.txt")


def test_california_partnership_authorization_uses_official_8453_p_number():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "California: FTB 8453, FTB 8453-C, FTB 8453-P, FTB 8453-LLC" in prompt


def test_voucher_task_section_present():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "TASK B — PAYMENT VOUCHER PAGE IDENTIFICATION" in prompt


def test_voucher_catalog_federal_forms_present():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "1040-V" in prompt
    assert "1040-ES" in prompt


def test_voucher_catalog_california_forms_present():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    for form in ["FTB 3582", "540-ES", "FTB 3893", "FTB 3522", "FTB 3536"]:
        assert form in prompt, form


def test_voucher_catalog_new_york_forms_present():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "IT-201-V" in prompt
    assert "IT-2105" in prompt


def test_voucher_catalog_north_carolina_forms_present():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "D-400V" in prompt
    assert "NC-40" in prompt


def test_voucher_general_agency_rule_present():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert 'header/title containing: "payment voucher"' in prompt


def test_voucher_exclude_rules_present():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    # letter chỉ nhắc tên form
    assert "MENTION a" in prompt and "voucher form by name" in prompt
    # instructions/worksheet của preparer
    assert "Instructions or worksheet pages prepared for the preparer" in prompt
    # index / table of contents
    assert "Table of contents or form index pages that LIST voucher" in prompt
    # e-consent forms thuộc task A
    assert "E-consent / e-file authorization forms" in prompt
    assert "TASK A, not TASK B" in prompt
    # extension forms
    assert "Extension forms (Form 7004, Form 4868)" in prompt
    # Record of estimated tax payments
    assert '"Record of Estimated Tax Payments" pages' in prompt


def test_voucher_include_rules_present():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "official form number printed on the page" in prompt
    assert "pre-printed" in prompt and "payment amount" in prompt
    assert "ALL pages of a multi-page voucher" in prompt


def test_econsent_response_format_unchanged():
    """Phần JSON e-consent hiện có phải giữ nguyên, chỉ được nối thêm key mới."""
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    match = re.search(r"Return a single JSON object:\n\n(?P<body>\{.*\})\s*\Z", prompt, flags=re.DOTALL)
    assert match, "không tìm thấy block JSON response format"

    payload = json.loads(match.group("body"))
    assert payload["econsent_pages"] == [10, 26, 27]
    assert payload["econsent_forms"] == [
        {
            "form_number": "string",
            "title": "string",
            "pages": [10],
            "jurisdiction": "Federal or state-name",
        }
    ]


def test_response_format_includes_voucher_keys():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    match = re.search(r"Return a single JSON object:\n\n(?P<body>\{.*\})\s*\Z", prompt, flags=re.DOTALL)
    assert match, "không tìm thấy block JSON response format"

    payload = json.loads(match.group("body"))
    assert "voucher_pages" in payload
    assert isinstance(payload["voucher_pages"], list)

    assert "voucher_forms" in payload
    assert isinstance(payload["voucher_forms"], list)
    assert len(payload["voucher_forms"]) == 1

    voucher_form = payload["voucher_forms"][0]
    expected_fields = {
        "form_number",
        "title",
        "pages",
        "jurisdiction",
        "payment_type",
        "amount",
        "due_date",
    }
    assert expected_fields <= set(voucher_form)
