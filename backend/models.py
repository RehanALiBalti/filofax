"""ORM and API schemas."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Date, DateTime, Integer, String, Text, Time, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.config import ALLOWED_CATEGORIES
from backend.database import Base

Category = Literal["To Do", "Appointment", "Important"]
Intent = Literal["create_event", "search_events", "clarify", "unclear", "unknown"]


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    event_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    event_date: date
    event_time: Optional[time] = None
    label: str
    category: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class EventCreate(BaseModel):
    user_id: str = "default"
    event_date: date
    event_time: Optional[time] = None
    label: str = Field(min_length=1, max_length=255)
    category: Category
    notes: Optional[str] = None


class EventUpdate(BaseModel):
    event_date: Optional[date] = None
    event_time: Optional[time] = None
    label: Optional[str] = Field(default=None, min_length=1, max_length=255)
    category: Optional[Category] = None
    notes: Optional[str] = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    user_id: str = "default"
    confirm: bool = False
    pending_event: Optional[dict[str, Any]] = None


class LanguageInfo(BaseModel):
    """Dynamically detected language — not constrained to a fixed enum."""

    code: str = "und"
    name: str = "Unknown"
    is_mixed: bool = False


class AIEventPayload(BaseModel):
    date: Optional[str] = None
    time: Optional[str] = None
    label: Optional[str] = None
    category: Optional[str] = None
    notes: Optional[str] = None


class AIFiltersPayload(BaseModel):
    date: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    category: Optional[str] = None
    label: Optional[str] = None
    keyword: Optional[str] = None
    notes: Optional[str] = None


class AIResponse(BaseModel):
    intent: Intent
    language: Union[LanguageInfo, str, dict[str, Any]] = Field(
        default_factory=lambda: LanguageInfo(code="und", name="Unknown", is_mixed=False)
    )
    event: Optional[AIEventPayload] = None
    filters: Optional[AIFiltersPayload] = None
    missing_fields: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False
    requires_clarification: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    clarification: Optional[str] = None
    raw: Optional[dict[str, Any]] = None

    @field_validator("intent", mode="before")
    @classmethod
    def _normalize_intent(cls, value: Any) -> str:
        if value is None:
            return "unknown"
        text = str(value).strip().lower()
        allowed = {"create_event", "search_events", "clarify", "unclear", "unknown"}
        return text if text in allowed else "unknown"


class AssistantResponse(BaseModel):
    ok: bool
    intent: Intent
    language: LanguageInfo
    confidence: float
    message: str
    missing_fields: list[str] = Field(default_factory=list)
    needs_confirmation: bool = False
    requires_clarification: bool = False
    pending_event: Optional[dict[str, Any]] = None
    event: Optional[EventOut] = None
    events: list[EventOut] = Field(default_factory=list)
    filters: Optional[dict[str, Any]] = None
    ai: Optional[AIResponse] = None


def is_allowed_category(value: str | None) -> bool:
    return bool(value) and value in ALLOWED_CATEGORIES
