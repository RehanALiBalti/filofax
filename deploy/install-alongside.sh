#!/usr/bin/env bash
# Install Filofax on the same Ubuntu server as JAMS (+ optional CV Builder).
# Result: http://IP/filofax/
#
# First time:
#   sudo git clone https://github.com/RehanALiBalti/filofax.git /opt/filofax
#   sudo DOMAIN=65.108.236.135 bash /opt/filofax/deploy/install-alongside.sh
#
# After code update:
#   cd /opt/filofax && sudo -u www-data git pull
#   sudo DOMAIN=65.108.236.135 bash /opt/filofax/deploy/install-alongside.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/filofax}"
APP_USER="${APP_USER:-www-data}"
DOMAIN="${DOMAIN:-65.108.236.135}"
NGINX_SITE="${NGINX_SITE:-/etc/nginx/sites-available/jams}"
SNIPPET_DST="/etc/nginx/snippets/filofax.conf"

echo "==> Filofax alongside existing apps"
echo "    URL: http://$DOMAIN/filofax/"

if [[ ! -d "$APP_DIR" ]]; then
  echo "ERROR: $APP_DIR not found. Clone the repo first:"
  echo "  sudo git clone https://github.com/RehanALiBalti/filofax.git /opt/filofax"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx curl ca-certificates >/dev/null

mkdir -p "$APP_DIR/data" "$APP_DIR/.home"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# Python venv
echo "==> Python venv + dependencies"
if [[ ! -d "$APP_DIR/.venv" ]]; then
  sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
fi
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip -q
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

# .env
if [[ ! -f "$APP_DIR/.env" ]]; then
  cp "$APP_DIR/deploy/env.example" "$APP_DIR/.env"
fi
# Production-oriented defaults (do not overwrite custom AI_* if already set carefully)
grep -q '^FILOFAX_HOST=' "$APP_DIR/.env" 2>/dev/null || echo 'FILOFAX_HOST=127.0.0.1' >> "$APP_DIR/.env"
sed -i "s|^FILOFAX_HOST=.*|FILOFAX_HOST=127.0.0.1|" "$APP_DIR/.env" 2>/dev/null || true
sed -i "s|^FILOFAX_PORT=.*|FILOFAX_PORT=8002|" "$APP_DIR/.env" 2>/dev/null || true
if grep -q '^FILOFAX_CORS_ORIGINS=' "$APP_DIR/.env" 2>/dev/null; then
  sed -i "s|^FILOFAX_CORS_ORIGINS=.*|FILOFAX_CORS_ORIGINS=http://$DOMAIN,http://$DOMAIN/filofax|" "$APP_DIR/.env"
else
  echo "FILOFAX_CORS_ORIGINS=http://$DOMAIN,http://$DOMAIN/filofax" >> "$APP_DIR/.env"
fi
if ! grep -q '^FILOFAX_DATA_DIR=' "$APP_DIR/.env" 2>/dev/null; then
  echo "FILOFAX_DATA_DIR=/opt/filofax/data" >> "$APP_DIR/.env"
else
  sed -i "s|^FILOFAX_DATA_DIR=.*|FILOFAX_DATA_DIR=/opt/filofax/data|" "$APP_DIR/.env"
fi
if ! grep -q '^AI_BASE_URL=' "$APP_DIR/.env" 2>/dev/null; then
  echo "AI_BASE_URL=http://127.0.0.1:11434" >> "$APP_DIR/.env"
fi
if ! grep -q '^AI_MODEL=' "$APP_DIR/.env" 2>/dev/null; then
  echo "AI_MODEL=qwen2.5:7b" >> "$APP_DIR/.env"
fi
if ! grep -q '^AI_PROVIDER=' "$APP_DIR/.env" 2>/dev/null; then
  echo "AI_PROVIDER=ollama" >> "$APP_DIR/.env"
fi
chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
chmod -R u+rwX "$APP_DIR/data"

# systemd
echo "==> systemd filofax-backend"
cp "$APP_DIR/deploy/filofax-backend.service" /etc/systemd/system/filofax-backend.service
systemctl daemon-reload
systemctl enable filofax-backend
systemctl restart filofax-backend

# nginx snippet
echo "==> nginx /filofax/ location"
mkdir -p /etc/nginx/snippets
cp "$APP_DIR/deploy/nginx-filofax.snippet" "$SNIPPET_DST"

if [[ -f "$NGINX_SITE" ]]; then
  if ! grep -q 'snippets/filofax.conf' "$NGINX_SITE" 2>/dev/null; then
    # Insert include after server_name / client_max_body_size if possible, else after "server {"
    if grep -q 'client_max_body_size' "$NGINX_SITE"; then
      sed -i '/client_max_body_size/a\n    # Filofax\n    include /etc/nginx/snippets/filofax.conf;' "$NGINX_SITE"
    else
      sed -i '/server {/a\    include /etc/nginx/snippets/filofax.conf;' "$NGINX_SITE"
    fi
    echo "    Added include to $NGINX_SITE"
  else
    echo "    Filofax include already present in $NGINX_SITE"
  fi
else
  echo "WARNING: $NGINX_SITE not found."
  echo "  Copy snippet manually into your nginx server block:"
  echo "    include /etc/nginx/snippets/filofax.conf;"
fi

nginx -t
systemctl reload nginx

# Shared Ollama (already used by JAMS / CV Builder)
if command -v ollama &>/dev/null; then
  echo "==> Ensuring Ollama model"
  systemctl enable ollama 2>/dev/null || true
  systemctl start ollama 2>/dev/null || true
  ollama pull qwen2.5:7b 2>/dev/null || true
else
  echo "WARNING: ollama not found — install it or Filofax AI will be unavailable"
fi

echo ""
echo "==> Done"
systemctl is-active filofax-backend nginx 2>/dev/null || true
curl -sf "http://127.0.0.1:8002/api/health" && echo "  Filofax API OK" || echo "  Filofax API FAILED"
curl -sf "http://127.0.0.1/filofax/api/health" && echo "  nginx /filofax OK" || echo "  nginx /filofax check failed"
echo ""
echo "Open: http://$DOMAIN/filofax/"
