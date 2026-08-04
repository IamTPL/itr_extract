# Deploy Tutorial — ITR Extract

> **Mục đích:** hướng dẫn deploy hệ thống ITR Extract lên server Ubuntu **từ con số 0**, và quy trình **cập nhật/vận hành** hằng ngày.
> **Đối tượng đọc:** mọi dev trong team, kể cả người chưa từng deploy. Cứ làm đúng thứ tự, sau mỗi bước đều có **✅ Điểm kiểm tra** — đạt thì đi tiếp, không đạt thì dừng lại xử lý.
>
> Tài liệu liên quan: [RUNBOOK-AWS.md](RUNBOOK-AWS.md) (nhật ký triển khai thực tế + cấu hình Azure chi tiết) · [README.md](README.md) (bản tổng quát).

---

## 0. Bức tranh hệ thống

```
Người dùng ──HTTPS──▶ nginx (cổng 80/443)
                       ├── /            → file tĩnh frontend  (/var/www/itr_extract)
                       ├── /api/...     → backend FastAPI     (127.0.0.1:8000, service itr-api)
                       └── /healthz     → backend FastAPI
                                            │
                              ┌─────────────┼──────────────┐
                              ▼             ▼              ▼
                        PostgreSQL      Redis (queue)   Thư mục file
                        (users, jobs)       │           /var/lib/itr_extract/files
                                            ▼
                                     worker arq (service itr-worker)
                                     → gọi Gemini xử lý PDF
```

- **2 repo:** backend `git@github.com:IamTPL/itr_extract.git` · frontend `git@github.com:IamTPL/itr_extract_fe.git`
- **Đăng nhập:** Microsoft Entra ID (1 app registration `dca257ea-bb51-40cd-8e80-5e32abd9752e` dùng chung SPA + API). Backend chỉ chấp nhận token thuộc **đúng 1 tenant** cấu hình trong `MSAL_TENANT_ID`.

### Bảng tra cứu nhanh (cheat sheet)

| Thứ | Ở đâu |
|---|---|
| Server production | AWS EC2 · Elastic IP `35.174.254.48` · Ubuntu 24.04 · user SSH `ubuntu` |
| Domain | `https://itr.cynu.com` (DNS A record trên GoDaddy của khách → Elastic IP) |
| Code backend | `/opt/itr_extract` |
| Code frontend | `/opt/itr_extract_fe` |
| File cấu hình (env) | `/etc/itr_extract/api.env` và `/etc/itr_extract/worker.env` |
| File tĩnh frontend (nginx phục vụ) | `/var/www/itr_extract` |
| File dữ liệu (PDF upload/kết quả) | `/var/lib/itr_extract/files` |
| Cấu hình nginx | `/etc/nginx/sites-available/itr_extract` |
| Chứng chỉ SSL | `/etc/letsencrypt/live/itr.cynu.com/` (certbot tự quản, tự gia hạn) |
| 2 dịch vụ nền | `itr-api` (API) · `itr-worker` (xử lý PDF) — quản bởi systemd |
| Xem log | `sudo journalctl -u itr-api -f` · `sudo journalctl -u itr-worker -f` |

---

# PHẦN 1 — DEPLOY LẦN ĐẦU (server trắng)

## 1.0 Chuẩn bị trước khi bắt đầu

Cần có đủ trước khi gõ lệnh đầu tiên:

- [ ] **SSH key** vào server (file `.pem`) + server Ubuntu 22.04/24.04 có **Elastic IP**.
- [ ] **Security Group (AWS)** mở inbound: `22` (SSH), `80` (HTTP), `443` (HTTPS) — nhờ IT quản AWS.
- [ ] **DNS**: bản ghi A `itr.cynu.com → <Elastic IP>` đã trỏ đúng (kiểm tra: `dig +short itr.cynu.com`).
- [ ] **Gemini API key** (bí mật — lấy từ quản lý dự án).
- [ ] **Azure app registration** đã tồn tại (làm 1 lần cho cả hệ thống, KHÔNG phải mỗi lần deploy — xem mục Azure trong [RUNBOOK-AWS.md](RUNBOOK-AWS.md)). Cần biết: Client ID + Tenant ID sẽ pin.
- [ ] Tài khoản GitHub có quyền đọc 2 repo private.

> 🔑 **Quy ước bí mật:** `<DB_PASSWORD>` và `<GEMINI_KEY>` là bí mật — không commit, không dán vào chat/ticket. Sinh và lưu vào trình quản lý mật khẩu của team.

**Kết nối vào server** (mọi lệnh Phần 1 chạy TRÊN SERVER, trừ khi ghi rõ "trên máy bạn"):

```bash
ssh -i ~/.ssh/<KEY>.pem ubuntu@35.174.254.48
```

## 1.1 Cài phần mềm nền

```bash
sudo apt update && sudo apt upgrade -y

sudo apt install -y postgresql redis-server nginx git \
    python3.12 python3.12-venv \
    certbot python3-certbot-nginx
```

Cài **Node.js 22** (⚠️ qua NodeSource — KHÔNG dùng `apt install nodejs` mặc định vì bản đó quá cũ):

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
```

**✅ Điểm kiểm tra:**
```bash
psql --version && redis-cli --version && nginx -v && node --version
# → 4 dòng phiên bản, không có "command not found". Node phải là v22.x
```

## 1.2 PostgreSQL — tạo database

```bash
# Sinh mật khẩu mạnh → LƯU LẠI làm <DB_PASSWORD>
openssl rand -hex 24

sudo -u postgres createuser itr
sudo -u postgres createdb -O itr itr_extract
sudo -u postgres psql -c "ALTER USER itr WITH PASSWORD '<DB_PASSWORD>';"
sudo systemctl enable --now postgresql
```

> Ghi chú: `itr` ở đây là **user của database** — không liên quan user Linux (`ubuntu`). Đừng nhầm.

**✅ Điểm kiểm tra:**
```bash
PGPASSWORD='<DB_PASSWORD>' psql -h localhost -U itr -d itr_extract -c '\conninfo'
# → "You are connected to database "itr_extract" as user "itr"..."
```

## 1.3 Redis

```bash
sudo systemctl enable --now redis-server
```

**✅ Điểm kiểm tra:** `redis-cli ping` → `PONG`

## 1.4 Lấy code về `/opt`

> ⚠️ Code **bắt buộc nằm ở `/opt`**, không để trong `/home/...` — vì 2 service systemd bật `ProtectHome=true` (dịch vụ bị cấm đọc mọi thứ trong home).

Nếu server chưa có SSH key GitHub:

```bash
ssh-keygen -t ed25519 -C "itr-server-deploy" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
# → copy dòng in ra, thêm vào GitHub: Settings → SSH and GPG keys → New SSH key
ssh -o StrictHostKeyChecking=accept-new -T git@github.com   # → "Hi <user>! You've successfully authenticated"
```

Clone 2 repo:

```bash
sudo mkdir -p /opt/itr_extract && sudo chown ubuntu:ubuntu /opt/itr_extract
git clone git@github.com:IamTPL/itr_extract.git /opt/itr_extract

sudo mkdir -p /opt/itr_extract_fe && sudo chown ubuntu:ubuntu /opt/itr_extract_fe
git clone git@github.com:IamTPL/itr_extract_fe.git /opt/itr_extract_fe
```

## 1.5 Cài thư viện Python (backend)

```bash
cd /opt/itr_extract
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

**✅ Điểm kiểm tra:** dòng cuối là `Successfully installed ...` (không có ERROR đỏ).

## 1.6 Thư mục lưu file PDF

```bash
sudo mkdir -p /var/lib/itr_extract/files
sudo chown -R ubuntu:ubuntu /var/lib/itr_extract
sudo chmod 700 /var/lib/itr_extract
```

## 1.7 File cấu hình env

```bash
sudo mkdir -p /etc/itr_extract
sudo chown root:ubuntu /etc/itr_extract
sudo chmod 750 /etc/itr_extract
sudo nano /etc/itr_extract/api.env
```

Dán nội dung sau, thay 3 chỗ `<...>`:

```bash
DATABASE_URL=postgresql+asyncpg://itr:<DB_PASSWORD>@localhost:5432/itr_extract
REDIS_URL=redis://localhost:6379
# Pin đúng 1 tenant được phép đăng nhập:
#   Giai đoạn TEST nội bộ  = Tenant ID Bestarion: 57a2790d-9e61-427a-87f0-6ede7caf4a2e
#   Giai đoạn PRODUCTION   = Tenant ID của khách CYNU (+ thêm dòng ENVIRONMENT=production)
MSAL_TENANT_ID=<TENANT_ID>
MSAL_BE_CLIENT_ID=dca257ea-bb51-40cd-8e80-5e32abd9752e
GEMINI_API_KEY=<GEMINI_KEY>
ALLOWED_ORIGINS='["https://itr.cynu.com"]'
FILES_ROOT=/var/lib/itr_extract/files
```

> ⚠️ **BẪY KINH ĐIỂN — đọc kỹ:** giá trị `ALLOWED_ORIGINS` **bắt buộc bọc nháy đơn** `'[...]'`. App đọc nó dạng JSON (cần nháy kép bên trong); thiếu nháy đơn ngoài thì `source`/systemd sẽ "ăn mất" nháy kép → lỗi `error parsing value for field "allowed_origins"` và dịch vụ không khởi động.

Lưu (`Ctrl+O` → Enter → `Ctrl+X`), phân quyền và tạo bản cho worker:

```bash
sudo chown root:ubuntu /etc/itr_extract/api.env
sudo chmod 640 /etc/itr_extract/api.env
sudo cp /etc/itr_extract/api.env /etc/itr_extract/worker.env
sudo chown root:ubuntu /etc/itr_extract/worker.env
sudo chmod 640 /etc/itr_extract/worker.env
```

**✅ Điểm kiểm tra:** `sudo grep -c '<' /etc/itr_extract/api.env` → `0` (không còn placeholder nào quên thay).

## 1.8 Tạo bảng database (migrations)

Chạy tay nên phải tự nạp env (systemd chưa tham gia ở bước này):

```bash
bash -c 'set -a; source /etc/itr_extract/api.env; set +a; cd /opt/itr_extract && .venv/bin/alembic upgrade head'
```

**✅ Điểm kiểm tra:**
```bash
sudo -u postgres psql -d itr_extract -c '\dt'
# → 3 bảng: alembic_version, jobs, users
```

## 1.9 Bật 2 dịch vụ nền (systemd)

File service có sẵn trong repo (đã cấu hình `User=ubuntu`):

```bash
cd /opt/itr_extract
sudo cp deploy/itr-api.service    /etc/systemd/system/
sudo cp deploy/itr-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now itr-api itr-worker
```

**✅ Điểm kiểm tra:**
```bash
systemctl is-active itr-api itr-worker    # → active / active
curl -s http://127.0.0.1:8000/healthz     # → {"status":"ok"}
```
> Dịch vụ không chạy? `sudo journalctl -u itr-api -n 50 --no-pager` — 90% do sai `DATABASE_URL` hoặc quên nháy đơn `ALLOWED_ORIGINS`.

## 1.10 Tường lửa UFW

⚠️ Dòng `allow 22` **phải chạy trước** `enable` — không là tự khóa SSH của chính mình:

```bash
sudo ufw allow 22
sudo ufw allow 80
sudo ufw allow 443
sudo ufw --force enable
```

**✅ Điểm kiểm tra:** `sudo ufw status` → `Status: active` + 3 dòng ALLOW.

## 1.11 Build frontend

```bash
cat > /opt/itr_extract_fe/.env.production <<'EOF'
VITE_API_BASE_URL=https://itr.cynu.com
VITE_MSAL_CLIENT_ID=dca257ea-bb51-40cd-8e80-5e32abd9752e
VITE_MSAL_BE_CLIENT_ID=dca257ea-bb51-40cd-8e80-5e32abd9752e
VITE_MSAL_TENANT_ID=<TENANT_ID>
EOF
```

> `<TENANT_ID>` phải **khớp với backend** (`MSAL_TENANT_ID` trong `api.env`). Frontend "nướng" các giá trị này vào file tĩnh lúc build — **đổi env là phải build lại** (xem 2.3).
>
> ⚠️ **BẪY `.env.local`:** trước khi build, đảm bảo thư mục FE **KHÔNG có file `.env.local`** (`ls -a /opt/itr_extract_fe | grep env`) — file này (thường sót lại từ lúc dev/test) sẽ đè giá trị của `.env.production`, làm bản build gọi nhầm `localhost` → app live bị "Failed to fetch". Sau khi build, kiểm chứng: `grep -rlo 'localhost' /var/www/itr_extract/assets/ | head -1` phải **trống**.

```bash
cd /opt/itr_extract_fe
npm ci                # cài đúng theo package-lock.json
npm run build         # tạo thư mục dist/, chốt bằng "✓ built in ..."
sudo mkdir -p /var/www/itr_extract
sudo rsync -av --delete dist/ /var/www/itr_extract/
```

## 1.12 Cấu hình nginx

```bash
sudo nano /etc/nginx/sites-available/itr_extract
```

Dán nguyên khối:

```nginx
server {
    listen 80;
    server_name itr.cynu.com;

    root /var/www/itr_extract;
    index index.html;

    client_max_body_size 60M;      # upload PDF tối đa ~50MB

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

Bật site, tắt trang mặc định:

```bash
sudo ln -sf /etc/nginx/sites-available/itr_extract /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t                      # BẮT BUỘC "syntax is ok" mới đi tiếp
sudo systemctl reload nginx
```

**✅ Điểm kiểm tra** (trên máy bạn): `curl -m 5 http://35.174.254.48/healthz` → `{"status":"ok"}`

## 1.13 Bật HTTPS (SSL) — certbot

Điều kiện: DNS đã trỏ đúng + port 80 mở (đã đảm bảo ở các bước trên).

```bash
sudo certbot --nginx -d itr.cynu.com -m longtp@bestarion.com --agree-tos --no-eff-email
sudo nginx -t && sudo systemctl reload nginx
```

certbot tự: xin chứng chỉ Let's Encrypt → sửa nginx thêm cổng 443 → chuyển hướng HTTP→HTTPS → cài lịch **tự gia hạn**.

**✅ Điểm kiểm tra:**
```bash
sudo certbot renew --dry-run       # → "all simulated renewals succeeded"
# Trên máy bạn:
curl -m 8 https://itr.cynu.com/healthz    # → {"status":"ok"}
```

## 1.14 Nghiệm thu cuối Phần 1

- [ ] `https://itr.cynu.com` mở được trên trình duyệt, có khóa 🔒
- [ ] Đăng nhập bằng tài khoản Microsoft **thuộc tenant đã pin** → vào được app
- [ ] Upload 1 PDF mẫu → job `pending → done` → tải được kết quả
- [ ] Tài khoản ngoài tenant → bị chặn
- [ ] `systemctl is-active itr-api itr-worker nginx postgresql redis-server` → 5 × `active`

---

# PHẦN 2 — CẬP NHẬT & VẬN HÀNH

## 2.1 Cập nhật BACKEND (khi có code mới trên GitHub)

```bash
cd /opt/itr_extract
git pull
.venv/bin/pip install -r requirements.txt        # phòng khi requirements đổi
bash -c 'set -a; source /etc/itr_extract/api.env; set +a; .venv/bin/alembic upgrade head'   # phòng khi có migration mới
sudo systemctl restart itr-api itr-worker
```

**✅ Kiểm tra:** `systemctl is-active itr-api itr-worker` → `active/active` · `curl -s http://127.0.0.1:8000/healthz` → ok.

## 2.2 Cập nhật FRONTEND

```bash
cd /opt/itr_extract_fe
git pull
npm ci
npm run build
sudo rsync -av --delete dist/ /var/www/itr_extract/
```

Không cần restart gì cả (file tĩnh). Trình duyệt bấm `Ctrl+Shift+R` (hard refresh) để chắc chắn nhận bản mới.

## 2.3 Đổi cấu hình (env)

**Quy tắc vàng — backend và frontend ăn env KHÁC NHAU:**

| | Backend (`/etc/itr_extract/*.env`) | Frontend (`/opt/itr_extract_fe/.env.production`) |
|---|---|---|
| Đọc lúc nào | Lúc dịch vụ **khởi động** | Lúc **build** (nướng vào file tĩnh) |
| Sau khi sửa phải | `restart` 2 dịch vụ | **Build lại + rsync** (mục 2.2, bỏ `git pull`) |

**Quy trình sửa env backend (LUÔN đủ 3 bước):**

```bash
sudo nano /etc/itr_extract/api.env        # 1. sửa

sudo cp /etc/itr_extract/api.env /etc/itr_extract/worker.env      # 2. đồng bộ worker
sudo chown root:ubuntu /etc/itr_extract/worker.env && sudo chmod 640 /etc/itr_extract/worker.env

sudo systemctl restart itr-api itr-worker                          # 3. restart CẢ HAI
```

Các biến quan trọng:

| Biến | Ý nghĩa | Lưu ý |
|---|---|---|
| `MSAL_TENANT_ID` | Tenant duy nhất được đăng nhập | Đổi thì phải đổi **cả** `VITE_MSAL_TENANT_ID` của FE rồi build lại — 2 bên phải khớp |
| `ALLOWED_ORIGINS` | Origin được phép gọi API (CORS) | **Bọc nháy đơn** `'["https://..."]'` |
| `ENVIRONMENT` | `production` = bật kiểm tra nghiêm ngặt lúc khởi động | Chỉ bật khi go-live khách (cùng lúc với tenant khách); bật mà thiếu config → dịch vụ **từ chối chạy** (chủ đích) |
| `GEMINI_API_KEY` | Key gọi AI | Bí mật |
| `DATABASE_URL` | Kết nối Postgres | User DB là `itr`, đừng đổi |

## 2.4 Đổi cấu hình nginx

```bash
sudo nano /etc/nginx/sites-available/itr_extract
sudo nginx -t                     # BẮT BUỘC pass mới reload
sudo systemctl reload nginx
```

> Phần `listen 443`/`ssl_certificate` do certbot tự thêm — **đừng sửa tay**. Chứng chỉ tự gia hạn; kiểm tra sức khỏe: `sudo certbot renew --dry-run`.

## 2.5 Xem log & chẩn đoán nhanh

**Cách nhanh nhất — script tổng hợp 8 mục** (chạy từ máy bạn, cần chìa SSH ở `~/.ssh/CNY_Key.pem`; chỉ ĐỌC, không sửa gì trên server):

```bash
bash deploy/checklog.sh
# 1 dịch vụ · 2 healthz · 3 users đã login · 4 jobs mới nhất
# 5 thống kê job · 6 upload gần nhất · 7 lỗi 24h · 8 dung lượng đĩa
```

**Hoặc từng lệnh riêng lẻ (chạy trên server):**

```bash
sudo journalctl -u itr-api -f            # log API theo thời gian thực (Ctrl+C để thoát)
sudo journalctl -u itr-worker -n 100     # 100 dòng log worker gần nhất
systemctl status itr-api itr-worker      # trạng thái (q để thoát)
redis-cli ping                           # → PONG
sudo -u postgres psql -d itr_extract -c 'SELECT status, COUNT(*) FROM jobs GROUP BY status;'
df -h /                                  # dung lượng đĩa
```

## 2.6 Sự cố thường gặp

| Triệu chứng | Nguyên nhân thường gặp → cách xử lý |
|---|---|
| Web **502 Bad Gateway** | `itr-api` chết → `systemctl status itr-api` + `journalctl -u itr-api -n 50` |
| Dịch vụ không khởi động, log có `error parsing ... allowed_origins` | Quên **nháy đơn** quanh `ALLOWED_ORIGINS` (mục 1.7) |
| Login báo **401 Wrong tenant** | Tài khoản không thuộc tenant đang pin, HOẶC `MSAL_TENANT_ID` (backend) ≠ `VITE_MSAL_TENANT_ID` (bản FE đã build) |
| Login báo **"Need admin approval"** | Tenant chưa được grant admin consent (việc của IT tenant đó) |
| Login báo **redirect_uri mismatch** | Domain chưa được thêm vào Azure → Authentication → SPA Redirect URIs |
| Job kẹt **pending** mãi | Worker/Redis: `journalctl -u itr-worker -n 100` + `redis-cli ping` |
| Upload báo **413** | `client_max_body_size` trong nginx < kích thước file |
| Sửa env xong "không thấy đổi gì" | Backend: quên restart. Frontend: quên **build lại + rsync** (mục 2.3) |
| App live báo **"Failed to fetch"** khi gọi API; DevTools thấy Request URL = `localhost:8000` | Bản build dính env sai — thường do file `.env.local` còn sót đè `.env.production` → xóa `.env.local`, build lại + rsync, hard refresh (Ctrl+Shift+R) |

## 2.7 Chuyển giai đoạn TEST → PRODUCTION (khách CYNU)

Tóm tắt (chi tiết đầy đủ: mục **PHA C** trong [RUNBOOK-AWS.md](RUNBOOK-AWS.md)):

1. Nhận **Tenant ID của khách** (sau khi admin khách bấm link admin consent).
2. Backend: sửa `api.env` → `MSAL_TENANT_ID=<tenant-khách>` + thêm `ENVIRONMENT=production` → đồng bộ worker.env → restart (quy trình 2.3).
3. Frontend: sửa `.env.production` → `VITE_MSAL_TENANT_ID=<tenant-khách>` → build lại + rsync (quy trình 2.2).
4. Kiểm tra: chỉ tài khoản khách đăng nhập được; tài khoản Bestarion bị chặn.

## 2.8 Backup & khôi phục

**Backup tự động** (đã cài 2026-08-04): script `/etc/cron.daily/itr_extract_backup` chạy mỗi ngày — dump DB + nén thư mục PDF vào `/var/lib/itr_extract` → lưu tại `/var/backups/itr_extract/` (root-only), giữ 30 ngày. Kiểm tra: `sudo ls -la /var/backups/itr_extract/`.

**Khôi phục khi cần** (thay `YYYYMMDD` bằng ngày muốn khôi phục):

```bash
# 1. Dừng app trước khi khôi phục DB
sudo systemctl stop itr-api itr-worker

# 2. Khôi phục database (XÓA dữ liệu hiện tại — chắc chắn rồi mới chạy!)
sudo -u postgres dropdb itr_extract
sudo -u postgres createdb -O itr itr_extract
sudo bash -c "zcat /var/backups/itr_extract/db-YYYYMMDD.sql.gz | sudo -u postgres psql -d itr_extract"

# 3. Khôi phục file PDF
sudo tar xzf /var/backups/itr_extract/files-YYYYMMDD.tgz -C /var/lib/itr_extract
sudo chown -R ubuntu:ubuntu /var/lib/itr_extract

# 4. Bật lại app + kiểm tra
sudo systemctl start itr-api itr-worker
curl -s http://127.0.0.1:8000/healthz
```

> Giới hạn: backup nằm cùng ổ đĩa server — chống "xóa nhầm/hỏng dữ liệu", không chống "mất nguyên ổ". Lớp bổ sung: nhờ IT quản AWS bật **EBS snapshot định kỳ** cho volume của instance.

## 2.9 Quy tắc an toàn

- **Không commit bí mật** (mật khẩu DB, Gemini key) lên git — bí mật chỉ nằm trong `/etc/itr_extract/`.
- **Không sửa code trực tiếp trên server** — mọi thay đổi code đi qua GitHub rồi `git pull` (server chỉ được sửa tay: env + nginx config).
- Trước thao tác "phá" (xóa, ghi đè): chụp/backup thứ sắp đụng.
- Máy chủ có Elastic IP → Stop/Start/Reboot **không đổi IP**; nhưng tránh Stop nếu không cần.
- Sau `apt upgrade` nếu MOTD báo `*** System restart required ***` → chọn lúc vắng người dùng, `sudo reboot` (dịch vụ tự bật lại).
