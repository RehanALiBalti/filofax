# Filofax Mobile REST API

All app traffic is **JSON** (`Content-Type: application/json`), except voice (`multipart/form-data`).

| Resource | URL |
|----------|-----|
| Interactive docs | `{baseUrl}/api/docs` |
| OpenAPI | `{baseUrl}/api/openapi.json` |
| Endpoint map | `GET {baseUrl}/api` |

**Local:** `http://127.0.0.1:8002`  
**Production:** `https://filofax.buzzwaretech.com`

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

5. Use a stable `user_id` per logged-in app user (never share `"default"` in production).

## Events CRUD

| Method | Path | Notes |
|--------|------|--------|
| GET | `/api/events?user_id=` | JSON array |
| GET | `/api/events/search?...` | Filters |
| POST | `/api/events` | Direct create |
| GET | `/api/events/{id}?user_id=` | One event |
| PATCH | `/api/events/{id}?user_id=` | Partial update |
| DELETE | `/api/events/{id}?user_id=` | `{ "ok": true, "deleted": id }` |
| DELETE | `/api/events?user_id=` | Clear all + draft |

Categories: `To Do` · `Appointment` · `Important`

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
