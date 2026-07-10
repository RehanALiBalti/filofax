"""Validate and normalize AI output before any database work."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from dateutil import parser as date_parser

from backend.config import ALLOWED_CATEGORIES, REQUIRED_CREATE_FIELDS
from backend.language import (
    help_message,
    missing_fields_message,
    normalize_language,
    unclear_message,
)
from backend.models import AIEventPayload, AIFiltersPayload, AIResponse, Intent, LanguageInfo


class ValidationResult:
    def __init__(
        self,
        *,
        ok: bool,
        intent: Intent,
        language: LanguageInfo,
        confidence: float,
        missing_fields: list[str] | None = None,
        event: dict[str, Any] | None = None,
        filters: dict[str, Any] | None = None,
        message: str | None = None,
        errors: list[str] | None = None,
        requires_confirmation: bool = False,
        requires_clarification: bool = False,
    ) -> None:
        self.ok = ok
        self.intent = intent
        self.language = language
        self.confidence = confidence
        self.missing_fields = missing_fields or []
        self.event = event
        self.filters = filters
        self.message = message
        self.errors = errors or []
        self.requires_confirmation = requires_confirmation
        self.requires_clarification = requires_clarification


def _parse_date(value: str | None) -> date | None:
    if value is None or str(value).strip() == "" or str(value).lower() == "null":
        return None
    try:
        return date_parser.parse(str(value).strip()).date()
    except (ValueError, OverflowError, TypeError):
        return None


def _parse_time(value: str | None) -> time | None:
    if value is None or str(value).strip() == "" or str(value).lower() == "null":
        return None
    text = str(value).strip()
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I %p"):
        try:
            return datetime.strptime(text, fmt).time().replace(second=0, microsecond=0)
        except ValueError:
            continue
    try:
        return date_parser.parse(text).time().replace(second=0, microsecond=0)
    except (ValueError, OverflowError, TypeError):
        return None


def _normalize_category(value: str | None) -> str | None:
    if value is None or str(value).strip() == "" or str(value).lower() == "null":
        return None
    text = str(value).strip()
    for allowed in ALLOWED_CATEGORIES:
        if text.lower() == allowed.lower():
            return allowed
    aliases = {
        "todo": "To Do",
        "to-do": "To Do",
        "to_do": "To Do",
        "task": "To Do",
        "appointment": "Appointment",
        "appt": "Appointment",
        "important": "Important",
        "priority": "Important",
    }
    return aliases.get(text.lower())


def _clean_str(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null":
        return None
    return text


def validate_ai_response(ai: AIResponse) -> ValidationResult:
    language = normalize_language(ai.language)
    confidence = float(ai.confidence or 0.0)
    intent: Intent = ai.intent if ai.intent in (
        "create_event",
        "search_events",
        "clarify",
        "unclear",
        "unknown",
    ) else "unknown"

    if intent == "unclear" or (ai.requires_clarification and intent not in ("create_event", "search_events")):
        return ValidationResult(
            ok=True,
            intent="unclear" if intent == "unclear" else intent,
            language=language,
            confidence=confidence,
            requires_clarification=True,
            message=ai.clarification or unclear_message(language),
        )

    if intent == "create_event":
        return _validate_create(
            ai.event,
            language,
            confidence,
            ai.missing_fields,
            ai.clarification,
            ai.requires_confirmation,
        )
    if intent == "search_events":
        return _validate_search(ai.filters, language, confidence, ai.clarification)

    return ValidationResult(
        ok=True,
        intent=intent,
        language=language,
        confidence=confidence,
        requires_clarification=bool(ai.requires_clarification or intent == "clarify"),
        message=ai.clarification or help_message(language),
    )


def _validate_create(
    event: AIEventPayload | None,
    language: LanguageInfo,
    confidence: float,
    ai_missing: list[str],
    clarification: str | None,
    requires_confirmation: bool,
) -> ValidationResult:
    errors: list[str] = []
    missing = [f for f in (ai_missing or []) if f in REQUIRED_CREATE_FIELDS or f == "time"]
    payload = event or AIEventPayload()

    parsed_date = _parse_date(payload.date)
    if payload.date and parsed_date is None:
        errors.append("Invalid date")
        if "date" not in missing:
            missing.append("date")

    parsed_time = _parse_time(payload.time)
    if payload.time and parsed_time is None:
        errors.append("Invalid time")

    label = _clean_str(payload.label)
    category = _normalize_category(payload.category)
    if payload.category and category is None:
        errors.append("Invalid category")
        if "category" not in missing:
            missing.append("category")

    notes = _clean_str(payload.notes)

    if parsed_date is None and "date" not in missing:
        missing.append("date")
    if not label and "label" not in missing:
        missing.append("label")
    if category is None and "category" not in missing:
        missing.append("category")

    seen: set[str] = set()
    missing_unique: list[str] = []
    for field in missing:
        if field not in seen and field in (*REQUIRED_CREATE_FIELDS, "time"):
            seen.add(field)
            missing_unique.append(field)

    normalized = {
        "date": parsed_date.isoformat() if parsed_date else None,
        "time": parsed_time.strftime("%H:%M") if parsed_time else None,
        "label": label,
        "category": category,
        "notes": notes,
    }

    if errors:
        return ValidationResult(
            ok=False,
            intent="create_event",
            language=language,
            confidence=confidence,
            missing_fields=missing_unique,
            event=normalized,
            message="; ".join(errors),
            errors=errors,
            requires_clarification=True,
        )

    if missing_unique:
        ask = clarification or missing_fields_message(missing_unique, language)
        return ValidationResult(
            ok=True,
            intent="create_event",
            language=language,
            confidence=confidence,
            missing_fields=missing_unique,
            event=normalized,
            message=ask,
            requires_clarification=True,
        )

    return ValidationResult(
        ok=True,
        intent="create_event",
        language=language,
        confidence=confidence,
        event=normalized,
        message=clarification or "Ready to create this event.",
        requires_confirmation=True if requires_confirmation or not missing_unique else False,
    )


def _validate_search(
    filters: AIFiltersPayload | None,
    language: LanguageInfo,
    confidence: float,
    clarification: str | None,
) -> ValidationResult:
    errors: list[str] = []
    payload = filters or AIFiltersPayload()

    def date_field(name: str, raw: str | None) -> str | None:
        if not raw:
            return None
        parsed = _parse_date(raw)
        if parsed is None:
            errors.append(f"Invalid {name}")
            return None
        return parsed.isoformat()

    category = _normalize_category(payload.category)
    if payload.category and category is None:
        errors.append("Invalid category")

    normalized = {
        "date": date_field("date", payload.date),
        "date_from": date_field("date_from", payload.date_from),
        "date_to": date_field("date_to", payload.date_to),
        "category": category,
        "label": _clean_str(payload.label),
        "keyword": _clean_str(payload.keyword),
        "notes": _clean_str(payload.notes),
    }

    if errors:
        return ValidationResult(
            ok=False,
            intent="search_events",
            language=language,
            confidence=confidence,
            filters=normalized,
            message="; ".join(errors),
            errors=errors,
            requires_clarification=True,
        )

    if not any(normalized.values()):
        return ValidationResult(
            ok=True,
            intent="search_events",
            language=language,
            confidence=confidence,
            filters=normalized,
            message=clarification or missing_fields_message(["keyword"], language),
            missing_fields=["keyword"],
            requires_clarification=True,
        )

    return ValidationResult(
        ok=True,
        intent="search_events",
        language=language,
        confidence=confidence,
        filters=normalized,
        message=clarification or "Searching events.",
    )


def merge_pending_event(
    previous: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> dict[str, Any]:
    """Preserve earlier slots when the user switches language mid-flow."""
    merged: dict[str, Any] = {}
    for source in (previous or {}, current or {}):
        for key, value in source.items():
            if value is not None and str(value).strip() != "" and str(value).lower() != "null":
                merged[key] = value
            elif key not in merged:
                merged[key] = value
    return merged


def pending_event_to_create_kwargs(pending: dict[str, Any], user_id: str) -> dict[str, Any]:
    event_date = _parse_date(pending.get("date"))
    if event_date is None:
        raise ValueError("date is required")
    label = _clean_str(pending.get("label"))
    category = _normalize_category(pending.get("category"))
    if not label:
        raise ValueError("label is required")
    if category is None:
        raise ValueError("category is required")
    return {
        "user_id": user_id,
        "event_date": event_date,
        "event_time": _parse_time(pending.get("time")),
        "label": label,
        "category": category,
        "notes": _clean_str(pending.get("notes")),
    }
