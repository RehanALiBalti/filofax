# Filofax AI Event Assistant — Ubuntu Deployment

| URL | App |
|-----|-----|
| http://65.108.236.135/ | JAMS |
| http://65.108.236.135/cvbuilder/ | CV Builder |
| http://filofax.buzzwaretech.com/ | **Filofax (primary)** |
| http://65.108.236.135/filofax/ | Filofax (optional IP path) |

Backend: FastAPI on **127.0.0.1:8002** (`filofax-backend`)  
AI: shared **Ollama** (`qwen2.5:7b`)  
Repo: https://github.com/RehanALiBalti/filofax

---

## Primary: subdomain `filofax.buzzwaretech.com`

### 1. DNS

Create an **A** record:

```text
filofax.buzzwaretech.com  →  65.108.236.135
```

Wait until it resolves:

```bash
dig +short filofax.buzzwaretech.com
# should print 65.108.236.135
```

### 2. Server install

```bash
ssh root@65.108.236.135

# If not cloned yet:
sudo git clone https://github.com/RehanALiBalti/filofax.git /opt/filofax
sudo chown -R www-data:www-data /opt/filofax

# Pull latest
cd /opt/filofax && sudo -u www-data git pull

# Optional: fix old IP-path nginx "n" bug if still present
sudo bash /opt/filofax/deploy/repair-nginx.sh || true

# Subdomain site (does not break JAMS / CV Builder)
sudo SUBDOMAIN=filofax.buzzwaretech.com MAIN_IP=65.108.236.135 \
  bash /opt/filofax/deploy/setup-subdomain.sh
```

### 3. Verify

```bash
curl -s -H "Host: filofax.buzzwaretech.com" http://127.0.0.1/api/health
curl -s http://filofax.buzzwaretech.com/api/health
```

Browser: **http://filofax.buzzwaretech.com/**

### 4. HTTPS (optional)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d filofax.buzzwaretech.com
sudo systemctl restart filofax-backend
```

---

## Optional: IP subpath `/filofax/`

```bash
sudo DOMAIN=65.108.236.135 bash /opt/filofax/deploy/install-alongside.sh
```

URL: http://65.108.236.135/filofax/

If nginx shows `unknown directive "n"`:

```bash
sudo bash /opt/filofax/deploy/repair-nginx.sh
```

---

## After code updates

```bash
cd /opt/filofax
sudo -u www-data git pull
sudo systemctl restart filofax-backend
# If nginx/deploy scripts changed:
sudo SUBDOMAIN=filofax.buzzwaretech.com bash /opt/filofax/deploy/setup-subdomain.sh
```

---

## Environment

`/opt/filofax/.env` — see `deploy/env.example`.

| Variable | Value |
|----------|--------|
| `FILOFAX_CORS_ORIGINS` | `http://filofax.buzzwaretech.com,...` |
| `AI_MODEL` | `qwen2.5:7b` |
| `AI_BASE_URL` | `http://127.0.0.1:11434` |

---

## Useful commands

```bash
sudo systemctl status filofax-backend
sudo journalctl -u filofax-backend -f
sudo nginx -t && sudo systemctl reload nginx
ollama list
```
