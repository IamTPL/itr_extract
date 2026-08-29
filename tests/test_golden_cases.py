"""Golden regression — đóng băng output đã xác nhận đúng (samples/ + jobs production).

Mỗi case dưới tests/golden/cases/<tên>/ gồm input đã đóng băng (raw_facts.json,
letter.txt, final_analysis.json) và output kỳ vọng (validated_facts.json,
expected_email.html). Test chạy OFFLINE — không gọi Gemini, không cần PDF.

Fixture chứa dữ liệu client nên KHÔNG commit (tests/golden/cases/ nằm trong
.gitignore). Máy không có fixture → module tự skip. Quy trình tạo lại fixture,
cập nhật golden khi đổi wording chủ đích: xem docs/TESTING.md.
"""
import json
import os
from pathlib import Path

import pytest

from jobs.email_html import generate_email_html
from jobs.facts_validation import validate_facts

CASES_DIR = Path(__file__).parent / "golden" / "cases"
UPDATE = os.environ.get("UPDATE_GOLDENS") == "1"

CASES = sorted(
    p for p in CASES_DIR.iterdir() if (p / "raw_facts.json").is_file()
) if CASES_DIR.is_dir() else []

if not CASES:
    pytest.skip(
        "Không có golden fixtures (dữ liệu client — không commit). Xem docs/TESTING.md",
        allow_module_level=True,
    )

_HINT = "Diff là thay đổi CHỦ ĐÍCH? → chạy: UPDATE_GOLDENS=1 pytest tests/test_golden_cases.py"


def _load(case: Path, name: str):
    return json.loads((case / name).read_text())


def _dump(case: Path, name: str, data) -> None:
    (case / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_validation_golden(case):
    got = validate_facts(_load(case, "raw_facts.json"), (case / "letter.txt").read_text())
    if UPDATE:
        _dump(case, "validated_facts.json", got)
        return
    assert got == _load(case, "validated_facts.json"), _HINT


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_render_golden(case):
    got = generate_email_html(_load(case, "final_analysis.json"))
    if UPDATE:
        (case / "expected_email.html").write_text(got)
        return
    expected = (case / "expected_email.html").read_text()
    assert got.splitlines() == expected.splitlines(), _HINT


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_final_analysis_consistent_with_validated(case):
    """final_analysis phải = validated_facts + Task 1 + ordinal FTB.

    Nếu test này fail sau khi UPDATE_GOLDENS: fixture final_analysis.json đã cũ
    so với logic validation mới → RE-CAPTURE case đó (docs/TESTING.md), vì
    ordinal FTB cần PDF gốc, không tự dựng lại được ở đây.
    """
    validated = _load(case, "validated_facts.json")
    final = _load(case, "final_analysis.json")

    def norm(d):
        d = json.loads(json.dumps(d))
        for e in d.get("scheduled_payments") or []:
            e.pop("ordinal", None)
        return d

    final_t2_part = {k: final.get(k) for k in validated}
    assert norm(final_t2_part) == norm(validated)
