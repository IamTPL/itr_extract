# Deployment — Ubuntu VPS

## Prereqs
- Ubuntu 22.04+
- `apt install postgresql redis-server nginx python3.11 python3.11-venv`

## Postgres
```bash
sudo -u postgres createuser itr
sudo -u postgres createdb -O itr itr_extract
sudo -u postgres psql -c "ALTER USER itr WITH PASSWORD '<pw>';"
```

## App
```bash
sudo useradd -r -m -d /opt/itr_extract itr
sudo -u itr git clone <repo> /opt/itr_extract
cd /opt/itr_extract && sudo -u itr python3.11 -m venv .venv
sudo -u itr .venv/bin/pip install -r requirements.txt
sudo mkdir -p /var/lib/itr_extract/files
sudo chown -R itr:itr /var/lib/itr_extract
sudo chmod 700 /var/lib/itr_extract
```

## Env files (`/etc/itr_extract/api.env`, `worker.env`)
```
DATABASE_URL=postgresql+asyncpg://itr:<pw>@localhost:5432/itr_extract
REDIS_URL=redis://localhost:6379
MSAL_TENANT_ID=<from client>
MSAL_BE_CLIENT_ID=<from client>
GEMINI_API_KEY=<key>
ALLOWED_ORIGINS=["https://app.example.com"]
FILES_ROOT=/var/lib/itr_extract/files
```

## Migrations
```bash
sudo -u itr .venv/bin/alembic upgrade head
```

## Services
```bash
sudo cp deploy/itr-api.service deploy/itr-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now itr-api itr-worker
```

## nginx (TLS via certbot, reverse-proxy to 127.0.0.1:8000, serve FE static build)
See `nginx.example.conf` (out of scope for this plan).

## Backups
- Nightly cron: `pg_dump itr_extract` + `tar czf files.tgz /var/lib/itr_extract/files`.
