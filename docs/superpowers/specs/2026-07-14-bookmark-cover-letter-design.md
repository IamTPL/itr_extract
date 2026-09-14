# Bookmark-First Cover Letter Selection Design

**Status:** Approved by the user on 2026-07-14.

## Goal

Select the PDF pages supplied to Task 2 deterministically, without adding an AI call:

1. Read the PDF outline/bookmarks with PyMuPDF.
2. Select the first top-level bookmark whose trimmed, case-insensitive title is exactly `Letter`.
3. Include pages from that bookmark through the page before the next top-level bookmark whose destination is later in the document.
4. If `Letter` is missing, its destination is invalid, or a usable section cannot be derived, use the first PDF page.
5. If `Letter` is the final top-level bookmark and therefore has no safe end boundary, include only its destination page.

Exact matching deliberately excludes titles such as `Engagement Letter` and `Letter Instructions`.

## Integration

- Keep the selector in `main.py`, alongside the existing PDF extraction helpers, to avoid introducing another production module for this small behavior.
- Use the same helper from the CLI and `jobs/pipeline.py`, preventing worker/CLI drift.
- Keep Task 1 on the complete original PDF. E-consent detection and extraction are unchanged.
- Task 2 keeps its existing single Gemini call. Only the PDF bytes passed to that call change.
- Update the Task 2 prompt so its input may contain one or more pages from the `Letter` section.

## PTE wording already approved

Task 2 preserves `1st` only when the selected cover-letter input prints it. Because the Trevor Letter omits the ordinal while its filled FTB 8453-C Part IV labels the matching amount/date as `First Payment`, a deterministic postprocessor also checks the full PDF locally. It adds `1st` only when exactly one PTE sentence and exactly one filled California FTB 8453-C, 8453-LLC, or 8453-P payment agree on amount and date. Missing, conflicting, scanned, or unsupported evidence leaves the sentence unchanged. This adds no AI call.

## Safety

- Validate all 1-based bookmark destinations against the document page count.
- Ignore nested bookmarks when locating section boundaries.
- Preserve the old first-page helper for compatibility; new call sites use the new selector.
- Use canonical no-ordinal wording and unique amount/date matches before modifying a PTE sentence; never rewrite ambiguous rows.
- Cover generated PDFs, malformed/missing bookmarks, exact matching, multi-page sections, worker integration, prompt wording, and the real sample PDFs with tests.
- Do not commit any spec, plan, test, or implementation file.
