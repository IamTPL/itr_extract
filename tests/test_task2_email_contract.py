import json
import re
from pathlib import Path

from schemas import TASK2_RESPONSE_SCHEMA


PROMPT_PATH = Path("prompts/task2_email.txt")


def _worked_example_outputs(prompt):
    blocks = re.findall(
        r"EXPECTED OUTPUT:\n(?P<body>  \{.*?^  \})",
        prompt,
        flags=re.DOTALL | re.MULTILINE,
    )
    return [json.loads(block) for block in blocks]


def _assert_matches_schema(value, schema, path="$"):
    if value is None:
        assert schema.get("nullable") is True, f"{path} is unexpectedly null"
        return

    schema_type = schema["type"]
    expected_types = {
        "STRING": (str,),
        "NUMBER": (int, float),
        "INTEGER": (int,),
        "BOOLEAN": (bool,),
        "ARRAY": (list,),
        "OBJECT": (dict,),
    }[schema_type]
    assert isinstance(value, expected_types), f"{path} does not match {schema_type}"
    if schema_type in {"NUMBER", "INTEGER"}:
        assert not isinstance(value, bool), f"{path} must not use a boolean as a number"
    if "enum" in schema:
        assert value in schema["enum"], f"{path} is outside the allowed enum"

    if schema_type == "OBJECT":
        properties = schema.get("properties", {})
        assert set(schema.get("required", [])) <= set(value), f"{path} is missing required keys"
        assert set(value) <= set(properties), f"{path} contains undeclared keys"
        for key, child in value.items():
            _assert_matches_schema(child, properties[key], f"{path}.{key}")
    elif schema_type == "ARRAY":
        for index, child in enumerate(value):
            _assert_matches_schema(child, schema["items"], f"{path}[{index}]")


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
    assert len(examples) == 7
    for index, example in enumerate(examples):
        _assert_matches_schema(example, TASK2_RESPONSE_SCHEMA, f"example[{index}]")


def test_worked_examples_cover_decision_space():
    examples = _worked_example_outputs(PROMPT_PATH.read_text())
    methods = {j["balance_due"]["payment_method"]
               for e in examples for j in e["jurisdictions"] if j["balance_due"]}
    assert {"direct_debit", "mail_check"} <= methods
    kinds = {p["type"] for e in examples for p in e["scheduled_payments"]}
    assert {"estimated", "annual", "pte"} <= kinds
    sched_methods = {p["payment_method"] for e in examples for p in e["scheduled_payments"]}
    assert {"direct_debit", "unspecified", "electronic"} <= sched_methods
    labels = {j.get("display_label") for e in examples for j in e["jurisdictions"]}
    assert "CA LLC Income Tax" in labels
    assert any(p["type"] == "annual" for e in examples for p in e["scheduled_payments"])
    assert any(((j.get("overpayment") or {}).get("total") or 0) >
               ((j.get("overpayment") or {}).get("credited_next_year", 0) +
                (j.get("overpayment") or {}).get("refunded", 0))
               for e in examples for j in e["jurisdictions"] if j.get("overpayment"))


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


def test_dr_sam_example_produces_electronic_pte_sentence():
    """Wording client chốt 2026-09-04 (Marlene) — PTE tự trả điện tử qua Web Pay."""
    from jobs import summary_sentences as ss

    examples = _worked_example_outputs(PROMPT_PATH.read_text())
    pte = examples[6]["scheduled_payments"][0]
    assert ss.scheduled_sentence(pte, examples[6]["next_year"]) == (
        "2026 PTE tax payment of **$3,500** is due on or before "
        "**June 15, 2026** and must be paid electronically."
    )


def test_kramer_example_produces_p1c():
    from jobs import summary_sentences as ss

    examples = _worked_example_outputs(PROMPT_PATH.read_text())
    kramer_fed = examples[2]["jurisdictions"][0]
    sentence = ss.jurisdiction_sentence(kramer_fed, "2026")
    assert sentence == (
        "**Balance due** of **$130,828**, see the voucher on the Client "
        "Portal, due on or before **August 26, 2026**."
    )
