"""Orchestrates AI parsing → slot filling → soft-confirm save / search."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from backend.ai.service import AIService, AIServiceError, ai_service
from backend import event_service
from backend.language import (
    ask_next_field_message,
    confirm_save_message,
    created_message,
    default_language,
    greeting_message,
    help_message,
    normalize_language,
    progress_ask_message,
    retry_prefix,
    search_message,
    smalltalk_message,
    unclear_message,
)
from backend.chat_style import is_affirmative, is_negative, suggested_replies_for, chat_only_message
from backend.conversation import (
    draft_has_meaningful_progress,
    is_conversational_message,
    is_declining_event_setup,
)
from backend.models import AssistantResponse, EventOut, LanguageInfo
from backend.draft_store import clear_draft, merge_client_pending, save_draft
from backend.slot_fill import (
    absorb_user_message,
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


def _clean_event(event: dict[str, Any]) -> dict[str, Any]:
    """Drop internal flags before persist."""
    return {k: v for k, v in event.items() if not str(k).startswith("_")}


def _awaiting_confirm(event: dict[str, Any] | None) -> bool:
    return bool(event and event.get("_awaiting_confirm"))


def _with_confirm_flag(event: dict[str, Any]) -> dict[str, Any]:
    out = dict(event)
    out["_awaiting_confirm"] = True
    return out


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
    # Strip accidental trailing letter stuck to "you" (e.g. "how are youF")
    text = re.sub(r"\b(you|u)[a-z]\b", r"\1", text)
    text = re.sub(r"[^a-z0-9\s']+", " ", text)
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


def _is_smalltalk(message: str) -> bool:
    """Friendly check-ins like 'I'm fine' — not slot answers."""
    text = _normalize_greeting_text(message)
    if not text or _is_greeting(text):
        return False
    if message_has_explicit_date(text) or message_has_explicit_time(text):
        return False
    # Any category answer is never smalltalk ("ok so the category is to do")
    if _parse_category_reply_safe(text):
        return False
    if re.search(r"\b(category|label|title|name|date|time|reminder)\b", text):
        return False
    phrases = {
        "i am fine",
        "i'm fine",
        "im fine",
        "i am good",
        "i'm good",
        "im good",
        "doing fine",
        "doing well",
        "all good",
        "all fine",
        "yes i am fine",
        "yes i'm fine",
        "fine",
        "great",
        "good",
        "not bad",
        "same here",
        "and you",
        "how about you",
        "also fine",
        "me too",
        "okay",
        "ok",
        "alright",
    }
    if text in phrases:
        return True
    m = re.match(
        r"^(yes[, ]+)?(i('m| am) )?(doing )?(fine|good|great|okay|ok|well)\b",
        text,
    )
    if m:
        rest = text[m.end() :].strip(" .,!")
        # "ok so the category…" must NOT count as smalltalk
        return not rest or rest in {"thanks", "thank you", "thx"}
    return False


def _parse_category_reply_safe(text: str):
    from backend.slot_fill import _parse_category_reply

    return _parse_category_reply(text)


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
        timezone: str | None = None,
    ) -> AssistantResponse:
        text = message.strip()
        lang = default_language()
        tz = (timezone or "").strip() or None
        self._request_timezone = tz

        if not text and not confirm:
            return AssistantResponse(
                ok=False,
                intent="unknown",
                language=lang,
                confidence=0.0,
                message=help_message(lang),
            )

        # Cancel / clear first — never treat as a new create
        if text and _is_cancel(text):
            clear_draft(user_id)
            return AssistantResponse(
                ok=True,
                intent="cancel_event",
                language=lang,
                confidence=1.0,
                message="Reminder cleared. No event was saved.",
                pending_event=None,
            )

        # Load current draft first so soft-confirm is not wiped by "please add"
        pending_event = merge_client_pending(user_id, pending_event)
        draft = merge_ai_into_draft(pending_event, None) if pending_event else None
        if pending_event and pending_event.get("_awaiting_confirm"):
            if draft is None:
                draft = dict(pending_event)
            else:
                draft["_awaiting_confirm"] = True

        # Soft confirm BEFORE fresh-create wipe ("yeah looks good please add…")
        if draft and not missing_fields(draft) and (confirm or _awaiting_confirm(draft)):
            gate = self._handle_confirm_gate(
                db,
                user_id=user_id,
                text=text or "yes",
                draft=draft,
                confirm=confirm,
                language=lang,
            )
            if gate is not None:
                return gate

        # New "add reminder / create event" always starts clean — ignore stale draft
        if text and is_fresh_create_request(text):
            clear_draft(user_id)
            pending_event = None
            draft = None
        elif not draft and pending_event:
            draft = merge_ai_into_draft(pending_event, None)

        if text and _is_greeting(text):
            greet = greeting_message(lang, user_id=user_id, text=text)
            # Mid-setup: answer socially, then gently continue the open slot
            if draft and draft_has_meaningful_progress(draft) and missing_fields(draft):
                nxt = next_missing(draft)
                ask = (
                    ask_next_field_message(nxt, lang, user_id=user_id, text=text)
                    if nxt
                    else ""
                )
                combined = greet if ask and ask in greet else f"{greet} {ask}".strip()
                save_draft(user_id, draft)
                return AssistantResponse(
                    ok=True,
                    intent="create_event",
                    language=lang,
                    confidence=1.0,
                    message=combined,
                    missing_fields=missing_fields(draft),
                    requires_clarification=True,
                    pending_event=draft,
                    suggested_replies=suggested_replies_for(nxt or "date"),
                )
            # Greeting alone → social reply only (no forced event draft)
            if draft and not draft_has_meaningful_progress(draft):
                clear_draft(user_id)
            return AssistantResponse(
                ok=True,
                intent="clarify",
                language=lang,
                confidence=1.0,
                message=greet,
                pending_event=None,
            )

        if text and _is_smalltalk(text):
            chatty = smalltalk_message(lang, user_id=user_id, text=text)
            if draft and draft_has_meaningful_progress(draft) and missing_fields(draft):
                nxt = next_missing(draft)
                ask = (
                    ask_next_field_message(nxt, lang, user_id=user_id, text=text)
                    if nxt
                    else ""
                )
                combined = chatty if ask and ask in chatty else f"{chatty} {ask}".strip()
                save_draft(user_id, draft)
                return AssistantResponse(
                    ok=True,
                    intent="create_event",
                    language=lang,
                    confidence=1.0,
                    message=combined,
                    missing_fields=missing_fields(draft),
                    requires_clarification=True,
                    pending_event=draft,
                    suggested_replies=suggested_replies_for(nxt or "date"),
                )
            if draft and not draft_has_meaningful_progress(draft):
                clear_draft(user_id)
            return AssistantResponse(
                ok=True,
                intent="clarify",
                language=lang,
                confidence=1.0,
                message=chatty,
                pending_event=None,
            )

        # Soft confirm again if still complete (after greeting/smalltalk paths unused)
        if draft and not missing_fields(draft) and (confirm or _awaiting_confirm(draft)):
            gate = self._handle_confirm_gate(
                db,
                user_id=user_id,
                text=text or "yes",
                draft=draft,
                confirm=confirm,
                language=lang,
            )
            if gate is not None:
                return gate

        if text and is_conversational_message(text) and not is_fresh_create_request(text):
            if draft and missing_fields(draft):
                return self._continue_slot_fill(db, user_id=user_id, text=text, draft=draft)
            return self._handle_conversational(
                user_id=user_id,
                text=text,
                draft=draft,
                language=lang,
            )

        # Explicit create ask ("can you set up an event…") — start clean, ask date/time
        if text and is_fresh_create_request(text) and not (draft and missing_fields(draft)):
            started = enrich_draft_from_message(empty_draft(), text)
            started = scrub_invented_date(started, text)
            started = scrub_invented_time(started, text)
            started = scrub_invented_category(started, text)
            started = scrub_invented_label(started, text)
            return self._finish_or_ask(db, user_id, started, lang, 0.9, None)

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
            if is_conversational_message(text) and not is_fresh_create_request(text):
                return self._handle_conversational(
                    user_id=user_id,
                    text=text,
                    draft=None,
                    language=language,
                )
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

    def _handle_conversational(
        self,
        *,
        user_id: str,
        text: str,
        draft: dict[str, Any] | None,
        language: LanguageInfo,
    ) -> AssistantResponse:
        declining = is_declining_event_setup(text)
        meaningful = draft_has_meaningful_progress(draft)
        if declining or not meaningful:
            clear_draft(user_id)
            return AssistantResponse(
                ok=True,
                intent="clarify",
                language=language,
                confidence=1.0,
                message=chat_only_message(
                    language,
                    user_id=user_id,
                    text=text,
                    declining=declining,
                ),
                pending_event=None,
                requires_clarification=False,
            )
        save_draft(user_id, draft)
        return AssistantResponse(
            ok=True,
            intent="clarify",
            language=language,
            confidence=1.0,
            message=chat_only_message(
                language,
                user_id=user_id,
                text=text,
                nudge=True,
            ),
            pending_event=draft,
            requires_clarification=False,
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

        if is_conversational_message(text):
            return self._handle_conversational(
                user_id=user_id,
                text=text,
                draft=draft,
                language=language,
            )

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

        # Order-agnostic: accept any slot / pack / correction in one pass
        absorbed = absorb_user_message(
            draft, text, preferred_field=field, today=date.today()
        )
        if absorbed is not None:
            changed = self._changed_slot_keys(draft, absorbed)
            newly = {
                k
                for k in ("date", "time", "category", "label")
                if not draft.get(k)
                and absorbed.get(k)
                and str(absorbed.get(k)).strip()
                and str(absorbed.get(k)).lower() != "null"
            }
            allow = changed | newly
            absorbed = lock_confirmed_slots(draft, absorbed, allow_update=allow or None)
            filled_field = self._prefer_filled_field(allow, fallback=field)
            corrected = bool(
                filled_field
                and filled_field in changed
                and draft.get(filled_field)
            )
            return self._finish_or_ask(
                db,
                user_id,
                absorbed,
                language,
                0.95,
                None,
                filled_field=filled_field,
                corrected=corrected,
            )

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

        # AI fallback — still accept any fields in any order
        context = {
            "intent": "create_event",
            "event": draft,
            "missing_fields": missing_fields(draft),
            "next_ask": field,
            "instruction": (
                f"User may answer any fields in any order (date, time, category, label), "
                f"or correct previous values. Currently missing: {missing_fields(draft)}. "
                f"We next planned to ask '{field}', but extract EVERY clear field they give. "
                "Preserve all previous event fields unless the user clearly changes them."
            ),
        }
        try:
            ai_result = self.ai.parse_message(text, conversation_context=context)
            language = normalize_language(ai_result.language)
            validated = validate_ai_response(ai_result)
            language = validated.language
            merged = merge_ai_into_draft(draft, validated.event)
            merged = enrich_draft_from_message(merged, text)
            absorbed2 = absorb_user_message(
                merged, text, preferred_field=field, today=date.today()
            )
            if absorbed2 is not None:
                merged = absorbed2
            allow = {field} | self._changed_slot_keys(draft, merged)
            allow |= {
                k
                for k in ("date", "time", "category", "label")
                if not draft.get(k)
                and merged.get(k)
                and str(merged.get(k)).strip()
                and str(merged.get(k)).lower() != "null"
            }
            merged = lock_confirmed_slots(draft, merged, allow_update=allow)
            changed = self._changed_slot_keys(draft, merged)
            newly = allow - changed
            if field in missing_fields(merged) and not changed and not newly:
                return self._ask_next(
                    merged,
                    language,
                    confidence=validated.confidence,
                    ai_result=ai_result,
                    retry=True,
                    user_id=user_id,
                )
            filled_field = self._prefer_filled_field(changed | newly, fallback=field)
            return self._finish_or_ask(
                db, user_id, merged, language, validated.confidence, ai_result, filled_field=filled_field
            )
        except AIServiceError:
            fallback = absorb_user_message(
                draft, text, preferred_field=field, today=date.today()
            )
            if fallback is not None:
                changed = self._changed_slot_keys(draft, fallback)
                newly = {
                    k
                    for k in ("date", "time", "category", "label")
                    if not draft.get(k) and fallback.get(k)
                }
                fallback = lock_confirmed_slots(
                    draft, fallback, allow_update=changed | newly or None
                )
                return self._finish_or_ask(
                    db,
                    user_id,
                    fallback,
                    language,
                    0.7,
                    None,
                    filled_field=self._prefer_filled_field(changed | newly),
                )
            return self._ask_next(draft, language, confidence=0.5, retry=True, user_id=user_id)

    @staticmethod
    def _changed_slot_keys(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
        changed: set[str] = set()
        for key in ("date", "time", "category", "label"):
            prev = before.get(key)
            cur = after.get(key)
            if prev in (None, "", "null") or cur in (None, "", "null"):
                continue
            if str(prev).strip().lower() == "null" or str(cur).strip().lower() == "null":
                continue
            if str(prev).strip() != str(cur).strip():
                changed.add(key)
        return changed

    @staticmethod
    def _prefer_filled_field(keys: set[str], fallback: str | None = None) -> str | None:
        for prefer in ("time", "date", "category", "label"):
            if prefer in keys:
                return prefer
        return fallback

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
        *,
        filled_field: str | None = None,
        corrected: bool = False,
    ) -> AssistantResponse:
        miss = missing_fields(event)
        if miss:
            return self._ask_next(
                event,
                language,
                confidence=confidence,
                ai_result=ai_result,
                user_id=user_id,
                filled_field=filled_field,
                filled_value=event.get(filled_field) if filled_field else None,
                corrected=corrected,
            )
        return self._offer_confirm(
            user_id=user_id,
            pending=event,
            language=language,
            confidence=confidence,
            ai_result=ai_result,
        )

    def _handle_confirm_gate(
        self,
        db: Session,
        *,
        user_id: str,
        text: str,
        draft: dict[str, Any],
        confirm: bool,
        language: LanguageInfo,
    ) -> AssistantResponse | None:
        """Yes → save; No → discard; mid-edit → update + re-confirm."""
        if confirm or is_affirmative(text):
            return self._commit_pending(
                db,
                user_id=user_id,
                pending=draft,
                language=language,
                confidence=1.0,
            )

        # Chip / intent: "Change time" / "Change date" while confirming
        lower = text.strip().lower()
        change_time = bool(re.search(r"\b(change|edit|update)\s+(the\s+)?time\b", lower))
        change_date = bool(re.search(r"\b(change|edit|update)\s+(the\s+)?date\b", lower))
        if (change_time or change_date) and not (
            message_has_explicit_time(text) or message_has_explicit_date(text)
        ):
            ask_field = "time" if change_time else "date"
            held = dict(draft)
            held["_awaiting_confirm"] = True
            held[f"_fix_{ask_field}"] = True
            save_draft(user_id, held)
            ask = ask_next_field_message(ask_field, language, user_id=user_id, text=text)
            return AssistantResponse(
                ok=True,
                intent="confirm_event",
                language=language,
                confidence=0.95,
                message=f"Sure — {ask}",
                missing_fields=[],
                needs_confirmation=False,
                requires_clarification=True,
                pending_event=held,
                suggested_replies=suggested_replies_for(ask_field),
            )

        # Allow fixing slots while confirming (any field, any order)
        updated = absorb_user_message(dict(draft), text, today=date.today())
        if updated is not None:
            changed = self._changed_slot_keys(draft, updated)
            newly = {
                k
                for k in ("date", "time", "category", "label")
                if not draft.get(k) and updated.get(k)
            }
            if changed or newly:
                updated = lock_confirmed_slots(
                    draft, updated, allow_update=changed | newly
                )
                updated["_awaiting_confirm"] = True
                for flag in ("_fix_time", "_fix_date"):
                    updated.pop(flag, None)
                return self._offer_confirm(
                    user_id=user_id,
                    pending=updated,
                    language=language,
                    confidence=0.95,
                )

        if is_negative(text):
            clear_draft(user_id)
            return AssistantResponse(
                ok=True,
                intent="cancel_event",
                language=language,
                confidence=1.0,
                message="Okay — not saved. Say “add reminder” when you want to try again.",
                needs_confirmation=False,
                pending_event=None,
                suggested_replies=[],
            )
        return self._offer_confirm(
            user_id=user_id,
            pending=draft,
            language=language,
            confidence=0.95,
        )

    def _offer_confirm(
        self,
        *,
        user_id: str,
        pending: dict[str, Any],
        language: LanguageInfo,
        confidence: float = 1.0,
        ai_result: Any = None,
    ) -> AssistantResponse:
        event = _with_confirm_flag(pending)
        for flag in ("_fix_time", "_fix_date"):
            event.pop(flag, None)
        save_draft(user_id, event)
        msg = confirm_save_message(event, language, user_id=user_id)
        return AssistantResponse(
            ok=True,
            intent="confirm_event",
            language=language,
            confidence=confidence,
            message=msg,
            missing_fields=[],
            needs_confirmation=True,
            requires_clarification=False,
            pending_event=event,
            suggested_replies=suggested_replies_for(None, needs_confirmation=True),
            ai=ai_result,
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
        filled_field: str | None = None,
        filled_value: Any = None,
        corrected: bool = False,
    ) -> AssistantResponse:
        from backend.chat_style import draft_so_far_line

        info = ask_again(event=event, language=language, confidence=confidence)
        nxt = info["next_field"]
        style_kw: dict[str, Any] = {"user_id": user_id or "default"}

        if retry and nxt:
            prefix = retry_prefix(language, **style_kw)
            line = draft_so_far_line(event, language, user_id=style_kw["user_id"])
            ask = ask_next_field_message(nxt, language, **style_kw)
            msg = " ".join(p for p in (prefix.strip(), line, ask) if p)
        elif filled_field and filled_value not in (None, ""):
            msg = progress_ask_message(
                filled_field=filled_field,
                filled_value=filled_value,
                next_field=nxt,
                language=language,
                event=event,
                corrected=corrected,
                **style_kw,
            )
        else:
            msg = progress_ask_message(
                filled_field=None,
                filled_value=None,
                next_field=nxt,
                language=language,
                event=event,
                **style_kw,
            ) or info["message"]

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
            suggested_replies=suggested_replies_for(nxt),
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
            kwargs = pending_event_to_create_kwargs(
                _clean_event(pending),
                user_id,
                timezone=getattr(self, "_request_timezone", None),
            )
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
            message=created_message(event.label, lang, user_id=user_id),
            needs_confirmation=False,
            requires_clarification=False,
            event=EventOut.model_validate(event),
            suggested_replies=["Yes, new reminder", "No thanks"],
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
