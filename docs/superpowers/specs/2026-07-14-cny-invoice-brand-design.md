# Global CNY Invoice Brand Design

## Goal

Render this exact introduction in every generated client email, regardless of the CPA firm name extracted from the uploaded PDF:

> Your 2025 Income Tax Return and CNY invoice are now available on the ShareFile portal.

The tax year remains dynamic. The fixed product-level invoice brand is exactly `CNY`, and the correctly spelled word is exactly `invoice`.

## Scope

This is a presentation-only rule for the introductory sentence in:

- production HTML email output;
- CLI-generated DOCX email output.

The extracted `cpa_firm.name` remains unchanged in `analysis_data`. It may still be used for metadata, diagnostics, and any behavior outside the invoice phrase. The ShareFile subdomain remains the separately extracted `cpa_firm.sharefile_subdomain`.

Both renderers normalize a missing or `null` `cpa_firm` object to an empty dictionary. This keeps the fixed invoice phrase renderable and preserves the existing fallback ShareFile instruction instead of allowing DOCX generation to fail on `.get()`.

## Considered Approaches

### 1. Global product constant — selected

Define `INVOICE_BRAND_NAME = "CNY"` once in `config/constants.py`. Both renderers use it only for the invoice phrase.

- Implements the requirement literally for every input firm.
- Deterministic and independent of Gemini output.
- Keeps HTML and DOCX aligned.
- Does not mutate extracted accounting or firm metadata.
- Requires no deployment environment change.

### 2. Exact-match override

Map only `CNY LLP` to `CNY` and preserve every other extracted firm name.

Rejected because the confirmed requirement is now global: every rendered email must say `CNY invoice`.

### 3. Gemini field or environment setting

Ask Gemini for an invoice brand or configure it per deployment.

Rejected because the value is a fixed product rule, not document data or an operational choice. Either alternative creates unnecessary variability and additional failure modes.

## Rendering Design

Add this centralized constant:

```python
INVOICE_BRAND_NAME = "CNY"
```

Update both introductory-sentence renderers to use it:

```text
Your {tax_year} Income Tax Return and {INVOICE_BRAND_NAME} invoice are now available on the ShareFile portal.
```

Do not rewrite, strip suffixes from, or replace `data["cpa_firm"]["name"]`. Do not change the prompt or Gemini response schema for this branding rule.

## Compatibility and Impact

Intentionally changed:

- `CNY LLP` input renders `CNY invoice`.
- `ABC LLP`, missing firm name, or any other input also renders `CNY invoice`.

Unchanged:

- tax year;
- `cpa_firm.name` and `cpa_firm.sharefile_subdomain` in extracted data;
- ShareFile instruction text and subdomain;
- tax-summary labels, sentences, amounts, estimates, and PTE payments;
- Task 1 e-consent selection;
- database and API schemas.

No database migration is required. As with the tax-label correction, successful historical jobs retain their already-materialized `email_html`; they change only after a new upload or a separately authorized backfill.

## Test Strategy

Add regression tests before implementation:

1. Parameterized HTML cases with `CNY LLP`, an unrelated firm, missing name, `null` name, empty name, missing `cpa_firm`, and `cpa_firm: null` all contain the exact introduction with `CNY invoice` and no extracted-name invoice phrase.
2. DOCX has the same parameterized behavior.
3. A combined Im regression contains `CNY invoice`, `State Income Tax`, and `OR Metro Income Tax` in both HTML and DOCX.
4. The rendered text never contains the misspelling `incoive`.
5. `cpa_firm.name` in the input dictionary is not mutated.
6. ShareFile subdomain rendering remains based on `cpa_firm.sharefile_subdomain`.

## Files in Scope

- `config/constants.py`
- `jobs/email_html.py`
- `main.py`
- focused HTML/DOCX regression tests

## Files and Behavior Out of Scope

- `prompts/task2_email.txt` and `schemas.py` for invoice branding
- changing extracted firm metadata
- database migrations or API response models
- production deployment or historical job mutation

## Relationship to the Tax-Label Correction

This is a separate presentation rule from the jurisdiction-label design in `2026-07-14-tax-jurisdiction-email-label-design.md`. They share the same HTML and DOCX renderers but have independent data contracts and tests. Implementation should complete the jurisdiction-label change first, then apply this fixed invoice-brand rule.
