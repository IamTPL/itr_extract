#!/usr/bin/env python3
"""
ITR Tax Packaging AI — Demo Script
===================================
Analyzes an Income Tax Return (ITR) PDF using Google Gemini AI to:
  1. Detect and extract e-consent / e-file authorization pages → Econsent.pdf
  2. Extract financial data and generate a client email template → email_template.docx

Usage:
  python3 itr_packaging.py <input_pdf> [--output-dir <dir>]

Requirements:
  pip install pymupdf python-docx

Environment:
  GEMINI_API_KEY — Google Gemini API key (reads from .env if not set)
"""

import os
import sys
import json
import base64
import urllib.request
import urllib.error
import argparse
import re
from pathlib import Path
from datetime import datetime
import time
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import fitz  # pymupdf
except ImportError:
    sys.exit("ERROR: pymupdf not installed. Run: pip install pymupdf --break-system-packages")

try:
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
except ImportError:
    sys.exit("ERROR: python-docx not installed. Run: pip install python-docx --break-system-packages")


# ═══════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3-flash-preview"

# Gemini pricing per 1M tokens (USD) — update when pricing changes
GEMINI_PRICING = {
    "input_per_1m": 0.5,
    "output_per_1m": 3.00,
    "thinking_per_1m": 3.00,
}

# Per-task generation config — tuned independently because Task 1 scans the whole
# PDF (reasoning-heavy) while Task 2 reads a single cover-letter page.
TASK1_CONFIG = {"temperature": 0.0, "thinking_budget": 4096, "timeout_s": 240}
TASK2_CONFIG = {"temperature": 0.0, "thinking_budget": 0,    "timeout_s": 120}

# Return types eligible for PTE elective tax (hard whitelist, also enforced in prompt).
PTE_ELIGIBLE_RETURN_TYPES = {"S-Corporation (1120S)", "Partnership (1065)"}

# ═══════════════════════════════════════════════════════════════════
# PROMPT — TASK 1: E-CONSENT / E-FILE AUTHORIZATION PAGE DETECTION
# ═══════════════════════════════════════════════════════════════════

TASK1_PROMPT = """
You are a senior U.S. Certified Public Accountant (CPA) and tax compliance specialist with 20+ years of experience in federal and multi-state income tax return preparation, IRS Modernized e-File (MeF) procedures, and state e-file programs.

You are analyzing a complete Income Tax Return (ITR) packaging PDF. This PDF was compiled by a CPA firm and bundles ALL finalized tax forms, schedules, worksheets, transmittal letters, and supporting statements for a single client entity into one document.

═══════════════════════════════════════════════════════════════════
TASK — E-CONSENT / E-FILE AUTHORIZATION PAGE IDENTIFICATION
═══════════════════════════════════════════════════════════════════

Scan EVERY page of this PDF and identify ALL pages that ARE actual IRS or state e-file authorization / e-consent forms — the forms that require the taxpayer's or corporate officer's signature to authorize electronic filing of the return.

FORMS TO DETECT (include all variants known to the IRS and state agencies):

── Federal IRS Forms ──
  • Form 8879           — IRS e-file Signature Authorization (Individual)
  • Form 8879-C         — IRS e-file Signature Authorization for Form 1120
  • Form 8879-CORP      — E-file Authorization for Corporations
  • Form 8879-S         — IRS e-file Signature Authorization for S Corporation
  • Form 8879-PE        — IRS e-file Signature Authorization for Form 1065
  • Form 8879-EMP       — IRS e-file Signature Authorization for Employment Tax Return
  • Form 8879-F         — IRS e-file Signature Authorization for Form 1041
  • Form 8879-EO        — IRS e-file Signature Authorization for Form 990
  • Form 8453           — U.S. Individual Income Tax Transmittal for an IRS e-file Return
  • Form 8453-CORP      — E-file Declaration for Corporations
  • Form 8453-S         — E-file Declaration for S Corporations
  • Form 8453-PE        — Partnership e-file Declaration
  • Form 8453-FE        — Foreign Entity e-file Declaration
  • Form 8453-EO        — Exempt Organization e-file Declaration
  • Form 8453-F         — Fiduciary e-file Declaration

── State Forms (detect ANY equivalent across all states) ──
  • California: FTB 8453, FTB 8453-C, FTB 8453-PE, FTB 8453-LLC, FTB 8879
  • New York: IT-8879, CT-8879, PT-8879
  • Any form with header/title containing: "e-file authorization", "electronic filing authorization",
    "e-consent", "declaration for electronic filing", "e-file signature authorization",
    "e-file return authorization"

CRITICAL DETECTION RULES:
  ✅ INCLUDE: Pages that ARE the actual printed tax form itself
     — Identified by: official form number printed in the header/footer area,
       structured Parts/Sections layout, signature lines, OMB numbers
  ✅ INCLUDE: ALL pages of a multi-page form (e.g., if Form 8453-C has Parts I-VI
     on page 1 and Part VII on page 2, include BOTH pages)
  ❌ EXCLUDE: Cover letters / transmittal letters that only MENTION a form by name
  ❌ EXCLUDE: Table of contents or form index pages that LIST form names
  ❌ EXCLUDE: "Preparer e-file Instructions" worksheets (instructional pages for the preparer)
  ❌ EXCLUDE: Financial summary pages, depreciation schedules, comparison worksheets
  ❌ EXCLUDE: Schedule K-1 pages (these are NOT e-consent forms)
  ❌ EXCLUDE: Extension forms (Form 7004, Form 4868) — these are NOT e-consent forms
  ❌ EXCLUDE: Any page that merely references or discusses a form without BEING the form

Page numbering rule: 1-based index (the very first page of the PDF document = page 1).

═══════════════════════════════════════════════════════════════════
RESPONSE FORMAT — STRICT JSON
═══════════════════════════════════════════════════════════════════

Return a single JSON object:

{
  "econsent_pages": [10, 26, 27],
  "econsent_forms": [
    {
      "form_number": "string",
      "title": "string",
      "pages": [10],
      "jurisdiction": "Federal or state-name"
    }
  ]
}
"""

# ═══════════════════════════════════════════════════════════════════
# PROMPT — TASK 2: CLIENT EMAIL DATA EXTRACTION (page 1 cover letter only)
# ═══════════════════════════════════════════════════════════════════

TASK2_PROMPT = r"""
You are a senior U.S. Certified Public Accountant (CPA) with 20+ years of experience preparing
federal and multi-state income tax returns. You are reading a CLIENT COVER (TRANSMITTAL) LETTER
that summarizes the outcome of a finalized tax return. The PDF you receive contains EXACTLY
ONE PAGE — this cover letter — and nothing else.

Your job: extract structured data AND write the exact client-facing summary sentences that
will appear in a notification email (DOCX) sent to the client via ShareFile.

═══════════════════════════════════════════════════════════════════
ABSOLUTE SCOPE RULES
═══════════════════════════════════════════════════════════════════
• Use ONLY information literally present on this page. Never invent values.
• If a field is not present in the letter, return null (or [] for arrays).
• Ignore intermediate calculations (ACA premium tax credit reconciliation, depreciation,
  K-1 distribution instructions, signature blocks, preparer notes).

═══════════════════════════════════════════════════════════════════
OUTPUT JSON SCHEMA (strict)
═══════════════════════════════════════════════════════════════════
{
  "client": { "name": "string — as printed in salutation/address block" },
  "cpa_firm": {
    "name": "string — firm letterhead",
    "sharefile_subdomain": "string — lowercase alphanumeric, derived from firm name (e.g. 'CNY LLP' → 'cnyllp')"
  },
  "tax_year":   "string — 4-digit year of the return (e.g. '2025')",
  "next_year":  "string — tax_year + 1 (e.g. '2026')",
  "return_type": "Individual (1040)" | "S-Corporation (1120S)" | "C-Corporation (1120)" | "Partnership (1065)" | "Trust/Estate (1041)" | "Non-Profit (990)",

  "tax_summary": {
    "federal_sentence": "string — one sentence following PATTERNS below; null if Federal not mentioned",
    "state_sentences": [
      {
        "state_name": "string — full state name (e.g. 'California')",
        "state_abbreviation": "string — USPS 2-letter code (e.g. 'CA', 'NC', 'NY', 'TX')",
        "sentence": "string"
      }
    ]
  },

  "estimated_payments": [
    { "date": "MM/DD/YYYY", "federal": number, "state": number, "state_name": "string|null" }
  ],

  "pte_payments": [
    { "sentence": "string — full PTE sentence" }
  ]
}

═══════════════════════════════════════════════════════════════════
SENTENCE PATTERNS — TAX PAYMENT SUMMARY
═══════════════════════════════════════════════════════════════════
Write ONE sentence per jurisdiction (Federal + each state). Use Markdown **bold** to emphasize
status keywords (Balance due, Overpayment, Refund, No tax) and dollar amounts.

╔══════════════════════════════════════════════════════════════╗
║  STEP-BY-STEP DECISION (do this for EACH jurisdiction)        ║
║                                                                ║
║  1. Does the letter say "no tax payable" / "balance due"      ║
║     / "overpayment" / "refund" for this jurisdiction?         ║
║                                                                ║
║  2. If "balance due":                                         ║
║       → Search the SAME paragraph for an explicit calendar    ║
║         date next to "withdrawn" (e.g. "on April 15, 2026"    ║
║         or "on 4/15/2026").                                   ║
║       → Date FOUND     → use P1b (with that date in bold).    ║
║       → Date NOT FOUND → use P1a.                             ║
║                                                                ║
║  3. If "overpayment": determine disposition (credited /       ║
║     refunded / both) → P2 / P3 / P4.                          ║
║                                                                ║
║  4. If "no tax payable" alone → P5.                           ║
╚══════════════════════════════════════════════════════════════╝

P1a — BALANCE DUE, NO EXPLICIT WITHDRAWAL DATE in letter:
   "**Balance due** of **$X**, which will be withdrawn from your account once your return has been processed."

P1b — BALANCE DUE WITH EXPLICIT WITHDRAWAL DATE in letter (e.g. "withdrawn ... on April 15, 2026"):
   "**Balance due** of **$X**, will be withdrawn from account on **{Month Day, Year}**."

P2 — OVERPAYMENT FULLY CREDITED to next year (no money returned to client):
   "No tax is payable with the filing of this return. **Overpayment** of **$X** of which **$X** credited to {next_year} tax."

P3 — REFUND FULLY DEPOSITED (no credit applied to next year):
   "No tax is payable with the filing of this return. **Refund** of **$X** will be deposited to your account."

P4 — OVERPAYMENT PARTIALLY CREDITED + PARTIALLY REFUNDED:
   "No tax is payable with the filing of this return. **Overpayment** of **$X** of which **$Y** credited to {next_year} tax. **Refund** of **$Z** will be deposited to your account."

P5 — ZERO OUTCOME (no tax, no overpayment, no refund mentioned):
   "No tax is payable with the filing of this return."

NORMALIZE these equivalent cover-letter phrasings → standard patterns above:
• "has been applied to your {YYYY} estimated tax"                        → credited to {next_year} tax (P2/P4)
• "directly deposited into your checking account"                         → deposited to your account (P3/P4)
• "withdrawn ... once the return has been processed"                      → P1a (no date)
• "withdrawn ... once [agency] processed the return"                      → P1a (no date)
• "directly withdrawn from your bank account on April 15, 2026"           → P1b (preserve the explicit date)
• "withdrawn ... on {Month Day, Year}"                                    → P1b
• "There is an overpayment of $X"                                         → P2/P3/P4 depending on disposition

P1a vs P1b decision rule:
  If the letter states a specific calendar date (e.g. "April 15, 2026", "4/15/2026") for the
  withdrawal → use P1b and put that date in the sentence.
  If the letter only says "once the return has been processed" with no date → use P1a.

CRITICAL DISTINCTION:
  "Overpayment" ≠ "Refund". An overpayment can be (a) credited to next year, (b) refunded to
  the client, or (c) split between both. Read the letter carefully to determine the disposition.

═══════════════════════════════════════════════════════════════════
ESTIMATED PAYMENTS RULES
═══════════════════════════════════════════════════════════════════
• Include only payments listed in the letter's payment schedule table.
• Normalize dates to MM/DD/YYYY (e.g. "4/15/26" → "04/15/2026", "1/15/27" → "01/15/2027").
• Each row has a Federal column, a State column, or both. Set missing column to 0.
• If the schedule is single-jurisdiction (e.g. only "California"), set state_name accordingly
  and federal=0; conversely federal-only schedules set state=0 and state_name=null.

═══════════════════════════════════════════════════════════════════
PASS-THROUGH ENTITY (PTE) ELECTIVE TAX RULES
═══════════════════════════════════════════════════════════════════
ELIGIBILITY (hard gate):
  PTE applies ONLY to S-Corporation (1120S) and Partnership (1065) returns that have made a
  state PTE election. For Individual (1040), C-Corporation (1120), Trust (1041), and
  Non-Profit (990): "pte_payments" MUST be [] regardless of any number on the page.

EXTRACTION:
  Even for eligible return types, include a PTE entry ONLY if the letter EXPLICITLY mentions
  a "Pass-Through Entity Elective Tax" (or "PTE elective tax") payment with both an amount
  AND a date. Do NOT infer PTE from any other dollar figure.

PTE SENTENCE PATTERNS (use **bold** for amount and date):
  • Single payment (most common — 1 PTE installment):
     "{next_year} PTE tax payment of **$X** will be automatically withdrawn on **{Month Day, Year}**."
  • Multiple payments (rare — installment series):
     "{next_year} {Nth} PTE tax payment of **$X** will be automatically withdrawn on **{Month Day, Year}**."
     (where {Nth} = 1st, 2nd, 3rd, 4th)

DO NOT add ordinals "1st"/"2nd" when there is only ONE PTE payment.

═══════════════════════════════════════════════════════════════════
NEGATIVE CONSTRAINTS — DO NOT
═══════════════════════════════════════════════════════════════════
✗ Fabricate any amount, date, or jurisdiction not present on the page.
✗ Include ACA premium tax credit, depreciation, or any intermediate calculation in summary sentences.
✗ Output PTE entries for non-passthrough returns.
✗ Add ordinal "1st" when only one PTE payment exists.
✗ Include K-1 distribution notices, preparer instructions, or signature blocks.
✗ Confuse "credited to next year" (no money returned) with "refund deposited" (money returned).

═══════════════════════════════════════════════════════════════════
SELF-VERIFICATION (perform before final output)
═══════════════════════════════════════════════════════════════════
1. Every dollar amount in my output appears literally on the page. ✓
2. pte_payments matches the return_type eligibility rule. ✓
3. estimated_payments dates use MM/DD/YYYY format. ✓
4. Each summary sentence starts with a bolded status keyword (Balance due / Overpayment / Refund / No tax). ✓
5. No ordinal "1st" added to a single PTE payment. ✓
6. CRITICAL — P1a vs P1b: For every "Balance due" jurisdiction, I scanned the letter for an
   explicit calendar date next to the withdrawal phrase. If a date like "April 15, 2026" or
   "4/15/2026" is present, I used P1b with that date in **bold**. Otherwise I used P1a. ✓
7. CRITICAL — Every entry in state_sentences has a non-null "state_abbreviation" field with
   the correct USPS 2-letter code (CA, NC, NY, TX, FL, IL, ...). ✓

═══════════════════════════════════════════════════════════════════
WORKED EXAMPLE — Individual return, Federal credit + State refund
═══════════════════════════════════════════════════════════════════
LETTER EXCERPT:
  "Your 2025 Federal Individual Income Tax return ... No tax is payable with the filing of
   this return. There is an overpayment of $3,597, of which $3,597 has been applied to your
   2026 estimated tax. Your 2025 California Individual Income Tax Return ... No tax is
   payable with the filing of this return. The refund of $2,052 will be directly deposited
   into your checking account."

EXPECTED OUTPUT:
  {
    "tax_year": "2025", "next_year": "2026", "return_type": "Individual (1040)",
    "tax_summary": {
      "federal_sentence": "No tax is payable with the filing of this return. **Overpayment** of **$3,597** of which **$3,597** credited to 2026 tax.",
      "state_sentences": [
        {"state_name": "California", "state_abbreviation": "CA", "sentence": "No tax is payable with the filing of this return. **Refund** of **$2,052** will be deposited to your account."}
      ]
    },
    "pte_payments": []
  }

═══════════════════════════════════════════════════════════════════
WORKED EXAMPLE 2 — Individual return, multi-state with explicit withdrawal date (P1b)
═══════════════════════════════════════════════════════════════════
LETTER EXCERPT:
  "Your 2025 Federal Individual Income Tax return ... There is a balance due of $14,917. The
   balance due will be directly withdrawn from your bank account on April 15, 2026.
   Your 2025 California Individual Income Tax Return ... There is a balance due of $29. The
   balance due will be directly withdrawn from your bank account on April 15, 2026.
   Your 2025 North Carolina Individual Income Tax Return ... No tax is payable with the
   filing of this return. The refund of $95 will be deposited directly into your bank account."

EXPECTED OUTPUT:
  {
    "tax_year": "2025", "next_year": "2026", "return_type": "Individual (1040)",
    "tax_summary": {
      "federal_sentence": "**Balance due** of **$14,917**, will be withdrawn from account on **April 15, 2026**.",
      "state_sentences": [
        {"state_name": "California", "state_abbreviation": "CA", "sentence": "**Balance due** of **$29**, will be withdrawn from account on **April 15, 2026**."},
        {"state_name": "North Carolina", "state_abbreviation": "NC", "sentence": "No tax is payable with the filing of this return. **Refund** of **$95** will be deposited to your account."}
      ]
    },
    "pte_payments": []
  }

Return ONLY the JSON object — no markdown fences, no commentary.
"""


# ═══════════════════════════════════════════════════════════════════
# CONFIGURATION LOADER
# ═══════════════════════════════════════════════════════════════════

def load_api_key(env_file=None):
    """Load Gemini API key from environment variable or .env file."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key

    # Search for .env file
    if env_file is None:
        candidates = [
            Path.cwd() / ".env",
            Path(__file__).resolve().parent.parent.parent / ".env",
        ]
        for candidate in candidates:
            if candidate.exists():
                env_file = candidate
                break

    if env_file and Path(env_file).exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")

    return None


# ═══════════════════════════════════════════════════════════════════
# GEMINI AI SERVICE
# ═══════════════════════════════════════════════════════════════════

def call_gemini(pdf_bytes, prompt, config, api_key, model=DEFAULT_MODEL, label=""):
    """
    Send ``pdf_bytes`` + ``prompt`` to Gemini using ``config``.

    config = {"temperature": float, "thinking_budget": int, "timeout_s": int}
    Returns (parsed_json_dict, token_usage_dict).
    """
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    payload = {
        "contents": [
            {
                "parts": [
                    {"inline_data": {"mime_type": "application/pdf", "data": pdf_b64}},
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": config["temperature"],
            "thinkingConfig": {"thinkingBudget": config["thinking_budget"]},
        },
    }

    url = f"{GEMINI_API_BASE}/models/{model}:generateContent?key={api_key}"

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    pdf_size_kb = len(pdf_bytes) / 1024
    tag = f"[{label}] " if label else ""
    print(f"   📡 {tag}Sending to Gemini ({model}, {pdf_size_kb:.1f} KB)...")

    result = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=config["timeout_s"]) as response:
                result = json.loads(response.read().decode("utf-8"))
            break
        except (TimeoutError, ConnectionResetError) as e:
            if attempt == 0:
                print(f"\n   ⚠️  {tag}Timeout, retrying once (30s)...")
                time.sleep(30)
                continue
            print(f"\n   ❌ Request timed out after 2 attempts.")
            sys.exit(1)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            print(f"\n   ❌ Gemini API Error (HTTP {e.code}):")
            try:
                err = json.loads(error_body)
                print(f"      {err.get('error', {}).get('message', error_body[:500])}")
            except json.JSONDecodeError:
                print(f"      {error_body[:500]}")
            sys.exit(1)
        except urllib.error.URLError as e:
            # urllib wraps socket.timeout as URLError — treat as timeout and retry
            if isinstance(e.reason, (TimeoutError, socket.timeout)):
                if attempt == 0:
                    print(f"\n   ⚠️  {tag}Timeout (connection), retrying once (30s)...")
                    time.sleep(10)
                    continue
                print(f"\n   ❌ Request timed out after 2 attempts.")
                sys.exit(1)
            print(f"\n   ❌ Network Error: {e.reason}")
            sys.exit(1)

    # ── Token usage & cost ──
    usage = result.get("usageMetadata", {})
    input_tokens = usage.get("promptTokenCount", 0)
    output_tokens = usage.get("candidatesTokenCount", 0)
    thinking_tokens = usage.get("thoughtsTokenCount", 0)
    total_tokens = usage.get("totalTokenCount", 0)

    input_cost = (input_tokens / 1_000_000) * GEMINI_PRICING["input_per_1m"]
    output_cost = (output_tokens / 1_000_000) * GEMINI_PRICING["output_per_1m"]
    thinking_cost = (thinking_tokens / 1_000_000) * GEMINI_PRICING["thinking_per_1m"]
    total_cost = input_cost + output_cost + thinking_cost

    # Parse Gemini response — extract the non-thought text part
    candidates = result.get("candidates", [])
    if not candidates:
        print("   ❌ No candidates in Gemini response")
        sys.exit(1)

    parts = candidates[0].get("content", {}).get("parts", [])

    # Prefer non-thought text parts; fall back to any text
    text_content = None
    for part in parts:
        if "text" in part and not part.get("thought", False):
            text_content = part["text"]
            break

    if text_content is None:
        for part in parts:
            if "text" in part:
                text_content = part["text"]
                break

    if not text_content:
        print("   ❌ No text content in Gemini response")
        sys.exit(1)

    # Clean markdown fences if present
    cleaned = text_content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
    cleaned = re.sub(r"\n?\s*```\s*$", "", cleaned)

    token_usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "thinking_tokens": thinking_tokens,
        "total_tokens": total_tokens,
        "input_cost": input_cost,
        "output_cost": output_cost,
        "thinking_cost": thinking_cost,
        "total_cost": total_cost,
    }

    try:
        parsed, _ = json.JSONDecoder().raw_decode(cleaned)
    except json.JSONDecodeError as e:
        print(f"   ❌ JSON parse error: {e}")
        print(f"      Raw response (first 500 chars): {text_content[:500]}")
        sys.exit(1)

    # Guard: unwrap if model wrapped response in a single-element array
    if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
        parsed = parsed[0]

    return parsed, token_usage


# ═══════════════════════════════════════════════════════════════════
# PDF EXTRACTION SERVICE
# ═══════════════════════════════════════════════════════════════════

def extract_page1_bytes(source_pdf):
    """Return the first page of ``source_pdf`` as an in-memory single-page PDF (bytes)."""
    src = fitz.open(source_pdf)
    out = fitz.open()
    out.insert_pdf(src, from_page=0, to_page=0)
    data = out.write()
    out.close()
    src.close()
    return data


def extract_econsent_pdf(source_pdf, page_numbers, output_path):
    """
    Extract specified pages from source PDF into a new Econsent PDF.
    page_numbers: list of 1-based page numbers.
    """
    doc = fitz.open(source_pdf)

    # Validate and convert to 0-based indices
    valid_pages = sorted(
        [p - 1 for p in page_numbers if isinstance(p, int) and 1 <= p <= doc.page_count]
    )

    if not valid_pages:
        print("   ⚠️  No valid e-consent pages to extract.")
        doc.close()
        return False

    new_doc = fitz.open()
    for page_idx in valid_pages:
        new_doc.insert_pdf(doc, from_page=page_idx, to_page=page_idx)

    new_doc.save(output_path)
    new_doc.close()
    doc.close()
    return True


# ═══════════════════════════════════════════════════════════════════
# EMAIL TEMPLATE GENERATOR
# ═══════════════════════════════════════════════════════════════════

def _add_paragraph(doc, text, bold=False, size=11, space_after=0, space_before=0, font_name="Calibri"):
    """Helper: add a styled paragraph to the document."""
    para = doc.add_paragraph()
    run = para.add_run(text)
    run.font.name = font_name
    run.font.size = Pt(size)
    run.font.bold = bold
    para.paragraph_format.space_after = Pt(space_after)
    para.paragraph_format.space_before = Pt(space_before)
    return para


def _add_markdown_paragraph(doc, text, size=11, space_after=4, space_before=0, font_name="Calibri"):
    """Add a paragraph, rendering ``**bold**`` markdown segments as bold runs.

    Splits the text on ``**...**`` — odd-indexed segments become bold runs.
    Empty segments (e.g. when text starts with ``**``) are skipped to avoid
    creating zero-width runs.
    """
    para = doc.add_paragraph()
    segments = re.split(r"\*\*(.+?)\*\*", text)
    for idx, segment in enumerate(segments):
        if segment == "":
            continue
        run = para.add_run(segment)
        run.font.name = font_name
        run.font.size = Pt(size)
        run.font.bold = (idx % 2 == 1)
    para.paragraph_format.space_after = Pt(space_after)
    para.paragraph_format.space_before = Pt(space_before)
    return para


def _format_currency(amount):
    """Format a number as USD currency string."""
    if amount is None or amount == 0:
        return "$0"
    return f"${amount:,.0f}"


def _format_date_long(date_str):
    """Convert 'MM/DD/YYYY' to 'Month Day, Year' (e.g., '06/15/2026' → 'June 15, 2026')."""
    try:
        dt = datetime.strptime(date_str, "%m/%d/%Y")
        return f"{dt.strftime('%B')} {dt.day}, {dt.year}"
    except (ValueError, TypeError):
        return date_str


def generate_email_docx(data, output_path):
    """
    Generate a professional client email template DOCX from extracted ITR data.
    Follows the standard CPA firm tax return delivery email format.
    """
    doc = Document()

    # Page margins
    for section in doc.sections:
        section.top_margin = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)

    # ── Shortcuts ──
    client = data.get("client", {})
    firm = data.get("cpa_firm", {})
    tax_year = str(data.get("tax_year", "2025"))
    next_year = str(int(tax_year) + 1) if tax_year.isdigit() else "2026"

    # ════════════════════════════════════════
    # BODY — Email Content
    # (No letterhead — handled by email/ShareFile system)
    # ════════════════════════════════════════

    # Greeting
    _add_paragraph(doc, "Dear Client,", size=11, space_after=12)

    # Introduction
    firm_name = firm.get("name", "our firm")
    _add_paragraph(
        doc,
        f"Your {tax_year} Income Tax Return and {firm_name} invoice are now available "
        f"on the ShareFile portal.",
        size=11,
        space_after=8,
    )

    # E-file authorization notice
    _add_paragraph(
        doc,
        "E-file authorization forms will be sent to you in a separate ShareFile email. "
        "Please review and sign these documents electronically at your earliest convenience, "
        "as we are unable to submit your return to the taxing authorities without your authorization.",
        size=11,
        space_after=16,
    )

    # ── Current Year Tax Payment Summary ──
    _add_paragraph(doc, f"{tax_year} Tax Payment Summary", bold=True, size=11, space_after=8)

    tax_summary = data.get("tax_summary", {}) or {}

    # Federal sentence (AI-authored, with **bold** markdown)
    fed_sentence = tax_summary.get("federal_sentence")
    if fed_sentence:
        _add_markdown_paragraph(doc, f"Federal Income Tax: {fed_sentence}", space_after=4)

    # State sentence(s)
    state_sentences = tax_summary.get("state_sentences", []) or []
    multi_state = len(state_sentences) > 1
    for st in state_sentences:
        sentence = st.get("sentence")
        if not sentence:
            continue
        if multi_state:
            abbr = st.get("state_abbreviation") or st.get("state_name", "State")
            label = f"{abbr} State"
        else:
            label = "State"
        _add_markdown_paragraph(doc, f"{label} Income Tax: {sentence}", space_after=8)

    # ── Next Year Estimated Tax Payments ──
    estimated = data.get("estimated_payments", [])
    if estimated:
        _add_paragraph(
            doc,
            f"{next_year} Tax Payment Summary",
            bold=True,
            size=11,
            space_before=8,
            space_after=8,
        )

        has_federal_est = any((ep.get("federal") or 0) > 0 for ep in estimated)
        has_state_est = any((ep.get("state") or 0) > 0 for ep in estimated)

        intro_parts = []
        if has_federal_est and has_state_est:
            intro_parts.append("Federal and state estimated tax payments")
        elif has_federal_est:
            intro_parts.append("Federal estimated tax payments")
        elif has_state_est:
            intro_parts.append("State estimated tax payments")
        else:
            intro_parts.append("Estimated tax payments")

        _add_paragraph(
            doc,
            f"{intro_parts[0]} will be automatically withdrawn as shown below",
            size=11,
            space_after=8,
        )

        # Build payment schedule table
        col_headers = ["Payment Date"]
        if has_federal_est:
            col_headers.append("Federal")
        if has_state_est:
            col_headers.append("State")

        table = doc.add_table(rows=1, cols=len(col_headers))
        table.style = "Table Grid"

        # Header row
        for i, header in enumerate(col_headers):
            cell = table.rows[0].cells[i]
            cell.text = header
            for para in cell.paragraphs:
                for run in para.runs:
                    run.font.bold = True
                    run.font.size = Pt(10)
                    run.font.name = "Calibri"

        # Data rows
        for ep in estimated:
            row = table.add_row()
            col_idx = 0
            row.cells[col_idx].text = ep.get("date", "")
            col_idx += 1

            if has_federal_est:
                fed_amt = ep.get("federal") or 0
                row.cells[col_idx].text = _format_currency(fed_amt) if fed_amt else "—"
                col_idx += 1

            if has_state_est:
                state_amt = ep.get("state") or 0
                row.cells[col_idx].text = _format_currency(state_amt) if state_amt else "—"

            # Style data cells
            for cell in row.cells:
                for para in cell.paragraphs:
                    for run in para.runs:
                        run.font.size = Pt(10)
                        run.font.name = "Calibri"

        _add_paragraph(doc, "", space_after=8)  # spacing after table

    # ── PTE Payments — render only for passthrough returns (code-level guard) ──
    return_type = data.get("return_type")
    if return_type in PTE_ELIGIBLE_RETURN_TYPES:
        for pte in data.get("pte_payments", []) or []:
            sentence = pte.get("sentence")
            if sentence:
                _add_markdown_paragraph(doc, sentence, space_after=8)


    # ── ShareFile Instructions ──
    _add_paragraph(doc, "Instructions for Accessing ShareFile", bold=True, size=11, space_after=8)
    subdomain = firm.get("sharefile_subdomain", "")
    sharefile_steps = [
        "1. Visit the ShareFile website at https://www.sharefile.com/",
        f'2. Enter "{subdomain}" as the subdomain' if subdomain else '2. Enter the firm subdomain',
        "3. Enter your email address",
        '4. If you forgot your password, click "Forgot password" to reset your password',
    ]
    for step in sharefile_steps:
        _add_paragraph(doc, step, size=11, space_after=2)

    _add_paragraph(doc, "", space_after=4)
    _add_paragraph(
        doc,
        "Should you experience any difficulty accessing the portal or have questions regarding "
        "the enclosed documents, please do not hesitate to contact our office for assistance.",
        size=11,
        space_after=16,
    )


    # Save document
    doc.save(output_path)


# ═══════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="ITR Tax Packaging AI — Extract e-consent pages and generate email templates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 itr_packaging.py "Trevor K Holloway DDS Inc ITR 2025 Original.pdf"
  python3 itr_packaging.py input.pdf --output-dir ./results
  python3 itr_packaging.py input.pdf --model gemini-2.5-pro
        """,
    )
    parser.add_argument("pdf", help="Path to the ITR PDF file")
    parser.add_argument(
        "--output-dir", "-o", default=None, help="Output directory (default: ./output next to input)"
    )
    parser.add_argument(
        "--model", "-m", default=DEFAULT_MODEL, help=f"Gemini model (default: {DEFAULT_MODEL})"
    )
    parser.add_argument("--env-file", default=None, help="Path to .env file with GEMINI_API_KEY")

    args = parser.parse_args()

    # ── Validate input ──
    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.exists():
        print(f"❌ File not found: {pdf_path}")
        sys.exit(1)
    if not pdf_path.suffix.lower() == ".pdf":
        print(f"❌ Not a PDF file: {pdf_path}")
        sys.exit(1)

    # ── Output directory ──
    output_dir = Path(args.output_dir).resolve() if args.output_dir else Path(__file__).parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── API key ──
    api_key = load_api_key(args.env_file)
    if not api_key:
        print("❌ GEMINI_API_KEY not found.")
        print("   Set it as environment variable or in a .env file.")
        sys.exit(1)

    # ═══════════════════════════════════════════════════════════
    print()
    print("═" * 60)
    print("🏛️  ITR Tax Packaging AI — Demo")
    print("═" * 60)

    # ── Step 1: AI Analysis (two sequential calls) ──
    print(f"\n📄 STEP 1: Analyzing ITR with Gemini AI (2 calls)")
    print(f"   {'─' * 45}")

    pdf_bytes = Path(pdf_path).read_bytes()
    page1_bytes = extract_page1_bytes(str(pdf_path))

    # Run both calls in parallel — they're independent inputs
    with ThreadPoolExecutor(max_workers=2) as executor:
        fut1 = executor.submit(
            call_gemini, pdf_bytes, TASK1_PROMPT, TASK1_CONFIG, api_key, args.model, "Task 1"
        )
        fut2 = executor.submit(
            call_gemini, page1_bytes, TASK2_PROMPT, TASK2_CONFIG, api_key, args.model, "Task 2"
        )
        task1_data, t1_usage = fut1.result()
        task2_data, t2_usage = fut2.result()

    analysis_data = {**task2_data, **task1_data}

    # Aggregate token usage across both calls
    token_usage = {
        k: t1_usage.get(k, 0) + t2_usage.get(k, 0)
        for k in ("input_tokens", "output_tokens", "thinking_tokens",
                  "total_tokens", "input_cost", "output_cost",
                  "thinking_cost", "total_cost")
    }

    # Save raw JSON for inspection
    json_out = output_dir / "analysis_result.json"
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(analysis_data, f, indent=2, ensure_ascii=False)
    print(f"   ✅ Analysis complete → {json_out.name}")

    # Token usage & cost — per-task breakdown
    for label, usage in [("Task 1", t1_usage), ("Task 2", t2_usage)]:
        print(f"\n   📊 Token Usage [{label}]:")
        print(f"      Input:    {usage['input_tokens']:,} tokens  (${usage['input_cost']:.4f})")
        print(f"      Output:   {usage['output_tokens']:,} tokens  (${usage['output_cost']:.4f})")
        if usage['thinking_tokens'] > 0:
            print(f"      Thinking: {usage['thinking_tokens']:,} tokens  (${usage['thinking_cost']:.4f})")
        print(f"      Total:    {usage['total_tokens']:,} tokens  → ${usage['total_cost']:.4f}")
    print(f"\n   💰 Combined cost: ${token_usage['total_cost']:.4f}")

    # Summary
    print(f"\n   📋 Return Type:  {analysis_data.get('return_type', '?')}")
    print(f"   📋 Tax Year:     {analysis_data.get('tax_year', '?')}")
    print(f"   📋 Client:       {analysis_data.get('client', {}).get('name', '?')}")
    print(f"   📋 CPA Firm:     {analysis_data.get('cpa_firm', {}).get('name', '?')}")

    econsent_pages = analysis_data.get("econsent_pages", [])
    econsent_forms = analysis_data.get("econsent_forms", [])
    print(f"   📋 E-consent pages: {econsent_pages}")
    for form_info in econsent_forms:
        fn = form_info.get("form_number", "?").removeprefix("Form ").removeprefix("form ")
        jd = form_info.get("jurisdiction", "?")
        pp = form_info.get("pages", [])
        print(f"      • Form {fn} ({jd}) → page(s) {pp}")

    # ── Step 2: Extract E-Consent PDF ──
    econsent_out = output_dir / "Econsent.pdf"
    print(f"\n📑 STEP 2: Extracting e-consent pages")
    print(f"   {'─' * 45}")

    if econsent_pages:
        success = extract_econsent_pdf(str(pdf_path), econsent_pages, str(econsent_out))
        if success:
            page_count = len(econsent_pages)
            size_kb = econsent_out.stat().st_size / 1024
            print(f"   ✅ Econsent.pdf → {econsent_out.name}")
            print(f"      {page_count} page(s), {size_kb:.1f} KB")
        else:
            print("   ⚠️  Extraction failed — check page numbers.")
    else:
        print("   ⚠️  No e-consent pages detected by AI.")

    # ── Step 3: Generate Email Template ──
    email_out = output_dir / "email_template.docx"
    print(f"\n✉️  STEP 3: Generating email template")
    print(f"   {'─' * 45}")

    generate_email_docx(analysis_data, str(email_out))
    size_kb = email_out.stat().st_size / 1024
    print(f"   ✅ email_template.docx → {email_out.name} ({size_kb:.1f} KB)")

    # ── Final Summary ──
    print(f"\n{'═' * 60}")
    print("✅ ALL DONE — Output files:")
    print(f"   📊 {json_out}")
    print(f"   📑 {econsent_out}")
    print(f"   ✉️  {email_out}")
    print(f"{'═' * 60}\n")


if __name__ == "__main__":
    main()
