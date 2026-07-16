"""Detect casual chat vs reminder slot answers."""

from __future__ import annotations

import re
from typing import Any

_DECLINE_PATTERNS = (
    r"\b(don'?t|do not|dont)\s+(want|like|need)\b.*\b(set up|setup|event|reminder|meeting|schedule)\b",
    r"\bnot\s+(set up|setup|setting up|an event|a reminder)\b",
    r"\b(no|stop)\s+(event|reminder)\b",
    r"\bjust\s+(talk|chat|speak)\b",
    r"\b(only|just)\s+(talk|chat|speak)\b",
    r"\bcan you talk (with|to) me\b",
    r"\btalk (with|to) me\b",
    r"\bchat (with|to) me\b",
    r"\bi('?m| am)\s+free\b",
    r"\bi('?m| am)\s+(talking|speaking)\s+(with|to)\s+you\b",
    r"\bnot\s+set\s+up\s+(your|the|any)?\s*(name|event|reminder)?\b",
)

_CONVERSATIONAL_PATTERNS = (
    r"^(what|who|why|how|when|where|which|can you|could you|would you|will you|do you|are you|tell me)\b",
    r"\bwhat are you doing\b",
    r"\bhow are you\b",
    r"\bwho are you\b",
    r"\bwhat is your name\b",
    r"\byour name\b",
    r"\bwhat('?s| is) up\b",
    r"\btalking (with|to) you\b",
    r"\b(speak|talk|chat)\s+(with|to)\s+(you|me)\b",
    r"\bmy love\b",
    r"\bhello hello\b",
)

_SLOT_HINT_WORDS = (
    "reminder",
    "event",
    "meeting",
    "appointment",
    "date",
    "time",
    "tomorrow",
    "today",
    "category",
    "title",
    "label",
    "schedule",
    "add",
    "create",
    "save",
    "important",
    "todo",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


def normalize_chat_text(message: str) -> str:
    text = message.strip().lower()
    text = text.replace("'", "'")
    text = re.sub(r"[.!?,;:]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def draft_has_progress(draft: dict[str, Any] | None) -> bool:
    draft = draft or {}
    for key in ("date", "time", "category", "label"):
        val = draft.get(key)
        if val is not None and str(val).strip() and str(val).lower() != "null":
            return True
    return False


def draft_has_meaningful_progress(draft: dict[str, Any] | None) -> bool:
    """Date, time, or category — label-only drafts are often misfires from chitchat."""
    draft = draft or {}
    for key in ("date", "time", "category"):
        val = draft.get(key)
        if val is not None and str(val).strip() and str(val).lower() != "null":
            return True
    return False


def is_declining_event_setup(message: str) -> bool:
    t = normalize_chat_text(message)
    if not t:
        return False
    return any(re.search(p, t) for p in _DECLINE_PATTERNS)


def is_conversational_message(message: str) -> bool:
    """
    Casual chat or questions to the assistant — not slot answers.
    Declining setup always wins; clear reminder keywords keep slot parsing.
    """
    t = normalize_chat_text(message)
    if not t:
        return False
    if is_declining_event_setup(message):
        return True
    if any(re.search(rf"\b{re.escape(w)}\b", t) for w in _SLOT_HINT_WORDS):
        return False
    if any(re.search(p, t) for p in _CONVERSATIONAL_PATTERNS):
        return True
    if "?" in message or t.endswith(" right now"):
        if re.search(r"\b(you|your|u)\b", t):
            return True
    if len(t.split()) >= 7 and not re.search(r"\b\d{1,2}(?::\d{2})?\s*(am|pm)\b", t):
        if re.search(r"\b(i('?m| am)|you|your|talk|chat|love|free)\b", t):
            return True
    return False
