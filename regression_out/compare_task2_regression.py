"""So sánh baseline vs after: diff text HTML đã normalize + chênh lệch tập số tiền.

Dùng: venv/bin/python regression_out/compare_task2_regression.py \
        regression_out/baseline regression_out/after regression_out/report.md
"""
import difflib
import pathlib
import re
import sys


def html_lines(path: pathlib.Path) -> list[str]:
    text = re.sub(r"<[^>]+>", "\n", path.read_text())
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return [line for line in lines if line]


def amounts(lines: list[str]) -> set[str]:
    return set(re.findall(r"\$[\d,]+(?:\.\d{2})?", " ".join(lines)))


def main() -> None:
    base, after, out = (pathlib.Path(a) for a in sys.argv[1:4])
    report: list[str] = ["# Task 2 facts — regression report\n"]
    for base_html in sorted(base.glob("*.html")):
        after_html = after / base_html.name
        report.append(f"\n{'=' * 80}\n## {base_html.stem}\n")
        if not after_html.exists():
            report.append("**MISSING** trong after/")
            continue
        old, new = html_lines(base_html), html_lines(after_html)
        diff = list(difflib.unified_diff(old, new, "baseline", "after", lineterm=""))
        report.append("(không có khác biệt text)" if not diff else "```diff\n" + "\n".join(diff) + "\n```")
        gone, added = amounts(old) - amounts(new), amounts(new) - amounts(old)
        if gone or added:
            report.append(f"\n**AMOUNTS** mất: {sorted(gone)} — thêm: {sorted(added)}")
        if any("NEEDS REVIEW" in line for line in new):
            report.append("\n**⚠️ CÓ REVIEW BLOCK** — theo catalog phải là 0 với 8 samples")
    out.write_text("\n".join(report))
    print(f"report: {out}")


if __name__ == "__main__":
    main()
