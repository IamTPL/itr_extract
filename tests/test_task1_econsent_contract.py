from pathlib import Path


PROMPT_PATH = Path("prompts/task1_econsent.txt")


def test_california_partnership_authorization_uses_official_8453_p_number():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "California: FTB 8453, FTB 8453-C, FTB 8453-P, FTB 8453-LLC" in prompt
