# ITR Extract — CYNU Microsoft Setup (Bestarion thực hiện giùm)

> **Cập nhật 2026-07-11:** CYNU **không có bộ phận IT** (lead xác nhận) → Bestarion sẽ tự thực hiện phần cấu hình Microsoft trên tenant của khách, dùng tài khoản admin do khách cung cấp — giống mô hình đã làm với GoDaddy.
> File này gồm: **(A)** mẫu email xin quyền truy cập, **(B)** kịch bản từng bước để người của Bestarion thực hiện.

---

## A. Mẫu email gửi khách (tiếng Anh)

> **Subject:** ITR Extract — Microsoft setup (~15 mins)

Hi [Name],

The app is live at **https://itr.cynu.com**. One last step: approving it in your Microsoft 365 — we'll handle this for you, like we did with the domain.

Could you:
1. Reply with your **Microsoft 365 admin email address** (the account that manages your company email — no password yet);
2. Suggest a convenient time — at that point we'll need a **temporary password** (you can change it right after) and a **verification code** Microsoft may text you, like the GoDaddy step.

We'll only approve the app and note your organization ID — nothing else will be changed.

Thanks!
Long — Bestarion

---

## B. Kịch bản thực hiện (người Bestarion làm, khi có tài khoản admin CYNU)

**Chuẩn bị:**
- Dùng **cửa sổ ẩn danh** (Ctrl+Shift+N) cho TOÀN BỘ phiên làm việc — tránh lẫn session Microsoft của Bestarion.
- Hẹn khách **online sẵn** để đọc mã OTP (Microsoft nhiều khả năng gửi mã về điện thoại/email của họ).
- Mở sẵn file này để làm theo từng bước.

**Các bước:**

1. **Đăng nhập** tài khoản admin CYNU tại `portal.azure.com` (cửa sổ ẩn danh). Vượt MFA bằng mã khách đọc.
2. **Lấy Tenant ID:** menu → **Microsoft Entra ID** → **Overview** → copy ô **Tenant ID** → lưu lại (đây là giá trị cho Pha C).
3. **Grant admin consent:** mở link (cùng cửa sổ ẩn danh đó):
   ```
   https://login.microsoftonline.com/cynu.com/adminconsent?client_id=dca257ea-bb51-40cd-8e80-5e32abd9752e
   ```
   *(Nếu báo lỗi tenant → thay `cynu.com` trong link bằng Tenant ID vừa lấy ở bước 2.)*
   Màn hình Microsoft liệt kê đúng **3 quyền** (bảng dưới) → bấm **Accept** → trình duyệt chuyển về `https://itr.cynu.com` là xong.

   | Quyền hiển thị | Ý nghĩa |
   |---|---|
   | Sign in and read user profile | Đọc tên/email khi nhân viên CYNU đăng nhập |
   | Read and write access to user mail | Tạo email **nháp** kết quả trong hộp thư của chính người dùng (không gửi được, không đụng hộp thư người khác) |
   | Access ITR Extract API | Gọi API của app |

4. **Kiểm tra consent đã ghi:** Entra ID → **Enterprise applications** → thấy **ITR_Extraction** xuất hiện trong danh sách (tab Permissions hiển thị 3 quyền granted).
5. ***(Tùy chọn — chỉ khi khách yêu cầu giới hạn người dùng):*** Enterprise applications → ITR_Extraction → **Properties** → *Assignment required?* = **Yes** → Save → **Users and groups** → thêm đích danh các nhân viên khách chỉ định.
6. **Đăng xuất + đóng toàn bộ cửa sổ ẩn danh.** Nhắn khách: *"We're done — feel free to change the password now."*
7. Ghi lại: ngày giờ truy cập, các bước đã làm (đúng danh sách trên, không gì khác) — để minh bạch với khách khi cần.

**Sau đó (phía hệ thống mình):** thực hiện **Pha C flip** với Tenant ID vừa lấy — theo mục PHA C trong [RUNBOOK-AWS.md](RUNBOOK-AWS.md) hoặc mục 2.7 trong [deploy_tutorial.md](deploy_tutorial.md).

**Nguyên tắc:** chỉ làm đúng các bước trên — không tạo/sửa/xóa user, không đụng cấu hình email, không cài thêm gì vào tenant khách.
