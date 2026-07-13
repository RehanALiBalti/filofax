"""Filofax AI Event Assistant — FastAPI application."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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

FRONTEND_DIR = APP_ROOT / "frontend"

app = FastAPI(
    title="Filofax AI Event Assistant",
    description="Self-hosted event create/search assistant powered by local Ollama models.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/api/health")
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
    }


@app.post("/api/assistant/chat", response_model=AssistantResponse)
def assistant_chat(body: ChatRequest, db: Session = Depends(get_db)) -> AssistantResponse:
    result = assistant_service.handle_chat(
        db,
        message=body.message,
        user_id=body.user_id or DEFAULT_USER_ID,
        confirm=body.confirm,
        pending_event=body.pending_event,
    )
    return result.model_copy(update={"input_mode": "text"})


@app.post("/api/assistant/voice", response_model=AssistantResponse)
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


@app.get("/api/events", response_model=list[EventOut])
def list_events(
    user_id: str = Query(DEFAULT_USER_ID),
    db: Session = Depends(get_db),
) -> list[EventOut]:
    return [EventOut.model_validate(e) for e in event_service.list_events(db, user_id)]


@app.get("/api/events/search", response_model=list[EventOut])
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


@app.post("/api/events", response_model=EventOut, status_code=201)
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


@app.get("/api/events/{event_id}", response_model=EventOut)
def get_event(
    event_id: int,
    user_id: str = Query(DEFAULT_USER_ID),
    db: Session = Depends(get_db),
) -> EventOut:
    event = event_service.get_event(db, event_id, user_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return EventOut.model_validate(event)


@app.patch("/api/events/{event_id}", response_model=EventOut)
def update_event(
    event_id: int,
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


@app.delete("/api/events", status_code=200)
def delete_all_events(
    user_id: str = Query(DEFAULT_USER_ID),
    db: Session = Depends(get_db),
) -> dict:
    """Delete all saved events for a user and clear any in-progress draft."""
    from backend.draft_store import clear_draft

    count = event_service.delete_all_events(db, user_id)
    clear_draft(user_id)
    return {"ok": True, "deleted": count, "message": f"Cleared {count} reminder(s)."}


@app.delete("/api/events/{event_id}", status_code=204)
def delete_event(
    event_id: int,
    user_id: str = Query(DEFAULT_USER_ID),
    db: Session = Depends(get_db),
) -> None:
    event = event_service.get_event(db, event_id, user_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    event_service.delete_event(db, event)
