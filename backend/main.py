"""Filofax AI Event Assistant — FastAPI application."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
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
        "ollama": runtime,
        "ai": runtime,
    }


@app.post("/api/assistant/chat", response_model=AssistantResponse)
def assistant_chat(body: ChatRequest, db: Session = Depends(get_db)) -> AssistantResponse:
    return assistant_service.handle_chat(
        db,
        message=body.message,
        user_id=body.user_id or DEFAULT_USER_ID,
        confirm=body.confirm,
        pending_event=body.pending_event,
    )


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
