"""Varied, friendly chat copy — collect date → time → category → label attractively."""

from __future__ import annotations

import hashlib
import random
import re
from collections import defaultdict, deque
from typing import Any

from backend.models import LanguageInfo

# Per-user recent lines so we don't repeat the same phrase
_RECENT: dict[str, deque[str]] = defaultdict(lambda: deque(maxlen=6))


def _pick(options: list[str], *, salt: str = "", user_id: str = "default") -> str:
    if not options:
        return ""
    recent = _RECENT[user_id]
    fresh = [o for o in options if o not in recent]
    pool = fresh or list(options)
    try:
        choice = random.choice(pool)
    except Exception:  # noqa: BLE001
        idx = int(hashlib.md5(f"{salt}:{user_id}".encode()).hexdigest(), 16) % len(pool)
        choice = pool[idx]
    recent.append(choice)
    return choice


def detect_lang_bucket(text: str, language: LanguageInfo | None = None) -> str:
    """Pick en / ur-Latn / ur / hi-Latn from user text + model language."""
    t = (text or "").strip()
    if re.search(r"[\u0600-\u06FF]", t):
        return "ur"
    if re.search(r"[\u0900-\u097F]", t):
        return "hi"
    roman_ur = (
        r"\b(haan|han|theek|acha|achha|kala|kal|aaj|baje|waqt|yaad|karo|karein|"
        r"assalam|salam|kaise|kya|nahi|rehne|shukriya|bohat)\b"
    )
    if re.search(roman_ur, t, re.I):
        return "ur-Latn"
    if language:
        code = (language.code or "en").strip()
        if code.startswith("ur"):
            return "ur-Latn" if "Latn" in code or code == "ur-Latn" else "ur"
        if code.startswith("hi"):
            return "hi-Latn" if "Latn" in code else "hi"
    return "en"


def _lang_bucket(language: LanguageInfo | None, text: str = "") -> str:
    if text.strip():
        return detect_lang_bucket(text, language)
    return detect_lang_bucket("", language)


# Friendly reply to "hi / how are you" — always followed by the setup opener.
_GREETING_SOCIAL: dict[str, list[str]] = {
    "en": [
        "Hey! I'm doing great — thanks for asking.",
        "Hi! I'm good, thanks — nice to hear from you.",
        "Hello! I'm well, thank you.",
        "Hey there — I'm fine, thanks!",
        "Hi! Doing well over here.",
    ],
    "ur-Latn": [
        "Assalamualaikum! Main theek hoon, shukriya.",
        "Salam! Bilkul theek — aap?",
        "Hey! Main achha hoon, thanks.",
    ],
    "ur": [
        "وعلیکم السلام! میں ٹھیک ہوں، شکریہ۔",
    ],
    "hi-Latn": [
        "Namaste! Main theek hoon, dhanyavad.",
        "Hey! Main accha hoon, thanks.",
    ],
    "hi": [
        "नमस्ते! मैं ठीक हूँ, धन्यवाद।",
    ],
}

_SETUP_OPENER: dict[str, str] = {
    "en": "Let's set up the event. What is the date and time for this event?",
    "ur-Latn": "Chalen event set karte hain. Date aur time kya rakhain?",
    "ur": "چلیں ایونٹ سیٹ کرتے ہیں۔ تاریخ اور وقت کیا رکھیں؟",
    "hi-Latn": "Chaliye event set karte hain. Date aur time kya rakhein?",
    "hi": "चलिए इवेंट सेट करते हैं। तारीख और समय क्या रखें?",
}

_GREETINGS: dict[str, list[str]] = {
    bucket: [f"{s} {_SETUP_OPENER.get(bucket, _SETUP_OPENER['en'])}" for s in socials]
    for bucket, socials in _GREETING_SOCIAL.items()
}

_SMALLTALK: dict[str, list[str]] = {
    "en": [
        "Nice to hear! Let's set up the event. What is the date and time for this event?",
        "Awesome. Let's set up the event — what's the date and time?",
        "Cool — let's get into it. Date and time for this event?",
    ],
    "ur-Latn": [
        "Achha sun ke khushi hui! Chalen event set karte hain — date aur time?",
        "Zabardast. Date aur time bata dein?",
    ],
    "ur": [
        "اچھا! تاریخ اور وقت بتائیں؟",
    ],
    "hi-Latn": [
        "Badhiya! Date aur time kya rakhein?",
    ],
    "hi": [
        "बहुत अच्छा! तारीख और समय?",
    ],
}

_ACK: dict[str, dict[str, list[str]]] = {
    "date": {
        "en": [
            "Lovely — {value} is on the page.",
            "Perfect, {value} feels right.",
            "Date locked: {value}.",
            "Nice — circling {value}.",
            "Got it, {value}.",
            "Smooth. {value} it is.",
        ],
        "ur-Latn": [
            "Bohat achha — {value} set.",
            "Date lock: {value}.",
            "Theek — {value} note.",
        ],
    },
    "time": {
        "en": [
            "Nice beat — {value}.",
            "Time penciled: {value}.",
            "Cool, {value} works.",
            "Slot saved for {value}.",
            "Got the clock: {value}.",
        ],
        "ur-Latn": [
            "Waqt set — {value}.",
            "Theek, {value}.",
            "Clock lock: {value}.",
        ],
    },
    "category": {
        "en": [
            "Filed under {value}.",
            "{value} — good shelf for it.",
            "Marked {value}. Clean.",
            "Nice pick: {value}.",
        ],
        "ur-Latn": [
            "{value} me rakh diya.",
            "Category set: {value}.",
        ],
    },
    "label": {
        "en": [
            "Title sparkles: \"{value}\".",
            "Calling it \"{value}\" — clear and short.",
            "Nice name — \"{value}\".",
            "Locked the title: \"{value}\".",
        ],
        "ur-Latn": [
            "Title \"{value}\" set — clear.",
            "Naam rakh diya: \"{value}\".",
        ],
    },
}

_ASK: dict[str, dict[str, list[str]]] = {
    "date": {
        "en": [
            "Let's set up the event. What is the date and time for this event?",
            "What date and time should this event be?",
            "Which day and time work for you?",
            "Tell me the date and time.",
        ],
        "ur-Latn": [
            "Chalen event set karte hain. Date aur time kya rakhain?",
            "Date aur time bata dein?",
            "Kab aur kis waqt ka event hai?",
        ],
    },
    "time": {
        "en": [
            "And what time should it be?",
            "What time should it land?",
            "Around when — morning, evening, or exact time?",
            "Got a time in mind?",
        ],
        "ur-Latn": [
            "Aur time kya rakhain?",
            "Kis waqt ka hai?",
            "Subah, sham, ya exact time?",
        ],
    },
    "category": {
        "en": [
            "Quick sort — To Do, Appointment, or Important?",
            "Where should this sit: To Do, Appointment, or Important?",
            "Pick a lane: To Do / Appointment / Important?",
        ],
        "ur-Latn": [
            "Category? To Do, Appointment, ya Important?",
            "Teeno me se: To Do / Appointment / Important?",
        ],
    },
    "label": {
        "en": [
            "What title or label should we use for this event?",
            "Give it a short title / label?",
            "What should we call this one — a short name?",
            "A tiny title for the list — what do you want?",
            "How should it show up — title please?",
        ],
        "ur-Latn": [
            "Is event ka title / label kya rakhein?",
            "Chhota sa title bata dein?",
            "Naam / label kya den?",
            "List pe kaise dikhe — title?",
        ],
    },
}

# Extra hint after date (varied — not always "nice idea")
_DATE_HINTS: dict[str, list[str]] = {
    "en": [
        "Prefer morning or evening?",
        "A rough time works — like 9 AM or 6 PM.",
        "Whenever suits you.",
        "",
        "",
    ],
    "ur-Latn": [
        "Subah pasand hai ya sham?",
        "Rough time bhi chalega — jaise 9 AM.",
        "",
        "",
    ],
}

_CREATED: dict[str, list[str]] = {
    "en": [
        "All set — \"{label}\" is safely on your list.",
        "Done. \"{label}\" is tucked into your calendar.",
        "Beautiful — saved \"{label}\".",
        "You're good. \"{label}\" is locked in.",
        "Nice close — \"{label}\" is saved.",
    ],
    "ur-Latn": [
        "Ho gaya — \"{label}\" list pe safe hai.",
        "Done! \"{label}\" save ho gaya.",
        "Zabardast — \"{label}\" lock.",
    ],
    "ur": [
        "ہو گیا! یاد دہانی محفوظ: {label}۔",
    ],
    "hi-Latn": [
        "Ho gaya — \"{label}\" list pe safe hai.",
    ],
    "hi": [
        "हो गया! रिमाइंडर सेव: {label}।",
    ],
}

_CONFIRM: dict[str, list[str]] = {
    "en": [
        "Here's what I've got:\n{summary}\nAnything to change, or shall I save it?",
        "Quick check:\n{summary}\nLooks right? Say yes to save — or tell me what to fix.",
        "Ready when you are:\n{summary}\nSave it, or say what you'd like to change.",
    ],
    "ur-Latn": [
        "Yeh rakha hai:\n{summary}\nTheek hai to yes — change chahiye to bata dein.",
        "Confirm?\n{summary}\nSave karein, ya kuch change?",
    ],
    "ur": [
        "یہ ہیں تفصیلات:\n{summary}\nمحفوظ کریں یا کچھ بدلیں؟",
    ],
    "hi-Latn": [
        "Yeh hai:\n{summary}\nSave karein, ya change batayein?",
    ],
    "hi": [
        "यह है:\n{summary}\nसेव करें या बदलें?",
    ],
}

_RETRY: dict[str, list[str]] = {
    "en": [
        "No worries — let's try that again. ",
        "All good — still need that bit. ",
        "Easy — one more detail for me. ",
        "Happy to wait — ",
    ],
    "ur-Latn": [
        "Koi baat nahi — dobara bata dein. ",
        "Theek hai — thora clear bata dein. ",
        "Easy — ek baar aur. ",
    ],
    "ur": [
        "کوئی بات نہیں — دوبارہ بتائیں۔ ",
    ],
}

_CORRECT: dict[str, dict[str, list[str]]] = {
    "time": {
        "en": [
            "No worries — updated to {value}.",
            "Got it — time is now {value}.",
            "Updated: {value}.",
        ],
        "ur-Latn": [
            "Koi baat nahi — time {value} update.",
            "Theek — ab {value}.",
        ],
    },
    "date": {
        "en": [
            "No worries — date updated to {value}.",
            "Updated the date to {value}.",
        ],
        "ur-Latn": [
            "Date update: {value}.",
        ],
    },
    "category": {
        "en": [
            "Updated — now marked as {value}.",
            "Switched to {value}.",
        ],
        "ur-Latn": [
            "Category update: {value}.",
        ],
    },
    "label": {
        "en": [
            "Renamed to \"{value}\".",
            "Got it — title is now \"{value}\".",
        ],
        "ur-Latn": [
            "Title update: \"{value}\".",
        ],
    },
}


def _fmt_time(value: Any) -> str:
    if not isinstance(value, str) or len(value) < 5:
        return str(value)
    try:
        h, m = int(value[:2]), int(value[3:5])
        suffix = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d} {suffix}" if m else f"{h12} {suffix}"
    except ValueError:
        return str(value)


def _fmt_date(value: Any) -> str:
    if not isinstance(value, str) or len(value) < 10:
        return str(value)
    try:
        from datetime import date as date_cls

        d = date_cls.fromisoformat(value[:10])
        return d.strftime("%d %b %Y")
    except ValueError:
        return str(value)


def event_summary(event: dict[str, Any]) -> str:
    label = event.get("label") or "Reminder"
    date_s = _fmt_date(event.get("date")) if event.get("date") else "—"
    time_s = _fmt_time(event.get("time")) if event.get("time") else "—"
    cat = event.get("category") or "—"
    return (
        f"• Title: {label}\n"
        f"• Date: {date_s}\n"
        f"• Time: {time_s}\n"
        f"• Category: {cat}"
    )


def draft_so_far_line(
    event: dict[str, Any] | None,
    language: LanguageInfo | None = None,
    *,
    user_id: str = "default",
    text: str = "",
) -> str:
    """Compact running summary of filled slots with field labels."""
    event = event or {}
    bits: list[str] = []
    if event.get("date"):
        bits.append(f"Date: {_fmt_date(event.get('date'))}")
    if event.get("time"):
        bits.append(f"Time: {_fmt_time(event.get('time'))}")
    if event.get("category"):
        bits.append(f"Category: {event.get('category')}")
    if event.get("label"):
        bits.append(f'Title: "{event.get("label")}"')
    if not bits:
        return ""
    bucket = _lang_bucket(language, text)
    joined = " · ".join(bits)
    templates = {
        "en": [f"So far: {joined}.", f"Got it: {joined}."],
        "ur-Latn": [f"Ab tak: {joined}.", f"Set: {joined}."],
        "ur": [f"اب تک: {joined}۔"],
        "hi-Latn": [f"Ab tak: {joined}."],
        "hi": [f"अब तक: {joined}।"],
    }
    opts = templates.get(bucket) or templates["en"]
    return _pick(opts, salt=joined, user_id=user_id)


def correction_ack_message(
    field: str,
    value: Any,
    language: LanguageInfo | None = None,
    *,
    user_id: str = "default",
    text: str = "",
) -> str:
    bucket = _lang_bucket(language, text)
    by_field = _CORRECT.get(field) or {}
    opts = by_field.get(bucket) or by_field.get("en") or ["Updated to {value}."]
    display = value
    if field == "time":
        display = _fmt_time(value)
    elif field == "date":
        display = _fmt_date(value)
    return _pick(opts, salt=f"fix:{field}:{display}", user_id=user_id).format(value=display)


def suggested_replies_for(
    next_field: str | None,
    *,
    needs_confirmation: bool = False,
) -> list[str]:
    """Quick-tap chips for the UI."""
    if needs_confirmation:
        return ["Yes, save", "Change time", "Change date", "No"]
    if next_field == "date":
        return ["Today", "Tomorrow", "9:00 AM", "5:00 PM"]
    if next_field == "time":
        return ["9:00 AM", "5:00 PM", "9:25 PM", "10:00 PM"]
    if next_field == "category":
        return ["To Do", "Appointment", "Important"]
    if next_field == "label":
        return []  # free-text title — no fake chips
    return []


def greeting_message(
    language: LanguageInfo | None = None,
    *,
    user_id: str = "default",
    text: str = "",
) -> str:
    """Answer hello / how-are-you, then invite event setup."""
    bucket = _lang_bucket(language, text)
    socials = _GREETING_SOCIAL.get(bucket) or _GREETING_SOCIAL["en"]
    social = _pick(socials, user_id=user_id, salt="greet-social")
    opener = _SETUP_OPENER.get(bucket) or _SETUP_OPENER["en"]
    return f"{social} {opener}"


def smalltalk_message(
    language: LanguageInfo | None = None,
    *,
    user_id: str = "default",
    text: str = "",
) -> str:
    bucket = _lang_bucket(language, text)
    opts = _SMALLTALK.get(bucket) or _SMALLTALK["en"]
    return _pick(opts, user_id=user_id)


_CHAT_ONLY: dict[str, list[str]] = {
    "en": [
        "I'm here — happy to chat. When you want a reminder, just tell me the date and time.",
        "Sure, we can talk. Whenever you're ready for an event, say the word.",
        "Got you. No rush on events — just tell me when you want to set one up.",
    ],
    "ur-Latn": [
        "Bilkul — baat karte hain. Jab reminder chahiye ho, date aur time bata dena.",
        "Theek hai, koi jaldi nahi. Jab event set karna ho, bas bata dena.",
    ],
    "ur": [
        "میں یہاں ہوں — بات کرتے ہیں۔ جب یاد دہانی چاہیے ہو، تاریخ اور وقت بتائیں۔",
    ],
    "hi-Latn": [
        "Main yahan hoon — baat karte hain. Jab reminder chahiye, date aur time bata dena.",
    ],
}

_CHAT_DECLINE: dict[str, list[str]] = {
    "en": [
        "No problem — we can just chat. When you want a reminder, tell me anytime.",
        "Sure thing. No event setup for now — I'm here if you want to talk.",
        "All good — let's skip the event. Just say when you want to schedule something.",
    ],
    "ur-Latn": [
        "Theek hai — sirf baat karte hain. Jab reminder chahiye ho, bata dena.",
    ],
    "ur": [
        "ٹھیک ہے — بات کرتے ہیں۔ جب یاد دہانی چاہیے ہو، بتائیں۔",
    ],
}

_CHAT_DOING: dict[str, list[str]] = {
    "en": [
        "Just here helping you stay organized. What's on your mind?",
        "Right now? Listening to you. What would you like to talk about?",
        "I'm your Filofax assistant — happy to chat or help with reminders.",
    ],
}

_CHAT_NUDGE: dict[str, list[str]] = {
    "en": [
        "We can keep chatting. Your draft is still here whenever you want to finish it.",
        "Sure — say the word when you want to pick the event back up.",
    ],
}


def chat_only_message(
    language: LanguageInfo | None = None,
    *,
    user_id: str = "default",
    text: str = "",
    declining: bool = False,
    nudge: bool = False,
) -> str:
    """Friendly reply without forcing event setup."""
    bucket = _lang_bucket(language, text)
    lower = (text or "").strip().lower()
    if declining:
        opts = _CHAT_DECLINE.get(bucket) or _CHAT_DECLINE.get("en") or _CHAT_ONLY["en"]
        return _pick(opts, user_id=user_id, salt="decline")
    if nudge:
        opts = _CHAT_NUDGE.get(bucket) or _CHAT_NUDGE.get("en") or _CHAT_ONLY["en"]
        return _pick(opts, user_id=user_id, salt="nudge")
    if re.search(r"what are you doing", lower):
        opts = _CHAT_DOING.get("en", _CHAT_ONLY["en"])
        return _pick(opts, user_id=user_id, salt="doing")
    if re.search(r"(who are you|your name|what is your name)", lower):
        return _pick(
            [
                "I'm Filofax — your reminder assistant. Happy to chat too.",
                "Filofax here — I help with reminders and events, and I can chat.",
            ],
            user_id=user_id,
            salt="who",
        )
    opts = _CHAT_ONLY.get(bucket) or _CHAT_ONLY["en"]
    return _pick(opts, user_id=user_id, salt="chat")


def ask_next_field_message(
    field: str,
    language: LanguageInfo | None = None,
    *,
    user_id: str = "default",
    text: str = "",
) -> str:
    bucket = _lang_bucket(language, text)
    # Opening ask: date+time together when we still need the date
    if field == "date" and bucket == "en":
        return "Let's set up the event. What is the date and time for this event?"
    by_field = _ASK.get(field) or _ASK["date"]
    opts = by_field.get(bucket) or by_field.get("en") or [f"Please provide {field}."]
    return _pick(opts, salt=field, user_id=user_id)


def ack_slot_message(
    field: str,
    value: Any,
    language: LanguageInfo | None = None,
    *,
    user_id: str = "default",
    text: str = "",
) -> str:
    bucket = _lang_bucket(language, text)
    by_field = _ACK.get(field) or {}
    opts = by_field.get(bucket) or by_field.get("en") or ["Got it — {value}."]
    display = value
    if field == "time":
        display = _fmt_time(value)
    elif field == "date":
        display = _fmt_date(value)
    return _pick(opts, salt=f"{field}:{display}", user_id=user_id).format(value=display)


def progress_ask_message(
    *,
    filled_field: str | None,
    filled_value: Any,
    next_field: str | None,
    language: LanguageInfo | None = None,
    user_id: str = "default",
    text: str = "",
    event: dict[str, Any] | None = None,
    corrected: bool = False,
) -> str:
    parts: list[str] = []
    if filled_field and filled_value not in (None, ""):
        if corrected:
            parts.append(
                correction_ack_message(
                    filled_field, filled_value, language, user_id=user_id, text=text
                )
            )
        else:
            parts.append(
                ack_slot_message(
                    filled_field, filled_value, language, user_id=user_id, text=text
                )
            )
    # Running summary once we have at least one filled slot (not only the one just set)
    if event:
        filled_count = sum(
            1
            for k in ("date", "time", "category", "label")
            if event.get(k) not in (None, "", "null")
        )
        if filled_count >= 1 and next_field:
            so_far = draft_so_far_line(event, language, user_id=user_id, text=text)
            if so_far:
                parts.append(so_far)
    if next_field == "time" and filled_field == "date" and not corrected:
        bucket = _lang_bucket(language, text)
        hint = _pick(_DATE_HINTS.get(bucket) or _DATE_HINTS["en"], user_id=user_id)
        if hint:
            parts.append(hint)
    if next_field:
        parts.append(
            ask_next_field_message(next_field, language, user_id=user_id, text=text)
        )
    return " ".join(p for p in parts if p).strip()


def created_message(
    label: str,
    language: LanguageInfo | None = None,
    *,
    user_id: str = "default",
    text: str = "",
) -> str:
    bucket = _lang_bucket(language, text)
    opts = _CREATED.get(bucket) or _CREATED["en"]
    return _pick(opts, salt=label, user_id=user_id).format(label=label)


def confirm_save_message(
    event: dict[str, Any],
    language: LanguageInfo | None = None,
    *,
    user_id: str = "default",
    text: str = "",
) -> str:
    bucket = _lang_bucket(language, text)
    opts = _CONFIRM.get(bucket) or _CONFIRM["en"]
    return _pick(opts, user_id=user_id).format(summary=event_summary(event))


def retry_prefix(
    language: LanguageInfo | None = None,
    *,
    user_id: str = "default",
    text: str = "",
) -> str:
    bucket = _lang_bucket(language, text)
    opts = _RETRY.get(bucket) or _RETRY["en"]
    return _pick(opts, user_id=user_id)


def is_affirmative(message: str) -> bool:
    t = re.sub(r"[.!?,]+$", "", message.strip().lower()).strip()
    if t in {
        "yes",
        "y",
        "yeah",
        "yep",
        "yup",
        "ok",
        "okay",
        "sure",
        "haan",
        "han",
        "ji",
        "ji haan",
        "save",
        "confirm",
        "correct",
        "theek",
        "theek hai",
        "sahi",
        "add",
        "go ahead",
        "please save",
        "please add",
        "looks good",
        "sounds good",
    }:
        return True
    if t.startswith(("yes ", "yeah ", "yep ", "yup ", "haan", "han ")):
        return True
    if re.search(
        r"\b(looks good|sounds good|please (save|add)|save it|add it|"
        r"go ahead|add (in|to) my)\b",
        t,
    ):
        return True
    return False


def is_negative(message: str) -> bool:
    t = re.sub(r"[.!?,]+$", "", message.strip().lower()).strip()
    if t in {
        "no",
        "n",
        "nope",
        "nah",
        "nahi",
        "nai",
        "cancel",
        "dont",
        "don't",
        "discard",
        "rehne do",
        "mat karo",
        "stop",
        "no thanks",
        "no thank you",
    }:
        return True
    if not t.startswith("no "):
        return False
    # "no it's 9:25…" / "no change the time" = correction, not cancel
    if re.search(r"\b\d{1,2}(?::\d{2})?\s*(am|pm)\b", t):
        return False
    if re.search(r"\b(update|change|correct|instead|not\s+\d)\b", t):
        return False
    if re.search(r"\b(it'?s|it is)\b", t) and re.search(
        r"\b(am|pm|appointment|todo|to do|important|date|time)\b", t
    ):
        return False
    return True
