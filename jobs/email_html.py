import re
from main import PTE_ELIGIBLE_RETURN_TYPES


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
    if return_type in PTE_ELIGIBLE_RETURN_TYPES:
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
