#!/usr/bin/env bash
# Fix broken nginx config from older install-alongside.sh sed bug
# (literal "n" directive). Safe to re-run.
set -euo pipefail

NGINX_SITE="${NGINX_SITE:-/etc/nginx/sites-available/jams}"
APP_DIR="${APP_DIR:-/opt/filofax}"
SNIPPET_DST="/etc/nginx/snippets/filofax.conf"

if [[ ! -f "$NGINX_SITE" ]]; then
  echo "ERROR: $NGINX_SITE not found"
  exit 1
fi

echo "==> Cleaning bad lines in $NGINX_SITE"
# Show nearby context for debugging
sed -n '1,25p' "$NGINX_SITE" || true

# Old sed bug produced "n    # Filofax" (literal n glued to the next line)
sed -i 's/^n[[:space:]]\+/    /' "$NGINX_SITE"
# Also remove any leftover standalone "n" lines
sed -i '/^[[:space:]]*n[[:space:]]*$/d' "$NGINX_SITE"

# Ensure snippet exists
mkdir -p /etc/nginx/snippets
if [[ -f "$APP_DIR/deploy/nginx-filofax.snippet" ]]; then
  grep -v '^#' "$APP_DIR/deploy/nginx-filofax.snippet" | grep -v '^$' > "$SNIPPET_DST" || true
fi

# Ensure include exists once
if ! grep -q 'snippets/filofax.conf' "$NGINX_SITE"; then
  python3 - "$NGINX_SITE" <<'PY'
import sys
path = sys.argv[1]
include_line = "    include /etc/nginx/snippets/filofax.conf;"
with open(path, encoding="utf-8") as f:
    lines = f.readlines()
out = []
inserted = False
for line in lines:
    out.append(line)
    if not inserted and "client_max_body_size" in line:
        out.append("\n    # Filofax\n")
        out.append(include_line + "\n")
        inserted = True
if not inserted:
    out = []
    for line in lines:
        out.append(line)
        if not inserted and "server {" in line:
            out.append("    # Filofax\n")
            out.append(include_line + "\n")
            inserted = True
with open(path, "w", encoding="utf-8") as f:
    f.writelines(out)
PY
  echo "    Added filofax include"
else
  echo "    Filofax include already present"
fi

echo "==> nginx -t"
nginx -t
systemctl reload nginx
echo "OK — try: curl -s http://127.0.0.1/filofax/api/health"
