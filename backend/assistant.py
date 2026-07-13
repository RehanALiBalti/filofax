"""Orchestrates AI parsing → slot filling → auto-save / search."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from backend.ai.service import AIService, AIServiceError, ai_service
from backend import event_service
from backend.language import (
    ask_next_field_message,
    created_message,
    default_language,
    help_message,
    normalize_language,
    search_message,
    unclear_message,
)
from backend.models import AssistantResponse, EventOut, LanguageInfo
from backend.draft_store import clear_draft, merge_client_pending, save_draft
from backend.slot_fill import (
    apply_slot_reply,
    ask_again,
    empty_draft,
    enrich_draft_from_message,
    is_soft_ack,
    is_year_only_date,
    lock_confirmed_slots,
    merge_ai_into_draft,
    missing_fields,
    next_missing,
    scrub_invented_date,
    scrub_invented_time,
)
from backend.validators import pending_event_to_create_kwargs, validate_ai_response


GREETING_WORDS = {
    "hi",
    "hello",
    "hey",
    "salam",
    "salaam",
    "assalam",
    "asalam",
    "assalamu alaikum",
    "assalamualaikum",
    "aoa",
    "hola",
    "bonjour",
}

CANCEL_WORDS = {
    "cancel",
    "nah",
    "rehne do",
    "mat karo",
    "stop",
}


def _is_greeting(message: str) -> bool:
    """True only for short greetings, not 'Hello, remind me at 9pm'."""
    text = message.strip().lower()
    if text in GREETING_WORDS:
        return True
    bare = re.sub(r"[.!?,]+$", "", text).strip()
    return bare in GREETING_WORDS


def _is_cancel(message: str) -> bool:
    text = message.strip().lower()
    return text in CANCEL_WORDS or text.startswith("cancel")


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
        _ = confirm  # auto-save when complete; no confirm gate
        text = message.strip()
        lang = default_language()

        if not text:
            return AssistantResponse(
                ok=False,
                intent="unknown",
                language=lang,
                confidence=0.0,
                message=help_message(lang),
            )

        pending_event = merge_client_pending(user_id, pending_event)
        draft = merge_ai_into_draft(pending_event, None) if pending_event else None

        if draft and _is_cancel(text):
            clear_draft(user_id)
            return AssistantResponse(
                ok=True,
                intent="cancel_event",
                language=lang,
                confidence=1.0,
                message="Cancelled. No event was saved.",
                pending_event=None,
            )

        if _is_greeting(text) and not draft:
            return AssistantResponse(
                ok=True,
                intent="clarify",
                language=lang,
                confidence=1.0,
                message=help_message(lang),
                requires_clarification=True,
            )

        # --- Active create draft: fill next missing slot, keep asking until clear ---
        if draft and missing_fields(draft):
            return self._continue_slot_fill(db, user_id=user_id, text=text, draft=draft)

        # --- Fresh message: AI extract create/search ---
        try:
            ai_result = self.ai.parse_message(
                text,
                conversation_context=None,
            )
        except AIServiceError as exc:
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

        if validated.intent == "search_events":
            return self._handle_search(db, user_id, validated, ai_result)

        if validated.intent == "create_event" or (validated.event and any(
            validated.event.get(k) for k in ("date", "time", "label", "category")
        )):
            merged = merge_ai_into_draft(draft, validated.event)
            merged = enrich_draft_from_message(merged, text)
            # Never keep an AI-guessed date/time when user did not state one
            merged = scrub_invented_date(merged, text, trusted_pending=pending_event)
            merged = scrub_invented_time(merged, text, trusted_pending=pending_event)
            return self._finish_or_ask(db, user_id, merged, language, validated.confidence, ai_result)

        # Unclear start — begin create flow by asking for date
        if validated.intent in ("unclear", "clarify", "unknown"):
            # If message looks like create intent keywords, start draft
            lower = text.lower()
            create_hints = (
                "add",
                "create",
                "schedule",
                "reminder",
                "remind",
                "event",
                "meeting",
                "appointment",
                "kar do",
                "add kar",
            )
            if any(h in lower for h in create_hints):
                draft = enrich_draft_from_message(empty_draft(), text)
                draft = scrub_invented_date(draft, text)
                draft = scrub_invented_time(draft, text)
                return self._finish_or_ask(db, user_id, draft, language, 0.7, ai_result)
            return AssistantResponse(
                ok=True,
                intent=validated.intent,
                language=language,
                confidence=validated.confidence,
                message=validated.message or unclear_message(language),
                requires_clarification=True,
                ai=ai_result,
            )

        return AssistantResponse(
            ok=True,
            intent=validated.intent,
            language=language,
            confidence=validated.confidence,
            message=validated.message or help_message(language),
            requires_clarification=True,
            ai=ai_result,
        )

    def _continue_slot_fill(
        self,
        db: Session,
        *,
        user_id: str,
        text: str,
        draft: dict[str, Any],
    ) -> AssistantResponse:
        language = default_language()
        field = next_missing(draft)
        assert field is not None

        # Soft acks / thanks — keep draft and re-ask the same field
        if is_soft_ack(text):
            return self._ask_next(draft, language, confidence=0.9, retry=True, user_id=user_id)

        # Year alone is not a full date
        if field == "date" and is_year_only_date(text):
            save_draft(user_id, draft)
            return AssistantResponse(
                ok=True,
                intent="create_event",
                language=language,
                confidence=0.9,
                message="Year alone is not enough. Please give a full date, e.g. 20 June 2027.",
                missing_fields=missing_fields(draft),
                needs_confirmation=False,
                requires_clarification=True,
                pending_event=draft,
            )

        # 1) Deterministic fill for the field we asked
        filled = apply_slot_reply(pending=draft, message=text, field=field, today=date.today())
        if filled is not None:
            filled = enrich_draft_from_message(filled, text)
            filled = lock_confirmed_slots(draft, filled, allow_update={field})
            return self._finish_or_ask(db, user_id, filled, language, 0.95, None)

        # User may answer a different missing field (e.g. time while date was lost client-side)
        for other in missing_fields(draft):
            if other == field:
                continue
            alt = apply_slot_reply(pending=draft, message=text, field=other, today=date.today())
            if alt is not None:
                alt = enrich_draft_from_message(alt, text)
                alt = lock_confirmed_slots(draft, alt, allow_update={other})
                return self._finish_or_ask(db, user_id, alt, language, 0.95, None)

        # Also try enriching whole message (user may answer multiple fields)
        enriched = enrich_draft_from_message(dict(draft), text)
        enriched = lock_confirmed_slots(draft, enriched)
        if missing_fields(enriched) != missing_fields(draft):
            return self._finish_or_ask(db, user_id, enriched, language, 0.9, None)

        # Invalid calendar date like August 50
        if field == "date" and re.search(
            r"\b(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\b",
            text.lower(),
        ):
            save_draft(user_id, draft)
            return AssistantResponse(
                ok=True,
                intent="create_event",
                language=language,
                confidence=0.9,
                message="That date is not valid. Please use a real day, e.g. 20 August 2026.",
                missing_fields=missing_fields(draft),
                needs_confirmation=False,
                requires_clarification=True,
                pending_event=draft,
            )

        # 2) Ask AI with strong context — still merge; never drop draft
        context = {
            "intent": "create_event",
            "event": draft,
            "missing_fields": missing_fields(draft),
            "ask_only": field,
            "instruction": f"User is answering the missing field '{field}'. Extract only that if possible. Preserve all previous event fields.",
        }
        try:
            ai_result = self.ai.parse_message(text, conversation_context=context)
            language = normalize_language(ai_result.language)
            validated = validate_ai_response(ai_result)
            language = validated.language
            merged = merge_ai_into_draft(draft, validated.event)
            merged = enrich_draft_from_message(merged, text)
            merged = lock_confirmed_slots(draft, merged, allow_update={field})
            # If still missing the same field, re-ask clearly
            if field in missing_fields(merged):
                return self._ask_next(
                    merged,
                    language,
                    confidence=validated.confidence,
                    ai_result=ai_result,
                    retry=True,
                    user_id=user_id,
                )
            return self._finish_or_ask(
                db, user_id, merged, language, validated.confidence, ai_result
            )
        except AIServiceError:
            return self._ask_next(draft, language, confidence=0.5, retry=True, user_id=user_id)

    def _finish_or_ask(
        self,
        db: Session,
        user_id: str,
        event: dict[str, Any],
        language: LanguageInfo,
        confidence: float,
        ai_result: Any,
    ) -> AssistantResponse:
        miss = missing_fields(event)
        if miss:
            return self._ask_next(
                event, language, confidence=confidence, ai_result=ai_result, user_id=user_id
            )
        return self._commit_pending(
            db,
            user_id=user_id,
            pending=event,
            language=language,
            confidence=confidence,
            ai_result=ai_result,
        )

    def _ask_next(
        self,
        event: dict[str, Any],
        language: LanguageInfo,
        *,
        confidence: float = 0.9,
        ai_result: Any = None,
        retry: bool = False,
        user_id: str | None = None,
    ) -> AssistantResponse:
        info = ask_again(event=event, language=language, confidence=confidence)
        msg = info["message"]
        if retry and info["next_field"]:
            # Emphasize we still need a clear value
            again = {
                "en": "Please answer clearly. ",
                "ur-Latn": "Please clear bata dein. ",
                "ur": "براہ کرم واضح بتائیں۔ ",
            }
            code = language.code or "en"
            prefix = again.get(code) or again.get(code.split("-")[0]) or again["en"]
            msg = prefix + msg

        if user_id:
            save_draft(user_id, event)

        return AssistantResponse(
            ok=True,
            intent="create_event",
            language=language,
            confidence=confidence,
            message=msg,
            missing_fields=info["missing_fields"],
            needs_confirmation=False,
            requires_clarification=True,
            pending_event=event,
            ai=ai_result,
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
        # Safety: never save while still missing
        miss = missing_fields(pending)
        if miss:
            return self._ask_next(
                pending, lang, confidence=confidence, ai_result=ai_result, user_id=user_id
            )

        try:
            kwargs = pending_event_to_create_kwargs(pending, user_id)
        except ValueError:
            return self._ask_next(
                pending, lang, confidence=confidence, ai_result=ai_result, retry=True, user_id=user_id
            )

        event = event_service.create_event(db, **kwargs)
        clear_draft(user_id)
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
        if not filters:
            return AssistantResponse(
                ok=True,
                intent="search_events",
                language=language,
                confidence=validated.confidence,
                message=validated.message or "What should I search for? (date, category, or keyword)",
                missing_fields=["keyword"],
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
