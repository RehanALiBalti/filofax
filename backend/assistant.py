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
    greeting_message,
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
    is_fresh_create_request,
    is_soft_ack,
    is_year_only_date,
    lock_confirmed_slots,
    merge_ai_into_draft,
    message_has_explicit_date,
    message_has_explicit_time,
    missing_fields,
    next_missing,
    scrub_invented_category,
    scrub_invented_date,
    scrub_invented_label,
    scrub_invented_time,
)
from backend.validators import pending_event_to_create_kwargs, validate_ai_response


GREETING_WORDS = {
    "hi",
    "hello",
    "hey",
    "hiya",
    "yo",
    "salam",
    "salaam",
    "assalam",
    "asalam",
    "assalamu alaikum",
    "assalamualaikum",
    "aoa",
    "hola",
    "bonjour",
    "namaste",
    "good morning",
    "good afternoon",
    "good evening",
    "good night",
}

GREETING_PHRASES = GREETING_WORDS | {
    "how are you",
    "how are you doing",
    "how are u",
    "how r you",
    "how r u",
    "how's it going",
    "hows it going",
    "what's up",
    "whats up",
    "what up",
    "sup",
    "hi how are you",
    "hello how are you",
    "hey how are you",
    "hi how are u",
    "hello how are u",
    "hello how are you doing",
    "hi there",
    "hello there",
    "hey there",
    "kaise ho",
    "kesi ho",
    "kya haal hai",
    "kiya haal hai",
    "kaisa hai",
}


def _normalize_greeting_text(message: str) -> str:
    text = message.strip().lower()
    text = text.replace("’", "'")
    text = re.sub(r"[.!?,;:]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_greeting(message: str) -> bool:
    """True for hellos / how-are-you — not 'Hello, add a reminder'."""
    text = _normalize_greeting_text(message)
    if not text:
        return False
    if text in GREETING_PHRASES:
        return True

    # Must not be a create / schedule request
    create_noise = (
        "add",
        "create",
        "schedule",
        "remind",
        "reminder",
        "event",
        "meeting",
        "appointment",
        "todo",
        "to do",
        "important",
        "search",
        "find",
        "cancel",
        "clear",
    )
    if any(re.search(rf"\b{re.escape(w)}\b", text) for w in create_noise):
        return False
    if message_has_explicit_date(text) or message_has_explicit_time(text):
        return False

    words = text.split()
    if len(words) > 10:
        return False

    if words[0] in GREETING_WORDS or text.startswith(
        ("how are", "how's", "hows ", "whats up", "what's up", "good morning", "good afternoon", "good evening")
    ):
        return True

    # "hello, how are you" already normalized without commas
    if re.match(r"^(hi|hello|hey)\b.*\bhow are (you|u)\b", text):
        return True
    return False


CANCEL_WORDS = {
    "cancel",
    "clear",
    "clear reminder",
    "nah",
    "rehne do",
    "mat karo",
    "stop",
}


def _is_cancel(message: str) -> bool:
    text = message.strip().lower()
    return (
        text in CANCEL_WORDS
        or text.startswith("cancel")
        or text.startswith("clear")
    )


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

        # Cancel / clear first — never treat as a new create
        if _is_cancel(text):
            clear_draft(user_id)
            return AssistantResponse(
                ok=True,
                intent="cancel_event",
                language=lang,
                confidence=1.0,
                message="Reminder cleared. No event was saved.",
                pending_event=None,
            )

        # New "add reminder / create event" always starts clean — ignore stale server/client draft
        if is_fresh_create_request(text):
            clear_draft(user_id)
            pending_event = None
            draft = None
        else:
            pending_event = merge_client_pending(user_id, pending_event)
            draft = merge_ai_into_draft(pending_event, None) if pending_event else None

        if _is_greeting(text):
            greet = greeting_message(lang)
            if draft and missing_fields(draft):
                # Keep draft; answer politely then re-ask the same field
                nxt = next_missing(draft)
                ask = ask_next_field_message(nxt, lang) if nxt else ""
                save_draft(user_id, draft)
                return AssistantResponse(
                    ok=True,
                    intent="create_event",
                    language=lang,
                    confidence=1.0,
                    message=f"{greet} {ask}".strip(),
                    missing_fields=missing_fields(draft),
                    requires_clarification=True,
                    pending_event=draft,
                )
            return AssistantResponse(
                ok=True,
                intent="greeting",
                language=lang,
                confidence=1.0,
                message=greet,
                requires_clarification=False,
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
            # Never keep AI-guessed slots when user did not state them
            merged = scrub_invented_date(merged, text, trusted_pending=pending_event)
            merged = scrub_invented_time(merged, text, trusted_pending=pending_event)
            merged = scrub_invented_category(merged, text, trusted_pending=pending_event)
            merged = scrub_invented_label(merged, text, trusted_pending=pending_event)
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
                draft = scrub_invented_category(draft, text)
                draft = scrub_invented_label(draft, text)
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
            filled = self._scrub_unasked_inventions(filled, text, draft, field)
            return self._finish_or_ask(db, user_id, filled, language, 0.95, None)

        # User may answer a different missing field (e.g. time while date was lost client-side)
        for other in missing_fields(draft):
            if other == field:
                continue
            alt = apply_slot_reply(pending=draft, message=text, field=other, today=date.today())
            if alt is not None:
                alt = enrich_draft_from_message(alt, text)
                alt = lock_confirmed_slots(draft, alt, allow_update={other})
                alt = self._scrub_unasked_inventions(alt, text, draft, other)
                return self._finish_or_ask(db, user_id, alt, language, 0.95, None)

        # Also try enriching whole message (user may answer multiple fields)
        enriched = enrich_draft_from_message(dict(draft), text)
        enriched = lock_confirmed_slots(draft, enriched)
        enriched = self._scrub_unasked_inventions(enriched, text, draft, field)
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
            merged = self._scrub_unasked_inventions(merged, text, draft, field)
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

    @staticmethod
    def _scrub_unasked_inventions(
        event: dict[str, Any],
        text: str,
        draft: dict[str, Any],
        answered_field: str,
    ) -> dict[str, Any]:
        """Drop AI/heuristic values for slots the user did not just answer."""
        out = dict(event)
        if answered_field != "date" and not draft.get("date"):
            out = scrub_invented_date(out, text)
        if answered_field != "time" and not draft.get("time"):
            out = scrub_invented_time(out, text)
        if answered_field != "category" and not draft.get("category"):
            out = scrub_invented_category(out, text)
        if answered_field != "label" and not draft.get("label"):
            out = scrub_invented_label(out, text)
        return out

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
