# Product Requirements Document — ITR Extract

**Version:** 2.0
**Status:** Active baseline
**Last updated:** 2026-05-08

---

## 1. Vision

Tự động hóa workflow CPA xử lý Income Tax Return (ITR) PDF: từ extract dữ liệu → sinh email cho client → tạo Outlook draft với attachment e-consent. Mục tiêu giảm thời gian một CPA xử lý 1 hồ sơ ITR từ ~15 phút thủ công xuống <2 phút.

## 2. Problem statement

CPA firms ở Mỹ phải xử lý hàng trăm hồ sơ ITR mỗi mùa thuế. Mỗi hồ sơ yêu cầu:

1. Đọc cover letter để biết tax outcome (balance due / overpayment / refund / credit / zero)
2. Soạn email gửi client với câu summary đúng nghiệp vụ
3. Tách các trang e-consent (Form 8879, 8453, FTB 8453...) thành PDF riêng để client ký
4. Đính kèm vào draft email trong Outlook

Workflow thủ công tốn thời gian, dễ sai sót khi paraphrase outcome, và không scale.

## 3. Target users

| Persona        | Mô tả                                                | Use case chính                                                |
| -------------- | ---------------------------------------------------- | ------------------------------------------------------------- |
| **CPA staff**  | Nhân viên thuế tại CPA firm (Mỹ), Microsoft 365 user | Upload ITR PDF, review email AI sinh, tạo draft trong Outlook |
| **Firm admin** | Manager quản lý license/quota                        | (V2) Theo dõi usage, billing                                  |

## 4. Core use cases

### UC-1: Process single ITR

1. CPA login bằng Microsoft 365 work account
2. Upload PDF ITR (≤50MB)
3. Hệ thống extract trong ~30-60s:
   - Tax outcome (federal + state)
   - Client info (name, email, address)
   - E-consent form pages
4. CPA review email preview (có thể edit inline)
5. CPA chọn forms cần đính kèm e-consent
6. CPA điền email người nhận → "Create Outlook Draft"
7. Hệ thống tạo draft trong mailbox của CPA (qua Microsoft Graph), CPA mở Outlook gửi đi

### UC-2: Reprocess failed job

- Job FAILED do Gemini lỗi → CPA click "Reprocess" → hệ thống tạo job mới từ PDF gốc.

### UC-3: Manage history

- Xem 10 job gần nhất
- Switch giữa job để review/copy email
- Xóa job không cần (cùng files trên server)

## 5. Success metrics

| Metric                                      | Target                 |
| ------------------------------------------- | ---------------------- |
| Time from upload → email draft created      | < 90s p95              |
| Email outcome accuracy (vs. CPA review)     | ≥ 95%                  |
| AI hallucination rate (cover letter values) | ≤ 1%                   |
| System availability                         | 99.5% (business hours) |
| User satisfaction (CSAT)                    | ≥ 4.0/5.0              |

## 6. Out of scope (V2.0)

- Bulk upload (multiple PDFs cùng lúc)
- Direct send mail (chỉ tạo draft, CPA phải tự gửi)
- E-signature integration (DocuSign/HelloSign)
- Multi-language (English only)
- State tax forms khác ngoài CA/NY/NJ/IL
- Mobile app
- Prior-year ITR migration tools
- Analytics dashboard cho firm admin

## 7. Constraints

### Compliance

- PDF chứa PII (SSN, income, addresses) — không bao giờ commit vào git, không log content
- Storage trên server tier có encryption-at-rest
- Token Microsoft 365 lưu sessionStorage (per-tab, không persist)
- E-consent forms phải đúng pháp lý — không edit pages, chỉ trích xuất

### Technical

- Single tenant per deployment (mỗi CPA firm 1 instance hoặc 1 tenant ID Azure AD)
- Microsoft 365 work account (production) hoặc personal (dev only)
- Gemini API quota theo deployment
- PostgreSQL + Redis bắt buộc

### Business

- Khách hàng IT admin phải grant consent cho 3 scopes: `User.Read`, `Mail.ReadWrite`, custom `access_as_user`
- Pricing per Gemini call (~$0.005-0.05/job tùy PDF size)

## 8. Non-goals

Không thay thế phần mềm tax prep (Lacerte, ProSystem fx, UltraTax). Chỉ là layer post-processing sau khi tax return đã được prepare và export PDF.

## 9. Stakeholders

| Role             | Responsibility                              |
| ---------------- | ------------------------------------------- |
| Product Owner    | Roadmap, prioritization, customer feedback  |
| Engineering      | Build, deploy, monitor                      |
| QA               | Validate AI output accuracy via test corpus |
| Customer Success | Onboard CPA firms, training                 |
| Compliance       | PII review, legal forms accuracy            |

## 10. Roadmap snapshot

| Version          | Status     | Highlights                                                           |
| ---------------- | ---------- | -------------------------------------------------------------------- |
| **V1**           | Released   | CLI standalone, single PDF in/out                                    |
| **V2** (current) | In testing | Web UI, multi-user auth, async jobs, history, Mail draft integration |
| V2.1             | None       | Bulk upload (queue 1 PDF/job), retry policy refine                   |
| V3               | None       | Multi-firm SaaS, billing, admin dashboard                            |

## 11. Related documents

- [docs/SRS.md](SRS.md) — chi tiết requirements & rules
- [README.md](../README.md) — setup & runbook
