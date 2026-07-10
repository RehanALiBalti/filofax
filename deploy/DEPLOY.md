# Filofax AI Event Assistant — Ubuntu Deployment

Deploy on the same server as JAMS / CV Builder:

| URL | App |
|-----|-----|
| http://65.108.236.135/ | JAMS |
| http://65.108.236.135/cvbuilder/ | CV Builder |
| http://65.108.236.135/filofax/ | **Filofax** |

Backend: FastAPI on **127.0.0.1:8002** (systemd `filofax-backend`)  
AI: shared local **Ollama** (`qwen2.5:7b`)

Repo: https://github.com/RehanALiBalti/filofax

---

## First-time install (SSH to server)

```bash
ssh root@65.108.236.135

# 1. Clone
sudo git clone https://github.com/RehanALiBalti/filofax.git /opt/filofax
sudo chown -R www-data:www-data /opt/filofax

# 2. Install (venv + systemd + nginx /filofax/)
sudo DOMAIN=65.108.236.135 bash /opt/filofax/deploy/install-alongside.sh
```

### Verify

```bash
curl http://127.0.0.1:8002/api/health
curl http://127.0.0.1/filofax/api/health
```

Browser: **http://65.108.236.135/filofax/**

---

## After code updates

```bash
cd /opt/filofax
sudo -u www-data git pull
sudo DOMAIN=65.108.236.135 bash /opt/filofax/deploy/install-alongside.sh
```

Or quick restart only:

```bash
cd /opt/filofax
sudo -u www-data git pull
sudo systemctl restart filofax-backend
```

---

## Environment

File: `/opt/filofax/.env` (from `deploy/env.example`)

| Variable | Production value |
|----------|------------------|
| `FILOFAX_HOST` | `127.0.0.1` |
| `FILOFAX_PORT` | `8002` |
| `FILOFAX_CORS_ORIGINS` | `http://65.108.236.135,http://65.108.236.135/filofax` |
| `FILOFAX_DATA_DIR` | `/opt/filofax/data` |
| `AI_PROVIDER` | `ollama` |
| `AI_MODEL` | `qwen2.5:7b` |
| `AI_BASE_URL` | `http://127.0.0.1:11434` |

```bash
sudo systemctl restart filofax-backend
```

---

## Useful commands

```bash
sudo systemctl status filofax-backend
sudo journalctl -u filofax-backend -f
sudo nginx -t && sudo systemctl reload nginx
ollama list
```

---

## Notes

- Install script adds `include /etc/nginx/snippets/filofax.conf;` to `/etc/nginx/sites-available/jams` without removing JAMS or CV Builder.
- UI + API are proxied under `/filofax/` to port 8002.
- No paid AI APIs — Ollama must be running on the same host.
