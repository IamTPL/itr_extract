# ITR Tax Packaging AI

Tự động phân tích file PDF Income Tax Return (ITR) bằng Gemini AI để:

1. **Detect & extract** các trang e-consent → `output/Econsent.pdf`
2. **Extract dữ liệu** và sinh email template → `output/email_template.docx`

## Cấu trúc dự án

```text
tax-package/
├── README.md
├── .gitignore
├── requirements.txt
├── main.py                # Core module
├── test_main.py  # Unit tests
├── samples/               # Sample PDFs dùng để test (gitignored)
├── output/                # Generated files (gitignored)
└── docs/
    └── architecture.md    # Thiết kế kỹ thuật
```

## Cài đặt

```bash
pip install -r requirements.txt
```

## Cấu hình

Copy template `.env.example` → `.env` và điền API key (file `.env` đã gitignored):

```bash
cp .env.example .env
# rồi mở .env và điền GEMINI_API_KEY
```

Hoặc export environment variable:

```bash
export GEMINI_API_KEY=your_api_key_here
```

Lấy key tại: <https://aistudio.google.com/apikey>

## Chạy

### Chạy Backend API

Khởi chạy FastAPI server để cung cấp endpoint `POST /api/process`:

```bash
uvicorn api:app --reload
```

Server sẽ mặc định chạy tại `http://localhost:8000`.

### Chạy bằng CLI (Standalone)

```bash
python3 main.py "samples/<TEN_FILE>.pdf"
```

#### Ví dụ CLI

```bash
python3 main.py "samples/Trevor K Holloway DDS Inc ITR 2025 Original.pdf"
```

#### OptionsCLI

```bash
# Dùng model khác
python3 main.py input.pdf --model gemini-2.5-pro

# Chỉ định output directory
python3 main.py input.pdf --output-dir ./results

# Chỉ định .env file
python3 main.py input.pdf --env-file /path/to/.env
```

## Output

Kết quả lưu tại `output/` (mặc định):

| File                   | Nội dung                       |
| ---------------------- | ------------------------------ |
| `analysis_result.json` | Raw data AI phân tích (debug)  |
| `Econsent.pdf`         | Các trang e-consent trích xuất |
| `email_template.docx`  | Email template đã fill data    |

## How it works

Script thực hiện 2 lời gọi Gemini tuần tự:

1. **Task 1 — E-Consent Detection**: gửi toàn bộ PDF, quét tìm các trang e-file authorization (Form 8879, 8453, FTB 8453...).
2. **Task 2 — Email Data Extraction**: chỉ gửi page 1 (cover letter) để trích xuất dữ liệu email và sinh các câu tóm tắt tax payment summary theo 5 pattern nghiệp vụ (Balance due / Overpayment credited / Refund deposited / Partial credit + partial refund / Zero outcome). AI dùng Markdown `**bold**` cho keyword + số tiền, Python parse thành bold runs trong DOCX.

Config mỗi task (temperature, thinking_budget, timeout) nằm ở `TASK1_CONFIG` / `TASK2_CONFIG` trong `main.py`. PTE payments được gate 2 lớp (prompt + code whitelist `return_type`) — chỉ render cho S-Corp (1120S) và Partnership (1065).

Chi tiết thiết kế: [`docs/architecture.md`](docs/architecture.md)

## Unit tests

```bash
python3 test_main.py -v
```
