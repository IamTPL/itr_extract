# Tax Jurisdiction Email Label Design

## Goal

Render tax-summary headings exactly as the CPA firm expects when one return contains both a state tax and a local or regional tax, without changing tax amounts, summary sentences, estimated payments, PTE payments, or e-consent extraction.

The confirmed output for `samples/Im.pdf` is:

- `Federal Income Tax` — refund `$8,647`
- `State Income Tax` — Oregon refund `$7,447`
- `OR Metro Income Tax` — Metro SHS refund `$349`

The change in this document is limited to tax-summary display labels. The independently approved global `CNY invoice` rule is specified in `2026-07-14-cny-invoice-brand-design.md`.

## Problem

Task 2 currently stores all non-federal summaries in `tax_summary.state_sentences`. Both HTML and DOCX renderers infer whether a return is multi-state from `len(state_sentences) > 1`.

For `Im.pdf`, Task 2 correctly extracts two different jurisdictions:

1. Oregon state income tax, with abbreviation `OR`.
2. Oregon Metro Supportive Housing Services Personal Income Tax, also with abbreviation `OR`.

The renderer therefore treats the return as multi-state and emits `OR State Income Tax` for both rows. The amounts and sentences are correct; only the headings are wrong.

## Considered Approaches

### 1. Hard-code Oregon Metro in the renderers

Detect `Metro Supportive Housing Services` in `state_name` and emit `OR Metro Income Tax`.

- Smallest immediate patch.
- Duplicates business rules in HTML and DOCX.
- Does not generalize to city, county, or other regional taxes.
- Still requires special handling so the ordinary Oregon row remains `State Income Tax`.

Rejected because it is brittle and likely to create similar defects for future local jurisdictions.

### 2. Add an explicit `display_label` with a legacy fallback

Task 2 provides an explicit client-facing heading only for non-state local or regional rows. Ordinary state rows use `null`, so their headings remain code-generated exactly as before. A shared resolver returns an explicit heading when present and reproduces the current state-rendering behavior when it is absent.

- Produces the exact client-confirmed wording.
- Keeps old JSON payloads readable.
- Avoids database and API migrations.
- Centralizes HTML/DOCX behavior.
- Requires a coordinated prompt and Gemini response-schema update.

This is the selected approach.

### 3. Replace `state_sentences` with a full jurisdiction model

Introduce fields such as `jurisdiction_type`, `jurisdiction_name`, and `jurisdiction_abbreviation`, then derive headings in code.

- Stronger domain model for future analytics.
- Wider migration and compatibility surface than this presentation defect requires.
- Still needs a display-name rule for arbitrary local jurisdictions.

Rejected for this change as unnecessary scope.

## Data Contract

Keep the existing `tax_summary.state_sentences` key for compatibility and add one required-but-nullable field to each item. An ordinary state row uses `null`:

```json
{
  "state_name": "Oregon",
  "state_abbreviation": "OR",
  "display_label": null,
  "sentence": "No tax is payable with the filing of this return. **Refund** of **$7,447** will be deposited to your account."
}
```

A local or regional row supplies the complete heading:

```json
{
  "state_name": "Oregon Metro Supportive Housing Services",
  "state_abbreviation": "OR",
  "display_label": "OR Metro Income Tax",
  "sentence": "No tax is payable with the filing of this return. **Refund** of **$349** will be deposited to your account."
}
```

When non-null, `display_label` is the complete heading without a trailing colon. It includes `Income Tax` where applicable; renderers must not append another `Income Tax` suffix.

The nested Gemini schema lists `display_label` as a required, nullable `STRING`. Requiring the key prevents silent omission by Gemini, while `null` keeps all ordinary state headings deterministic in code. Runtime rendering remains defensive so previously stored analysis JSON without the field still works.

Label rules for new extraction:

- Ordinary state tax: set `display_label` to `null`; the renderer outputs `State Income Tax` for one state or `<USPS> State Income Tax` for two or more states.
- Local or regional tax: set a concise client-facing label that identifies the jurisdiction, such as `OR Metro Income Tax`.
- Do not include a colon in `display_label`.
- Do not change the jurisdiction sentence, amount, status, or ordering to construct the label.

The prompt update covers every part of the contract, not only the Metro example:

- change terminology from only “Federal + states” to “Federal + state/local/regional jurisdictions” where applicable;
- redefine `state_name` as the full state, local, or regional jurisdiction name and use the host state's USPS code in `state_abbreviation` for local/regional rows;
- define `display_label` in the output schema;
- add `display_label: null` to all ordinary-state worked examples;
- add the Oregon plus Metro worked example;
- add a self-check that rejects treating a local or regional tax as a second state.

## Rendering Design

Add `jobs/tax_labels.py` with a `resolve_tax_summary_labels(items)` helper that returns one aligned label per input row.

Resolution order:

1. Normalize each `display_label`: accept strings only, trim surrounding whitespace, remove all trailing colons and surrounding whitespace again, and treat an empty result as absent.
2. Count rows without a normalized explicit label. These are ordinary state rows for new payloads and all rows for legacy payloads.
3. For each row:
   - explicit label present: return it;
   - exactly one ordinary state row: return `State Income Tax`;
   - two or more ordinary state rows: return `<state_abbreviation> State Income Tax`, falling back to a non-blank `state_name`; if both are absent, return `State Income Tax` rather than the duplicated phrase `State State Income Tax`.

The state-row count includes rows with an empty sentence, matching the current renderer's ordering of “count first, skip empty sentence while rendering.” This deliberately preserves valid legacy behavior. The final generic fallback hardens malformed legacy payloads whose abbreviation and name are both missing or blank.

Both `jobs/email_html.py` and `main.py` call this helper and append only `: <sentence>`. This prevents HTML and DOCX from drifting and prevents output such as `OR Metro Income Tax Income Tax`.

The HTML renderer escapes the resolved label before interpolation because a local jurisdiction label originates in model output. DOCX receives it as plain text. Sentence rendering remains unchanged.

The renderers continue to:

- skip rows with an empty `sentence`;
- preserve extraction order;
- render `Federal Income Tax` exactly as before;
- leave Markdown bold conversion unchanged.

## Compatibility and Blast Radius

The following behaviors remain unchanged:

- Hong: one California row remains `State Income Tax` with refund `$297`.
- ACCUPUNCTURE: one California row remains `State Income Tax`; the 2026 estimate table and `$28,805` PTE sentence remain unchanged.
- A true California plus North Carolina return remains `CA State Income Tax` and `NC State Income Tax`.
- Federal summaries, tax calculations, refund/balance-due amounts, estimated payments, PTE rules, and Task 1 e-consent selection are untouched.
- Old analysis payloads without `display_label` retain the existing output through the fallback. Old payloads containing local taxes retain their old label until re-extracted because they do not carry the new metadata.

No database migration is needed because `analysis_data` is JSONB and the API exposes it as a dictionary. No pipeline, worker, database model, or Pydantic API schema change is required. The extra JSON key is an additive API-data change; consumers must tolerate unknown fields, while the backend contract already does.

`email_html` is materialized and stored when a job finishes. Deploying this change does not rewrite successful historical jobs. The existing Im job must be uploaded as a new job after deployment or updated through a separately authorized one-time backfill. A historical-data backfill is not part of this implementation.

## Error Handling

- Missing, `null`, non-string, blank, colon-only, or whitespace-and-colon-only `display_label`: use the state/legacy fallback rather than failing the job.
- One or more trailing colons in a model-produced label: normalize them so the renderer emits one colon.
- Missing abbreviation in a legacy multi-row payload: preserve the current fallback to `state_name`, then `State`.
- Invalid tax amounts or sentences are outside this helper's responsibility and remain governed by the existing Task 2 extraction contract.

## Test Strategy

Add focused tests before implementation:

1. Shared label resolver:
   - explicit `State Income Tax` as defensive behavior for manually supplied or legacy payloads;
   - explicit `OR Metro Income Tax`;
   - whitespace, one-or-more trailing-colon, and colon-only normalization;
   - legacy single-state fallback;
   - legacy true multi-state fallback;
   - blank/non-string fallback;
   - missing/null/blank abbreviation and state-name fallback;
   - an empty-sentence row still participates in the legacy state count.
2. HTML golden cases:
   - Im renders `State Income Tax` and `OR Metro Income Tax`, never a Metro `OR State Income Tax`;
   - Hong remains `State Income Tax`;
   - ACCUPUNCTURE keeps its state heading, estimated-payment section, and PTE sentence;
   - true CA plus NC remains differentiated;
   - no `Income Tax Income Tax` or double colon;
   - a model-produced label containing `&`, `<`, or `>` is HTML-escaped.
3. DOCX parity:
   - generated paragraph text contains the same Im, single-state, and multi-state headings as HTML.
4. Schema contract:
   - `display_label` exists, is required, and is nullable for newly generated Task 2 items;
   - all ordinary-state examples contain `display_label: null`;
   - prompt terminology and the Metro example cover local/regional jurisdictions.
5. Extraction smoke check when a Gemini key is configured:
   - run Task 2 against page 1 of Im, Hong, and ACCUPUNCTURE;
   - verify Im produces `null` for Oregon and `OR Metro Income Tax` for Metro;
   - verify Hong and ACCUPUNCTURE produce `null` for California;
   - verify all amounts and sentences remain unchanged.

The focused tests must pass independently. The full suite must also be run and any pre-existing failures reported separately from regressions introduced by this change.

## Files in Scope

- `prompts/task2_email.txt`
- `schemas.py`
- `jobs/tax_labels.py`
- `jobs/email_html.py`
- `main.py`
- focused unit/regression tests

## Files and Behavior Out of Scope

- `prompts/task1_econsent.txt` and e-consent page selection
- tax calculation or accounting logic
- database migrations and API response models
- production deployment or historical job mutation
- the global `CNY invoice` rule, which is covered by the companion design spec
