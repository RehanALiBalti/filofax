"""Filofax AI Event Assistant — FastAPI application."""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from backend.ai.service import ai_service
from backend.assistant import assistant_service
from backend.config import (
    AI_BASE_URL,
    AI_MODEL,
    AI_PROVIDER,
    ALLOWED_CATEGORIES,
    APP_ROOT,
    CORS_ORIGINS,
    DEFAULT_USER_ID,
    VOICE_ENABLED,
    VOICE_MAX_BYTES,
)
from backend.database import get_db, init_db
from backend import event_service
from backend.models import (
    AssistantResponse,
    ChatRequest,
    EventCreate,
    EventOut,
    EventUpdate,
)
from backend.voice import VoiceTranscriptionError, transcribe_audio_bytes, whisper_status
from backend.firebase_app import check_firebase
from backend import reminder_store

FRONTEND_DIR = APP_ROOT / "frontend"

API_DESCRIPTION = """
JSON REST API for Android / iOS / web clients.

**Chat flow**
1. `POST /api/assistant/chat` with `{ message, user_id }`
2. Show `message` and chips from `suggested_replies`
3. Echo `pending_event` on every follow-up until saved or cleared
4. When `needs_confirmation` is true, send `{ confirm: true, message: "yes", pending_event }`

**Events CRUD** also available under `/api/events`.
"""

app = FastAPI(
    title="Filofax Mobile API",
    description=API_DESCRIPTION,
    version="1.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error_json(status: int, detail: Any, *, code: str = "error") -> JSONResponse:
    if isinstance(detail, list):
        message = "Validation failed"
    else:
        message = str(detail)
    return JSONResponse(
        status_code=status,
        content={
            "ok": False,
            "error": {
                "code": code,
                "message": message,
                "detail": detail,
            },
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    return _error_json(exc.status_code, exc.detail, code="http_error")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _error_json(422, exc.errors(), code="validation_error")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/")
def root() -> FileResponse:
    index = FRONTEND_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index)


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/api", tags=["Meta"])
def api_index() -> dict:
    """Mobile/app discovery — list of JSON endpoints."""
    return {
        "ok": True,
        "service": "filofax",
        "version": "1.1.0",
        "docs": "/api/docs",
        "openapi": "/api/openapi.json",
        "categories": list(ALLOWED_CATEGORIES),
        "endpoints": {
            "health": {"method": "GET", "path": "/api/health"},
            "chat": {
                "method": "POST",
                "path": "/api/assistant/chat",
                "body": {
                    "message": "string",
                    "user_id": "string",
                    "confirm": "bool (optional)",
                    "pending_event": "object|null (echo from previous reply)",
                },
            },
            "voice": {
                "method": "POST",
                "path": "/api/assistant/voice",
                "content_type": "multipart/form-data",
                "fields": ["audio", "user_id", "confirm", "pending_event"],
            },
            "list_events": {"method": "GET", "path": "/api/events?user_id="},
            "list_reminders_by_user": {
                "method": "GET",
                "path": "/api/reminders/{userId}",
                "note": "Firestore myReminders where userId == path",
            },
            "search_events": {"method": "GET", "path": "/api/events/search"},
            "create_event": {"method": "POST", "path": "/api/events"},
            "get_event": {"method": "GET", "path": "/api/events/{id}"},
            "update_event": {"method": "PATCH", "path": "/api/events/{id}"},
            "delete_event": {"method": "DELETE", "path": "/api/events/{id}"},
            "clear_events": {"method": "DELETE", "path": "/api/events?user_id="},
        },
        "storage": check_firebase(),
        "chat_response_fields": [
            "ok",
            "intent",
            "message",
            "pending_event",
            "suggested_replies",
            "needs_confirmation",
            "requires_clarification",
            "missing_fields",
            "event",
            "events",
            "language",
            "confidence",
            "input_mode",
            "transcript",
        ],
    }


@app.get("/api/health", tags=["Meta"])
def health() -> dict:
    runtime = ai_service.health()
    return {
        "ok": True,
        "service": "filofax",
        "ai_provider": AI_PROVIDER,
        "ai_model": AI_MODEL,
        "ai_base_url": AI_BASE_URL,
        "model": AI_MODEL,
        "categories": list(ALLOWED_CATEGORIES),
        "languages": "open — any language/script the configured model understands",
        "voice": whisper_status(),
        "ollama": runtime,
        "ai": runtime,
        "firebase": check_firebase(),
        "reminders_collection": reminder_store.collection_name(),
    }


@app.post("/api/assistant/chat", response_model=AssistantResponse, tags=["Assistant"])
def assistant_chat(body: ChatRequest, db: Session = Depends(get_db)) -> AssistantResponse:
    """Natural-language chat. Always JSON. Echo `pending_event` each turn."""
    result = assistant_service.handle_chat(
        db,
        message=body.message,
        user_id=body.user_id or DEFAULT_USER_ID,
        confirm=body.confirm,
        pending_event=body.pending_event,
    )
    return result.model_copy(update={"input_mode": "text"})


@app.post("/api/assistant/voice", response_model=AssistantResponse, tags=["Assistant"])
async def assistant_voice(
    audio: UploadFile = File(...),
    user_id: str = Form(DEFAULT_USER_ID),
    confirm: bool = Form(False),
    pending_event: Optional[str] = Form(None),
    db: Session = Depends(get_db),
) -> AssistantResponse:
    """Voice note → local Whisper transcript → same assistant flow as text chat."""
    if not VOICE_ENABLED:
        raise HTTPException(status_code=503, detail="Voice is disabled on this server.")

    data = await audio.read()
    if not data:
        raise HTTPException(status_code=422, detail="Empty audio file.")
    if len(data) > VOICE_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio too large (max {VOICE_MAX_BYTES} bytes).",
        )

    pending: dict | None = None
    if pending_event and pending_event.strip() and pending_event.strip().lower() != "null":
        try:
            parsed = json.loads(pending_event)
            if isinstance(parsed, dict):
                pending = parsed
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="pending_event must be JSON object") from exc

    try:
        stt = transcribe_audio_bytes(data, filename=audio.filename or "audio.webm")
    except VoiceTranscriptionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    transcript = stt["transcript"]
    result = assistant_service.handle_chat(
        db,
        message=transcript,
        user_id=user_id or DEFAULT_USER_ID,
        confirm=confirm,
        pending_event=pending,
    )
    return result.model_copy(update={"transcript": transcript, "input_mode": "voice"})


@app.get("/api/reminders/{user_id}", response_model=list[EventOut], tags=["Reminders"])
def list_reminders_by_user(
    user_id: str,
    db: Session = Depends(get_db),
) -> list[EventOut]:
    """Get this user's reminders from Firestore `myReminders` (userId == path)."""
    return [EventOut.model_validate(e) for e in event_service.list_events(db, user_id)]


@app.get("/api/events", response_model=list[EventOut], tags=["Events"])
def list_events(
    user_id: str = Query(DEFAULT_USER_ID),
    db: Session = Depends(get_db),
) -> list[EventOut]:
    """List all events/reminders for a user (JSON array). Prefer `/api/reminders/{userId}`."""
    return [EventOut.model_validate(e) for e in event_service.list_events(db, user_id)]


@app.get("/api/events/search", response_model=list[EventOut], tags=["Events"])
def search_events(
    user_id: str = Query(DEFAULT_USER_ID),
    date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    category: Optional[str] = None,
    label: Optional[str] = None,
    keyword: Optional[str] = None,
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
) -> list[EventOut]:
    filters = {
        "date": date,
        "date_from": date_from,
        "date_to": date_to,
        "category": category,
        "label": label,
        "keyword": keyword,
        "notes": notes,
    }
    events = event_service.search_events(db, user_id, filters)
    return [EventOut.model_validate(e) for e in events]


@app.post("/api/events", response_model=EventOut, status_code=201, tags=["Events"])
def create_event(body: EventCreate, db: Session = Depends(get_db)) -> EventOut:
    event = event_service.create_event(
        db,
        user_id=body.user_id or DEFAULT_USER_ID,
        event_date=body.event_date,
        event_time=body.event_time,
        label=body.label,
        category=body.category,
        notes=body.notes,
    )
    return EventOut.model_validate(event)


@app.get("/api/events/{event_id}", response_model=EventOut, tags=["Events"])
def get_event(
    event_id: str,
    user_id: str = Query(DEFAULT_USER_ID),
    db: Session = Depends(get_db),
) -> EventOut:
    event = event_service.get_event(db, event_id, user_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return EventOut.model_validate(event)


@app.patch("/api/events/{event_id}", response_model=EventOut, tags=["Events"])
def update_event(
    event_id: str,
    body: EventUpdate,
    user_id: str = Query(DEFAULT_USER_ID),
    db: Session = Depends(get_db),
) -> EventOut:
    event = event_service.get_event(db, event_id, user_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    updated = event_service.update_event(
        db,
        event,
        **body.model_dump(exclude_unset=True),
    )
    return EventOut.model_validate(updated)


@app.delete("/api/events", status_code=200, tags=["Events"])
def delete_all_events(
    user_id: str = Query(DEFAULT_USER_ID),
    db: Session = Depends(get_db),
) -> dict:
    """Delete all saved events for a user and clear any in-progress draft."""
    from backend.draft_store import clear_draft

    count = event_service.delete_all_events(db, user_id)
    clear_draft(user_id)
    return {"ok": True, "deleted": count, "message": f"Cleared {count} reminder(s)."}


@app.delete("/api/events/{event_id}", status_code=200, tags=["Events"])
def delete_event(
    event_id: str,
    user_id: str = Query(DEFAULT_USER_ID),
    db: Session = Depends(get_db),
) -> dict:
    """Delete one event — JSON body so mobile clients always get a response."""
    event = event_service.get_event(db, event_id, user_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    event_service.delete_event(db, event)
    return {"ok": True, "deleted": event_id}


@app.delete(
    "/api/reminders/{user_id}/{reminder_id}",
    status_code=200,
    tags=["Reminders"],
)
def delete_reminder_for_user(
    user_id: str,
    reminder_id: str,
    db: Session = Depends(get_db),
) -> dict:
    event = event_service.get_event(db, reminder_id, user_id)
    if not event:
        raise HTTPException(status_code=404, detail="Reminder not found")
    event_service.delete_event(db, event)
    return {"ok": True, "deleted": reminder_id}
