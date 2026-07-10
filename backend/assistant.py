"""Orchestrates AI parsing → validation → auto-save / search (Blueline-style tools)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.ai.service import AIService, AIServiceError, ai_service
from backend import event_service
from backend.config import ASK_FIELD_ORDER
from backend.language import (
    created_message,
    default_language,
    help_message,
    normalize_language,
    search_message,
    unclear_message,
)
from backend.models import AssistantResponse, EventOut, LanguageInfo
from backend.validators import (
    merge_pending_event,
    pending_event_to_create_kwargs,
    validate_ai_response,
)


CONFIRM_WORDS = {
    "yes",
    "y",
    "ok",
    "okay",
    "confirm",
    "haan",
    "han",
    "ji",
    "ha",
    "sure",
    "create",
    "save",
    "sí",
    "si",
    "oui",
    "نعم",
    "是",
    "ja",
    "sim",
    "ہاں",
    "हां",
}

GREETING_WORDS = {
    "hi",
    "hello",
    "hey",
    "salam",
    "salaam",
    "assalam",
    "asalam",
    "aoa",
    "hola",
    "bonjour",
}

CANCEL_WORDS = {
    "cancel",
    "no",
    "nah",
    "rehne do",
    "mat karo",
    "stop",
}


def _is_confirm(message: str) -> bool:
    return message.strip().lower() in {w.lower() for w in CONFIRM_WORDS} or message.strip() in CONFIRM_WORDS


def _is_greeting(message: str) -> bool:
    return message.strip().lower() in GREETING_WORDS


def _is_cancel(message: str) -> bool:
    text = message.strip().lower()
    return text in CANCEL_WORDS or text.startswith("cancel")


def _missing_from_event(event: dict[str, Any] | None) -> list[str]:
    event = event or {}
    missing = []
    for field in ASK_FIELD_ORDER:
        value = event.get(field)
        if value is None or str(value).strip() == "" or str(value).lower() == "null":
            missing.append(field)
    return missing


class AssistantService:
    def __init__(self, ai: AIService | None = None) -> None:
        self.ai = ai or ai_service

    def handle_chat(
        self,
        db: Session,
        *,
        message: str,
        user_id: str,
        confirm: bool = False,
        pending_event: dict[str, Any] | None = None,
    ) -> AssistantResponse:
        text = message.strip()
        if not text:
            lang = default_language()
            return AssistantResponse(
                ok=False,
                intent="unknown",
                language=lang,
                confidence=0.0,
                message=help_message(lang),
            )

        if pending_event and _is_cancel(text):
            lang = default_language()
            return AssistantResponse(
                ok=True,
                intent="cancel_event",
                language=lang,
                confidence=1.0,
                message="Cancelled. No event was saved.",
                pending_event=None,
            )

        # Legacy: if client still sends confirm + complete draft, save it
        if pending_event and (confirm or _is_confirm(text)):
            missing = _missing_from_event(pending_event)
            if not missing:
                return self._commit_pending(db, user_id=user_id, pending=pending_event)

        if _is_greeting(text) and not pending_event:
            lang = default_language()
            return AssistantResponse(
                ok=True,
                intent="clarify",
                language=lang,
                confidence=1.0,
                message=help_message(lang),
                requires_clarification=True,
            )

        context = None
        if pending_event:
            context = {
                "intent": "create_event",
                "event": pending_event,
                "missing_fields": _missing_from_event(pending_event),
            }

        try:
            ai_result = self.ai.parse_message(text, conversation_context=context)
        except AIServiceError as exc:
            lang = default_language()
            return AssistantResponse(
                ok=False,
                intent="unknown",
                language=lang,
                confidence=0.0,
                message=f"AI service error: {exc}",
            )

        language = normalize_language(ai_result.language)
        ai_result.language = language
        validated = validate_ai_response(ai_result)
        language = validated.language

        if validated.intent == "create_event" or (pending_event and validated.event is not None):
            if validated.event is not None or pending_event:
                merged = merge_pending_event(pending_event, validated.event)
                validated.event = merged
                validated.intent = "create_event"
                missing = _missing_from_event(merged)
                validated.missing_fields = missing
                if missing:
                    validated.requires_confirmation = False
                    validated.requires_clarification = True
                else:
                    validated.requires_confirmation = False
                    validated.requires_clarification = False

        if not validated.ok:
            return AssistantResponse(
                ok=False,
                intent=validated.intent,
                language=language,
                confidence=validated.confidence,
                message=validated.message or "Could not validate AI output.",
                missing_fields=validated.missing_fields,
                requires_clarification=validated.requires_clarification,
                pending_event=validated.event or pending_event,
                filters=validated.filters,
                ai=ai_result,
            )

        if validated.intent in ("unclear", "clarify", "unknown") and not (
            pending_event and validated.event
        ):
            return AssistantResponse(
                ok=True,
                intent=validated.intent,
                language=language,
                confidence=validated.confidence,
                message=validated.message or unclear_message(language),
                requires_clarification=True,
                pending_event=pending_event,
                ai=ai_result,
            )

        if validated.intent == "create_event":
            return self._handle_create(db, user_id, validated, ai_result)

        if validated.intent == "search_events":
            return self._handle_search(db, user_id, validated, ai_result)

        return AssistantResponse(
            ok=True,
            intent=validated.intent,
            language=language,
            confidence=validated.confidence,
            message=validated.message or help_message(language),
            requires_clarification=validated.requires_clarification,
            pending_event=pending_event,
            ai=ai_result,
        )

    def _handle_create(
        self,
        db: Session,
        user_id: str,
        validated: Any,
        ai_result: Any,
    ) -> AssistantResponse:
        pending = validated.event or {}
        language: LanguageInfo = validated.language
        missing = validated.missing_fields or _missing_from_event(pending)

        if missing:
            return AssistantResponse(
                ok=True,
                intent="create_event",
                language=language,
                confidence=validated.confidence,
                message=validated.message or "More details needed.",
                missing_fields=missing,
                needs_confirmation=False,
                requires_clarification=True,
                pending_event=pending,
                ai=ai_result,
            )

        # Complete → immediately save (add_reminder tool equivalent)
        return self._commit_pending(
            db,
            user_id=user_id,
            pending=pending,
            language=language,
            confidence=validated.confidence,
            ai_result=ai_result,
        )

    def _commit_pending(
        self,
        db: Session,
        *,
        user_id: str,
        pending: dict[str, Any],
        language: LanguageInfo | None = None,
        confidence: float = 1.0,
        ai_result: Any = None,
    ) -> AssistantResponse:
        lang = language or default_language()
        try:
            kwargs = pending_event_to_create_kwargs(pending, user_id)
        except ValueError as exc:
            return AssistantResponse(
                ok=False,
                intent="create_event",
                language=lang,
                confidence=confidence,
                message=str(exc),
                requires_clarification=True,
                pending_event=pending,
                ai=ai_result,
            )

        event = event_service.create_event(db, **kwargs)
        return AssistantResponse(
            ok=True,
            intent="create_event",
            language=lang,
            confidence=confidence,
            message=created_message(event.label, lang),
            needs_confirmation=False,
            requires_clarification=False,
            event=EventOut.model_validate(event),
            ai=ai_result,
        )

    def _handle_search(
        self,
        db: Session,
        user_id: str,
        validated: Any,
        ai_result: Any,
    ) -> AssistantResponse:
        language: LanguageInfo = validated.language
        filters = {k: v for k, v in (validated.filters or {}).items() if v is not None}
        if validated.missing_fields and not filters:
            return AssistantResponse(
                ok=True,
                intent="search_events",
                language=language,
                confidence=validated.confidence,
                message=validated.message or "What should I search for?",
                missing_fields=validated.missing_fields,
                requires_clarification=True,
                filters=validated.filters,
                ai=ai_result,
            )

        # Always call search (search_reminder tool equivalent) and return events array
        events = event_service.search_events(db, user_id, filters)
        return AssistantResponse(
            ok=True,
            intent="search_events",
            language=language,
            confidence=validated.confidence,
            message=search_message(len(events), language),
            events=[EventOut.model_validate(e) for e in events],
            filters=validated.filters,
            ai=ai_result,
        )


assistant_service = AssistantService()
