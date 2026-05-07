# Báo cáo Solution — ITR Tax Packaging AI

**Ngày:** 2026-05-06
**Phạm vi:** Tự động hóa quy trình xử lý ITR PDF → tạo email draft Outlook + đính kèm file Econsent

---

## 1. Yêu cầu của khách hàng (KH)

| # | Yêu cầu |
|---|---------|
| 1 | Input: file PDF ITR (Income Tax Return) của từng khách hàng CPA firm — 50+ trang |
| 2 | Tự động trích xuất các trang **e-consent / e-file authorization** (Form 8879, FTB 8453, v.v.) ra file **Econsent.pdf** |
| 3 | Tự động đọc trang cover letter và sinh sẵn nội dung email gửi cho client, bao gồm: tóm tắt số thuế phải nộp/hoàn, lịch estimated tax payments, hướng dẫn ShareFile |
| 4 | Tạo **email draft** trực tiếp trong **Microsoft Outlook** của nhân viên (để review trước khi gửi) |
| 5 | Có thể điền sẵn địa chỉ **To:** của email |
| 6 | **Đính kèm file Econsent.pdf** vào draft email |
| 7 | Số user sử dụng: < 10 người |
| 8 | Không lưu lại dữ liệu PDF trên server (zero-storage / stateless) |

---

## 2. Solution đề xuất

Hệ thống được xây dựng dưới dạng một **web application** chạy trên server (Ubuntu VPS) của bên mình, gồm hai phần: **giao diện web** (frontend) và **xử lý nghiệp vụ** (backend).

### Luồng xử lý tổng thể

```
[1] Nhân viên mở website
         │ chưa đăng nhập → chỉ thấy màn hình login
         ▼
[2] Đăng nhập Microsoft 365
         │ redirect sang trang login của Microsoft
         │ xác thực thành công → nhận OAuth token
         ▼
[3] Giao diện upload hiện ra
         │ nhân viên kéo thả file "ClientName ITR 2025.pdf"
         ▼
[4] Browser gửi PDF + OAuth token lên Backend
         │
         ├──▶ Backend xác thực token với Microsoft
         │
         ├──▶ Gọi Gemini AI — Task 1 (song song):
         │         Toàn bộ PDF → phát hiện trang e-consent (Form 8879, FTB 8453...)
         │
         └──▶ Gọi Gemini AI — Task 2 (song song):
                   Chỉ trang 1 (cover letter) → trích xuất: tên client, số thuế,
                   estimated payments, PTE payments
         │
         ▼
[5] Backend trả về kết quả (không lưu gì trên server):
         - Nội dung email (HTML) với bold formatting cho số tiền, ngày tháng
         - File Econsent.pdf (các trang e-consent đã tách ra)
         │
         ▼
[6] Nhân viên xem preview email trên giao diện
         │ nhập địa chỉ To: của client → nhấn "Create Draft"
         ▼
[7] Browser gọi Microsoft Graph API (bằng token của nhân viên):
         - Tạo draft email trong Outlook của nhân viên
         - Điền sẵn: To, Subject, Body (HTML)
         - Đính kèm file Econsent.pdf
         │
         ▼
[8] Nhân viên vào Outlook, review draft → gửi
```

### Các thành phần kỹ thuật

| Thành phần | Công nghệ | Vai trò |
|-----------|-----------|---------|
| Giao diện web | React + TypeScript | Màn hình login, upload PDF, preview email, nhập To: |
| Xác thực Microsoft | MSAL.js (thư viện chính thức của Microsoft) | Đăng nhập M365, lấy OAuth token để gọi Graph API |
| Backend API | FastAPI (Python) + Uvicorn | Nhận PDF, xử lý nghiệp vụ, gọi Gemini AI |
| Web server | Nginx (reverse proxy) | Serve giao diện web + chuyển tiếp request đến backend |
| Xử lý PDF | PyMuPDF | Trích xuất trang e-consent ra file Econsent.pdf |
| Tạo email draft | Microsoft Graph API | Tạo draft trong Outlook, điền nội dung, đính kèm file |
| AI | Google Gemini 2.5 Flash | Xem mục 3 |

> **Lưu ý bảo mật:** Gemini API key chỉ nằm trên backend server, không bao giờ xuất hiện trong browser. Toàn bộ PDF được xử lý trong bộ nhớ (in-memory) và không được lưu lại trên server sau khi xử lý xong.

---

## 3. AI Service sử dụng

### Model: Google Gemini 2.5 Flash

| Thông số | Giá trị |
|---------|---------|
| Model | `gemini-2.5-flash-preview` |
| Provider | Google AI (Gemini API) |
| Cách lấy API key | https://aistudio.google.com/apikey (miễn phí đăng ký) |

### 2 lời gọi AI mỗi file PDF

| | Task 1 — E-Consent Detection | Task 2 — Email Data Extraction |
|---|---|---|
| Input | Toàn bộ PDF (50+ trang) | Chỉ trang 1 (cover letter) |
| Nhiệm vụ | Quét tìm các trang Form 8879, FTB 8453, v.v. và trả về số trang | Đọc cover letter, trích xuất: tên client, số thuế, estimated payments, PTE payments |
| Output | `{econsent_pages: [...], econsent_forms: [...]}` | `{tax_summary, estimated_payments, pte_payments, ...}` |
| Thinking budget | 4096 tokens | 0 (tắt thinking — không cần cho trang đơn) |
| Timeout | 240s | 120s |

### Chi phí AI (ước tính)

Dựa trên test thực tế với 2 file PDF mẫu:

| Hạng mục | Chi phí |
|---------|---------|
| Mỗi file ITR xử lý | ~$0.01–0.02 |
| 100 file/tháng | ~$1.00–2.00 |
| 500 file/tháng | ~$5.00–10.00 |

**Pricing Gemini 2.5 Flash (tham khảo tại thời điểm build):**

| Loại token | Giá |
|-----------|-----|
| Input | $0.50 / 1M tokens |
| Output | $3.00 / 1M tokens |
| Thinking | $3.00 / 1M tokens |

> Giá thực tế có thể thay đổi. Tham khảo tại: https://ai.google.dev/pricing

---

## 4. Yêu cầu hạ tầng & cấu hình

### 4.1 Server (client đã có sẵn)

| Yêu cầu | Chi tiết |
|---------|---------|
| Hệ điều hành | Ubuntu VPS (đã có) |
| Web server | Nginx (đã có) |
| Python | Python 3.10+ |
| Cổng | 443 (HTTPS) qua Nginx → proxy vào FastAPI port 8000 |
| RAM tối thiểu | 1 GB (xử lý PDF 50+ trang in-memory) |
| Domain/subdomain | Cần cấu hình sau (hiện tại test trên localhost + ngrok) |

### 4.2 Microsoft Azure AD — App Registration (BẮT BUỘC)

Đây là bước **client CPA firm phải thực hiện** (hoặc IT admin của họ):

| Bước | Mô tả |
|------|-------|
| 1 | Vào https://portal.azure.com → Azure Active Directory → App registrations |
| 2 | Tạo app mới, ghi lại **Client ID** và **Tenant ID** |
| 3 | Thêm **Redirect URI**: `http://localhost:5173` (dev) / domain thật (prod) |
| 4 | Cấp quyền Microsoft Graph API: **`Mail.ReadWrite`** (để tạo draft email) và **`User.Read`** (để xác thực login) |
| 5 | Bật **"Allow public client flows"** (cho PKCE / MSAL.js) |

> Không cần secret key — app dùng OAuth 2.0 PKCE flow (an toàn cho SPA).

### 4.3 API Keys

| Key | Mô tả | Lưu ở đâu |
|-----|-------|-----------|
| `GEMINI_API_KEY` | Google Gemini API key | File `.env` trên server (không commit vào git) |
| Microsoft `clientId` + `tenantId` | Từ Azure App Registration | Config trong frontend build |

---

## 5. Luồng hoạt động (User Flow)

```
1. Nhân viên CPA firm mở website
2. Đăng nhập bằng tài khoản Microsoft 365 (SSO, trang login của Microsoft)
3. Kéo thả file "ClientName ITR 2025.pdf" vào ô upload
4. App gửi PDF lên backend → backend gọi Gemini AI (~30–60 giây)
5. Kết quả hiện ra:
   - Preview nội dung email (Federal tax: ..., State tax: ..., Estimated payments: ...)
   - Tên client, tax year được điền sẵn
6. Nhân viên nhập địa chỉ email To: của client
7. Nhấn "Create Draft in Outlook"
   - App tạo draft email trong Outlook của nhân viên
   - Đính kèm Econsent.pdf (các trang Form 8879)
   - Điền sẵn Subject và Body (HTML formatted)
8. Nhân viên vào Outlook, review draft, gửi
```

---

## 6. Security & Data Privacy

| Vấn đề | Giải pháp |
|--------|-----------|
| API key Gemini bị lộ | Key chỉ nằm trên server (backend), không bao giờ xuất hiện trong browser |
| Dữ liệu PDF nhạy cảm | Xử lý in-memory, không ghi disk, không lưu database |
| Truy cập trái phép | Yêu cầu đăng nhập Microsoft 365 hợp lệ trước khi xử lý bất kỳ file nào |
| Token OAuth | PKCE flow — không có client secret trong frontend |
| Dữ liệu qua server bên thứ 3 | Dùng VPS tự quản lý, không qua Railway/Render/Vercel |

---

## 7. Tóm tắt chi phí vận hành hàng tháng

| Hạng mục | Chi phí |
|---------|---------|
| VPS Ubuntu | $0 (client đã có sẵn) |
| Gemini API | ~$1–10/tháng (tùy số lượng file) |
| Microsoft 365 | $0 thêm (đã có license) |
| Domain/SSL | Cần thuê thêm (sau khi lên production) |
| **Tổng ước tính** | **~$1–10/tháng + domain** |

---

## 8. Trạng thái hiện tại

| Phase | Nội dung | Trạng thái |
|-------|---------|-----------|
| Core AI engine | Python CLI: xử lý PDF → Econsent.pdf + email template | ✅ Hoàn thành |
| Backend API | FastAPI endpoint `/api/process` | ✅ Hoàn thành |
| Frontend | React app: upload, preview, create draft | ✅ Hoàn thành (Phase 1–2) |
| Microsoft Graph integration | Login MSAL.js + tạo Outlook draft | ⏳ Phase 3 — chờ Azure App Registration từ client |
| Production deployment | Domain, SSL, Nginx config | ⏳ Sau khi có domain |
