"""Language helpers — no application-level language allowlist."""

from __future__ import annotations

from typing import Any

from backend.models import LanguageInfo

# Convenience templates only. Unknown codes fall back to English —
# messages are never rejected for language.
_MISSING_TEMPLATES: dict[str, str] = {
    "en": "I need a bit more information: {fields}.",
    "ur-Latn": "Thori aur detail chahiye: {fields}. Please bata dein.",
    "ur": "مزید تفصیل درکار ہے: {fields}۔",
    "hi-Latn": "Thodi aur detail chahiye: {fields}. Please bataiye.",
    "hi": "थोड़ी और जानकारी चाहिए: {fields}।",
    "es": "Necesito un poco más de información: {fields}.",
    "fr": "J'ai besoin de plus d'informations : {fields}.",
    "ar": "أحتاج إلى مزيد من المعلومات: {fields}.",
    "zh": "还需要更多信息：{fields}。",
    "de": "Ich brauche noch etwas mehr Information: {fields}.",
    "pt": "Preciso de mais algumas informações: {fields}.",
    "mixed": "I need a bit more information: {fields}.",
    "und": "I need a bit more information: {fields}. Please rephrase if needed.",
}

_CONFIRM_TEMPLATES: dict[str, str] = {
    "en": "Create this event? {summary} (yes/no)",
    "ur-Latn": "Event create karun? {summary} (yes/no)",
    "ur": "کیا یہ ایونٹ شامل کر دوں؟ {summary} (ہاں/نہیں)",
    "hi-Latn": "Event create karun? {summary} (yes/no)",
    "hi": "क्या यह इवेंट बना दूँ? {summary} (हाँ/नहीं)",
    "es": "¿Crear este evento? {summary} (sí/no)",
    "fr": "Créer cet événement ? {summary} (oui/non)",
    "ar": "هل أنشئ هذا الحدث؟ {summary} (نعم/لا)",
    "zh": "要创建这个事件吗？{summary}（是/否）",
    "de": "Dieses Ereignis erstellen? {summary} (ja/nein)",
    "pt": "Criar este evento? {summary} (sim/não)",
    "mixed": "Create this event? {summary} (yes/no)",
}

_CREATED_TEMPLATES: dict[str, str] = {
    "en": "Got it! I've added your event: {label}.",
    "ur-Latn": "Ho gaya! Event add ho gaya: {label}.",
    "ur": "ہو گیا! آپ کا ایونٹ شامل کر دیا گیا: {label}۔",
    "hi-Latn": "Ho gaya! Event add ho gaya: {label}.",
    "hi": "हो गया! आपका इवेंट जोड़ दिया गया: {label}।",
    "es": "¡Listo! He añadido tu evento: {label}.",
    "fr": "C'est noté ! J'ai ajouté votre événement : {label}.",
    "ar": "تم! أضفت حدثك: {label}.",
    "zh": "好的！已添加事件：{label}。",
    "de": "Erledigt! Ereignis hinzugefügt: {label}.",
    "pt": "Pronto! Adicionei seu evento: {label}.",
    "mixed": "Got it! I've added your event: {label}.",
}

_SEARCH_TEMPLATES: dict[str, str] = {
    "en": "Found {count} event(s).",
    "ur-Latn": "{count} event(s) mile.",
    "ur": "{count} ایونٹ ملے۔",
    "hi-Latn": "{count} event(s) mile.",
    "hi": "{count} इवेंट मिले।",
    "es": "Se encontraron {count} evento(s).",
    "fr": "{count} événement(s) trouvé(s).",
    "ar": "تم العثور على {count} حدث/أحداث.",
    "zh": "找到 {count} 个事件。",
    "de": "{count} Ereignis(se) gefunden.",
    "pt": "Encontrado(s) {count} evento(s).",
    "mixed": "Found {count} event(s).",
}

_UNCLEAR_TEMPLATES: dict[str, str] = {
    "en": "I couldn't understand that clearly. Please rephrase your request about creating or searching events.",
    "ur-Latn": "Samajh nahi aaya. Create ya search event ke bare mein dobara likhein.",
    "ur": "پیغام واضح نہیں سمجھا۔ براہ کرم ایونٹ بنانے یا تلاش کرنے کے بارے میں دوبارہ لکھیں۔",
    "hi-Latn": "Samajh nahi aaya. Event create ya search ke baare mein dobara likhiye.",
    "hi": "संदेश स्पष्ट नहीं समझा। कृपया इवेंट बनाने या खोजने के बारे में फिर से लिखें।",
    "es": "No lo entendí claramente. Reformule su solicitud sobre crear o buscar eventos.",
    "fr": "Je n'ai pas bien compris. Reformulez votre demande de création ou de recherche d'événements.",
    "ar": "لم أفهم الرسالة بوضوح. يرجى إعادة صياغة طلبك حول إنشاء أو البحث عن الأحداث.",
    "zh": "我不太明白。请重新说明您要创建或搜索的事件。",
    "und": "I couldn't understand that clearly. Please rephrase your request about creating or searching events.",
    "mixed": "I couldn't understand that clearly. Please rephrase your request about creating or searching events.",
}

_HELP_TEMPLATES: dict[str, str] = {
    "en": "I can create or search events. Tell me the date, or say something like 'Add a meeting tomorrow at 4 PM'. Categories: To Do, Appointment, Important.",
    "ur-Latn": "Main event create ya search kar sakta hoon. Pehle date bata dein, ya 'Kal 4 baje meeting add kar do' likhein. Categories: To Do, Appointment, Important.",
    "ur": "میں ایونٹ بنا یا تلاش کر سکتا ہوں۔ تاریخ بتائیں یا مکمل تفصیل لکھیں۔",
    "hi-Latn": "Main event create ya search kar sakta hoon. Pehle date bataiye.",
    "hi": "मैं इवेंट बना या खोज सकता हूँ। पहले तारीख बताएँ।",
    "es": "Puedo crear o buscar eventos. Empiece por la fecha.",
    "fr": "Je peux créer ou rechercher des événements. Commencez par la date.",
    "ar": "يمكنني إنشاء الأحداث أو البحث عنها. ابدأ بالتاريخ.",
    "zh": "我可以创建或搜索事件。请先告诉我日期。",
    "mixed": "I can create or search events. Start with the date.",
    "und": "I can create or search events. Start with the date.",
}

_GREETING_TEMPLATES: dict[str, str] = {
    "en": (
        "Hello! I'm doing well, thank you. "
        "I can help you add or find reminders — say \"add a reminder\" when you're ready."
    ),
    "ur-Latn": (
        "Assalamu alaikum! Main theek hoon, shukriya. "
        "Reminder add ya search karna ho to bata dein — jaise \"add a reminder\"."
    ),
    "ur": (
        "السلام علیکم! میں ٹھیک ہوں، شکریہ۔ "
        "یاد دہانی شامل یا تلاش کرنے کے لیے بتائیں — جیسے \"add a reminder\"۔"
    ),
    "hi-Latn": (
        "Namaste! Main theek hoon. "
        "Reminder add ya search ke liye bataiye — jaise \"add a reminder\"."
    ),
    "hi": (
        "नमस्ते! मैं ठीक हूँ। "
        "रिमाइंडर जोड़ने या खोजने के लिए बताइए — जैसे \"add a reminder\"।"
    ),
    "es": "¡Hola! Estoy bien, gracias. Puedo ayudarte a crear o buscar recordatorios — di \"add a reminder\".",
    "fr": "Bonjour ! Je vais bien, merci. Dites \"add a reminder\" pour commencer.",
    "ar": "مرحباً! بخير، شكراً. قل add a reminder للبدء.",
    "zh": "你好！我很好，谢谢。想添加提醒可以说 add a reminder。",
    "mixed": (
        "Hello! I'm doing well, thank you. "
        "I can help you add or find reminders — say \"add a reminder\" when you're ready."
    ),
    "und": (
        "Hello! I'm doing well, thank you. "
        "I can help you add or find reminders — say \"add a reminder\" when you're ready."
    ),
}

_ASK_NEXT: dict[str, dict[str, str]] = {
    "date": {
        "en": "What date should I set for the event?",
        "ur-Latn": "Event kis date ko rakhna hai?",
        "ur": "ایونٹ کس تاریخ کو رکھنا ہے؟",
    },
    "time": {
        "en": "What time should the event be?",
        "ur-Latn": "Event kis waqt ka hai?",
        "ur": "ایونٹ کس وقت کا ہے؟",
    },
    "category": {
        "en": "Which category? To Do, Appointment, or Important?",
        "ur-Latn": "Category kya hai? To Do, Appointment, ya Important?",
        "ur": "زمرہ کیا ہے؟ To Do، Appointment، یا Important؟",
    },
    "label": {
        "en": "What should I label this event?",
        "ur-Latn": "Event ka label / title kya rakhein?",
        "ur": "ایونٹ کا عنوان کیا رکھیں؟",
    },
}

_FIELD_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "date": "date",
        "time": "time",
        "label": "title/label",
        "category": "category (To Do, Appointment, or Important)",
    },
    "ur-Latn": {
        "date": "date",
        "time": "waqt",
        "label": "title/label",
        "category": "category (To Do, Appointment, Important)",
    },
}


def default_language() -> LanguageInfo:
    return LanguageInfo(code="en", name="English", is_mixed=False)


def unknown_language() -> LanguageInfo:
    return LanguageInfo(code="und", name="Unknown", is_mixed=False)


def normalize_language(raw: Any) -> LanguageInfo:
    """Accept object or legacy string. Never reject unknown languages."""
    if isinstance(raw, LanguageInfo):
        return raw
    if isinstance(raw, dict):
        code = str(raw.get("code") or "und").strip() or "und"
        name = str(raw.get("name") or code).strip() or code
        is_mixed = bool(raw.get("is_mixed", False))
        if code.lower() in ("mixed",):
            is_mixed = True
        return LanguageInfo(code=code, name=name, is_mixed=is_mixed)
    if isinstance(raw, str) and raw.strip():
        return _legacy_language_string(raw.strip())
    return unknown_language()


def _legacy_language_string(value: str) -> LanguageInfo:
    key = value.strip().lower().replace(" ", "_").replace("-", "_")
    mapping = {
        "english": ("en", "English", False),
        "en": ("en", "English", False),
        "urdu": ("ur", "Urdu", False),
        "ur": ("ur", "Urdu", False),
        "roman_urdu": ("ur-Latn", "Roman Urdu", True),
        "ur_latn": ("ur-Latn", "Roman Urdu", True),
        "hindi": ("hi", "Hindi", False),
        "hi": ("hi", "Hindi", False),
        "roman_hindi": ("hi-Latn", "Roman Hindi", True),
        "hi_latn": ("hi-Latn", "Roman Hindi", True),
        "arabic": ("ar", "Arabic", False),
        "ar": ("ar", "Arabic", False),
        "spanish": ("es", "Spanish", False),
        "es": ("es", "Spanish", False),
        "french": ("fr", "French", False),
        "fr": ("fr", "French", False),
        "chinese": ("zh", "Chinese", False),
        "zh": ("zh", "Chinese", False),
        "mixed": ("mixed", "Mixed", True),
        "unknown": ("und", "Unknown", False),
        "und": ("und", "Unknown", False),
    }
    if key in mapping:
        code, name, mixed = mapping[key]
        return LanguageInfo(code=code, name=name, is_mixed=mixed)
    # Pass through any other code the model returns — no allowlist.
    return LanguageInfo(code=value.strip(), name=value.strip(), is_mixed=False)


def _template(table: dict[str, str], language: LanguageInfo, **kwargs: Any) -> str:
    code = (language.code or "en").strip()
    primary = code.split("-")[0] if code not in table else code
    fmt = table.get(code) or table.get(primary) or table.get("en") or next(iter(table.values()))
    return fmt.format(**kwargs)


def missing_fields_message(fields: list[str], language: LanguageInfo) -> str:
    labels = _FIELD_LABELS.get(language.code) or _FIELD_LABELS["en"]
    pretty = ", ".join(labels.get(f, f) for f in fields)
    return _template(_MISSING_TEMPLATES, language, fields=pretty)


def confirm_message(summary: str, language: LanguageInfo) -> str:
    return _template(_CONFIRM_TEMPLATES, language, summary=summary)


def created_message(label: str, language: LanguageInfo) -> str:
    from backend.chat_style import created_message as _styled

    return _styled(label, language)


def search_message(count: int, language: LanguageInfo) -> str:
    return _template(_SEARCH_TEMPLATES, language, count=count)


def unclear_message(language: LanguageInfo) -> str:
    return _template(_UNCLEAR_TEMPLATES, language)


def help_message(language: LanguageInfo) -> str:
    return _template(_HELP_TEMPLATES, language)


def greeting_message(language: LanguageInfo) -> str:
    from backend.chat_style import greeting_message as _styled

    return _styled(language)


def ask_next_field_message(field: str, language: LanguageInfo) -> str:
    from backend.chat_style import ask_next_field_message as _styled

    return _styled(field, language)


def progress_ask_message(
    *,
    filled_field: str | None,
    filled_value: Any,
    next_field: str | None,
    language: LanguageInfo,
) -> str:
    from backend.chat_style import progress_ask_message as _styled

    return _styled(
        filled_field=filled_field,
        filled_value=filled_value,
        next_field=next_field,
        language=language,
    )


def smalltalk_message(language: LanguageInfo) -> str:
    from backend.chat_style import smalltalk_message as _styled

    return _styled(language)


def retry_prefix(language: LanguageInfo) -> str:
    from backend.chat_style import retry_prefix as _styled

    return _styled(language)
