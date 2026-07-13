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

    # next monday / is monday etc.
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
        if name in t:
            delta = (idx - today.weekday()) % 7
            if "next" in t and delta == 0:
                delta = 7
            if delta == 0 and "next" not in t:
                delta = 7
            return today + timedelta(days=delta or 7)

    parsed = _parse_date(text)
    if parsed:
        return parsed
    try:
        return date_parser.parse(text, fuzzy=True, default=datetime.combine(today, datetime.min.time())).date()
    except (ValueError, OverflowError, TypeError):
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
    """True only when the user clearly stated a calendar date (not place names, etc.)."""
    lower = text.strip().lower()
    if not lower:
        return False
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
        r"\b\d{1,2}\s+(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\b",
    ]
    return any(re.search(p, lower) for p in cues)


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
        out["date"] = trusted_pending["date"]
        return out
    if out.get("date") and not message_has_explicit_date(message):
        out["date"] = None
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
                if name in lower:
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

    return scrub_invented_date(out, text)


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
