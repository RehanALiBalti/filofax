"""Validator / language unit tests — no Ollama required."""

from __future__ import annotations

from backend.language import normalize_language
from backend.models import AIEventPayload, AIFiltersPayload, AIResponse, LanguageInfo
from backend.validators import merge_pending_event, validate_ai_response


def test_create_complete():
    ai = AIResponse(
        intent="create_event",
        language={"code": "en", "name": "English", "is_mixed": False},
        event=AIEventPayload(
            date="2026-07-11",
            time="16:00",
            label="Doctor Appointment",
            category="Appointment",
            notes=None,
        ),
        missing_fields=[],
        requires_confirmation=True,
        confidence=0.96,
    )
    result = validate_ai_response(ai)
    assert result.ok
    assert result.missing_fields == []
    assert result.event["category"] == "Appointment"
    assert result.event["time"] == "16:00"
    assert result.language.code == "en"
    assert result.requires_confirmation


def test_create_missing_category_roman_urdu():
    ai = AIResponse(
        intent="create_event",
        language={"code": "ur-Latn", "name": "Roman Urdu", "is_mixed": True},
        event=AIEventPayload(
            date="2026-07-11",
            time=None,
            label="Meeting",
            category=None,
            notes=None,
        ),
        missing_fields=["category"],
        confidence=0.5,
    )
    result = validate_ai_response(ai)
    assert result.ok
    assert "category" in result.missing_fields
    assert result.language.code == "ur-Latn"
    assert "detail" in result.message.lower() or "category" in result.message.lower()


def test_search_filters():
    ai = AIResponse(
        intent="search_events",
        language=LanguageInfo(code="es", name="Spanish", is_mixed=False),
        filters=AIFiltersPayload(
            date="2026-07-11",
            category="Appointment",
            keyword="doctor",
        ),
        confidence=0.94,
    )
    result = validate_ai_response(ai)
    assert result.ok
    assert result.filters["keyword"] == "doctor"
    assert result.filters["category"] == "Appointment"
    assert result.language.code == "es"


def test_invalid_category():
    ai = AIResponse(
        intent="create_event",
        language="english",
        event=AIEventPayload(
            date="2026-07-11",
            label="Thing",
            category="Party",
        ),
        confidence=0.8,
    )
    result = validate_ai_response(ai)
    assert "category" in result.missing_fields or result.errors


def test_unclear_does_not_claim_unsupported_language():
    ai = AIResponse(
        intent="unclear",
        language={"code": "und", "name": "Unknown", "is_mixed": False},
        event=None,
        requires_clarification=True,
        confidence=0.31,
        clarification="Please rephrase your create/search request.",
    )
    result = validate_ai_response(ai)
    assert result.ok
    assert result.intent == "unclear"
    assert result.requires_clarification
    assert "unsupported" not in (result.message or "").lower()


def test_normalize_language_accepts_any_code():
    lang = normalize_language({"code": "th", "name": "Thai", "is_mixed": False})
    assert lang.code == "th"
    assert lang.name == "Thai"
    legacy = normalize_language("roman_urdu")
    assert legacy.code == "ur-Latn"


def test_merge_pending_preserves_slots_across_language_switch():
    merged = merge_pending_event(
        {"date": "2026-07-11", "label": "Meeting", "category": None, "time": None},
        {"date": None, "label": "Meeting", "category": "Important", "time": "16:00"},
    )
    assert merged["date"] == "2026-07-11"
    assert merged["category"] == "Important"
    assert merged["time"] == "16:00"
