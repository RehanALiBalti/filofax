#!/usr/bin/env bash
# Install Let's Encrypt SSL for filofax.buzzwaretech.com (HTTPS)
#
# Prerequisites:
#   - DNS A record: filofax.buzzwaretech.com → 65.108.236.135
#   - HTTP site working: http://filofax.buzzwaretech.com/
#   - Port 80 and 443 open in firewall
#
# Run:
#   sudo CERTBOT_EMAIL=you@example.com bash /opt/filofax/deploy/setup-ssl-subdomain.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/filofax}"
APP_USER="${APP_USER:-www-data}"
SUBDOMAIN="${SUBDOMAIN:-filofax.buzzwaretech.com}"
MAIN_IP="${MAIN_IP:-65.108.236.135}"
EMAIL="${CERTBOT_EMAIL:-}"

if [[ -z "$EMAIL" ]]; then
  echo "ERROR: Set your email for Let's Encrypt:"
  echo "  sudo CERTBOT_EMAIL=you@example.com bash $APP_DIR/deploy/setup-ssl-subdomain.sh"
  exit 1
fi

if [[ ! -f /etc/nginx/sites-enabled/filofax-buzzware ]] && [[ ! -f /etc/nginx/sites-available/filofax-buzzware ]]; then
  echo "ERROR: Nginx site filofax-buzzware not found. Run setup-subdomain.sh first."
  exit 1
fi

echo "==> Install certbot (if needed)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq certbot python3-certbot-nginx

echo "==> Open firewall for HTTPS (if ufw active)"
if command -v ufw &>/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow 'Nginx Full' || true
  ufw allow 443/tcp || true
fi

echo "==> Request SSL certificate for $SUBDOMAIN"
certbot --nginx \
  -d "$SUBDOMAIN" \
  --non-interactive \
  --agree-tos \
  --email "$EMAIL" \
  --redirect

nginx -t
systemctl reload nginx

echo "==> Update .env CORS for HTTPS"
ENV_FILE="$APP_DIR/.env"
touch "$ENV_FILE"
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

upsert_env "FILOFAX_CORS_ORIGINS" "https://$SUBDOMAIN,http://$SUBDOMAIN,http://$MAIN_IP,http://$MAIN_IP/filofax"

systemctl restart filofax-backend

echo ""
echo "==> SSL installed"
echo "  Site: https://$SUBDOMAIN/"
echo "  HTTP will redirect to HTTPS."
echo ""
echo "Renewal test: sudo certbot renew --dry-run"
curl -sS "https://$SUBDOMAIN/api/health" | head -c 300 && echo "" || echo "(curl failed — check DNS / firewall)"
