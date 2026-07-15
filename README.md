# Filofax AI Event Assistant

Self-hosted AI event assistant for Filofax. Uses **local Ollama** (`qwen2.5:7b` by default) — no paid cloud AI APIs.

The AI only understands natural language and returns structured JSON. The backend validates every response and owns all database operations.

## Architecture

```
User → Backend → AI Service → Ollama (qwen2.5:7b) → JSON
                ↓
         Validation → SQLite
```

- **AI service** (`backend/ai/`) — prompts, Ollama client, JSON parsing. No DB access.
- **Backend** — validation, confirmation, CRUD/search.
- **Model swap** — set `AI_MODEL` (e.g. to a future Qwen3 tag). Business logic stays unchanged.

## Responsibilities

| Create events | Search events |
|---|---|
| Extract date, time, label, category, notes | Extract date / range, category, label, keyword, notes |
| Return `missing_fields` when required data is absent | Return filters only; backend queries DB |

Categories: `To Do` · `Appointment` · `Important`

**Languages:** open — any natural language, script, dialect, transliteration, or mix the configured model understands. No application-level language allowlist. Replies match the user's language/script.

## Project structure

```
filofax/
├── app.py
├── backend/
│   ├── main.py              # FastAPI routes
│   ├── assistant.py         # Orchestration
│   ├── validators.py        # Never trust AI output
│   ├── event_service.py     # DB CRUD / search
│   ├── language.py          # Open language helpers (no allowlist)
│   ├── models.py
│   └── ai/
│       ├── service.py       # Independent AI adapter
│       ├── ollama_client.py
│       └── prompts.py       # Version-controlled prompts
├── frontend/                # Simple chat UI
├── data/                    # SQLite DB
├── deploy/env.example
└── postman/
```

## Setup

### 1. Ollama

```powershell
ollama pull qwen2.5:7b
ollama serve
```

### 2. Backend

```powershell
cd E:\python\ji\filofax
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

API + UI: **http://127.0.0.1:8002**

### Production (Ubuntu server)

See **[deploy/DEPLOY.md](deploy/DEPLOY.md)**

**Primary:** http://filofax.buzzwaretech.com/  
Optional IP path: http://65.108.236.135/filofax/

### 3. Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_PROVIDER` | `ollama` | AI runtime provider |
| `AI_MODEL` | `qwen2.5:7b` | Model name (swappable) |
| `AI_BASE_URL` | `http://127.0.0.1:11434` | Provider base URL |
| `FILOFAX_PORT` | `8002` | API port |
| `FILOFAX_DATA_DIR` | `data` | SQLite directory |
| `FILOFAX_DATABASE_URL` | `sqlite:///…/filofax.db` | Optional override |

See `deploy/env.example`. Upgrading the model only requires changing env vars — not DB schema, API contracts, or create/search flows.

## API

**Mobile / Android / iOS:** all responses are JSON. See **[postman/API.md](postman/API.md)** and import:

- `postman/filofax.postman_collection.json`
- `postman/Filofax.local.postman_environment.json` or `Filofax.production.postman_environment.json`

Interactive docs: `/api/docs` · endpoint map: `GET /api`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api` | API index for apps |
| GET | `/api/health` | Health + AI / Whisper status |
| POST | `/api/assistant/chat` | Natural-language create/search (JSON) |
| POST | `/api/assistant/voice` | Audio upload → same chat flow |
| GET/POST | `/api/events` | List / create events |
| GET | `/api/events/search` | Filter events |
| GET/PATCH/DELETE | `/api/events/{id}` | Event CRUD (delete returns JSON) |
| DELETE | `/api/events` | Clear all events + draft |

### Chat flow

1. `POST /api/assistant/chat` with `{ "message": "Add doctor appointment tomorrow at 4 PM", "user_id": "…" }`
2. If fields are missing → `missing_fields`, `suggested_replies`, and `pending_event`
3. Echo `pending_event` on every follow-up
4. When complete → `needs_confirmation: true`
5. Confirm with `{ "message": "yes", "confirm": true, "pending_event": {…} }`

Search example: `{ "message": "Show tomorrow's appointments" }` → `events` array.

Language is returned as an object, e.g. `{ "code": "ur-Latn", "name": "Roman Urdu", "is_mixed": true }`. Messages are never rejected for language.

## Reminder storage (Firebase)

When Firebase is configured, reminders are stored in Firestore collection **`Reminders`**.

- List by URL user id: `GET /api/reminders/{userId}`
- Env template: `deploy/firebase.env.example`
- Without Firebase credentials, SQLite fallback is used for local/dev.

## AI rules

The model must never access or mutate the database. It only returns JSON. The backend rejects invalid dates, times, and categories before any write. Unclear input asks the user to rephrase — it never claims a language is unsupported.
