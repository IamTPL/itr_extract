# Email Presentation Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render Oregon Metro with the correct tax heading, preserve all ordinary state and multi-state behavior, and render the invoice phrase globally as `CNY invoice` in HTML and DOCX.

**Architecture:** Add one pure label resolver shared by both renderers. Extend Task 2 with required-nullable `display_label`, used only for local/regional taxes; ordinary state labels remain deterministic. Add one global `INVOICE_BRAND_NAME = "CNY"` constant used only in the introductory invoice phrase.

**Tech Stack:** Python 3.12, pytest, python-docx, Gemini structured response schema, HTML email rendering.

**Commit policy:** The user requested no commits during implementation. Keep specs, plan, tests, and code uncommitted for the user to commit after final verification.

---

## File Map

- Create `jobs/tax_labels.py`: pure normalization and label-resolution logic.
- Create `tests/test_tax_labels.py`: resolver edge cases and legacy compatibility.
- Create `tests/test_email_rendering.py`: HTML/DOCX golden and regression cases.
- Create `tests/test_task2_email_contract.py`: prompt/schema synchronization tests.
- Modify `config/constants.py`: global `INVOICE_BRAND_NAME` constant.
- Modify `jobs/email_html.py`: shared labels, label escaping, global CNY invoice phrase.
- Modify `main.py`: shared labels, global CNY invoice phrase, defensive `cpa_firm` normalization.
- Modify `schemas.py`: required-nullable `display_label`.
- Modify `prompts/task2_email.txt`: state/local/regional contract and worked examples.

### Task 1: Shared tax-label resolver

**Files:**
- Create: `tests/test_tax_labels.py`
- Create: `jobs/tax_labels.py`

- [ ] **Step 1: Write failing resolver tests**

```python
from jobs.tax_labels import resolve_tax_summary_labels


def test_resolves_state_plus_metro():
    rows = [
        {"state_name": "Oregon", "state_abbreviation": "OR", "display_label": None, "sentence": "state"},
        {
            "state_name": "Oregon Metro Supportive Housing Services",
            "state_abbreviation": "OR",
            "display_label": "OR Metro Income Tax",
            "sentence": "metro",
        },
    ]
    assert resolve_tax_summary_labels(rows) == ["State Income Tax", "OR Metro Income Tax"]


def test_legacy_single_state_stays_generic():
    rows = [{"state_name": "California", "state_abbreviation": "CA", "sentence": "refund"}]
    assert resolve_tax_summary_labels(rows) == ["State Income Tax"]


def test_explicit_state_label_is_supported_defensively():
    rows = [{"display_label": " State Income Tax: ", "sentence": "refund"}]
    assert resolve_tax_summary_labels(rows) == ["State Income Tax"]


def test_legacy_true_multi_state_stays_abbreviated():
    rows = [
        {"state_name": "California", "state_abbreviation": "CA", "sentence": "due"},
        {"state_name": "North Carolina", "state_abbreviation": "NC", "sentence": "refund"},
    ]
    assert resolve_tax_summary_labels(rows) == ["CA State Income Tax", "NC State Income Tax"]


def test_normalizes_explicit_label_and_falls_back_after_colon_only():
    rows = [
        {"state_name": "Metro", "state_abbreviation": "OR", "display_label": "  OR Metro Income Tax::  ", "sentence": "x"},
        {"state_name": "Oregon", "state_abbreviation": "OR", "display_label": " : ", "sentence": "y"},
    ]
    assert resolve_tax_summary_labels(rows) == ["OR Metro Income Tax", "State Income Tax"]


def test_invalid_labels_and_missing_names_use_safe_fallbacks():
    rows = [
        {"display_label": 123, "sentence": "x"},
        {"state_name": "", "state_abbreviation": None, "display_label": "", "sentence": "y"},
    ]
    assert resolve_tax_summary_labels(rows) == ["State Income Tax", "State Income Tax"]


def test_empty_sentence_row_still_participates_in_legacy_count():
    rows = [
        {"state_name": "California", "state_abbreviation": "CA", "sentence": "shown"},
        {"state_name": "North Carolina", "state_abbreviation": "NC", "sentence": ""},
    ]
    assert resolve_tax_summary_labels(rows) == ["CA State Income Tax", "NC State Income Tax"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `venv/bin/pytest tests/test_tax_labels.py -q`

Expected: collection error because `jobs.tax_labels` does not exist.

- [ ] **Step 3: Implement the pure resolver**

```python
"""Shared client-facing labels for non-federal tax-summary rows."""


def _normalize_display_label(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    label = value.strip()
    while label.endswith(":"):
        label = label[:-1].rstrip()
    return label or None


def _nonblank(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def resolve_tax_summary_labels(items: list[dict]) -> list[str]:
    explicit = [_normalize_display_label(item.get("display_label")) for item in items]
    ordinary_state_count = sum(label is None for label in explicit)
    labels: list[str] = []

    for item, display_label in zip(items, explicit):
        if display_label is not None:
            labels.append(display_label)
            continue
        if ordinary_state_count == 1:
            labels.append("State Income Tax")
            continue
        jurisdiction = (
            _nonblank(item.get("state_abbreviation"))
            or _nonblank(item.get("state_name"))
        )
        labels.append(f"{jurisdiction} State Income Tax" if jurisdiction else "State Income Tax")
    return labels
```

- [ ] **Step 4: Run resolver tests and verify GREEN**

Run: `venv/bin/pytest tests/test_tax_labels.py -q`

Expected: all resolver tests pass.

### Task 2: HTML rendering and global invoice brand

**Files:**
- Create: `tests/test_email_rendering.py`
- Modify: `config/constants.py`
- Modify: `jobs/email_html.py`

- [ ] **Step 1: Write failing HTML regression tests**

```python
import copy

import pytest
from docx import Document

from jobs.email_html import generate_email_html


def _base_data(firm_name="CNY LLP"):
    return {
        "cpa_firm": {"name": firm_name, "sharefile_subdomain": "cnyllp"},
        "tax_year": "2025",
        "return_type": "Individual (1040)",
        "tax_summary": {"federal_sentence": None, "state_sentences": []},
        "estimated_payments": [],
        "pte_payments": [],
    }


def _im_data():
    data = _base_data()
    data["tax_summary"] = {
        "federal_sentence": "No tax is payable. **Refund** of **$8,647**.",
        "state_sentences": [
            {
                "state_name": "Oregon",
                "state_abbreviation": "OR",
                "display_label": None,
                "sentence": "No tax is payable. **Refund** of **$7,447**.",
            },
            {
                "state_name": "Oregon Metro Supportive Housing Services",
                "state_abbreviation": "OR",
                "display_label": "OR Metro Income Tax",
                "sentence": "No tax is payable. **Refund** of **$349**.",
            },
        ],
    }
    return data


def test_html_combines_cny_brand_and_correct_im_labels():
    html = generate_email_html(_im_data())
    assert "Your 2025 Income Tax Return and CNY invoice are now available" in html
    assert "State Income Tax: No tax is payable" in html
    assert "OR Metro Income Tax: No tax is payable" in html
    assert "OR State Income Tax" not in html
    assert "Income Tax Income Tax" not in html
    assert "OR Metro Income Tax::" not in html
    assert "Enter &ldquo;cnyllp&rdquo; as the subdomain" in html


@pytest.mark.parametrize("firm", ["CNY LLP", "ABC LLP", None, ""])
def test_html_invoice_brand_is_global_and_does_not_mutate_input(firm):
    data = _base_data(firm)
    before = copy.deepcopy(data)
    html = generate_email_html(data)
    assert "Your 2025 Income Tax Return and CNY invoice are now available" in html
    assert "CNY LLP invoice" not in html
    assert "ABC LLP invoice" not in html
    assert "incoive" not in html
    assert data == before


@pytest.mark.parametrize("firm_value", ["missing", None])
def test_html_handles_missing_firm_object(firm_value):
    payload = _base_data()
    if firm_value == "missing":
        payload.pop("cpa_firm")
    else:
        payload["cpa_firm"] = None
    html = generate_email_html(payload)
    assert "CNY invoice" in html


def test_html_escapes_model_produced_display_label():
    data = _base_data()
    data["tax_summary"]["state_sentences"] = [{
        "state_name": "Local",
        "state_abbreviation": "OR",
        "display_label": "A&B <Local> Income Tax",
        "sentence": "**Refund** of **$1**.",
    }]
    html = generate_email_html(data)
    assert "A&amp;B &lt;Local&gt; Income Tax:" in html
    assert "A&B <Local> Income Tax:" not in html
```

- [ ] **Step 2: Run HTML tests and verify RED**

Run: `venv/bin/pytest tests/test_email_rendering.py -q -k html`

Expected: failures showing the old `CNY LLP invoice` and old `OR State Income Tax` labels.

- [ ] **Step 3: Add the global brand constant**

Append under a presentation section in `config/constants.py`:

```python
# ── Email presentation ──
INVOICE_BRAND_NAME = "CNY"
```

- [ ] **Step 4: Integrate the resolver and brand into HTML**

Update imports and the relevant blocks in `jobs/email_html.py`:

```python
from html import escape
import re

from config.constants import INVOICE_BRAND_NAME
from jobs.tax_labels import resolve_tax_summary_labels
from main import PTE_ELIGIBLE_RETURN_TYPES
```

```python
firm = data.get("cpa_firm", {}) or {}
# Remove firm_name; keep subdomain extraction unchanged.
```

```python
f'{p}Your {tax_year} Income Tax Return and {INVOICE_BRAND_NAME} invoice are now available '
```

```python
state_sentences = tax_summary.get("state_sentences", []) or []
state_labels = resolve_tax_summary_labels(state_sentences)
for st, label in zip(state_sentences, state_labels):
    sentence = st.get("sentence")
    if not sentence:
        continue
    lines.append(f'{p}{escape(label)}: {_md_to_html(sentence)}</p>')
```

- [ ] **Step 5: Run HTML tests and verify GREEN**

Run: `venv/bin/pytest tests/test_email_rendering.py -q -k html`

Expected: all HTML cases pass.

### Task 3: DOCX parity

**Files:**
- Modify: `tests/test_email_rendering.py`
- Modify: `main.py`

- [ ] **Step 1: Add failing DOCX parity tests**

Append to `tests/test_email_rendering.py`:

```python
def _docx_text(path):
    doc = Document(path)
    return "\n".join(paragraph.text for paragraph in doc.paragraphs)


def test_docx_combines_cny_brand_and_correct_im_labels(tmp_path):
    output = tmp_path / "im.docx"
    from main import generate_email_docx
    generate_email_docx(_im_data(), output)
    text = _docx_text(output)
    assert "Your 2025 Income Tax Return and CNY invoice are now available" in text
    assert "State Income Tax: No tax is payable" in text
    assert "OR Metro Income Tax: No tax is payable" in text
    assert "OR State Income Tax" not in text
    assert 'Enter "cnyllp" as the subdomain' in text


@pytest.mark.parametrize("firm", ["CNY LLP", "ABC LLP", None, ""])
def test_docx_invoice_brand_is_global(firm, tmp_path):
    output = tmp_path / "email.docx"
    data = _base_data(firm)
    before = copy.deepcopy(data)
    from main import generate_email_docx
    generate_email_docx(data, output)
    text = _docx_text(output)
    assert "CNY invoice" in text
    assert "CNY LLP invoice" not in text
    assert "ABC LLP invoice" not in text
    assert "incoive" not in text
    assert data == before


@pytest.mark.parametrize("firm_value", ["missing", None])
def test_docx_handles_missing_or_null_firm_object(firm_value, tmp_path):
    output = tmp_path / "email.docx"
    data = _base_data()
    if firm_value == "missing":
        data.pop("cpa_firm")
    else:
        data["cpa_firm"] = None
    from main import generate_email_docx
    generate_email_docx(data, output)
    assert "CNY invoice" in _docx_text(output)
```

- [ ] **Step 2: Run DOCX tests and verify RED**

Run: `venv/bin/pytest tests/test_email_rendering.py -q -k docx`

Expected: failures showing old labels/branding, and `cpa_firm=None` raising on `.get()`.

- [ ] **Step 3: Integrate shared behavior into DOCX**

Add imports to `main.py`:

```python
from config.constants import INVOICE_BRAND_NAME
from jobs.tax_labels import resolve_tax_summary_labels
```

Update `generate_email_docx`:

```python
firm = data.get("cpa_firm", {}) or {}
```

```python
f"Your {tax_year} Income Tax Return and {INVOICE_BRAND_NAME} invoice are now available "
```

```python
state_sentences = tax_summary.get("state_sentences", []) or []
state_labels = resolve_tax_summary_labels(state_sentences)
for st, label in zip(state_sentences, state_labels):
    sentence = st.get("sentence")
    if not sentence:
        continue
    _add_markdown_paragraph(doc, f"{label}: {sentence}", space_after=8)
```

- [ ] **Step 4: Run all rendering tests and verify GREEN**

Run: `venv/bin/pytest tests/test_tax_labels.py tests/test_email_rendering.py -q`

Expected: all resolver, HTML, and DOCX tests pass.

### Task 4: Task 2 prompt and response schema

**Files:**
- Create: `tests/test_task2_email_contract.py`
- Modify: `schemas.py`
- Modify: `prompts/task2_email.txt`

- [ ] **Step 1: Write failing schema/prompt contract tests**

```python
from pathlib import Path

from schemas import TASK2_RESPONSE_SCHEMA


def _state_item_schema():
    return TASK2_RESPONSE_SCHEMA["properties"]["tax_summary"]["properties"]["state_sentences"]["items"]


def test_display_label_is_required_and_nullable():
    item = _state_item_schema()
    assert "display_label" in item["required"]
    assert item["properties"]["display_label"] == {"type": "STRING", "nullable": True}


def test_prompt_covers_state_and_local_contract():
    prompt = Path("prompts/task2_email.txt").read_text(encoding="utf-8")
    assert '"display_label": "string|null' in prompt
    assert '"display_label": null' in prompt
    assert '"display_label": "OR Metro Income Tax"' in prompt
    assert "local or regional" in prompt
    assert "host state's USPS" in prompt
```

- [ ] **Step 2: Run contract tests and verify RED**

Run: `venv/bin/pytest tests/test_task2_email_contract.py -q`

Expected: schema and prompt assertions fail because `display_label` is absent.

- [ ] **Step 3: Extend the Gemini response schema**

In `schemas.py`, update the nested item:

```python
"required": ["state_name", "state_abbreviation", "display_label", "sentence"],
"properties": {
    "state_name": {"type": "STRING"},
    "state_abbreviation": {"type": "STRING"},
    "display_label": {"type": "STRING", "nullable": True},
    "sentence": {"type": "STRING"},
},
```

- [ ] **Step 4: Update the complete Task 2 prompt contract**

Make these exact contract changes in `prompts/task2_email.txt`:

```text
"state_name": "string — full state, local, or regional jurisdiction name",
"state_abbreviation": "string — USPS 2-letter code of the state, or host state for a local/regional tax",
"display_label": "string|null — null for an ordinary state tax; complete client-facing heading without a colon for local/regional tax (e.g. 'OR Metro Income Tax')",
```

Change “one sentence per jurisdiction” language to include Federal, state, local, and regional jurisdictions. Add this label rule:

```text
DISPLAY LABEL RULES
- Ordinary state tax: display_label = null.
- Local/regional tax: provide a concise complete heading, including “Income Tax” where applicable.
- Use the host state's USPS code in state_abbreviation.
- A state plus a local/regional tax is not a multi-state return.
- Never include a trailing colon in display_label.
```

Add `"display_label": null` to every ordinary-state object in both existing worked examples. Add an Oregon/Metro worked example whose two rows are:

```json
{"state_name": "Oregon", "state_abbreviation": "OR", "display_label": null, "sentence": "No tax is payable with the filing of this return. **Refund** of **$7,447** will be deposited to your account."},
{"state_name": "Oregon Metro Supportive Housing Services", "state_abbreviation": "OR", "display_label": "OR Metro Income Tax", "sentence": "No tax is payable with the filing of this return. **Refund** of **$349** will be deposited to your account."}
```

Extend self-verification to require the key on every row, require `null` for ordinary states, and reject labeling a local/regional row as state tax.

- [ ] **Step 5: Run schema/prompt and rendering tests**

Run: `venv/bin/pytest tests/test_task2_email_contract.py tests/test_tax_labels.py tests/test_email_rendering.py -q`

Expected: all focused tests pass.

### Task 5: Extraction smoke check and regression verification

**Files:**
- No code changes unless verification exposes a defect.

- [ ] **Step 1: Run Task 2 only against the three sample cover pages when a Gemini key is available**

Run:

```bash
venv/bin/python - <<'PY'
import json
from pathlib import Path
import main

api_key = main.load_api_key()
if not api_key:
    print("SKIP: GEMINI_API_KEY is not configured")
    raise SystemExit(0)

paths = [
    Path("samples/Im.pdf"),
    Path("samples/Hong, Jung.pdf"),
    Path("samples/ACCUPUNCTURE.pdf"),
]
for path in paths:
    result, _ = main.call_gemini(
        main.extract_page1_bytes(path),
        main.TASK2_PROMPT,
        main.TASK2_CONFIG,
        api_key,
        main.DEFAULT_MODEL,
        f"Task 2 smoke: {path.name}",
        main.TASK2_RESPONSE_SCHEMA,
    )
    print(path.name)
    print(json.dumps({
        "tax_summary": result.get("tax_summary"),
        "estimated_payments": result.get("estimated_payments"),
        "pte_payments": result.get("pte_payments"),
    }, indent=2))
PY
```

Expected:

- Im: Oregon `display_label=null`; Metro `display_label="OR Metro Income Tax"`; refunds remain `$8,647`, `$7,447`, `$349`.
- Hong: California `display_label=null`; refunds remain `$951`, `$297`.
- ACCUPUNCTURE: California `display_label=null`; estimates remain `$2,800`, `$3,800`, `$2,800`; PTE remains `$28,805`.

If no key is available, report the smoke check as skipped rather than fabricating a result.

- [ ] **Step 2: Run focused tests**

Run: `venv/bin/pytest tests/test_tax_labels.py tests/test_email_rendering.py tests/test_task2_email_contract.py -q`

Expected: all focused tests pass.

- [ ] **Step 3: Run the full suite**

Run: `venv/bin/pytest -q`

Expected baseline before this implementation was `32 passed, 2 failed`; the known unrelated failures were:

- `tests/test_auth_jwt.py::test_unknown_kid_rejected`
- `tests/test_jobs_retention.py::test_cap_evicts_oldest_when_exceeded`

Acceptance: no new failures, and all new focused tests pass. Report the two baseline failures separately if they remain.

- [ ] **Step 4: Inspect the final diff and leave it uncommitted**

Run:

```bash
git diff --check
git status --short
git diff -- config/constants.py jobs/tax_labels.py jobs/email_html.py main.py schemas.py prompts/task2_email.txt tests/
```

Expected: no whitespace errors; only intended code/test changes plus the user's pre-existing unrelated changes. Do not commit.
