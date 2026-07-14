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


_GREETINGS: dict[str, list[str]] = {
    "en": [
        "Hey — good to see you. Shall we capture a reminder while it's on your mind?",
        "Hi! I'm here and ready. Want to lock something onto your calendar?",
        "Hello! Fresh start. Tell me what you'd like to remember.",
        "Hey there. I make reminder-making feel light — want to try one?",
        "Hi! I'm Filofax. Drop a date, a time, or just the idea — I'll follow along.",
        "Welcome back. What's worth remembering today?",
        "Hello! Soft landings only. Want to add a reminder together?",
    ],
    "ur-Latn": [
        "Assalamu alaikum! Main ready hoon — kya reminder set karein?",
        "Salam! Aaj kya yaad rakhna hai? Bol dein, main sambhal loonga.",
        "Hello! Soft aur simple — reminder banate hain?",
        "Khush aamdeed. Date, time, ya sirf idea — jo bhi bolo, main follow karoon ga.",
        "Salam! Filofax yahan hai. Reminder add karein?",
    ],
    "ur": [
        "السلام علیکم! میں تیار ہوں — کیا یاد دہانی بنائیں؟",
        "سلام! آج کیا یاد رکھنا ہے؟",
    ],
    "hi-Latn": [
        "Namaste! Ready hoon — reminder banayein?",
        "Hi! Aaj kya yaad rakhna hai?",
        "Namaste! Soft aur simple — chaliye reminder set karein.",
    ],
    "hi": [
        "नमस्ते! मैं तैयार हूँ — क्या रिमाइंडर जोड़ें?",
    ],
}

_SMALLTALK: dict[str, list[str]] = {
    "en": [
        "Love that energy. Want to catch a reminder while we're chatting?",
        "Nice — I'm good too. Ready to pencil something in?",
        "Glad you're well. Shall we set one small thing so you don't forget?",
        "Cool. Whenever you're ready, toss me a date or a title.",
        "Happy to hear it. Want a reminder next?",
    ],
    "ur-Latn": [
        "Bohat khoob! Ab chhota sa reminder set karein?",
        "Achha laga sun ke. Ready hoon — batayein kya add karna hai.",
        "Zabardast! Date ya title jo bhi — main note kar loonga.",
    ],
    "ur": [
        "اچھا لگا! کیا اب یاد دہانی شامل کریں؟",
    ],
    "hi-Latn": [
        "Badhiya! Ab ek chhota reminder set karein?",
        "Bahut accha. Ready hoon — kya add karna hai?",
    ],
    "hi": [
        "बहुत अच्छा! क्या अब रिमाइंडर जोड़ें?",
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
            "Which day should hold this?",
            "What date feels right?",
            "When should this live on your calendar?",
            "Pick a date — today, tomorrow, or any day you like.",
            "Which date should I circle?",
        ],
        "ur-Latn": [
            "Kis date pe rakhna hai?",
            "Kaun si tareekh theek rahegi?",
            "Date bata dein — aaj, kal, ya koi bhi.",
        ],
    },
    "time": {
        "en": [
            "What time should it land?",
            "Around when — morning, evening, or exact time?",
            "Got a time in mind?",
            "And the clock?",
            "When during the day?",
        ],
        "ur-Latn": [
            "Kis waqt ka hai?",
            "Time kya rakhain?",
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
            "Give it a short, memorable name?",
            "What should we call this one?",
            "A tiny title — two or three words works great.",
            "How should it show up on your list?",
        ],
        "ur-Latn": [
            "Chhota sa title / label?",
            "Naam kya den — short aur clear?",
            "List pe kaise dikhe — title bata dein.",
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
    date_s = _fmt_date(event.get("date"))
    time_s = _fmt_time(event.get("time")) if event.get("time") else "—"
    cat = event.get("category") or "—"
    return f"• {label}\n• {date_s} · {time_s}\n• {cat}"


def draft_so_far_line(
    event: dict[str, Any] | None,
    language: LanguageInfo | None = None,
    *,
    user_id: str = "default",
    text: str = "",
) -> str:
    """Compact running summary of filled slots."""
    event = event or {}
    bits: list[str] = []
    if event.get("date"):
        bits.append(_fmt_date(event.get("date")))
    if event.get("time"):
        bits.append(_fmt_time(event.get("time")))
    if event.get("category"):
        bits.append(str(event.get("category")))
    if event.get("label"):
        bits.append(f'"{event.get("label")}"')
    if not bits:
        return ""
    bucket = _lang_bucket(language, text)
    joined = " · ".join(bits)
    templates = {
        "en": [f"So far: {joined}.", f"Got: {joined}."],
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
        return ["Today", "Tomorrow"]
    if next_field == "time":
        return ["9:00 AM", "5:00 PM", "9:25 PM"]
    if next_field == "category":
        return ["To Do", "Appointment", "Important"]
    return []


def greeting_message(
    language: LanguageInfo | None = None,
    *,
    user_id: str = "default",
    text: str = "",
) -> str:
    bucket = _lang_bucket(language, text)
    opts = _GREETINGS.get(bucket) or _GREETINGS["en"]
    return _pick(opts, user_id=user_id)


def smalltalk_message(
    language: LanguageInfo | None = None,
    *,
    user_id: str = "default",
    text: str = "",
) -> str:
    bucket = _lang_bucket(language, text)
    opts = _SMALLTALK.get(bucket) or _SMALLTALK["en"]
    return _pick(opts, user_id=user_id)


def ask_next_field_message(
    field: str,
    language: LanguageInfo | None = None,
    *,
    user_id: str = "default",
    text: str = "",
) -> str:
    bucket = _lang_bucket(language, text)
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
    return t in {
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
    } or t.startswith("yes ") or t.startswith("haan")


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
