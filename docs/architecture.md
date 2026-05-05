# ITR Task 2 (Client Email Data Extraction) — Refactor Design

**Date:** 2026-05-05
**Scope:** `scripts/tax-package/itr_packaging.py` — Task 2 (email data extraction)
**Status:** Approved for implementation

---

## 1. Problem Statement

### Bug 1 — Hardcoded 3-bucket English templates miss real business semantics

Current generator (`@scripts/tax-package/itr_packaging.py:466-506`) reduces Federal/State outcome to one of three fixed sentences:

```
if fed_bal > 0:    "Balance due of $X, ..."
elif fed_ref > 0:  "Refund of $X will be deposited ..."
else:              "No tax is payable with the filing of this return."
```

Real cover letters express richer disposition scenarios that this FSM cannot represent. Example from the Yamane 2025 ITR cover letter:

> *"No tax is payable with the filing of this return. There is an overpayment of $3,597, of which $3,597 has been applied to your 2026 estimated tax."*

Correct email output must be:

> **Federal Income Tax:** No tax is payable with the filing of this return. **Overpayment** of **$3,597** of which **$3,597** credited to 2026 tax.

The current logic misclassifies this as "Refund of $3,597 will be deposited into your account" because the existing AI schema only has `balance_due` / `refund` fields — no `overpayment` / `credited_to_next_year` distinction.

### Bug 2 — Phantom PTE line for non-passthrough returns

Output currently contains a PTE line (*"2026 1st PTE tax payment of $900 will be automatically withdrawn on April 15, 2026"*) even for Individual (1040) returns, which cannot have PTE elective tax. Root cause: AI is free to populate `pte_payments[]` for any return type, and the renderer only filters by `amount > 0`.

### Bug 3 — AI analyzes 50+ pages for Task 2 when only the cover letter matters

Task 2 needs information that lives **entirely on page 1** (transmittal letter). Sending the full PDF introduces noise — AI may confuse a $900 depreciation figure in a worksheet with a PTE payment, hallucinate jurisdictions, etc. It also costs ~6× more tokens than necessary.

---

## 2. Solution Overview

Refactor `itr_packaging.py` to:

1. **Split the single Gemini call into two focused calls:**
   - Call 1 (Task 1): full PDF → e-consent page detection (unchanged).
   - Call 2 (Task 2): **page 1 bytes only** → client email data extraction.

2. **Replace structured bucket fields with AI-authored sentences** (Approach A) guided by an explicit prompt that enumerates 5 business patterns + equivalent-wording normalization rules.

3. **Gate PTE at two layers:** prompt-level rule + code-level whitelist (`return_type ∈ {S-Corporation (1120S), Partnership (1065)}`).

4. **Render Markdown bold (`**...**`) to DOCX bold runs** via a small parser, so AI controls which keywords/amounts are emphasized.

5. **Externalize model config** into per-task dicts (`TASK1_CONFIG`, `TASK2_CONFIG`) with distinct temperature, thinking budget, and timeout.

---

## 3. Architecture

```
INPUT: <client> ITR 2025.pdf  (50+ pages)
   │
   ├──▶ CALL 1 (Task 1) — full PDF
   │       Gemini prompt: TASK1_PROMPT (e-consent detection only)
   │       Config: TASK1_CONFIG (thinking_budget=8192)
   │       Output: {econsent_pages, econsent_forms}
   │
   └──▶ pymupdf extract page 1 → bytes
           │
           ▼
         CALL 2 (Task 2) — page 1 only
           Gemini prompt: TASK2_PROMPT (client email extraction)
           Config: TASK2_CONFIG (thinking_budget=4096, timeout=90s)
           Output: {client, cpa_firm, tax_year, return_type, tax_summary, estimated_payments, pte_payments}

MERGE results → analysis_result.json → render Econsent.pdf + email_template.docx
```

Calls are **sequential**. Parallelization is out of scope for MVP.

---

## 4. Prompt Design — Task 2

### 4.1 Approach

**Approach A (AI-generated sentences)** — AI writes the final client-facing sentence for each jurisdiction following enumerated patterns. Python does not compose sentences; it only parses Markdown bold markers to produce DOCX bold runs.

This was chosen over Approach B (structured semantic components) because:
- After scoping to page 1, AI has full context for the letter's nuance.
- The letter's wording can mix patterns (overpayment + partial credit + partial refund) that a rigid schema would struggle to capture.
- Tested PASS on two real letters (Yamane, Trevor) — see §4.5.

### 4.2 Schema (new Task 2 output)

```json
{
  "client": { "name": "string" },
  "cpa_firm": {
    "name": "string",
    "sharefile_subdomain": "string — lowercase alphanumeric"
  },
  "tax_year":  "YYYY",
  "next_year": "YYYY",
  "return_type": "Individual (1040)" | "S-Corporation (1120S)" | "C-Corporation (1120)" | "Partnership (1065)" | "Trust/Estate (1041)" | "Non-Profit (990)",
  "tax_summary": {
    "federal_sentence": "string | null",
    "state_sentences": [
      { "state_name": "string", "sentence": "string" }
    ]
  },
  "estimated_payments": [
    { "date": "MM/DD/YYYY", "federal": 0, "state": 0, "state_name": "string|null" }
  ],
  "pte_payments": [
    { "sentence": "string" }
  ]
}
```

### 4.3 Five sentence patterns the prompt teaches

| ID | Case | Pattern |
|----|------|---------|
| P1 | Balance due | `**Balance due** of **$X**, which will be withdrawn from your account once your return has been processed.` |
| P2 | Overpayment fully credited | `No tax is payable with the filing of this return. **Overpayment** of **$X** of which **$X** credited to {next_year} tax.` |
| P3 | Refund fully deposited | `No tax is payable with the filing of this return. **Refund** of **$X** will be deposited to your account.` |
| P4 | Overpayment partial credit + partial refund | `No tax is payable with the filing of this return. **Overpayment** of **$X** of which **$Y** credited to {next_year} tax. **Refund** of **$Z** will be deposited to your account.` |
| P5 | Zero outcome | `No tax is payable with the filing of this return.` |

### 4.4 Normalization rules the prompt enforces

| Cover letter phrasing | Normalized to |
|----------------------|---------------|
| "has been applied to your {YYYY} estimated tax" | "credited to {next_year} tax" (P2/P4) |
| "directly deposited into your checking account" | "deposited to your account" (P3/P4) |
| "withdrawn from the taxpayer's bank account once the FTB has processed" | "withdrawn from your account once your return has been processed" (P1) |

### 4.5 PTE rules

**Eligibility gate:** `pte_payments` MUST be `[]` unless `return_type ∈ {S-Corporation (1120S), Partnership (1065)}`. Enforced in both prompt and code.

**Extraction rule:** Include a PTE entry only if the letter **explicitly** mentions "Pass-Through Entity Elective Tax" (or "PTE elective tax") with amount AND date. Do not infer from other figures.

**Sentence patterns** (AI uses Markdown bold):
- Single payment: `{next_year} PTE tax payment of **$X** will be automatically withdrawn on **{Month Day, Year}**.`
- Multiple payments: `{next_year} {Nth} PTE tax payment of **$X** will be automatically withdrawn on **{Month Day, Year}**.` where `{Nth}` ∈ {1st, 2nd, 3rd, 4th}.

**Critical:** Do NOT add ordinal "1st" if there is only one PTE payment.

### 4.6 Test results (performed during design phase)

Prompt v1 run against two real cover letters:

| Case | Expected behavior | Result |
|------|-------------------|--------|
| Yamane 1040 — Fed overpayment fully credited + CA refund | P2 federal + P3 state + empty pte | ✅ PASS |
| Trevor 1120S — Fed zero + CA balance due + 1 PTE payment $10,500/06-15-2026 | P5 federal + P1 state + 1 PTE no ordinal | ✅ PASS |

Token usage per Task 2 call: ~2,869 input + ~430 output + ~1,200 thinking ≈ **$0.004–0.006**.

---

## 5. Code Changes

### 5.1 New module-level constants

```python
TASK1_CONFIG = {"temperature": 0.0, "thinking_budget": 8192, "timeout_s": 180}
TASK2_CONFIG = {"temperature": 0.0, "thinking_budget": 4096, "timeout_s": 90}

PTE_ELIGIBLE_RETURN_TYPES = {"S-Corporation (1120S)", "Partnership (1065)"}

TASK1_PROMPT = """..."""   # split from current ANALYSIS_PROMPT — e-consent only
TASK2_PROMPT = """..."""   # new, already validated (see §4.3-4.6)
```

### 5.2 Generalize `call_gemini_api` → `call_gemini`

```python
def call_gemini(pdf_bytes: bytes, prompt: str, config: dict, api_key: str, model: str) -> tuple[dict, dict]:
    """Generic Gemini call — parameterized by prompt + config."""
```

Signature takes raw bytes (not path) so Task 2 can pass page-1 bytes extracted in memory.

### 5.3 New helper — extract page 1 bytes

```python
def extract_page1_bytes(pdf_path: str) -> bytes:
    src = fitz.open(pdf_path)
    out = fitz.open()
    out.insert_pdf(src, from_page=0, to_page=0)
    data = out.write()
    out.close(); src.close()
    return data
```

### 5.4 New main flow

```python
pdf_bytes = Path(pdf_path).read_bytes()
page1_bytes = extract_page1_bytes(pdf_path)

task1_result, t1_usage = call_gemini(pdf_bytes,  TASK1_PROMPT, TASK1_CONFIG, api_key, model)
task2_result, t2_usage = call_gemini(page1_bytes, TASK2_PROMPT, TASK2_CONFIG, api_key, model)

analysis_data = {**task2_result, **task1_result}   # merge
```

### 5.5 Markdown-bold DOCX parser

```python
def _add_markdown_paragraph(doc, text: str, size=11, space_after=4):
    """Render a sentence with **bold** segments into a DOCX paragraph."""
    para = doc.add_paragraph()
    for i, segment in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        run = para.add_run(segment)
        run.font.name = "Calibri"; run.font.size = Pt(size)
        run.font.bold = (i % 2 == 1)   # odd indices are bold
    para.paragraph_format.space_after = Pt(space_after)
    return para
```

### 5.6 `generate_email_docx` — rewritten sections

**Tax Payment Summary:**

```python
tax_summary = data.get("tax_summary", {})

fed_sentence = tax_summary.get("federal_sentence")
if fed_sentence:
    _add_markdown_paragraph(doc, f"Federal Income Tax: {fed_sentence}", space_after=4)

state_sentences = tax_summary.get("state_sentences", [])
for st in state_sentences:
    label = "State" if len(state_sentences) == 1 else st.get("state_name", "State")
    _add_markdown_paragraph(doc, f"{label} Income Tax: {st['sentence']}", space_after=8)
```

**PTE block with code-level guard:**

```python
pte_payments = data.get("pte_payments", []) if data.get("return_type") in PTE_ELIGIBLE_RETURN_TYPES else []
for pte in pte_payments:
    _add_markdown_paragraph(doc, pte["sentence"], space_after=8)
```

### 5.7 Remove dead code

Delete old fields no longer emitted by AI:
- `data["federal_tax"]`, `data["state_taxes"]`, `data.get("state_tax")` (legacy single-state)
- Hardcoded `if fed_bal > 0 / elif fed_ref > 0 / else` logic

Keep `_format_currency`, `_format_date_long` for estimated payment table (unchanged).

---

## 6. Testing Strategy

Manual verification against two checked-in sample PDFs:

1. `Yamane, Jon H & Gail ITR 2025.pdf` — expect:
   - Federal sentence matches P2 with `$3,597` twice
   - CA sentence matches P3 with `$2,052`
   - 4 Federal-only estimated payments
   - `pte_payments == []`
   - No "1st PTE" line in rendered DOCX

2. `Trevor K Holloway DDS Inc ITR 2025 Original.pdf` — expect:
   - Federal sentence = P5 zero outcome
   - CA sentence matches P1 with `$1,341`
   - 3 CA-only estimated payments
   - 1 PTE sentence, no "1st" ordinal, `$10,500` on `June 15, 2026`

3. Spot-check DOCX: confirm `**Overpayment**`, `**$3,597**`, `**Balance due**` render as bold runs (not literal asterisks).

Verification command:
```bash
python3 scripts/tax-package/itr_packaging.py "scripts/tax-package/Yamane, Jon H & Gail ITR 2025.pdf"
python3 scripts/tax-package/itr_packaging.py "scripts/tax-package/Trevor K Holloway DDS Inc ITR 2025 Original.pdf"
```

---

## 7. Out of Scope

- Parallelizing the two Gemini calls.
- Supporting cover letters on page 2+ (heuristic fallback) — revisit if a real case surfaces.
- Highlight color (yellow) on bold keywords — only bold is required for MVP.
- Multi-year or comparative summary.
- Letterhead reproduction in email DOCX.
- Refactor of Task 1 logic beyond splitting the prompt.
