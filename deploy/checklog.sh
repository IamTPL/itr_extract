#!/bin/bash
# checklog.sh — Kiểm tra nhanh hệ thống ITR Extract (https://itr.cynu.com)
# Cách dùng:   bash ~/checklog.sh
# Yêu cầu:     chìa SSH tại ~/.ssh/CNY_Key.pem (chỉ ĐỌC server, không sửa gì)

SERVER="ubuntu@35.174.254.48"
KEY="$HOME/.ssh/CNY_Key.pem"

ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 "$SERVER" bash -s <<'REMOTE'
echo "════════ 1. DỊCH VỤ (5 dòng 'active' = khỏe) ════════"
systemctl is-active itr-api itr-worker nginx postgresql redis-server

echo
echo "════════ 2. HEALTHZ ════════"
curl -s http://127.0.0.1:8000/healthz; echo

echo
echo "════════ 3. USERS — ai đã login (mới nhất trước) ════════"
sudo -u postgres psql -d itr_extract -c "SELECT email, tenant_id, last_login FROM users ORDER BY last_login DESC LIMIT 10;"

echo "════════ 4. JOBS — 10 dòng mới nhất (khách có dùng không) ════════"
sudo -u postgres psql -d itr_extract -c "SELECT u.email, j.status, j.original_filename, j.created_at FROM jobs j JOIN users u ON u.id = j.user_id ORDER BY j.created_at DESC LIMIT 10;"

echo "════════ 5. THỐNG KÊ JOB theo người & trạng thái ════════"
sudo -u postgres psql -d itr_extract -c "SELECT u.email, j.status, COUNT(*) FROM jobs j JOIN users u ON u.id = j.user_id GROUP BY u.email, j.status ORDER BY u.email, j.status;"

echo "════════ 6. UPLOAD gần nhất qua nginx (POST /api) ════════"
sudo grep "POST /api" /var/log/nginx/access.log | tail -3 | awk '{print $1, $4, $7, $9}'
echo "(trống = chưa có upload nào trong log hiện tại)"

echo
echo "════════ 7. LỖI backend 24h qua (trống = sạch) ════════"
sudo journalctl -u itr-api -u itr-worker --since -24h -p err --no-pager | tail -5

echo
echo "════════ 8. DUNG LƯỢNG ĐĨA ════════"
df -h / | tail -1
REMOTE
