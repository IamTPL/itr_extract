from types import SimpleNamespace
from pathlib import Path
import sys

import fitz

from jobs import pipeline


def _one_page_pdf_bytes():
    doc = fitz.open()
    try:
        doc.new_page().insert_text((72, 72), "full-pdf")
        return doc.write()
    finally:
        doc.close()


def test_run_extraction_uses_shared_cover_selector_only_for_task2(monkeypatch):
    full_pdf = _one_page_pdf_bytes()
    selected_letter = b"selected-letter-pdf"
    received = {}

    monkeypatch.setattr(
        pipeline,
        "get_settings",
        lambda: SimpleNamespace(gemini_api_key="test-key"),
    )
    monkeypatch.setattr(
        pipeline.itr,
        "extract_cover_letter_bytes",
        lambda value: selected_letter,
        raising=False,
    )

    def fake_call_gemini(pdf_bytes, _prompt, _config, _key, _model, task_name, *_args):
        received[task_name] = pdf_bytes
        if task_name == "Task 1":
            return {"econsent_pages": []}, {}
        return {}, {}

    monkeypatch.setattr(pipeline.itr, "call_gemini", fake_call_gemini)
    monkeypatch.setattr(pipeline, "generate_email_html", lambda _data: "email")

    pipeline.run_extraction(full_pdf)

    assert received["Task 1"] == full_pdf
    assert received["Task 2"] == selected_letter


def test_run_extraction_applies_full_pdf_pte_evidence_before_render(monkeypatch):
    full_pdf = _one_page_pdf_bytes()
    task2_data = {
        "return_type": "S-Corporation (1120S)",
        "scheduled_payments": [{"type": "pte", "jurisdiction": "California", "amount": 1, "date": "06/15/2026", "payment_method": "direct_debit", "ordinal": None, "source_quote": "q", "note": None}],
    }
    calls = []
    rendered = []

    monkeypatch.setattr(
        pipeline,
        "get_settings",
        lambda: SimpleNamespace(gemini_api_key="test-key"),
    )
    monkeypatch.setattr(
        pipeline.itr,
        "extract_cover_letter_bytes",
        lambda _value: b"selected-letter-pdf",
    )

    def fake_call_gemini(_pdf, _prompt, _config, _key, _model, task_name, *_args):
        if task_name == "Task 1":
            return {"econsent_pages": []}, {}
        return task2_data, {}

    def fake_apply(pdf_bytes, value):
        calls.append((pdf_bytes, value))
        return {**value, "pte_evidence_applied": True}

    monkeypatch.setattr(pipeline.itr, "call_gemini", fake_call_gemini)
    monkeypatch.setattr(
        pipeline.itr,
        "apply_ftb_first_pte_ordinal",
        fake_apply,
        raising=False,
    )
    monkeypatch.setattr(
        pipeline,
        "generate_email_html",
        lambda data: rendered.append(data) or "email",
    )

    analysis_data, _, _ = pipeline.run_extraction(full_pdf)

    assert calls[0][0] == full_pdf
    assert calls[0][1]["return_type"] == "S-Corporation (1120S)"
    assert calls[0][1]["needs_review"] is True  # letter bytes giả → verbatim check flag
    assert analysis_data["pte_evidence_applied"] is True
    assert rendered[0]["pte_evidence_applied"] is True


def test_cli_uses_cover_selector_and_full_pdf_pte_evidence(tmp_path, monkeypatch):
    source_path = tmp_path / "return.pdf"
    full_pdf = _one_page_pdf_bytes()
    source_path.write_bytes(full_pdf)
    output_dir = tmp_path / "output"
    selected_letter = b"selected-letter-pdf"
    selected_inputs = []
    evidence_inputs = []
    rendered = []

    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", str(source_path), "--output-dir", str(output_dir)],
    )
    monkeypatch.setattr(pipeline.itr, "load_api_key", lambda _env_file: "test-key")
    monkeypatch.setattr(
        pipeline.itr,
        "extract_cover_letter_bytes",
        lambda value: selected_inputs.append(value) or selected_letter,
    )

    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "thinking_tokens": 0,
        "total_tokens": 0,
        "input_cost": 0,
        "output_cost": 0,
        "thinking_cost": 0,
        "total_cost": 0,
    }

    def fake_call_gemini(pdf_bytes, _prompt, _config, _key, _model, task_name, *_args):
        if task_name == "Task 1":
            assert pdf_bytes == full_pdf
            return {"econsent_pages": [], "econsent_forms": []}, usage
        assert pdf_bytes == selected_letter
        return {
            "return_type": "S-Corporation (1120S)",
            "tax_year": "2025",
            "client": {"name": "Client"},
            "cpa_firm": {"name": "CNY LLP"},
            "scheduled_payments": [{"type": "pte", "jurisdiction": "California", "amount": 1, "date": "06/15/2026", "payment_method": "direct_debit", "ordinal": None, "source_quote": "q", "note": None}],
        }, usage

    def fake_apply(pdf_bytes, value):
        evidence_inputs.append((pdf_bytes, value))
        return {**value, "pte_evidence_applied": True}

    def fake_generate_docx(data, output_path):
        rendered.append(data)
        Path(output_path).write_bytes(b"docx")

    monkeypatch.setattr(pipeline.itr, "call_gemini", fake_call_gemini)
    monkeypatch.setattr(pipeline.itr, "apply_ftb_first_pte_ordinal", fake_apply)
    monkeypatch.setattr(pipeline.itr, "generate_email_docx", fake_generate_docx)

    pipeline.itr.main()

    assert selected_inputs == [str(source_path.resolve())]
    assert evidence_inputs[0][0] == full_pdf
    assert rendered[0]["pte_evidence_applied"] is True
