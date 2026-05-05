"""Unit tests for main.py pure-logic helpers.

Run:  python3 test_main.py -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from docx import Document

import main as itr


class TestMarkdownParagraph(unittest.TestCase):
    def setUp(self):
        self.doc = Document()

    def test_plain_text_has_one_non_bold_run(self):
        para = itr._add_markdown_paragraph(self.doc, "Hello world.")
        self.assertEqual(len(para.runs), 1)
        self.assertEqual(para.runs[0].text, "Hello world.")
        self.assertFalse(para.runs[0].font.bold)

    def test_single_bold_segment_alternates(self):
        para = itr._add_markdown_paragraph(self.doc, "Refund of **$2,052** deposited.")
        texts = [r.text for r in para.runs]
        bolds = [bool(r.font.bold) for r in para.runs]
        self.assertEqual(texts, ["Refund of ", "$2,052", " deposited."])
        self.assertEqual(bolds, [False, True, False])

    def test_multiple_bold_segments(self):
        text = "**Overpayment** of **$3,597** of which **$3,597** credited to 2026 tax."
        para = itr._add_markdown_paragraph(self.doc, text)
        bolds = [bool(r.font.bold) for r in para.runs]
        texts = [r.text for r in para.runs]
        # Leading "" segment is dropped; runs are: Overpayment, " of ", $3,597, " of which ", $3,597, " credited to 2026 tax."
        self.assertEqual(texts[0], "Overpayment")
        self.assertTrue(bolds[0])
        self.assertIn("$3,597", texts)

    def test_no_literal_asterisks_in_rendered_runs(self):
        para = itr._add_markdown_paragraph(self.doc, "A **B** C")
        for run in para.runs:
            self.assertNotIn("**", run.text)


class TestExtractPage1Bytes(unittest.TestCase):
    SAMPLE = Path(__file__).parent / "samples" / "Yamane, Jon H & Gail ITR 2025.pdf"

    def test_returns_non_empty_bytes(self):
        data = itr.extract_page1_bytes(str(self.SAMPLE))
        self.assertIsInstance(data, bytes)
        self.assertGreater(len(data), 1000)

    def test_result_is_a_one_page_pdf(self):
        import fitz
        data = itr.extract_page1_bytes(str(self.SAMPLE))
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            self.assertEqual(doc.page_count, 1)
        finally:
            doc.close()

    def test_first_page_text_preserved(self):
        import fitz
        data = itr.extract_page1_bytes(str(self.SAMPLE))
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            text = doc[0].get_text()
        finally:
            doc.close()
        self.assertIn("CNY LLP", text)
        self.assertIn("YAMANE", text)


if __name__ == "__main__":
    unittest.main()
