import json
import re
from pathlib import Path

from schemas import TASK2_RESPONSE_SCHEMA


PROMPT_PATH = Path("prompts/task2_email.txt")


def _state_item_schema():
    return (
        TASK2_RESPONSE_SCHEMA["properties"]["tax_summary"]["properties"]
        ["state_sentences"]["items"]
    )


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


def test_display_label_is_required_and_nullable():
    item = _state_item_schema()

    assert "display_label" in item["required"]
    assert item["properties"]["display_label"] == {
        "type": "STRING",
        "nullable": True,
    }


def test_prompt_defines_state_local_and_regional_jurisdictions():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert '"state_name": "string — full state, local, or regional jurisdiction name"' in prompt
    assert "host state's USPS" in prompt
    assert "local or regional" in prompt


def test_prompt_defines_display_label_rules_and_metro_example():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert '"display_label": "string|null' in prompt
    assert '"display_label": null' in prompt
    assert '"display_label": "OR Metro Income Tax"' in prompt
    assert "Ordinary state tax: set display_label to null" in prompt
    assert "A state plus a local or regional tax is not a multi-state return" in prompt


def test_all_worked_examples_follow_the_required_schema_contract():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    outputs = _worked_example_outputs(prompt)

    assert len(outputs) == 3
    for output in outputs:
        _assert_matches_schema(output, TASK2_RESPONSE_SCHEMA)

    ordinary_rows = [
        outputs[0]["tax_summary"]["state_sentences"][0],
        *outputs[1]["tax_summary"]["state_sentences"],
        outputs[2]["tax_summary"]["state_sentences"][0],
    ]
    assert all(row["display_label"] is None for row in ordinary_rows)
    assert outputs[2]["tax_summary"]["state_sentences"][1]["display_label"] == (
        "OR Metro Income Tax"
    )
