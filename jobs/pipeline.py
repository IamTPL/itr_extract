"""Pure pipeline: bytes in → (analysis_data, email_html, econsent_pdf_bytes_or_None)."""
import fitz
from concurrent.futures import ThreadPoolExecutor
import main as itr
from config.settings import get_settings
from jobs.email_html import generate_email_html

# Hard cap mỗi Gemini call. Phải nhỏ hơn JOB_TIMEOUT_SECONDS (300s)
# để worker không bị arq kill trước khi raise TimeoutError có ý nghĩa.
_GEMINI_HARD_TIMEOUT_S = 270


def run_extraction(pdf_bytes: bytes) -> tuple[dict, str, bytes | None]:
    # Source of truth = pydantic Settings (đọc .env hoặc env var thống nhất),
    # không gọi `itr.load_api_key` parser thủ công nữa.
    api_key = get_settings().gemini_api_key
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    cover_letter_bytes = itr.extract_cover_letter_bytes(pdf_bytes)

    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(
            itr.call_gemini,
            pdf_bytes, itr.TASK1_PROMPT, itr.TASK1_CONFIG,
            api_key, itr.DEFAULT_MODEL, "Task 1",
        )
        f2 = ex.submit(
            itr.call_gemini,
            cover_letter_bytes, itr.TASK2_PROMPT, itr.TASK2_CONFIG,
            api_key, itr.DEFAULT_MODEL, "Task 2",
            itr.TASK2_RESPONSE_SCHEMA,
        )
        t1, _ = f1.result(timeout=_GEMINI_HARD_TIMEOUT_S)
        t2, _ = f2.result(timeout=_GEMINI_HARD_TIMEOUT_S)
    t2 = itr.apply_ftb_first_pte_ordinal(pdf_bytes, t2)
    analysis_data = {**t2, **t1}

    econsent_bytes: bytes | None = None
    pages = analysis_data.get("econsent_pages") or []
    if pages:
        src = fitz.open(stream=pdf_bytes, filetype="pdf")
        valid = sorted(p - 1 for p in pages if isinstance(p, int) and 1 <= p <= src.page_count)
        if valid:
            new_doc = fitz.open()
            for idx in valid:
                new_doc.insert_pdf(src, from_page=idx, to_page=idx)
            econsent_bytes = new_doc.write()
            new_doc.close()
        src.close()

    email_html = generate_email_html(analysis_data)
    return analysis_data, email_html, econsent_bytes
