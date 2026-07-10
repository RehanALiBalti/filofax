#!/usr/bin/env bash
# Diagnose + repair Filofax backend (fixes most 502 Bad Gateway cases)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/filofax}"
APP_USER="${APP_USER:-www-data}"

echo "==> Service status"
systemctl status filofax-backend --no-pager -l || true
echo ""
echo "==> Recent logs"
journalctl -u filofax-backend -n 50 --no-pager || true
echo ""
echo "==> Port 8002"
ss -lntp | grep 8002 || echo "  nothing listening on 8002"

echo ""
echo "==> Ensure venv + deps"
if [[ ! -x "$APP_DIR/.venv/bin/uvicorn" ]]; then
  sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
fi
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip -q
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

mkdir -p "$APP_DIR/data" "$APP_DIR/.home"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# Import smoke test
echo "==> Import check"
sudo -u "$APP_USER" env HOME="$APP_DIR/.home" bash -lc \
  "cd '$APP_DIR' && .venv/bin/python -c 'from backend.main import app; print(app.title)'"

cp "$APP_DIR/deploy/filofax-backend.service" /etc/systemd/system/filofax-backend.service
systemctl daemon-reload
systemctl enable filofax-backend
systemctl restart filofax-backend
sleep 2

echo ""
if systemctl is-active --quiet filofax-backend; then
  echo "filofax-backend: active"
else
  echo "filofax-backend: STILL DOWN"
  journalctl -u filofax-backend -n 40 --no-pager || true
  exit 1
fi

curl -sf http://127.0.0.1:8002/api/health && echo && echo "Direct health OK"
curl -sf -H "Host: filofax.buzzwaretech.com" http://127.0.0.1/api/health && echo && echo "Nginx Host health OK" || true
