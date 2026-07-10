"""Orchestrates AI parsing → validation → confirmation → DB operations."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.ai.service import AIService, AIServiceError, ai_service
from backend import event_service
from backend.language import (
    confirm_message,
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


def _is_confirm(message: str) -> bool:
    return message.strip().lower() in {w.lower() for w in CONFIRM_WORDS} or message.strip() in CONFIRM_WORDS


def _event_summary(pending: dict[str, Any]) -> str:
    parts = [
        pending.get("label") or "Event",
        pending.get("date") or "?",
    ]
    if pending.get("time"):
        parts.append(pending["time"])
    if pending.get("category"):
        parts.append(pending["category"])
    return " · ".join(str(p) for p in parts)


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

        # Explicit confirmation of a previously proposed event
        if pending_event and (confirm or _is_confirm(text)):
            return self._commit_pending(db, user_id=user_id, pending=pending_event)

        try:
            ai_result = self.ai.parse_message(text)
        except AIServiceError as exc:
            lang = default_language()
            return AssistantResponse(
                ok=False,
                intent="unknown",
                language=lang,
                confidence=0.0,
                message=f"AI service error: {exc}",
            )

        # Prefer AI clarification language; never reject on language.
        language = normalize_language(ai_result.language)
        # Keep AIResponse.language normalized for API consumers
        ai_result.language = language

        validated = validate_ai_response(ai_result)
        language = validated.language

        if validated.event is not None and pending_event:
            validated.event = merge_pending_event(pending_event, validated.event)
            # Re-check missing fields after merge
            missing = [
                f
                for f in ("date", "label", "category")
                if not validated.event.get(f)
            ]
            validated.missing_fields = missing
            if missing:
                validated.requires_confirmation = False
                validated.requires_clarification = True
            elif validated.intent == "create_event":
                validated.requires_confirmation = True
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

        if validated.intent in ("unclear", "clarify"):
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
            return self._handle_create(db, user_id, validated, ai_result, confirm)

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
        confirm: bool,
    ) -> AssistantResponse:
        pending = validated.event or {}
        language: LanguageInfo = validated.language

        if validated.missing_fields:
            return AssistantResponse(
                ok=True,
                intent="create_event",
                language=language,
                confidence=validated.confidence,
                message=validated.message or "More details needed.",
                missing_fields=validated.missing_fields,
                needs_confirmation=False,
                requires_clarification=True,
                pending_event=pending,
                ai=ai_result,
            )

        if not confirm:
            return AssistantResponse(
                ok=True,
                intent="create_event",
                language=language,
                confidence=validated.confidence,
                message=confirm_message(_event_summary(pending), language),
                needs_confirmation=True,
                requires_clarification=False,
                pending_event=pending,
                ai=ai_result,
            )

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
