"""Deterministic slot filling — keep asking until date/time/category/label are clear."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from dateutil import parser as date_parser

from backend.config import ALLOWED_CATEGORIES, ASK_FIELD_ORDER
from backend.conversation import is_conversational_message
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


def _hhmm_from_parts(hour: int, minute: int, ampm: str = "") -> str | None:
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return None


def _is_negated_time_match(text: str, match_start: int) -> bool:
    """True when the time is preceded by not / instead of (e.g. 'not 9:00')."""
    before = text[max(0, match_start - 14) : match_start]
    return bool(re.search(r"\b(?:not|n't|instead\s+of)\s+$", before))


def _parse_flexible_time(text: str) -> str | None:
    """
    Extract a time. When several times appear, use the last non-negated one
    so '9:00 … 9:25' and '9:25 not 9:00' both resolve to 9:25.
    """
    original = text.strip().lower()
    t = original.replace("p.m.", "pm").replace("a.m.", "am").replace("p.m", "pm").replace("a.m", "am")
    t = t.replace("baje", " ").replace("bajay", " ").replace("o'clock", " ")
    t = re.sub(r"\s+", " ", t).strip()

    ampm_hits: list[str] = []
    for m in re.finditer(r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", t):
        if _is_negated_time_match(t, m.start()):
            continue
        value = _hhmm_from_parts(int(m.group(1)), int(m.group(2) or 0), m.group(3))
        if value:
            ampm_hits.append(value)
    if ampm_hits:
        return ampm_hits[-1]

    # "time/timer/waqt is 9pm" — last match wins
    time_is_hits: list[str] = []
    for m in re.finditer(
        r"(?:time|timer|waqt)\s+(?:will\s+be|is)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
        t,
    ):
        if _is_negated_time_match(t, m.start()):
            continue
        value = _hhmm_from_parts(int(m.group(1)), int(m.group(2) or 0), m.group(3) or "")
        if value:
            time_is_hits.append(value)
    if time_is_hits:
        return time_is_hits[-1]

    # 24h clock like 21:00 / 21:25 — last non-negated
    hits_24: list[str] = []
    for m24 in re.finditer(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", t):
        if _is_negated_time_match(t, m24.start()):
            continue
        hits_24.append(f"{int(m24.group(1)):02d}:{m24.group(2)}")
    if hits_24:
        return hits_24[-1]

    # "sham 4" / evening without am/pm — last digit group when evening cues present
    if any(w in original for w in ("sham", "evening", "night", "baje", "bajay")):
        evening_hits: list[str] = []
        for m2 in re.finditer(r"(\d{1,2})(?::(\d{2}))?", t):
            if _is_negated_time_match(t, m2.start()):
                continue
            hour = int(m2.group(1))
            minute = int(m2.group(2) or 0)
            if any(w in original for w in ("sham", "evening", "night")) and hour < 12:
                hour += 12
            value = _hhmm_from_parts(hour, minute)
            if value:
                evening_hits.append(value)
        if evening_hits:
            return evening_hits[-1]

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

    # Only set label when user explicitly says label/title — never invent / never auto Reminder
    if not out.get("label"):
        value = _extract_label(text)
        if value and message_has_explicit_label(text):
            out["label"] = value

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
    prior_category = draft.get("category")
    prior_label = draft.get("label")

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

    if prior_category:
        if message_has_explicit_category(text):
            parsed = _parse_category_reply(text)
            out["category"] = parsed or prior_category
        else:
            out["category"] = prior_category
    else:
        out = scrub_invented_category(out, text)

    if prior_label:
        if message_has_explicit_label(text):
            parsed = _extract_label(text)
            out["label"] = parsed or prior_label
        else:
            out["label"] = prior_label
    else:
        out = scrub_invented_label(out, text)

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


def message_has_explicit_category(text: str) -> bool:
    return _parse_category_reply(text) is not None


def message_has_explicit_label(text: str) -> bool:
    lower = text.strip().lower()
    if re.search(r"(?:label|title)\s+(?:will\s+be|is|:)\s*\S+", lower):
        return True
    if re.search(r"(?:my\s+)?(?:level\s+|event\s+|reminder\s+)?name\s+(?:will\s+be|is|:)\s*\S+", lower):
        return True
    if re.search(r"(?:event|reminder)\s+name\s+(?:will\s+be|is|:)\s*\S+", lower):
        return True
    if re.search(r"\bas\s+(?:a|an)\s+\S+", lower):
        return True
    if re.search(r"(?:name\s+it|call\s+it|titled|named)\s+\S+", lower):
        return True
    # Natural / Urdu-Roman cues
    if re.search(r"\b(?:naam|title|label)\s*(?:hai|he|:|=)\s*\S+", lower):
        return True
    if re.search(r"\b(?:reminder|event|meeting)\s+for\s+(?!me\b|you\b|us\b|please\b)\S+", lower):
        return True
    if re.search(r"\b(?:about|regarding)\s+(?:the\s+)?(?!me\b|you\b|it\b)\S+", lower):
        return True
    return False


_LABEL_TAIL_SPLIT = re.compile(
    r"\s+and\s+(?:the\s+)?(?:reminder\s+)?(?:date|time|category|label|title)\b"
    r"|\s+and\s+the\s+reminder\b"
    r"|\s+and\s+(?:it\s+)?(?:will\s+)?(?:be\s+)?(?:start|starts|starting|begin|begins|held)\b"
    r"|\s+and\s+it\s+will\b"
    r"|\s+and\s+(?:the\s+)?time\b"
    r"|\s+start(?:s|ing)?\s+on\b"
    r"|\s+will\s+(?:be\s+)?(?:start|starts|starting|begin|begins)\b"
    r"|\s+on\s+(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|"
    r"fri(?:day)?|sat(?:urday)?|sun(?:day)?|today|tomorrow)\b"
    r"|\s+this\s+(?:week|monday|coming)\b"
    r"|\s+(?:tomorrow|today|kal|aaj)\b"
    r"|\s+aur\b"
    r"|\s+(?:at|@)\s*\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?\b"
    r"|\s+on\s+\d{1,2}\b"
    r"|\s+for\s+\d{1,2}\b"
    r"|[.,;]",
    flags=re.IGNORECASE,
)

# Stop capturing the title once schedule chatter begins
_LABEL_STOP_LOOKAHEAD = (
    r"(?=\s+and\s+(?:the\s+)?(?:reminder\s+)?(?:date|time|category|label|title)\b"
    r"|\s+and\s+(?:it\s+)?(?:will\s+)?(?:be\s+)?(?:start|starts|starting|begin|begins|held)\b"
    r"|\s+and\s+it\s+will\b"
    r"|\s+and\s+(?:the\s+)?time\b"
    r"|\s+start(?:s|ing)?\s+on\b"
    r"|\s+on\s+(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|"
    r"fri(?:day)?|sat(?:urday)?|sun(?:day)?|today|tomorrow)\b"
    r"|\s+this\s+(?:week|monday|coming)\b"
    r"|\s+(?:tomorrow|today|kal|aaj)\b"
    r"|\s+aur\b"
    r"|\s+(?:at|@)\s*\d"
    r"|$)"
)


def _clean_label(raw: str) -> str | None:
    s = raw.strip(" .!?,;:\"'")
    s = re.sub(r"\s+", " ", s)
    # Cut trailing date/time chatter if the cue pattern missed it
    s = _LABEL_TAIL_SPLIT.split(s, maxsplit=1)[0].strip(" .!?,;:\"'")
    s = re.sub(r"\s+(please|thanks|thank you|now)\.?$", "", s, flags=re.IGNORECASE)
    if not s:
        return None
    if len(s) > 255:
        s = s[:255].rstrip()
    if s.lower() in {
        "to do",
        "todo",
        "appointment",
        "important",
        "event",
        "reminder",
        "me",
        "you",
        "us",
        "please",
        "it",
        "this",
        "that",
    }:
        return None
    # Keep labels reasonably short (STT dumps get truncated)
    words = s.split()
    if len(words) > 8:
        s = " ".join(words[:8])
        words = s.split()
    if len(words) <= 6:
        s = " ".join(w[:1].upper() + w[1:] if w else w for w in words)
    return s


def _extract_label(text: str) -> str | None:
    """Pull a short event title out of a full sentence when possible."""
    t = text.strip()
    if not t:
        return None

    stop = _LABEL_STOP_LOOKAHEAD
    # Last successful cue wins (user often corrects mid-sentence).
    patterns = [
        rf"(?:label|title)\s+(?:will\s+be|is|:)\s*(.+?){stop}",
        rf"(?:my\s+)?(?:level\s+|event\s+|reminder\s+)?name\s+(?:will\s+be|is|:)\s*(.+?){stop}",
        rf"(?:event|reminder)\s+name\s+(?:will\s+be|is|:)\s*(.+?){stop}",
        rf"(?:name\s+it|call\s+it|titled|named)\s+(.+?){stop}",
        rf"\bas\s+(?:a|an)\s+(.+?){stop}",
        rf"\b(?:naam|title|label)\s*(?:hai|he|:|=)\s*(.+?){stop}",
        rf"\b(?:reminder|event|meeting)\s+for\s+(.+?){stop}",
        rf"\b(?:about|regarding)\s+(?:the\s+)?(.+?){stop}",
        r"(?:enable|set|save|make)\s+(?:this\s+)?(?:event|reminder)?\s*as\s+(?:a|an)\s+(.+)$",
        r"(?:label|title)\s+(?:should\s+be|to)\s+(.+)$",
    ]
    found: str | None = None
    for pat in patterns:
        for m in re.finditer(pat, t, flags=re.IGNORECASE):
            value = _clean_label(m.group(1))
            if value:
                found = value
    if found:
        return found

    words = t.split()
    if (
        len(words) <= 6
        and not is_conversational_message(t)
        and not re.match(
            r"^(can|could|would|please|kindly|i\s+want|i\s+need|yeah|yes|yep|what|who|why|how|when|where|do|are|is)\b",
            t,
            flags=re.IGNORECASE,
        )
        and not re.search(r"\b(you|your|u)\b", t, flags=re.IGNORECASE)
    ):
        return _clean_label(t)

    return None


def scrub_invented_category(
    draft: dict[str, Any],
    message: str,
    *,
    trusted_pending: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(draft)
    if trusted_pending and trusted_pending.get("category"):
        if message_has_explicit_category(message):
            parsed = _parse_category_reply(message)
            if parsed:
                out["category"] = parsed
                return out
        out["category"] = trusted_pending["category"]
        return out
    if out.get("category") and not message_has_explicit_category(message):
        out["category"] = None
    return out


def scrub_invented_label(
    draft: dict[str, Any],
    message: str,
    *,
    trusted_pending: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(draft)
    if trusted_pending and trusted_pending.get("label"):
        if message_has_explicit_label(message):
            parsed = _extract_label(message)
            if parsed:
                out["label"] = parsed
                return out
        out["label"] = trusted_pending["label"]
        return out
    if out.get("label") and not message_has_explicit_label(message):
        if _extract_label(message) == out.get("label"):
            return out
        out["label"] = None
    return out


def is_fresh_create_request(text: str) -> bool:
    """True when the user is starting a new create, not answering a slot."""
    from backend.conversation import is_declining_event_setup

    lower = text.strip().lower()
    if not lower:
        return False
    if is_declining_event_setup(text):
        return False
    # Confirm / save intents must never wipe an in-progress reminder
    if re.search(
        r"\b(looks good|sounds good|please (save|add)|save it|add it|"
        r"go ahead|add (in|to) my)\b",
        lower,
    ):
        return False
    # Pure category / short slot answers are not a fresh create
    if _parse_category_reply(lower) and len(lower.split()) <= 6 and not any(
        h in lower for h in ("add", "create", "schedule", "remind", "reminder", "event")
    ):
        return False
    if is_year_only_date(lower) or message_has_explicit_date(lower) or message_has_explicit_time(lower):
        # "add reminder on 5 july" is fresh create WITH date — still fresh
        pass
    starters = (
        r"\b(add|create|schedule)\b",
        r"\b(remind|reminder)\b",
        r"\bnew\s+(event|reminder|meeting)\b",
        r"\b(set\s*up|setup)\s+(an?\s+)?(event|reminder|meeting)\b",
        r"\b(set\s*up|setup)\s+(for|an?\s+event)\b",
        r"\b(can|could|would)\s+you\s+(set\s*up|setup|create|add|schedule)\b",
        r"\b(please|kindly)\s+(set\s*up|setup|create|add|schedule)\b",
        r"\bhelp\s+me\s+(set\s*up|setup|create|add|schedule)\b",
        r"\bcan you add\b",
        r"\bplease add\b",
        r"\bi want to (add|create|set\s*up|setup)\b",
        r"\bi need (a |an )?(reminder|event|meeting)\b",
    )
    return any(re.search(p, lower) for p in starters)


def looks_like_create_request_not_title(text: str) -> bool:
    """True for imperative create asks that must never become the event title."""
    t = text.strip()
    if not t:
        return False
    if is_fresh_create_request(t):
        return True
    return bool(
        re.search(
            r"^(can|could|would|please|kindly|help|i\s+want|i\s+need)\b",
            t,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(set\s*up|setup|create|schedule|add)\b.*\b(event|reminder|meeting)\b",
            t,
            flags=re.IGNORECASE,
        )
    )


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
        if is_conversational_message(text):
            return None
        if looks_like_create_request_not_title(text) and not message_has_explicit_label(text):
            return None
        # Never steal date / time / category answers as the event name
        if message_has_explicit_time(text) and not message_has_explicit_label(text):
            return None
        if message_has_explicit_date(text) and not message_has_explicit_label(text):
            return None
        if message_has_explicit_category(text) and not message_has_explicit_label(text):
            return None
        if re.search(
            r"\b(category|date|time)\b",
            text,
            flags=re.IGNORECASE,
        ) and not message_has_explicit_label(text):
            return None

        value = _extract_label(text)
        if not value:
            # Plain short title only — e.g. "Card Check", not a full sentence dump
            words = text.split()
            if (
                1 <= len(words) <= 8
                and not looks_like_create_request_not_title(text)
                and not re.match(
                    r"^(can|could|would|please|kindly|i\s+want|i\s+need|yeah|yes|yep|what|who|why|how|when|where|do|are|is)\b",
                    text,
                    flags=re.IGNORECASE,
                )
                and not re.search(r"\b(you|your|u|for me)\b", text, flags=re.IGNORECASE)
                and not message_has_explicit_date(text)
                and not message_has_explicit_time(text)
                and not message_has_explicit_category(text)
            ):
                value = _clean_label(text)
            if not value:
                return None
        updated["label"] = value
        return updated

    return None


def _slot_filled(event: dict[str, Any], key: str) -> bool:
    value = event.get(key)
    return value is not None and str(value).strip() != "" and str(value).lower() != "null"


def absorb_user_message(
    draft: dict[str, Any],
    message: str,
    *,
    preferred_field: str | None = None,
    today: date | None = None,
) -> dict[str, Any] | None:
    """
    Order-agnostic intake: pull date / time / category / label from whatever the
    user said, even if it is not the field we asked for (or they packed several
    at once / corrected an earlier answer).

    Returns an updated draft when anything new was filled or changed, else None.
    """
    today = today or date.today()
    text = message.strip()
    if not text or is_conversational_message(text):
        return None

    before = dict(draft)
    out = enrich_draft_from_message(dict(draft), text, today=today)

    # Fill still-empty slots. Label last — it is the greediest matcher.
    for field in ("date", "time", "category", "label"):
        if _slot_filled(out, field):
            continue
        filled = apply_slot_reply(pending=out, message=text, field=field, today=today)
        if filled is not None:
            out = filled

    # Preferred slot as last resort if still empty (short answers like "tomorrow")
    if preferred_field and not _slot_filled(out, preferred_field):
        filled = apply_slot_reply(
            pending=out, message=text, field=preferred_field, today=today
        )
        if filled is not None:
            out = filled

    changed = False
    for key in ("date", "time", "category", "label", "notes"):
        prev = before.get(key)
        cur = out.get(key)
        prev_empty = not _slot_filled(before, key) if key != "notes" else (
            prev is None or str(prev).strip() == ""
        )
        cur_ok = _slot_filled(out, key) if key != "notes" else (
            cur is not None and str(cur).strip() != ""
        )
        if prev_empty and cur_ok:
            changed = True
            break
        if (
            not prev_empty
            and cur_ok
            and str(prev).strip() != str(cur).strip()
        ):
            changed = True
            break

    return out if changed else None


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
