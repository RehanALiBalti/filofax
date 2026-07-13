"""Deterministic slot filling — keep asking until date/time/category/label are clear."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from dateutil import parser as date_parser

from backend.config import ALLOWED_CATEGORIES, ASK_FIELD_ORDER
from backend.language import ask_next_field_message, default_language
from backend.models import LanguageInfo
from backend.validators import _normalize_category, _parse_date, _parse_time, merge_pending_event


def missing_fields(event: dict[str, Any] | None) -> list[str]:
    event = event or {}
    out: list[str] = []
    for field in ASK_FIELD_ORDER:
        value = event.get(field)
        if value is None or str(value).strip() == "" or str(value).lower() == "null":
            out.append(field)
    return out


def next_missing(event: dict[str, Any] | None) -> str | None:
    miss = missing_fields(event)
    return miss[0] if miss else None


def empty_draft() -> dict[str, Any]:
    return {
        "date": None,
        "time": None,
        "label": None,
        "category": None,
        "notes": None,
    }


_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _strip_ordinals(text: str) -> str:
    return re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)


def _parse_month_day_date(text: str, today: date) -> date | None:
    """Parse '20th July', 'July 20', '20 July 2026'."""
    t = _strip_ordinals(text.strip().lower())
    t = re.sub(r"\s+", " ", t)
    names = "|".join(_MONTHS.keys())

    m = re.search(rf"\b(\d{{1,2}})\s+(?:of\s+)?({names})(?:\s*,?\s*(\d{{4}}))?\b", t)
    if m:
        day, month = int(m.group(1)), _MONTHS[m.group(2)]
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            value = date(year, month, day)
        except ValueError:
            return None
        if not m.group(3) and value < today:
            try:
                value = date(today.year + 1, month, day)
            except ValueError:
                return None
        return value

    m = re.search(rf"\b({names})\s+(\d{{1,2}})(?:\s*,?\s*(\d{{4}}))?\b", t)
    if m:
        month, day = _MONTHS[m.group(1)], int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            value = date(year, month, day)
        except ValueError:
            return None
        if not m.group(3) and value < today:
            try:
                value = date(today.year + 1, month, day)
            except ValueError:
                return None
        return value
    return None


def _parse_relative_date(text: str, today: date) -> date | None:
    t = text.strip().lower()
    if t in {"today", "aaj", "aj"}:
        return today
    if t in {"tomorrow", "kal", "tmrw", "tmr"}:
        return today + timedelta(days=1)
    if t in {"day after tomorrow", "parso", "parsoun"}:
        return today + timedelta(days=2)
    if t in {"yesterday", "kal se pehle"}:
        return today - timedelta(days=1)

    month_day = _parse_month_day_date(text, today)
    if month_day:
        return month_day

    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    for name, idx in weekdays.items():
        if re.search(rf"\b{name}\b", t):
            delta = (idx - today.weekday()) % 7
            if "next" in t and delta == 0:
                delta = 7
            if delta == 0 and "next" not in t and "this" not in t:
                delta = 7
            return today + timedelta(days=delta or 7)

    if re.search(r"\b20\d{2}-\d{2}-\d{2}\b", t) or re.search(
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", t
    ):
        parsed = _parse_date(text)
        if parsed:
            return parsed
        try:
            return date_parser.parse(
                text, fuzzy=True, default=datetime.combine(today, datetime.min.time())
            ).date()
        except (ValueError, OverflowError, TypeError):
            return None
    return None


def _parse_flexible_time(text: str) -> str | None:
    original = text.strip().lower()
    t = original.replace("p.m.", "pm").replace("a.m.", "am").replace("p.m", "pm").replace("a.m", "am")
    t = t.replace("baje", " ").replace("bajay", " ").replace("o'clock", " ")
    t = re.sub(r"\s+", " ", t).strip()

    # Explicit am/pm: "at 9 pm", "9:30pm", "9 p m"
    m = re.search(r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", t)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    # Also accept "timer/time is 9pm" style
    m = re.search(r"(?:time|timer|waqt)\s+is\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", t)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3) or ""
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    # 24h clock like 21:00
    m24 = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", t)
    if m24:
        return f"{int(m24.group(1)):02d}:{m24.group(2)}"

    # "sham 4" / evening without am/pm
    m2 = re.search(r"(\d{1,2})(?::(\d{2}))?", t)
    if m2 and any(w in original for w in ("sham", "evening", "night", "baje", "bajay")):
        hour = int(m2.group(1))
        minute = int(m2.group(2) or 0)
        if any(w in original for w in ("sham", "evening", "night")) and hour < 12:
            hour += 12
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    parsed = _parse_time(text)
    if parsed:
        return parsed.strftime("%H:%M")
    return None


def message_has_explicit_date(text: str) -> bool:
    """True only when the user clearly stated a calendar date."""
    lower = _strip_ordinals(text.strip().lower())
    if not lower:
        return False
    if _parse_month_day_date(text, date.today()) is not None:
        return True
    cues = [
        r"\btoday\b",
        r"\baaj\b",
        r"\btomorrow\b",
        r"\bkal\b",
        r"\bparso\b",
        r"\byesterday\b",
        r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\bthis\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\bon\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b20\d{2}-\d{2}-\d{2}\b",
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        r"\b(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\s+\d{1,2}\b",
        r"\b\d{1,2}\s+(?:of\s+)?(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\b",
    ]
    return any(re.search(p, lower) for p in cues)


def message_has_explicit_time(text: str) -> bool:
    lower = text.strip().lower().replace("p.m.", "pm").replace("a.m.", "am")
    if not lower:
        return False
    cues = [
        r"\b\d{1,2}(?::\d{2})?\s*(am|pm)\b",
        r"\b([01]?\d|2[0-3]):([0-5]\d)\b",
        r"\b(baje|bajay|o'clock)\b",
        r"\b(time|timer|waqt)\s+is\b",
        r"\bat\s+\d{1,2}\b",
        r"\b(sham|evening|night)\s+\d{1,2}\b",
    ]
    return any(re.search(p, lower) for p in cues)


def is_year_only_date(text: str) -> bool:
    t = text.strip().lower().rstrip(".")
    return bool(re.fullmatch(r"(?:year\s+|in\s+)?((?:19|20)\d{2})", t))


def is_soft_ack(text: str) -> bool:
    t = re.sub(r"[.!?,]+$", "", text.strip().lower()).strip()
    return t in {
        "thanks",
        "thank you",
        "thx",
        "ok",
        "okay",
        "k",
        "sure",
        "yes",
        "yep",
        "yeah",
        "haan",
        "han",
        "ji",
        "theek",
        "theek hai",
        "alright",
        "got it",
    }


def scrub_invented_date(
    draft: dict[str, Any],
    message: str,
    *,
    trusted_pending: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Drop AI-guessed dates when the user never stated a date.
    Keep date if it was already confirmed in a previous turn (trusted_pending).
    """
    out = dict(draft)
    if trusted_pending and trusted_pending.get("date"):
        # Allow overwrite only when this message clearly states a new date
        if message_has_explicit_date(message):
            parsed = _parse_relative_date(message, date.today())
            if parsed:
                out["date"] = parsed.isoformat()
                return out
        out["date"] = trusted_pending["date"]
        return out
    if out.get("date") and not message_has_explicit_date(message):
        out["date"] = None
    return out


def scrub_invented_time(
    draft: dict[str, Any],
    message: str,
    *,
    trusted_pending: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(draft)
    if trusted_pending and trusted_pending.get("time"):
        if message_has_explicit_time(message):
            parsed = _parse_flexible_time(message)
            if parsed:
                out["time"] = parsed
                return out
        out["time"] = trusted_pending["time"]
        return out
    if out.get("time") and not message_has_explicit_time(message):
        out["time"] = None
    return out


def enrich_draft_from_message(
    draft: dict[str, Any],
    message: str,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Fill any still-missing slots by scanning the full user message."""
    today = today or date.today()
    out = dict(draft)
    text = message.strip()
    if not text:
        return out
    lower = text.lower()
    prior_date = draft.get("date")
    prior_time = draft.get("time")

    if not out.get("time"):
        value = _parse_flexible_time(text)
        if value:
            out["time"] = value

    if not out.get("date") and message_has_explicit_date(text):
        for token in ("today", "aaj", "tomorrow", "kal", "parso", "yesterday"):
            if re.search(rf"\b{re.escape(token)}\b", lower):
                value = _parse_relative_date(token, today)
                if value:
                    out["date"] = value.isoformat()
                    break
        if not out.get("date"):
            value = _parse_month_day_date(text, today)
            if value:
                out["date"] = value.isoformat()
        if not out.get("date"):
            m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
            if m:
                out["date"] = m.group(1)
        if not out.get("date"):
            for name in (
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            ):
                if re.search(rf"\b{name}\b", lower):
                    value = _parse_relative_date(text, today)
                    if value:
                        out["date"] = value.isoformat()
                    break

    if not out.get("category"):
        value = _parse_category_reply(text)
        if value:
            out["category"] = value

    if not out.get("label"):
        m = re.search(
            r"(?:label|title)\s+(?:will\s+be|is|:)\s*([^.?\n]+)",
            text,
            flags=re.IGNORECASE,
        )
        if m:
            out["label"] = m.group(1).strip(" .")[:255]
        elif "remind" in lower:
            out["label"] = "Reminder"
        elif "meeting" in lower:
            out["label"] = "Meeting"
        elif "appointment" in lower:
            out["label"] = "Appointment"

    if not out.get("notes"):
        m = re.search(
            r"(?:place|location|venue)\s+(?:of\s+meeting\s+)?(?:will\s+be|is|:)\s*([^.?\n]+)",
            text,
            flags=re.IGNORECASE,
        )
        if m:
            place = m.group(1).strip(" .")
            place = re.split(r"\s+and\s+the\s+label\b", place, flags=re.IGNORECASE)[0].strip(" .")
            if place:
                out["notes"] = place[:500]

    # Never wipe slots already confirmed when user answers another field
    if prior_date:
        if message_has_explicit_date(text):
            parsed = _parse_relative_date(text, today)
            out["date"] = parsed.isoformat() if parsed else prior_date
        else:
            out["date"] = prior_date
    else:
        out = scrub_invented_date(out, text)

    if prior_time:
        if message_has_explicit_time(text):
            parsed = _parse_flexible_time(text)
            out["time"] = parsed or prior_time
        else:
            out["time"] = prior_time
    else:
        out = scrub_invented_time(out, text)

    return out


def _parse_category_reply(text: str) -> str | None:
    cat = _normalize_category(text)
    if cat:
        return cat
    t = text.strip().lower()
    # partial matches
    if "appoint" in t or "doctor" in t or "dentist" in t:
        return "Appointment"
    if "important" in t or "urgent" in t or "zaroori" in t:
        return "Important"
    if "todo" in t or "to do" in t or "task" in t or "kaam" in t:
        return "To Do"
    for allowed in ALLOWED_CATEGORIES:
        if allowed.lower() in t:
            return allowed
    return None


def lock_confirmed_slots(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    allow_update: set[str] | None = None,
) -> dict[str, Any]:
    """
    Never drop date/time/category/label that were already set in `before`,
    unless the key is in allow_update (the field just answered).
    """
    out = dict(after)
    allow = allow_update or set()
    for key in ("date", "time", "category", "label", "notes"):
        prev = before.get(key)
        if prev is None or str(prev).strip() == "" or str(prev).lower() == "null":
            continue
        if key in allow and out.get(key):
            continue
        # Keep previous value if after cleared it or left it empty
        cur = out.get(key)
        if cur is None or str(cur).strip() == "" or str(cur).lower() == "null":
            out[key] = prev
    return out


def apply_slot_reply(
    *,
    pending: dict[str, Any],
    message: str,
    field: str,
    today: date | None = None,
) -> dict[str, Any] | None:
    """
    Try to fill one missing field from a short user reply.
    Returns updated event dict, or None if the reply was not understood for that field.
    """
    today = today or date.today()
    text = message.strip()
    if not text:
        return None

    updated = dict(pending)
    if field == "date":
        if is_year_only_date(text):
            return None
        value = _parse_relative_date(text, today)
        if not value:
            return None
        updated["date"] = value.isoformat()
        return updated

    if field == "time":
        value = _parse_flexible_time(text)
        if not value:
            return None
        updated["time"] = value
        return updated

    if field == "category":
        value = _parse_category_reply(text)
        if not value:
            return None
        updated["category"] = value
        return updated

    if field == "label":
        # Any non-empty short text becomes the label
        if len(text) > 255:
            text = text[:255]
        # Avoid treating pure category/time as label if those are somehow next
        if _parse_category_reply(text) and text.lower() in {
            "to do",
            "todo",
            "appointment",
            "important",
        }:
            return None
        updated["label"] = text
        return updated

    return None


def ask_again(
    *,
    event: dict[str, Any],
    language: LanguageInfo | None = None,
    confidence: float = 0.9,
) -> dict[str, Any]:
    """Build response payload fields for re-asking the next missing slot."""
    lang = language or default_language()
    miss = missing_fields(event)
    nxt = miss[0] if miss else None
    return {
        "missing_fields": miss,
        "pending_event": event,
        "message": ask_next_field_message(nxt, lang) if nxt else "",
        "requires_clarification": bool(miss),
        "next_field": nxt,
        "confidence": confidence,
        "language": lang,
    }


def merge_ai_into_draft(
    pending: dict[str, Any] | None,
    ai_event: dict[str, Any] | None,
) -> dict[str, Any]:
    base = empty_draft()
    if pending:
        base = merge_pending_event(base, pending)
    if ai_event:
        base = merge_pending_event(base, ai_event)
    return base
