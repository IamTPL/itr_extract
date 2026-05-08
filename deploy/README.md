# Deployment — Ubuntu VPS

Single-server deployment dùng systemd. Phù hợp cho 1 CPA firm hoặc staging environment.
Cho production scale lớn hơn → dùng Docker + reverse proxy + managed Postgres/Redis (xem roadmap).

## Prereqs

```bash
sudo apt update
sudo apt install -y postgresql redis-server nginx python3.12 python3.12-venv certbot python3-certbot-nginx
```

## Postgres setup

```bash
sudo -u postgres createuser itr
sudo -u postgres createdb -O itr itr_extract
sudo -u postgres psql -c "ALTER USER itr WITH PASSWORD '<strong-password>';"
```

## App user + clone

```bash
sudo useradd -r -m -d /opt/itr_extract itr
sudo -u itr git clone <repo-url> /opt/itr_extract
cd /opt/itr_extract
sudo -u itr python3.12 -m venv .venv
sudo -u itr .venv/bin/pip install --upgrade pip
sudo -u itr .venv/bin/pip install -r requirements.txt

sudo mkdir -p /var/lib/itr_extract/files
sudo chown -R itr:itr /var/lib/itr_extract
sudo chmod 700 /var/lib/itr_extract
```

## Env files

Tạo 2 file riêng để api/worker có thể có flag khác nhau (nội dung gần giống):

`/etc/itr_extract/api.env`
```bash
ENVIRONMENT=production
DATABASE_URL=postgresql+asyncpg://itr:<password>@localhost:5432/itr_extract
REDIS_URL=redis://localhost:6379
MSAL_TENANT_ID=<azure-tenant-id-from-customer>
MSAL_BE_CLIENT_ID=<azure-app-client-id>
GEMINI_API_KEY=<gemini-key>
ALLOWED_ORIGINS=["https://app.example.com"]
FILES_ROOT=/var/lib/itr_extract/files
```

`/etc/itr_extract/worker.env` — copy y hệt `api.env`.

```bash
sudo mkdir -p /etc/itr_extract
sudo chown root:itr /etc/itr_extract
sudo chmod 750 /etc/itr_extract
# Tạo file env, set quyền 640 — root sửa, itr đọc
sudo -e /etc/itr_extract/api.env       # paste content
sudo chown root:itr /etc/itr_extract/api.env
sudo chmod 640 /etc/itr_extract/api.env
sudo cp /etc/itr_extract/api.env /etc/itr_extract/worker.env
sudo chown root:itr /etc/itr_extract/worker.env
sudo chmod 640 /etc/itr_extract/worker.env
```

> ⚠️ **`ENVIRONMENT=production` BẮT BUỘC.**
> Nếu trống hoặc `=development`, app start nhưng chạy chế độ permissive (accept Microsoft account bất kỳ).
> Khi `ENVIRONMENT=production`, app fail-fast nếu thiếu `MSAL_TENANT_ID`, BE_CLIENT_ID placeholder, hoặc CORS chứa localhost.

## Migrations

```bash
cd /opt/itr_extract
sudo -u itr .venv/bin/alembic upgrade head
```

## Systemd services

```bash
sudo cp deploy/itr-api.service /etc/systemd/system/
sudo cp deploy/itr-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now itr-api itr-worker
sudo systemctl status itr-api itr-worker
```

Logs:
```bash
sudo journalctl -u itr-api -f
sudo journalctl -u itr-worker -f
```

## Frontend build

```bash
cd <itr_extract_fe>
# .env.production với VITE_MSAL_TENANT_ID, VITE_API_BASE_URL=https://api.example.com, ...
npm ci
npm run build
sudo rsync -av dist/ /var/www/itr_extract/
```

## nginx + TLS

```nginx
# /etc/nginx/sites-available/itr_extract

# Frontend SPA
server {
    listen 443 ssl http2;
    server_name app.example.com;

    ssl_certificate     /etc/letsencrypt/live/app.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.example.com/privkey.pem;

    root /var/www/itr_extract;
    index index.html;
    location / { try_files $uri /index.html; }
}

# Backend API
server {
    listen 443 ssl http2;
    server_name api.example.com;

    ssl_certificate     /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    client_max_body_size 60M;  # Cho upload PDF tối đa 50MB + buffer

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}

# HTTP → HTTPS redirect
server {
    listen 80;
    server_name app.example.com api.example.com;
    return 301 https://$host$request_uri;
}
```

```bash
sudo ln -s /etc/nginx/sites-available/itr_extract /etc/nginx/sites-enabled/
sudo certbot --nginx -d app.example.com -d api.example.com
sudo nginx -t && sudo systemctl reload nginx
```

## Backups

```bash
# /etc/cron.daily/itr_extract_backup
#!/bin/bash
set -e
BACKUP_DIR=/var/backups/itr_extract
mkdir -p $BACKUP_DIR
DATE=$(date +%Y%m%d)

sudo -u postgres pg_dump itr_extract | gzip > $BACKUP_DIR/db-$DATE.sql.gz
tar czf $BACKUP_DIR/files-$DATE.tgz -C /var/lib/itr_extract files

# Retention 30 ngày
find $BACKUP_DIR -mtime +30 -delete
```

## Update flow

```bash
cd /opt/itr_extract
sudo -u itr git pull
sudo -u itr .venv/bin/pip install -r requirements.txt
sudo -u itr .venv/bin/alembic upgrade head
sudo systemctl restart itr-api itr-worker
```

## Troubleshooting

| Triệu chứng | Cách xử lý |
|---|---|
| `itr-api` fail với `RuntimeError: Production config validation failed` | Check `MSAL_TENANT_ID`, `MSAL_BE_CLIENT_ID`, `GEMINI_API_KEY`, `ALLOWED_ORIGINS` trong `/etc/itr_extract/api.env` |
| 502 Bad Gateway | `systemctl status itr-api`; port 8000 có listen? |
| Worker không xử lý job | `journalctl -u itr-worker -n 100`; Redis kết nối ok? |
| 413 Payload Too Large | `client_max_body_size` trong nginx phải ≥ 50M |
| Job stuck PROCESSING | Đợi 6 phút (cron requeue) hoặc `systemctl restart itr-worker` |
| Token verify fail | `journalctl -u itr-api`: kid not found → JWKS auto-refresh thử lại; nếu lặp → check `MSAL_TENANT_ID` |

## Hardening checklist trước go-live

- [ ] `ENVIRONMENT=production` trong cả `api.env` lẫn `worker.env`
- [ ] `MSAL_TENANT_ID` là tenant thực của khách hàng
- [ ] `ALLOWED_ORIGINS` exact match domain frontend (không wildcard, không localhost)
- [ ] `chmod 640 /etc/itr_extract/*.env`, owner `root:itr`
- [ ] Postgres password ≥ 20 ký tự random
- [ ] Redis bind 127.0.0.1 only
- [ ] UFW firewall chỉ open 80, 443, 22
- [ ] SSH key-only auth, disable password
- [ ] Daily backup cron + test restore
- [ ] `certbot renew --dry-run` pass
- [ ] External monitor ping `/healthz` mỗi 5 phút
