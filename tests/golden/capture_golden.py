"""Capture golden fixtures cho tests/test_golden_cases.py.

Gọi Gemini THẬT (temperature 0) trên từng PDF và đóng băng 5 artifact/case:
  raw_facts.json       — Task 2 thô từ Gemini, TRƯỚC validation
  letter.txt           — text letter (letter_text_from_pdf)
  validated_facts.json — sau validate_facts (golden của tầng validation)
  final_analysis.json  — analysis_data đầy đủ (sau ordinal FTB + merge Task 1)
  expected_email.html  — HTML email đã render (golden của tầng render)
  meta.json            — nguồn gốc + ngày capture

Dùng:
  # toàn bộ samples local:
  venv/bin/python tests/golden/capture_golden.py --outdir tests/golden/cases --samples-dir samples
  # từng case tên tuỳ chọn (dùng cho prod trên server):
  venv/bin/python tests/golden/capture_golden.py --outdir CASES "prod_096a56c6=/path/input.pdf"

Quy trình đầy đủ (kể cả chạy trên server production): docs/TESTING.md.
"""
import argparse
import copy
import datetime
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import main as itr  # noqa: E402
from config.settings import get_settings  # noqa: E402
from jobs.email_html import generate_email_html  # noqa: E402
from jobs.facts_validation import letter_text_from_pdf, validate_facts  # noqa: E402


def _write_json(path: pathlib.Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def capture_case(name: str, pdf_path: pathlib.Path, outdir: pathlib.Path) -> None:
    api_key = get_settings().gemini_api_key
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")
    pdf_bytes = pdf_path.read_bytes()

    cover = itr.extract_cover_letter_bytes(pdf_bytes)
    t1, _ = itr.call_gemini(
        pdf_bytes, itr.TASK1_PROMPT, itr.TASK1_CONFIG, api_key, itr.DEFAULT_MODEL, "Task 1",
    )
    t2_raw, _ = itr.call_gemini(
        cover, itr.TASK2_PROMPT, itr.TASK2_CONFIG, api_key, itr.DEFAULT_MODEL, "Task 2",
        itr.TASK2_RESPONSE_SCHEMA,
    )
    letter = letter_text_from_pdf(cover)
    validated = validate_facts(t2_raw, letter)
    # deepcopy: giữ `validated` đúng là output validate_facts, không dính ordinal
    final_t2 = itr.apply_ftb_first_pte_ordinal(pdf_bytes, copy.deepcopy(validated))
    analysis = {**final_t2, **t1}
    html = generate_email_html(analysis)

    case = outdir / name
    case.mkdir(parents=True, exist_ok=True)
    _write_json(case / "raw_facts.json", t2_raw)
    (case / "letter.txt").write_text(letter)
    _write_json(case / "validated_facts.json", validated)
    _write_json(case / "final_analysis.json", analysis)
    (case / "expected_email.html").write_text(html)
    _write_json(case / "meta.json", {
        "source": str(pdf_path),
        "captured": datetime.date.today().isoformat(),
    })
    print(f"done: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--samples-dir", help="capture mọi *.pdf trong thư mục này")
    parser.add_argument("pairs", nargs="*", help="NAME=PDF_PATH")
    args = parser.parse_args()
    outdir = pathlib.Path(args.outdir)

    jobs: list[tuple[str, pathlib.Path]] = []
    if args.samples_dir:
        for pdf in sorted(pathlib.Path(args.samples_dir).glob("*.pdf")):
            stem = re.sub(r"[^A-Za-z0-9]+", "_", pdf.stem).strip("_")
            jobs.append((f"sample_{stem}", pdf))
    for pair in args.pairs:
        name, _, path = pair.partition("=")
        jobs.append((name, pathlib.Path(path)))

    failed = []
    for name, pdf in jobs:
        try:
            capture_case(name, pdf, outdir)
        except Exception as exc:  # tiếp tục các case còn lại, báo cuối
            failed.append((name, repr(exc)))
            print(f"FAILED: {name}: {exc!r}")
    if failed:
        sys.exit(f"{len(failed)} case failed: {failed}")


if __name__ == "__main__":
    main()
