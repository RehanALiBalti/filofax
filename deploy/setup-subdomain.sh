#!/usr/bin/env bash
# Filofax on subdomain — does NOT change main IP apps.
#
#   http://filofax.buzzwaretech.com/     → Filofax (port 8002)
#   http://65.108.236.135/               → JAMS (unchanged)
#   http://65.108.236.135/cvbuilder/     → CV Builder (unchanged)
#   http://65.108.236.135/filofax/       → Filofax subpath (optional, kept)
#
# Prerequisites:
#   1. DNS A record: filofax.buzzwaretech.com → 65.108.236.135
#   2. App installed: /opt/filofax + filofax-backend systemd running
#
# Run:
#   sudo SUBDOMAIN=filofax.buzzwaretech.com bash /opt/filofax/deploy/setup-subdomain.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/filofax}"
APP_USER="${APP_USER:-www-data}"
SUBDOMAIN="${SUBDOMAIN:-filofax.buzzwaretech.com}"
MAIN_IP="${MAIN_IP:-65.108.236.135}"
SITE_AVAIL="/etc/nginx/sites-available/filofax-buzzware"
SITE_ENABLED="/etc/nginx/sites-enabled/filofax-buzzware"

echo "==> Filofax subdomain setup"
echo "    Subdomain: http://$SUBDOMAIN/"
echo "    Main IP:   http://$MAIN_IP/ (JAMS / CV Builder unchanged)"

if [[ ! -d "$APP_DIR" ]]; then
  echo "ERROR: $APP_DIR missing. Clone + install first:"
  echo "  sudo git clone https://github.com/RehanALiBalti/filofax.git /opt/filofax"
  echo "  sudo DOMAIN=$MAIN_IP bash /opt/filofax/deploy/install-alongside.sh"
  exit 1
fi

# Ensure backend is installed/running
if [[ ! -f /etc/systemd/system/filofax-backend.service ]]; then
  echo "==> Backend not installed yet — running install-alongside.sh"
  DOMAIN="$MAIN_IP" bash "$APP_DIR/deploy/install-alongside.sh" || true
fi

# .env CORS + public URL
ENV_FILE="$APP_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$APP_DIR/deploy/env.example" "$ENV_FILE"
fi
chown "$APP_USER:$APP_USER" "$ENV_FILE"

upsert_env() {
  local key="$1"
  local val="$2"
  if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
}

upsert_env "FILOFAX_HOST" "127.0.0.1"
upsert_env "FILOFAX_PORT" "8002"
upsert_env "FILOFAX_DATA_DIR" "/opt/filofax/data"
upsert_env "FILOFAX_CORS_ORIGINS" "http://$SUBDOMAIN,https://$SUBDOMAIN,http://$MAIN_IP,http://$MAIN_IP/filofax"
upsert_env "AI_PROVIDER" "ollama"
upsert_env "AI_MODEL" "qwen2.5:7b"
upsert_env "AI_BASE_URL" "http://127.0.0.1:11434"

# nginx site
echo "==> nginx site for $SUBDOMAIN"
cp "$APP_DIR/deploy/nginx-filofax-subdomain.conf" "$SITE_AVAIL"
sed -i "s/filofax.buzzwaretech.com/$SUBDOMAIN/g" "$SITE_AVAIL"
ln -sf "$SITE_AVAIL" "$SITE_ENABLED"

nginx -t
systemctl reload nginx

systemctl enable filofax-backend 2>/dev/null || true
systemctl restart filofax-backend

echo "==> Local Host-header checks"
curl -sf -H "Host: $SUBDOMAIN" "http://127.0.0.1/api/health" && echo "  API OK" || echo "  API FAILED"
TITLE=$(curl -sS -H "Host: $SUBDOMAIN" "http://127.0.0.1/" | grep -oi '<title>[^<]*</title>' | head -1 || true)
echo "    Page title: ${TITLE:-unknown}"

echo ""
echo "==> Done"
echo "DNS must point: $SUBDOMAIN → $MAIN_IP"
echo "Open: http://$SUBDOMAIN/"
echo ""
echo "Optional HTTPS later:"
echo "  sudo apt install -y certbot python3-certbot-nginx"
echo "  sudo certbot --nginx -d $SUBDOMAIN"
