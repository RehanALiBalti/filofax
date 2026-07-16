# Filofax Mobile REST API

All app traffic is **JSON** (`Content-Type: application/json`), except voice (`multipart/form-data`).

| Resource | URL |
|----------|-----|
| Interactive docs | `{baseUrl}/api/docs` |
| OpenAPI | `{baseUrl}/api/openapi.json` |
| Endpoint map | `GET {baseUrl}/api` |

**Local:** `http://127.0.0.1:8002`  
**Production:** `https://filofax.buzzwaretech.com`

| UI | URL |
|----|-----|
| Text chat | `/` or `/?userid=…&timezone=…` |
| Talk (voice orb) | `/talk?userid=…&timezone=…` |
| Scan (diary photo) | `/scan?userid=…&timezone=…` |

## Chat (main mobile path)

```http
POST /api/assistant/chat
```

**Request**

```json
{
  "message": "Hello how are you",
  "user_id": "app-user-001",
  "confirm": false,
  "pending_event": null
}
```

**Response (always JSON)**

```json
{
  "ok": true,
  "intent": "create_event",
  "language": { "code": "en", "name": "English", "is_mixed": false },
  "confidence": 1.0,
  "message": "Hey! I'm doing great — thanks for asking. Let's set up the event...",
  "missing_fields": ["date", "time", "category", "label"],
  "needs_confirmation": false,
  "requires_clarification": true,
  "pending_event": { "date": null, "time": null, "category": null, "label": null },
  "event": null,
  "events": [],
  "filters": null,
  "suggested_replies": ["Today", "Tomorrow", "9:00 AM", "5:00 PM"],
  "ai": null,
  "transcript": null,
  "input_mode": "text"
}
```

### App rules

1. Show `message` in the chat bubble.
2. Render `suggested_replies` as chips.
3. **Store and echo `pending_event`** on every next request until save/clear.
4. When `needs_confirmation` is `true`, send:

```json
{
  "user_id": "app-user-001",
  "message": "yes",
  "confirm": true,
  "pending_event": { "...from last response..." }
}
```

5. Pass the app user **and timezone** in the page URL so chat saves under that id:

```
https://filofax.buzzwaretech.com/?userid=9Ty4Hx2dcfZ68dW3vNG4EF3QtKT2&timezone=Europe/Vienna
```

| Query | Also accepts | Example |
|-------|--------------|---------|
| `userid` | `user_id`, `userId` | Firebase Auth UID |
| `timezone` | `timeZone`, `tz` | `Europe/Vienna`, `Asia/Karachi` |

If timezone missing → browser timezone, else `Europe/Vienna`.  
Frontend sends both as `user_id` + `timezone` on every chat/voice call. Firestore gets `userId` + `timeZone`.

## Reminders (Firebase `Reminders`)

Primary list by user id in the URL:

```http
GET /api/reminders/{userId}
```

Example: `GET /api/reminders/abc123FirebaseUid`  
→ only documents in Firestore collection **`Reminders`** where **`userId == abc123FirebaseUid`**.

Chat save (`POST /api/assistant/chat` confirm) and `POST /api/events` also write into `Reminders` when Firebase env is configured.

Native document fields: `id`, `image`, `insertDate`, `isArchive`, `isDairy`, `isSent`, `notes`, `sdate`, `sdisplaydate`, `sdisplaymonth`, `sdisplayyear`, `smonth`, `ssdate`, `ssdisplaydate`, `status`, `syear`, `timeZone`, `title`, `type`, `userId`.
Timezone default: `Europe/Vienna` (`FIRESTORE_REMINDER_TIMEZONE`).

| Method | Path | Notes |
|--------|------|--------|
| GET | `/api/reminders/{userId}` | User's reminders (preferred) |
| GET | `/api/events?user_id=` | Same list (legacy query style) |
| GET | `/api/events/search?...` | Filters |
| POST | `/api/events` | Direct create → Firestore |
| GET | `/api/events/{id}?user_id=` | One reminder |
| PATCH | `/api/events/{id}?user_id=` | Partial update |
| DELETE | `/api/events/{id}?user_id=` | `{ "ok": true, "deleted": id }` |
| DELETE | `/api/reminders/{userId}/{id}` | Delete for that user |
| DELETE | `/api/events?user_id=` | Clear all + draft |

Categories: `To Do` · `Appointment` · `Important`

Without Firebase credentials, the API falls back to local SQLite (dev only).

## Diary photo → fields

```http
POST /api/assistant/extract-from-image
Content-Type: multipart/form-data
```

| Field | Type | Notes |
|-------|------|--------|
| `image` | file | JPEG / PNG / WebP (max ~8 MB) |
| `user_id` | text | App user id |
| `timezone` | text | e.g. `Europe/Vienna` |

**Response**

```json
{
  "ok": true,
  "title": "Doctor appointment",
  "date": "2026-07-20",
  "time": "15:30",
  "category": "Appointment",
  "notes": "Bring reports",
  "confidence": 0.86,
  "missing_fields": [],
  "needs_confirmation": true,
  "pending_event": {
    "label": "Doctor appointment",
    "date": "2026-07-20",
    "time": "15:30",
    "category": "Appointment",
    "notes": "Bring reports",
    "_awaiting_confirm": true
  },
  "message": "Got it from the photo: …",
  "suggested_replies": ["Yes, save", "Change time", "Change date", "No"],
  "input_mode": "image"
}
```

### App flow

1. Upload diary photo → extract
2. Show / edit `title`, `date`, `time`, `category`
3. If `needs_confirmation`, confirm via chat:

```json
{
  "user_id": "…",
  "message": "yes",
  "confirm": true,
  "pending_event": { "…from extract response…" }
}
```

Or create directly with `POST /api/events`.

Server needs an Ollama **vision** model, e.g. `ollama pull llava` (set `VISION_MODEL` in `.env`).


## Errors (JSON)

```json
{
  "ok": false,
  "error": {
    "code": "http_error",
    "message": "Event not found",
    "detail": "Event not found"
  }
}
```

## Postman

1. Import `filofax.postman_collection.json`
2. Import `Filofax.local.postman_environment.json` (or Production)
3. Select environment → run **01 Greeting** → **02…05** in order  
   (`pendingEvent` auto-saves from chat responses)
