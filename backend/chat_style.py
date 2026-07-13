"""Varied, friendly chat copy — keep collecting date → time → category → label."""

from __future__ import annotations

import hashlib
import random
from typing import Any

from backend.models import LanguageInfo


def _pick(options: list[str], *, salt: str = "") -> str:
    """Prefer random; fall back to stable pick if needed."""
    if not options:
        return ""
    try:
        return random.choice(options)
    except Exception:  # noqa: BLE001
        idx = int(hashlib.md5(salt.encode("utf-8")).hexdigest(), 16) % len(options)
        return options[idx]


def _lang_bucket(language: LanguageInfo | None) -> str:
    code = (language.code if language else "en") or "en"
    if code.startswith("ur"):
        return "ur-Latn" if "Latn" in code or code == "ur-Latn" else "ur"
    if code.startswith("hi"):
        return "hi-Latn" if "Latn" in code else "hi"
    return "en"


# --- Greetings / small talk ---

_GREETINGS: dict[str, list[str]] = {
    "en": [
        "Hey! I'm doing great — hope you are too. Want to add a reminder?",
        "Hi there! All good on my side. Shall we set up a reminder?",
        "Hello! I'm fine, thanks. Are you ready to add a reminder?",
        "Hey! Nice to chat. Want me to create a reminder for you?",
        "Hi! Doing well over here. Would you like to add a reminder?",
    ],
    "ur-Latn": [
        "Assalamu alaikum! Main theek hoon — aap kaise hain? Reminder add karein?",
        "Salam! Sab theek. Kya aap reminder banana chahte hain?",
        "Hello! Main bilkul fine hoon. Reminder set karein?",
    ],
    "ur": [
        "السلام علیکم! میں ٹھیک ہوں۔ کیا آپ یاد دہانی شامل کرنا چاہتے ہیں؟",
    ],
    "hi-Latn": [
        "Namaste! Main theek hoon. Reminder add karein?",
        "Hi! Sab badhiya. Kya reminder banana hai?",
    ],
    "hi": [
        "नमस्ते! मैं ठीक हूँ। क्या आप रिमाइंडर जोड़ना चाहेंगे?",
    ],
}

_SMALLTALK: dict[str, list[str]] = {
    "en": [
        "Glad to hear that! Want to add a reminder now?",
        "Awesome — I'm good too. Shall we create a reminder?",
        "Nice! Ready when you are — want to add a reminder?",
        "Cool. I can set a reminder whenever you like — shall we?",
    ],
    "ur-Latn": [
        "Bohat khoob! Ab reminder add karein?",
        "Achha laga sun ke. Reminder set karein?",
    ],
    "ur": [
        "اچھا لگا! کیا اب یاد دہانی شامل کریں؟",
    ],
    "hi-Latn": [
        "Badhiya! Ab reminder add karein?",
    ],
    "hi": [
        "बहुत अच्छा! क्या अब रिमाइंडर जोड़ें?",
    ],
}

# Acknowledgments after a slot is filled (varied — not the same every time)
_ACK: dict[str, dict[str, list[str]]] = {
    "date": {
        "en": [
            "Got it — {value} works.",
            "Perfect, locked in {value}.",
            "Nice choice for {value}.",
            "Alright, {value} it is.",
            "Noted: {value}.",
            "Sounds good — {value}.",
        ],
        "ur-Latn": [
            "Theek hai — {value} set.",
            "Bohat achha, {value} note kar li.",
            "Done — {value}.",
        ],
    },
    "time": {
        "en": [
            "Time set to {value}.",
            "Cool — {value} works for me.",
            "Got it, {value}.",
            "Alright, penciled in for {value}.",
            "Nice, {value} it is.",
        ],
        "ur-Latn": [
            "Waqt {value} set ho gaya.",
            "Theek — {value}.",
        ],
    },
    "category": {
        "en": [
            "Category: {value} — good pick.",
            "Okay, filing under {value}.",
            "Got it — {value}.",
            "{value} sounds right.",
        ],
        "ur-Latn": [
            "Category {value} set.",
            "Theek — {value}.",
        ],
    },
    "label": {
        "en": [
            "Calling it \"{value}\".",
            "Title set: {value}.",
            "Nice name — {value}.",
            "Alright, labeled \"{value}\".",
        ],
        "ur-Latn": [
            "Label \"{value}\" set.",
            "Title: {value}.",
        ],
    },
}

_ASK: dict[str, dict[str, list[str]]] = {
    "date": {
        "en": [
            "What date should we put this on?",
            "Which day works for you?",
            "When should this happen — what date?",
            "Pick a date for me?",
            "What date should I set?",
        ],
        "ur-Latn": [
            "Kis date pe rakhna hai?",
            "Kaun si tareekh theek rahegi?",
            "Date bata dein?",
        ],
    },
    "time": {
        "en": [
            "What time should it be?",
            "And the time?",
            "What time works best?",
            "Around what time?",
            "Got a preferred time?",
        ],
        "ur-Latn": [
            "Kis waqt ka hai?",
            "Time kya rakhain?",
            "Waqt bata dein?",
        ],
    },
    "category": {
        "en": [
            "Which category fits — To Do, Appointment, or Important?",
            "Pick a category: To Do, Appointment, or Important?",
            "Is this a To Do, Appointment, or Important?",
            "Category please — To Do / Appointment / Important?",
        ],
        "ur-Latn": [
            "Category? To Do, Appointment, ya Important?",
            "Ye To Do hai, Appointment, ya Important?",
        ],
    },
    "label": {
        "en": [
            "What should we call this reminder?",
            "Give it a short title?",
            "What label should I use?",
            "A quick name for this event?",
            "How should I title it?",
        ],
        "ur-Latn": [
            "Iska short title / label kya rakhein?",
            "Naam kya den?",
            "Label bata dein?",
        ],
    },
}

_CREATED: dict[str, list[str]] = {
    "en": [
        "All set! Saved your reminder: {label}.",
        "Done — \"{label}\" is on your list.",
        "Boom, reminder added: {label}.",
        "You're good to go — saved \"{label}\".",
        "Nice work — \"{label}\" is saved.",
    ],
    "ur-Latn": [
        "Ho gaya! Reminder save: {label}.",
        "Done — \"{label}\" add ho gaya.",
    ],
    "ur": [
        "ہو گیا! یاد دہانی محفوظ: {label}۔",
    ],
    "hi-Latn": [
        "Ho gaya! Reminder save: {label}.",
    ],
    "hi": [
        "हो गया! रिमाइंडर सेव: {label}।",
    ],
}

_RETRY: dict[str, list[str]] = {
    "en": [
        "Hmm, I didn't quite catch that. ",
        "Could you say that a bit more clearly? ",
        "Almost — just need that again clearly. ",
        "One more try, a bit clearer please. ",
    ],
    "ur-Latn": [
        "Clear bata dein please. ",
        "Thora clear dobara? ",
    ],
    "ur": [
        "براہ کرم واضح بتائیں۔ ",
    ],
}


def greeting_message(language: LanguageInfo | None = None) -> str:
    bucket = _lang_bucket(language)
    opts = _GREETINGS.get(bucket) or _GREETINGS["en"]
    return _pick(opts)


def smalltalk_message(language: LanguageInfo | None = None) -> str:
    bucket = _lang_bucket(language)
    opts = _SMALLTALK.get(bucket) or _SMALLTALK["en"]
    return _pick(opts)


def ask_next_field_message(field: str, language: LanguageInfo | None = None) -> str:
    bucket = _lang_bucket(language)
    by_field = _ASK.get(field) or _ASK["date"]
    opts = by_field.get(bucket) or by_field.get("en") or [f"Please provide {field}."]
    return _pick(opts, salt=field)


def ack_slot_message(
    field: str,
    value: Any,
    language: LanguageInfo | None = None,
) -> str:
    bucket = _lang_bucket(language)
    by_field = _ACK.get(field) or {}
    opts = by_field.get(bucket) or by_field.get("en") or ["Got it — {value}."]
    display = value
    if field == "time" and isinstance(value, str) and len(value) >= 5:
        # 12:00 → friendlier
        try:
            h, m = int(value[:2]), int(value[3:5])
            suffix = "AM" if h < 12 else "PM"
            h12 = h % 12 or 12
            display = f"{h12}:{m:02d} {suffix}" if m else f"{h12} {suffix}"
        except ValueError:
            display = value
    return _pick(opts, salt=f"{field}:{display}").format(value=display)


def progress_ask_message(
    *,
    filled_field: str | None,
    filled_value: Any,
    next_field: str | None,
    language: LanguageInfo | None = None,
) -> str:
    """Acknowledge what was just filled, then ask the next slot — varied wording."""
    parts: list[str] = []
    if filled_field and filled_value not in (None, ""):
        parts.append(ack_slot_message(filled_field, filled_value, language))
    if next_field:
        parts.append(ask_next_field_message(next_field, language))
    return " ".join(parts).strip()


def created_message(label: str, language: LanguageInfo | None = None) -> str:
    bucket = _lang_bucket(language)
    opts = _CREATED.get(bucket) or _CREATED["en"]
    return _pick(opts, salt=label).format(label=label)


def retry_prefix(language: LanguageInfo | None = None) -> str:
    bucket = _lang_bucket(language)
    opts = _RETRY.get(bucket) or _RETRY["en"]
    return _pick(opts)
