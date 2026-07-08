# Runbook: Deploy ITR Extract lên AWS EC2

> Hướng dẫn deploy **từng bước, dành cho người mới**, viết riêng cho instance AWS mà IT đã cấp.
> Đọc [deploy/README.md](README.md) nếu muốn bản gốc tổng quát. File này là bản **thực chiến** cho tình huống cụ thể của bạn.

## Chiến lược (nhắc lại để bạn nhớ)

- **Mục tiêu:** production cho khách hàng, chạy trên **IP tĩnh (Elastic IP)**.
- **Giai đoạn 1 (Pha A + B):** dựng đầy đủ hạ tầng, cho khách **dùng thử** với đăng nhập tạm (chấp nhận tài khoản Microsoft bất kỳ).
- **Giai đoạn 2 (Pha C):** khi có **Tenant ID + admin consent** của khách → siết lên **production auth thật** (chỉ đổi cấu hình + build lại frontend, **không sửa code**).
- **1 tên miền duy nhất:** frontend ở `/`, backend ở `/api` → gọn, không lo CORS.

---

## Ghi chú triển khai thực tế (baseline)

> Runbook này đã được điều chỉnh theo **cách triển khai thực tế** để dùng làm tài liệu tham chiếu.

**Khác biệt chính so với thiết kế gốc:** dịch vụ chạy bằng user Linux **`ubuntu`** có sẵn (KHÔNG tạo user `itr` riêng) — chấp nhận đánh đổi bảo mật (ubuntu có `sudo`) để đơn giản hóa cho giai đoạn dùng thử. Do đó: code đặt ở `/opt` thuộc sở hữu `ubuntu`; 2 file systemd trong repo dùng `User`/`Group` = `ubuntu`; các lệnh bỏ tiền tố `sudo -u itr`; `chown` dùng `ubuntu:ubuntu`.

> ⚠️ User **database** vẫn là `itr` (tạo ở A2) — đây là tài khoản của PostgreSQL, KHÁC với user Linux. Vì vậy `DATABASE_URL` giữ nguyên `itr:...`.

**Tiến độ (cập nhật 2026-07-08):**
- [x] A1 — cài phần mềm nền (Postgres 16, Redis 7, nginx 1.24, Node 22)
- [x] A2 — PostgreSQL: user `itr` + DB `itr_extract`
- [x] A3 — Redis
- [x] A4 — code về `/opt` (clone bằng `ubuntu`)
- [x] A5 — cài thư viện Python (`.venv`)
- [x] A6 — thư mục file `/var/lib/itr_extract`
- [x] A7 — file env `/etc/itr_extract/{api,worker}.env`
- [x] A8 — migrations (tạo bảng: alembic_version, jobs, users)
- [ ] A9 — systemd services ← đang ở đây
- [ ] A10 — kiểm tra `/healthz`
- [ ] Pha B — mở ra Internet (chờ Elastic IP)
- [ ] Pha C — production auth (chờ Tenant ID khách)

---

## 0. Quy ước — điền 1 lần rồi dùng xuyên suốt

Trong runbook có các "chỗ trống" dạng `<...>`. Điền giá trị của bạn vào bảng này rồi thay khi gặp:

| Ký hiệu | Ý nghĩa | Giá trị của bạn |
|---|---|---|
| `<ELASTIC_IP>` | Elastic IP sau khi IT cấp | `............` (chờ IT) |
| `<HOST>` | Tên miền công khai | `itr.bestarion.com` **hoặc** `<ELASTIC_IP dạng gạch nối>.nip.io` (vd `1-2-3-4.nip.io`) |
| `<DB_PASSWORD>` | Mật khẩu database (tự sinh ở bước A2) | `............` |
| `<GEMINI_KEY>` | Gemini API key | Copy từ file `.env` local (dòng `GEMINI_API_KEY=`) |
| `<AZURE_CLIENT_ID>` | Client ID app Azure | `dca257ea-bb51-40cd-8e80-5e32abd9752e` *(kiểm tra khớp với `.env` local)* |

> **Client ID không phải bí mật** (nó lộ ra trong trình duyệt) nên ghi thẳng được.
> **Gemini key và mật khẩu DB là bí mật** — không commit, không gửi chat.

---

## 1. Checklist chuẩn bị (làm trước, phần lâu nhất)

- [ ] **SSH vào được máy** (xem mục 2 bên dưới).
- [ ] **IT đã cấp Elastic IP** và gắn vào instance `i-0d4965bad3a8b2bf9` → ghi vào `<ELASTIC_IP>`. *(Bắt buộc cho Pha B)*
- [ ] **IT đã mở Security Group** inbound: **22** (SSH), **80** (HTTP), **443** (HTTPS).
- [ ] *(Nếu xin được)* IT tạo DNS `itr.bestarion.com` → `<ELASTIC_IP>`. Không có thì dùng `nip.io`.
- [ ] Có **Gemini API key** (đã có trong `.env` local).
- [ ] Có **Client ID Azure** (đã có: `dca257ea-…`).
- [ ] Quyền vào **portal.azure.com** để thêm Redirect URI (bước B6).
- [ ] *(Pha C — làm song song từ giờ)* Xin **Tenant ID** của khách + nhờ **admin bên khách grant consent**.

> **Pha A không cần Elastic IP** — bạn có thể chạy hết Pha A ngay hôm nay, chờ IT là chạy tiếp Pha B.

---

## 2. Kết nối SSH vào máy chủ

```bash
# Lần đầu: copy chìa khóa từ Teams (tải về Windows) vào WSL
cp /mnt/c/Users/<TênWindows>/Downloads/CNY_Key.pem ~/.ssh/CNY_Key.pem
chmod 600 ~/.ssh/CNY_Key.pem

# Kết nối (dùng Elastic IP nếu đã có, chưa thì dùng IP hiện tại 44.192.106.125)
ssh -i ~/.ssh/CNY_Key.pem ubuntu@<ELASTIC_IP>
```

Vào được sẽ thấy `ubuntu@ip-172-31-...:~$`. Từ giờ mọi lệnh **chạy TRÊN máy chủ này** (trừ khi ghi rõ "trên máy bạn").

> **Không SSH được?** → thường do Security Group chưa mở port 22, hoặc IP Whitelist chưa có IP của bạn → nhắn IT. Báo `Permission denied (publickey)` → sai key hoặc sai user (`ubuntu`).

---

# PHA A — Cài đặt nội bộ (KHÔNG cần Elastic IP)

Kết thúc Pha A: backend + worker + database chạy ngon **bên trong máy**, chỉ còn chờ "mở cửa ra internet" ở Pha B.

## A1. Cập nhật hệ thống & cài phần mềm nền

```bash
sudo apt update && sudo apt upgrade -y

# Kiểm tra phiên bản Ubuntu và Python có sẵn
lsb_release -a
python3 --version
```

Cài các gói nền:

```bash
sudo apt install -y postgresql redis-server nginx git \
    python3.12 python3.12-venv \
    certbot python3-certbot-nginx
```

> **Nếu báo không tìm thấy `python3.12`** (Ubuntu cũ hơn 24.04): thêm kho deadsnakes rồi cài lại:
> ```bash
> sudo add-apt-repository -y ppa:deadsnakes/ppa
> sudo apt update
> sudo apt install -y python3.12 python3.12-venv
> ```

Cài **Node.js 22** (để build frontend ở Pha B — cài luôn cho tiện):

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
node --version   # v22.x
```

## A2. PostgreSQL (database)

```bash
# Sinh 1 mật khẩu mạnh, an toàn cho URL — LƯU LẠI vào bảng mục 0
openssl rand -hex 24

# Tạo user 'itr' và database 'itr_extract'
sudo -u postgres createuser itr
sudo -u postgres createdb -O itr itr_extract
sudo -u postgres psql -c "ALTER USER itr WITH PASSWORD '<DB_PASSWORD>';"

# Bật Postgres chạy nền tự động
sudo systemctl enable --now postgresql
```

## A3. Redis (hàng đợi công việc)

```bash
sudo systemctl enable --now redis-server
redis-cli ping        # → PONG là ok
```

> Redis mặc định chỉ nghe ở `127.0.0.1` (nội bộ máy) — đúng như ta cần, không lộ ra ngoài.

## A4. Lấy code từ GitHub về `/opt` (chạy bằng user `ubuntu`)

> **Bản này chạy dịch vụ bằng user `ubuntu` có sẵn**, không tạo user `itr` riêng (xem *Ghi chú triển khai thực tế* ở đầu file). Code đặt tại `/opt` (ngoài `/home`) để giữ được lớp bảo vệ `ProtectHome` của systemd.

**Cho `ubuntu` quyền đọc repo private qua SSH.** Nếu `ubuntu` chưa có khóa GitHub, tạo và thêm vào GitHub:

```bash
# Tạo khóa cho ubuntu (nếu đã có ~/.ssh/id_ed25519 thì bỏ qua bước này)
ssh-keygen -t ed25519 -C "itr-server-deploy" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

→ Copy dòng `ssh-ed25519 ...`, thêm vào **GitHub → Settings → SSH and GPG keys → New SSH key** → Save. Kiểm tra:

```bash
ssh -o StrictHostKeyChecking=accept-new -T git@github.com
#   → "Hi IamTPL! You've successfully authenticated..." là ok
```

Clone **cả 2 repo** vào `/opt` (thư mục thuộc sở hữu `ubuntu`):

```bash
# Backend → /opt/itr_extract  (systemd trỏ đúng vào đây)
sudo mkdir -p /opt/itr_extract && sudo chown ubuntu:ubuntu /opt/itr_extract
git clone git@github.com:IamTPL/itr_extract.git /opt/itr_extract

# Frontend → /opt/itr_extract_fe
sudo mkdir -p /opt/itr_extract_fe && sudo chown ubuntu:ubuntu /opt/itr_extract_fe
git clone git@github.com:IamTPL/itr_extract_fe.git /opt/itr_extract_fe
```

> *Ghi chú lần chạy này:* code ban đầu được clone vào `~/itr/`, sau đó chuyển sang `/opt` bằng `sudo mv /home/ubuntu/itr/itr_extract /opt/itr_extract` (và tương tự cho `_fe`) — kết quả cuối giống hệt các lệnh trên.

## A5. Cài thư viện Python (backend)

```bash
cd /opt/itr_extract
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

## A6. Thư mục lưu file (PDF + kết quả)

```bash
sudo mkdir -p /var/lib/itr_extract/files
sudo chown -R ubuntu:ubuntu /var/lib/itr_extract
sudo chmod 700 /var/lib/itr_extract
```

## A7. File cấu hình (env) — GIAI ĐOẠN DÙNG THỬ

Backend đọc cấu hình từ 2 file env (api và worker giống nhau).

```bash
sudo mkdir -p /etc/itr_extract
sudo chown root:ubuntu /etc/itr_extract
sudo chmod 750 /etc/itr_extract

# Mở trình soạn thảo tạo file api.env
sudo nano /etc/itr_extract/api.env
```

Dán nội dung sau (thay `<DB_PASSWORD>` và `<GEMINI_KEY>`):

```bash
# === GIAI ĐOẠN DÙNG THỬ ===
# CHƯA đặt ENVIRONMENT=production (sẽ bật ở Pha C khi có Tenant ID).
# MSAL_TENANT_ID để TRỐNG = chấp nhận tài khoản Microsoft bất kỳ (chỉ dùng tạm).
DATABASE_URL=postgresql+asyncpg://itr:<DB_PASSWORD>@localhost:5432/itr_extract
REDIS_URL=redis://localhost:6379
MSAL_TENANT_ID=
MSAL_BE_CLIENT_ID=dca257ea-bb51-40cd-8e80-5e32abd9752e
GEMINI_API_KEY=<GEMINI_KEY>
ALLOWED_ORIGINS='["http://localhost:5173"]'
FILES_ROOT=/var/lib/itr_extract/files
```

> `ALLOWED_ORIGINS` để tạm localhost cũng được vì Pha A chỉ test nội bộ. **Pha B sẽ đổi thành `https://<HOST>`.**
>
> ⚠️ **Bắt buộc bọc nháy đơn** `'[...]'` quanh giá trị `ALLOWED_ORIGINS`. App phân tích nó dưới dạng JSON (cần nháy kép bên trong). Nếu chỉ viết `["..."]` không có nháy đơn ngoài, lệnh `source` ở A8 (và systemd ở A9) sẽ "ăn mất" nháy kép → JSON hỏng → lỗi `error parsing value for field "allowed_origins"`.

Lưu file (trong nano: `Ctrl+O` → Enter → `Ctrl+X`), phân quyền, và tạo bản copy cho worker:

```bash
sudo chown root:ubuntu /etc/itr_extract/api.env
sudo chmod 640 /etc/itr_extract/api.env
sudo cp /etc/itr_extract/api.env /etc/itr_extract/worker.env
sudo chown root:ubuntu /etc/itr_extract/worker.env
sudo chmod 640 /etc/itr_extract/worker.env
```

## A8. Tạo bảng database (migrations)

Vì cấu hình nằm ở `/etc/itr_extract/` chứ không phải `.env` trong thư mục code, ta **nạp env thủ công** khi chạy migration:

```bash
bash -c 'set -a; source /etc/itr_extract/api.env; set +a; cd /opt/itr_extract && .venv/bin/alembic upgrade head'
```

Kiểm tra đã có bảng:

```bash
sudo -u postgres psql -d itr_extract -c '\dt'
#   → phải thấy: alembic_version, jobs, users
```

## A9. Bật dịch vụ chạy nền (systemd)

2 file dịch vụ trong repo đã cấu hình sẵn `User=ubuntu`/`Group=ubuntu` (giữ `ProtectHome=true` vì code nằm ở `/opt`). Chỉ cần copy vào hệ thống rồi bật:

```bash
cd /opt/itr_extract
sudo cp deploy/itr-api.service    /etc/systemd/system/
sudo cp deploy/itr-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now itr-api itr-worker
sudo systemctl status itr-api itr-worker      # cả 2 phải "active (running)"
```

> **Dự phòng:** nếu bản clone trên máy còn cũ (service file vẫn `User=itr`), đổi nhanh rồi restart:
> ```bash
> sudo sed -i 's/^User=itr/User=ubuntu/; s/^Group=itr/Group=ubuntu/' \
>     /etc/systemd/system/itr-api.service /etc/systemd/system/itr-worker.service
> sudo systemctl daemon-reload && sudo systemctl restart itr-api itr-worker
> ```

Kiểm tra đã đổi đúng:

```bash
grep -E '^User=|^Group=' /etc/systemd/system/itr-api.service   # → User=ubuntu / Group=ubuntu
```

> **Dịch vụ không chạy?** Xem log ngay: `sudo journalctl -u itr-api -n 50` (thường do sai `DATABASE_URL` hoặc Postgres chưa chạy).

## A10. Kiểm tra backend

```bash
curl http://127.0.0.1:8000/healthz
#   → {"status":"ok"}   ✅ Pha A HOÀN THÀNH
```

---

# PHA B — Mở ra Internet (CẦN Elastic IP + hostname)

> Chỉ bắt đầu khi **IT đã cấp Elastic IP** và **mở port 80/443**.

## B1. Xác định `<HOST>`

- **Có subdomain** (`itr.bestarion.com`): kiểm tra DNS đã trỏ đúng:
  ```bash
  dig +short itr.bestarion.com     # phải in ra <ELASTIC_IP>
  ```
- **Dùng nip.io**: `<HOST>` = Elastic IP thay dấu chấm bằng gạch nối + `.nip.io`.
  Ví dụ Elastic IP `52.10.20.30` → `<HOST>` = `52-10-20-30.nip.io` (không cần cấu hình gì, tự trỏ về đúng IP).

Ghi `<HOST>` vào bảng mục 0.

## B2. Bật tường lửa trên máy (UFW)

```bash
sudo ufw allow 22
sudo ufw allow 80
sudo ufw allow 443
sudo ufw --force enable
sudo ufw status
```

> Đây là tường lửa **trong máy**. Security Group của AWS (do IT quản) là lớp tường lửa **bên ngoài** — cần mở cùng các port này.

## B3. Build frontend

Frontend "nướng" (bake) sẵn địa chỉ backend + cấu hình đăng nhập vào lúc build → **phải build với đúng `<HOST>`**.

```bash
sudo nano /opt/itr_extract_fe/.env.production
```

Dán (thay `<HOST>`):

```bash
VITE_API_BASE_URL=https://<HOST>
VITE_MSAL_CLIENT_ID=dca257ea-bb51-40cd-8e80-5e32abd9752e
VITE_MSAL_BE_CLIENT_ID=dca257ea-bb51-40cd-8e80-5e32abd9752e
VITE_MSAL_TENANT_ID=
```

> `VITE_MSAL_TENANT_ID` để **trống** trong giai đoạn dùng thử (khớp với backend). Pha C sẽ điền.

Build và đưa file tĩnh cho nginx phục vụ:

```bash
cd /opt/itr_extract_fe
npm ci
npm run build          # tạo thư mục dist/
sudo mkdir -p /var/www/itr_extract
sudo rsync -av --delete dist/ /var/www/itr_extract/
```

## B4. Cấu hình nginx (1 tên miền, FE ở `/`, BE ở `/api`)

```bash
sudo nano /etc/nginx/sites-available/itr_extract
```

Dán (thay `<HOST>`):

```nginx
server {
    listen 80;
    server_name <HOST>;

    root /var/www/itr_extract;
    index index.html;

    client_max_body_size 60M;      # cho upload PDF tối đa ~50MB

    # Backend API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
    location /healthz { proxy_pass http://127.0.0.1:8000; }

    # Frontend SPA (mọi đường dẫn khác trả về index.html)
    location / { try_files $uri /index.html; }
}
```

Bật site, bỏ site mặc định, kiểm tra cú pháp:

```bash
sudo ln -sf /etc/nginx/sites-available/itr_extract /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t                      # phải "syntax is ok"
sudo systemctl reload nginx
```

## B5. Cập nhật CORS + bật HTTPS

Đổi `ALLOWED_ORIGINS` sang tên miền thật rồi restart backend:

```bash
sudo nano /etc/itr_extract/api.env
#   sửa dòng:  ALLOWED_ORIGINS='["https://<HOST>"]'
sudo cp /etc/itr_extract/api.env /etc/itr_extract/worker.env
sudo chown root:ubuntu /etc/itr_extract/worker.env && sudo chmod 640 /etc/itr_extract/worker.env
sudo systemctl restart itr-api itr-worker
```

Lấy chứng chỉ HTTPS miễn phí (Let's Encrypt):

```bash
sudo certbot --nginx -d <HOST> -m longtp@bestarion.com --agree-tos --no-eff-email
sudo nginx -t && sudo systemctl reload nginx
```

> certbot cần `<HOST>` trỏ đúng về máy này và **port 80 mở** (SG + UFW). Xong nó tự thêm cấu hình 443 + tự chuyển hướng HTTP→HTTPS.

## B6. Đăng ký Redirect URI trên Azure

Đăng nhập Microsoft cần biết địa chỉ được phép quay về sau khi login.

1. Vào **portal.azure.com** → **Microsoft Entra ID** → **App registrations** → mở app có Client ID `dca257ea-…`.
2. **Authentication** → **Add a platform** → **Single-page application** (nếu chưa có).
3. Thêm Redirect URI: **`https://<HOST>`** → **Save**.

> **Lưu ý (giai đoạn dùng thử):** để nhận **mọi tài khoản Microsoft**, app phải ở loại *"any organizational directory + personal accounts"*. Nếu app đang là *single-tenant*, chỉ tài khoản trong tenant đó đăng nhập được. Kiểm tra ở tab **Overview → Supported account types**.

## B7. Kiểm tra toàn bộ (go-live dùng thử)

Trên **máy bạn**, mở trình duyệt: **`https://<HOST>`**
- [ ] Trang web hiện ra, có khóa 🔒 (HTTPS hợp lệ).
- [ ] Bấm đăng nhập → login bằng tài khoản Microsoft → quay lại app thành công.
- [ ] Upload 1 file PDF mẫu → job chuyển từ *pending* → *done*, tải được kết quả.

✅ **Pha B hoàn thành — khách có thể dùng thử.**

---

# PHA C — Siết lên PRODUCTION AUTH (khi có Tenant ID + admin consent)

Làm khi đã có **Tenant ID của khách** và **admin bên khách đã grant consent**.

**1. Phía Azure (khách hàng làm phần admin):**
- Admin của tenant khách **Grant admin consent** cho `User.Read`, `Mail.ReadWrite`, `access_as_user`.
- Đảm bảo `https://<HOST>` đã nằm trong Redirect URIs (đã thêm ở B6).

**2. Backend — bật chế độ chặt:**
```bash
sudo nano /etc/itr_extract/api.env
#   sửa/thêm 2 dòng:
#     ENVIRONMENT=production
#     MSAL_TENANT_ID=<tenant-id-của-khách>
sudo cp /etc/itr_extract/api.env /etc/itr_extract/worker.env
sudo chown root:ubuntu /etc/itr_extract/worker.env && sudo chmod 640 /etc/itr_extract/worker.env
sudo systemctl restart itr-api itr-worker
sudo systemctl status itr-api        # nếu fail → xem journalctl, thường do thiếu config
```

> Khi `ENVIRONMENT=production`, backend **tự kiểm tra nghiêm ngặt** và **từ chối khởi động** nếu thiếu `MSAL_TENANT_ID`, client ID còn placeholder, hoặc `ALLOWED_ORIGINS` còn `localhost` ([config/settings.py](../config/settings.py)).

**3. Frontend — build lại với Tenant ID:**
```bash
sudo nano /opt/itr_extract_fe/.env.production
#   sửa dòng:  VITE_MSAL_TENANT_ID=<tenant-id-của-khách>
cd /opt/itr_extract_fe
npm run build
sudo rsync -av --delete dist/ /var/www/itr_extract/
```

**4. Kiểm tra:** chỉ tài khoản **thuộc tổ chức khách** mới đăng nhập được; tài khoản ngoài bị từ chối. ✅ Production thật.

---

# Vận hành hằng ngày

**Xem log (theo thời gian thực):**
```bash
sudo journalctl -u itr-api -f       # backend API
sudo journalctl -u itr-worker -f    # worker xử lý PDF
```

**Cập nhật code mới (khi bạn push lên GitHub):**
```bash
# Backend
cd /opt/itr_extract
git pull
.venv/bin/pip install -r requirements.txt
bash -c 'set -a; source /etc/itr_extract/api.env; set +a; .venv/bin/alembic upgrade head'
sudo systemctl restart itr-api itr-worker

# Frontend
cd /opt/itr_extract_fe
git pull
npm ci
npm run build
sudo rsync -av --delete dist/ /var/www/itr_extract/
```

**Backup hằng ngày** (tùy chọn, khuyến nghị cho production): xem mục *Backups* trong [deploy/README.md](README.md).

**Gia hạn HTTPS:** certbot tự gia hạn. Kiểm tra:
```bash
sudo certbot renew --dry-run
```

**⚠️ CẢNH BÁO QUAN TRỌNG:**
- **Đừng "Stop" instance** nếu chưa gắn Elastic IP — IP sẽ đổi và làm hỏng toàn bộ (HTTPS, đăng nhập, frontend). "Reboot" thì an toàn.
- Nếu đã có Elastic IP thì Stop/Start vẫn giữ nguyên IP — an tâm hơn.

---

# Xử lý sự cố (Troubleshooting)

| Triệu chứng | Cách xử lý |
|---|---|
| SSH không vào được | IT mở Security Group port 22 / thêm IP bạn vào whitelist |
| `itr-api` báo `Production config validation failed` | Thiếu `MSAL_TENANT_ID` / client ID / `ALLOWED_ORIGINS` còn localhost trong `/etc/itr_extract/api.env` |
| Web mở ra nhưng **502 Bad Gateway** | `sudo systemctl status itr-api`; backend chưa chạy hoặc chưa nghe port 8000 |
| Lỗi kết nối DB liên quan SSL | Thử thêm `?ssl=disable` vào cuối `DATABASE_URL` |
| Upload PDF báo **413** | `client_max_body_size` trong nginx phải ≥ 50M (đã set 60M) |
| Job kẹt *pending* mãi | `sudo journalctl -u itr-worker -n 100`; kiểm tra Redis (`redis-cli ping`) |
| Đăng nhập MS lỗi *redirect_uri mismatch* | `https://<HOST>` chưa được thêm vào Redirect URIs của app Azure (bước B6) |
| certbot thất bại | `<HOST>` chưa trỏ đúng IP, hoặc port 80 chưa mở (SG + UFW) |
| API 401 `Wrong tenant` (giai đoạn thử) | Đảm bảo `MSAL_TENANT_ID` đang **để trống** (chưa lên Pha C) |

Danh sách đầy đủ các lỗi thường gặp: [docs/SETUP_REPORT.md](../docs/SETUP_REPORT.md) và [deploy/README.md](README.md).

---

# Checklist go-live (tick trước khi giao khách)

**Dùng thử (sau Pha B):**
- [ ] `https://<HOST>` mở được, HTTPS hợp lệ (khóa 🔒)
- [ ] Đăng nhập Microsoft OK, upload + xử lý PDF OK
- [ ] `certbot renew --dry-run` pass
- [ ] Đã nhờ IT bật IP Whitelist (chỉ mạng bạn + khách) trong giai đoạn thử

**Production thật (sau Pha C):**
- [ ] `ENVIRONMENT=production` trong cả `api.env` lẫn `worker.env`
- [ ] `MSAL_TENANT_ID` là tenant thật của khách; admin đã grant consent
- [ ] `ALLOWED_ORIGINS=["https://<HOST>"]` (không còn localhost)
- [ ] Frontend đã build lại với `VITE_MSAL_TENANT_ID`
- [ ] Chỉ tài khoản của khách đăng nhập được; tài khoản ngoài bị chặn
- [ ] Đã có Elastic IP (IP không đổi khi restart)
- [ ] Đã bật backup DB + file hằng ngày
```
