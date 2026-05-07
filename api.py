"""
ITR Extract — FastAPI backend wrapper.
Processes ITR PDF entirely in memory, returns JSON.
"""

import base64
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import fitz
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import main as itr

app = FastAPI(title="ITR Extract API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost",
    ],
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════════
# RESPONSE SCHEMA
# ═══════════════════════════════════════════════════════════════════

class ProcessResponse(BaseModel):
    econsent_pdf_b64: Optional[str]
    analysis_data: dict
    email_html: str


# ═══════════════════════════════════════════════════════════════════
# EMAIL HTML GENERATOR
# ═══════════════════════════════════════════════════════════════════

def _md_to_html(text: str) -> str:
    """Convert **bold** markdown markers to <strong> HTML tags."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)


def generate_email_html(data: dict) -> str:
    """
    Generate HTML email body from analysis_data.
    Mirrors generate_email_docx() logic but outputs an HTML string
    suitable for Outlook draft via Microsoft Graph API.
    """
    firm = data.get("cpa_firm", {}) or {}
    tax_year = str(data.get("tax_year", ""))
    next_year = str(int(tax_year) + 1) if tax_year.isdigit() else ""
    tax_summary = data.get("tax_summary", {}) or {}
    estimated = data.get("estimated_payments", []) or []
    return_type = data.get("return_type")
    firm_name = firm.get("name", "our firm")
    subdomain = firm.get("sharefile_subdomain", "")

    p = '<p style="margin:0 0 10px 0;">'
    lines = []
    lines.append('<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt;line-height:1.6;color:#000;">')

    lines.append(f'{p}Dear Client,</p>')
    lines.append(
        f'{p}Your {tax_year} Income Tax Return and {firm_name} invoice are now available '
        f'on the ShareFile portal.</p>'
    )
    lines.append(
        f'{p}E-file authorization forms will be sent to you in a separate ShareFile email. '
        f'Please review and sign these documents electronically at your earliest convenience, '
        f'as we are unable to submit your return to the taxing authorities without your authorization.</p>'
    )

    # ── Current Year Tax Payment Summary ──
    lines.append(f'<p style="margin:16px 0 8px 0;"><strong>{tax_year} Tax Payment Summary</strong></p>')

    fed_sentence = tax_summary.get("federal_sentence")
    if fed_sentence:
        lines.append(f'{p}Federal Income Tax: {_md_to_html(fed_sentence)}</p>')

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
        lines.append(f'{p}{label} Income Tax: {_md_to_html(sentence)}</p>')

    # ── Next Year Estimated Tax Payments ──
    if estimated:
        lines.append(f'<p style="margin:16px 0 8px 0;"><strong>{next_year} Tax Payment Summary</strong></p>')

        has_fed = any((ep.get("federal") or 0) > 0 for ep in estimated)
        has_state = any((ep.get("state") or 0) > 0 for ep in estimated)

        if has_fed and has_state:
            intro = "Federal and state estimated tax payments"
        elif has_fed:
            intro = "Federal estimated tax payments"
        else:
            intro = "State estimated tax payments"
        lines.append(f'{p}{intro} will be automatically withdrawn as shown below</p>')

        # Table
        td = 'style="border:1px solid #ccc;padding:6px 10px;"'
        th = 'style="border:1px solid #ccc;padding:6px 10px;background:#f2f2f2;font-weight:bold;"'
        lines.append('<table style="border-collapse:collapse;font-size:10pt;margin-bottom:12px;">')
        lines.append('<tr>')
        lines.append(f'<th {th}>Payment Date</th>')
        if has_fed:
            lines.append(f'<th {th}>Federal</th>')
        if has_state:
            lines.append(f'<th {th}>State</th>')
        lines.append('</tr>')
        for ep in estimated:
            lines.append('<tr>')
            lines.append(f'<td {td}>{ep.get("date", "")}</td>')
            if has_fed:
                amt = ep.get("federal") or 0
                lines.append(f'<td {td}>{"${:,.0f}".format(amt) if amt else "—"}</td>')
            if has_state:
                amt = ep.get("state") or 0
                lines.append(f'<td {td}>{"${:,.0f}".format(amt) if amt else "—"}</td>')
            lines.append('</tr>')
        lines.append('</table>')

    # ── PTE Payments (passthrough returns only) ──
    if return_type in itr.PTE_ELIGIBLE_RETURN_TYPES:
        for pte in data.get("pte_payments", []) or []:
            sentence = pte.get("sentence")
            if sentence:
                lines.append(f'{p}{_md_to_html(sentence)}</p>')

    # ── ShareFile Instructions ──
    lines.append(f'<p style="margin:16px 0 8px 0;"><strong>Instructions for Accessing ShareFile</strong></p>')
    lines.append('<ol style="margin:0 0 12px 0;padding-left:1.4em;">')
    lines.append('<li>Visit the ShareFile website at <a href="https://www.sharefile.com/">https://www.sharefile.com/</a></li>')
    if subdomain:
        lines.append(f'<li>Enter &ldquo;{subdomain}&rdquo; as the subdomain</li>')
    else:
        lines.append('<li>Enter the firm subdomain</li>')
    lines.append('<li>Enter your email address</li>')
    lines.append('<li>If you forgot your password, click &ldquo;Forgot password&rdquo; to reset your password</li>')
    lines.append('</ol>')
    lines.append(
        f'{p}Should you experience any difficulty accessing the portal or have questions regarding '
        f'the enclosed documents, please do not hesitate to contact our office for assistance.</p>'
    )

    lines.append('</div>')
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# ENDPOINT
# ═══════════════════════════════════════════════════════════════════

@app.post("/api/process", response_model=ProcessResponse)
async def process_pdf(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    api_key = itr.load_api_key()
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured on server")

    # Extract page 1 in-memory for Task 2 (no disk writes)
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    out_doc = fitz.open()
    out_doc.insert_pdf(src, from_page=0, to_page=0)
    page1_bytes = out_doc.write()
    out_doc.close()
    src.close()

    # Run both Gemini calls in parallel
    with ThreadPoolExecutor(max_workers=2) as executor:
        fut1 = executor.submit(
            itr.call_gemini,
            pdf_bytes, itr.TASK1_PROMPT, itr.TASK1_CONFIG,
            api_key, itr.DEFAULT_MODEL, "Task 1",
        )
        fut2 = executor.submit(
            itr.call_gemini,
            page1_bytes, itr.TASK2_PROMPT, itr.TASK2_CONFIG,
            api_key, itr.DEFAULT_MODEL, "Task 2",
            itr.TASK2_RESPONSE_SCHEMA,
        )
        task1_data, _ = fut1.result()
        task2_data, _ = fut2.result()

    analysis_data = {**task2_data, **task1_data}

    # Extract Econsent pages in-memory
    econsent_b64 = None
    econsent_pages = analysis_data.get("econsent_pages", [])
    if econsent_pages:
        src = fitz.open(stream=pdf_bytes, filetype="pdf")
        valid_pages = sorted([
            p - 1 for p in econsent_pages
            if isinstance(p, int) and 1 <= p <= src.page_count
        ])
        if valid_pages:
            new_doc = fitz.open()
            for idx in valid_pages:
                new_doc.insert_pdf(src, from_page=idx, to_page=idx)
            econsent_b64 = base64.standard_b64encode(new_doc.write()).decode("utf-8")
            new_doc.close()
        src.close()

    return ProcessResponse(
        econsent_pdf_b64=econsent_b64,
        analysis_data=analysis_data,
        email_html=generate_email_html(analysis_data),
    )
