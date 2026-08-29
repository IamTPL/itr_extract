import re
from html import escape

from config.constants import INVOICE_BRAND_NAME
from jobs import summary_sentences as ss
from jobs.tax_labels import resolve_tax_summary_labels


def _md_to_html(text: str) -> str:
    """Escape dynamic text, then convert **bold** markers to safe HTML tags."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escape(text))


def _review_div(prefix: str, item: dict) -> str:
    body = escape(f"{prefix}{ss.review_note(item)}") if prefix else escape(ss.review_note(item))
    return ('<div style="background:#fff3cd;border:1px solid #e0a800;'
            'border-radius:4px;padding:8px 12px;margin:0 0 10px 0;">'
            f"{body}</div>")


def generate_email_html(data: dict) -> str:
    """
    Generate HTML email body from analysis_data.
    Mirrors generate_email_docx() logic but outputs an HTML string
    suitable for Outlook draft via Microsoft Graph API.
    """
    firm = data.get("cpa_firm", {}) or {}
    tax_year = str(data.get("tax_year", ""))
    next_year = str(int(tax_year) + 1) if tax_year.isdigit() else ""
    escaped_tax_year = escape(tax_year)
    escaped_next_year = escape(next_year)
    subdomain = firm.get("sharefile_subdomain", "")

    p = '<p style="margin:0 0 10px 0;">'
    lines = []
    lines.append('<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt;line-height:1.6;color:#000;">')

    lines.append(f'{p}Dear Client,</p>')
    lines.append(
        f'{p}Your {escaped_tax_year} Income Tax Return and {INVOICE_BRAND_NAME} invoice are now available '
        f'on the ShareFile portal.</p>'
    )
    lines.append(
        f'{p}E-file authorization forms will be sent to you in a separate ShareFile email. '
        f'Please review and sign these documents electronically at your earliest convenience, '
        f'as we are unable to submit your return to the taxing authorities without your authorization.</p>'
    )

    # ── Current Year Tax Payment Summary ──
    lines.append(f'<p style="margin:16px 0 8px 0;"><strong>{escaped_tax_year} Tax Payment Summary</strong></p>')

    jurisdictions = data.get("jurisdictions", []) or []
    scheduled = data.get("scheduled_payments", []) or []
    federal = next((j for j in jurisdictions if ss.is_federal(j.get("jurisdiction_name"))), None)
    states = [j for j in jurisdictions if j is not federal]

    if federal is not None:
        sentence = ss.jurisdiction_sentence(federal, next_year)
        if sentence is None:
            lines.append(_review_div("Federal Income Tax: ", federal))
        else:
            lines.append(f'{p}Federal Income Tax: {_md_to_html(sentence)}</p>')

    labels = resolve_tax_summary_labels(
        [{**j, "state_name": j.get("jurisdiction_name")} for j in states]
    )
    for j, label in zip(states, labels):
        sentence = ss.jurisdiction_sentence(j, next_year)
        if sentence is None:
            lines.append(_review_div(f"{label}: ", j))
        else:
            lines.append(f'{p}{escape(label)}: {_md_to_html(sentence)}</p>')

    # ── Next Year Tax Payment Summary ──
    est = ss.estimated_entries(scheduled)
    others = [e for e in scheduled if e.get("type") != "estimated" or e.get("needs_review")]
    if est or others:
        lines.append(f'<p style="margin:16px 0 8px 0;"><strong>{escaped_next_year} Tax Payment Summary</strong></p>')

    if est:
        lines.append(f'{p}{escape(ss.estimated_intro(est))}</p>')

        rows = ss.estimated_rows(est)
        has_fed = any(row["federal"] for row in rows)
        has_state = any(row["state"] for row in rows)

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
        for row in rows:
            lines.append('<tr>')
            lines.append(f'<td {td}>{escape(row["date"])}</td>')
            if has_fed:
                amt = row["federal"]
                lines.append(f'<td {td}>{ss.format_amount(amt) if amt else "—"}</td>')
            if has_state:
                amt = row["state"]
                lines.append(f'<td {td}>{ss.format_amount(amt) if amt else "—"}</td>')
            lines.append('</tr>')
        lines.append('</table>')

    for e in others:
        sentence = ss.scheduled_sentence(e, next_year)
        lines.append(_review_div("", e) if sentence is None
                     else f'{p}{_md_to_html(sentence)}</p>')

    # ── ShareFile Instructions ──
    lines.append(f'<p style="margin:16px 0 8px 0;"><strong>Instructions for Accessing ShareFile</strong></p>')
    lines.append('<ol style="margin:0 0 12px 0;padding-left:1.4em;">')
    lines.append('<li>Visit the ShareFile website at <a href="https://www.sharefile.com/">https://www.sharefile.com/</a></li>')
    if subdomain:
        lines.append(f'<li>Enter &ldquo;{escape(str(subdomain))}&rdquo; as the subdomain</li>')
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
