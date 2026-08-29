"""Chạy pipeline trên toàn bộ samples/ và lưu JSON + HTML per file.

Dùng:  venv/bin/python regression_out/run_task2_regression.py regression_out/baseline
Gọi Gemini thật (~17s + vài cent mỗi file). Không ghi DB.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from jobs.pipeline import run_extraction  # noqa: E402


def main() -> None:
    outdir = pathlib.Path(sys.argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    for pdf in sorted(pathlib.Path("samples").glob("*.pdf")):
        data, html, _econsent = run_extraction(pdf.read_bytes())
        stem = pdf.stem.replace(" ", "_").replace(",", "")
        (outdir / f"{stem}.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False)
        )
        (outdir / f"{stem}.html").write_text(html)
        print(f"done: {pdf.name}")


if __name__ == "__main__":
    main()
