# Bookmark-First Cover Letter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Feed Task 2 the bookmarked `Letter` section, fall back safely to page 1, and preserve explicitly printed PTE ordinals without adding an AI call.

**Architecture:** Add one pure page-range resolver and one extraction helper to `main.py`, then reuse that helper from both the CLI and worker pipeline. PyMuPDF's existing `Document.get_toc()` API supplies bookmark data. After the existing two Gemini calls, deterministic code may enrich `1st PTE` only from a unique amount/date match against a filled California e-file authorization form; no API call is added.

**Tech Stack:** Python 3.12, PyMuPDF, pytest/unittest, Gemini prompt contract.

**Commit policy:** The user requested no commits. All work remains uncommitted for the user to inspect and commit later.

**Implementation status:** Completed and verified locally; checkboxes below preserve the original execution recipe.

---

## File Map

- Modify `test_main.py`: generated-PDF behavior tests for exact `Letter`, ranges, and fallback.
- Create `tests/test_pipeline.py`: worker integration regression proving Task 2 receives selector output.
- Modify `tests/test_task2_email_contract.py`: prompt contract for multi-page Letter input and evidence-based PTE ordinals.
- Create `tests/test_task1_econsent_contract.py`: official California partnership form-number contract.
- Modify `main.py`: bookmark page-range resolver, reusable extraction helper, and CLI integration.
- Modify `jobs/pipeline.py`: replace its duplicated first-page extraction with the shared helper.
- Modify `prompts/task2_email.txt`: align scope wording and PTE ordinal rule with approved behavior.
- Modify `prompts/task1_econsent.txt`: use official California FTB 8453-P partnership form number.

### Task 1: Selector behavior tests

- [ ] Add a generated-PDF fixture/helper to `test_main.py` that creates distinguishable pages and an optional TOC.
- [ ] Add a test where a normalized top-level `Letter` starts on page 2 and the next top-level bookmark starts on page 4; expect pages 2-3 only.
- [ ] Add independent tests proving missing `Letter`, substring-only `Engagement Letter`, and invalid `Letter` destination all fall back to page 1.
- [ ] Run `venv/bin/pytest test_main.py -q` and verify failures are caused by the missing `extract_cover_letter_bytes` API.

### Task 2: Shared bookmark-first selector

- [ ] Add `_letter_page_range(doc)` to `main.py`. Return zero-based inclusive `(start, end)`, defaulting to `(0, 0)`; match only level-1 exact normalized `Letter`; validate destinations; stop before the next later level-1 destination; use only the start page if no safe boundary exists.
- [ ] Add `extract_cover_letter_bytes(source_pdf)` accepting either path-like input or PDF bytes and returning a new in-memory PDF containing the resolved range.
- [ ] Keep `extract_page1_bytes` unchanged for compatibility.
- [ ] Run `venv/bin/pytest test_main.py -q` and verify all selector and legacy tests pass.

### Task 3: Worker and CLI parity

- [ ] Add `tests/test_pipeline.py` with a monkeypatched selector sentinel; verify `run_extraction` sends that sentinel to Task 2 while Task 1 still receives the original full PDF.
- [ ] Run the new test and verify RED because `jobs/pipeline.py` still performs its own page-1 extraction.
- [ ] Update `jobs/pipeline.py` and the CLI analysis path in `main.py` to call `extract_cover_letter_bytes`.
- [ ] Run `venv/bin/pytest tests/test_pipeline.py test_main.py -q` and verify GREEN.

### Task 4: Prompt contract

- [ ] Add prompt tests requiring `one or more pages` from the bookmarked `Letter` section and prohibiting the old `EXACTLY ONE PAGE` claim.
- [ ] Add prompt tests requiring preservation of an explicitly printed `1st`/`first` PTE label and prohibiting inference from the count of extracted entries.
- [ ] Run `venv/bin/pytest tests/test_task2_email_contract.py -q` and verify RED against the old prompt.
- [ ] Update `prompts/task2_email.txt` consistently: scope references use the selected Letter section; a single payment keeps an ordinal only when explicitly present; self-verification checks evidence rather than row count.
- [ ] Run `venv/bin/pytest tests/test_task2_email_contract.py -q` and verify GREEN.

### Task 5: Regression and review

- [ ] Programmatically run `extract_cover_letter_bytes` over all six sample PDFs. Verify the five bookmarked returns select the expected Letter content and the bookmark-free `House.pdf` selects page 1.
- [ ] Run focused tests covering PDF selection, pipeline integration, prompt contract, email rendering, and existing tax labels.
- [ ] Run the repository's complete feasible test suite and separate pre-existing/environmental failures from regressions.
- [ ] Request an independent code review against this design, fix all Critical/Important findings, and rerun affected tests.
- [ ] Confirm `git status --short`; ensure user-owned deployment edits remain untouched and create no commit.

### Task 6: Deterministic PTE First Payment evidence

- [ ] Add failing synthetic tests for filled/blank/mismatched FTB 8453-C, 8453-LLC, and official 8453-P sections, duplicate payment ambiguity, noneligible returns, and existing ordinals.
- [ ] Parse each official California e-file authorization Part locally with PyMuPDF, requiring `First Payment`, exactly one filled amount, and exactly one withdrawal date.
- [ ] Match normalized form evidence to exactly one canonical Task 2 PTE sentence before inserting `1st`; otherwise preserve all data.
- [ ] Invoke the shared postprocessor in worker and CLI before render/save; keep Task 1 and Task 2 API calls unchanged.
- [ ] Verify Trevor and ACCUPUNCTURE enrich correctly while Yamane's blank form produces no evidence.
