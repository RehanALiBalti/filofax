"""Normalize vision-model output into Filofax reminder fields."""

from __future__ import annotations

import re
from datetime import date, datetime, time
from typing import Any

from backend.ai.service import AIService, AIServiceError, ai_service
from backend.chat_style import suggested_replies_for
from backend.draft_store import save_draft
from backend.language import default_language
from backend.models import ImageExtractResponse, LanguageInfo
from backend.slot_fill import empty_draft, missing_fields, next_missing
from backend.validators import _normalize_category, _parse_date, _parse_time

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


def _clean_title(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().strip("\"'")
    if not text or text.lower() in {"null", "none", "n/a", "-"}:
        return None
    # Drop template chrome often misread as title
    if re.fullmatch(r"(june|july|may|april|march|sunday|monday|important|blueline)", text, re.I):
        return None
    words = text.split()
    if len(words) > 12:
        text = " ".join(words[:12])
    return text[:255]


def _clean_notes(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a"}:
        return None
    return text[:500]


def _confidence(value: Any, *, has_any: bool) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = 0.7 if has_any else 0.2
    return max(0.0, min(1.0, score))


def _as_int(value: Any) -> int | None:
    if value is None or str(value).strip().lower() in {"", "null", "none"}:
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _month_num(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text in {"null", "none"}:
        return None
    if text.isdigit():
        n = int(text)
        return n if 1 <= n <= 12 else None
    # "June" / "Jun 2025"
    token = re.split(r"[\s,/]+", text)[0]
    return _MONTHS.get(token)


def _compose_date(
    payload: dict[str, Any],
    *,
    today: date | None = None,
) -> date | None:
    """Prefer header_month + header_day + calendar_year over model date string."""
    today = today or date.today()
    month = _month_num(payload.get("header_month"))
    day = _as_int(payload.get("header_day"))
    year = _as_int(payload.get("calendar_year"))

    if month and day:
        if year is None or year < 2000 or year > 2100:
            # Prefer year embedded in model date if present
            raw = payload.get("date")
            parsed = _parse_date(None if raw is None else str(raw))
            year = parsed.year if parsed else today.year
        try:
            return date(year, month, day)
        except ValueError:
            pass

    raw = payload.get("date")
    return _parse_date(None if raw is None else str(raw))


def _coerce_vision_time(value: Any) -> time | None:
    """Accept planner times: 11:00, 11, 11.00, 11am, 3:30 PM."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a", "-"}:
        return None

    m = re.fullmatch(r"(\d{1,2})", text)
    if m:
        hour = int(m.group(1))
        if 0 <= hour <= 23:
            return time(hour=hour, minute=0)

    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})\s*(a\.?m\.?|p\.?m\.?)?", text, flags=re.I)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        ampm = (m.group(3) or "").lower().replace(".", "")
        if ampm.startswith("p") and hour < 12:
            hour += 12
        if ampm.startswith("a") and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return time(hour=hour, minute=minute)

    parsed = _parse_time(text)
    if parsed:
        return parsed

    try:
        return datetime.strptime(text, "%H%M").time().replace(second=0, microsecond=0)
    except ValueError:
        return None


def _pick_time_from_payload(payload: dict[str, Any]) -> time | None:
    # Prefer explicit planner row
    for key in ("time_row", "time", "time_slot", "start_time", "hour", "schedule_time"):
        if key in payload and payload.get(key) not in (None, "", "null"):
            got = _coerce_vision_time(payload.get(key))
            if got:
                # Apply PM flag for morning-looking hours when model says afternoon half
                if payload.get("time_is_pm") is True and got.hour < 12:
                    got = time(hour=got.hour + 12, minute=got.minute)
                return got
    return None


def _title_looks_like_meeting(title: str | None) -> bool:
    if not title:
        return False
    return bool(
        re.search(
            r"\b(meeting|meet|boss|doctor|dentist|interview|appointment|call|zoom|client)\b",
            title.lower(),
        )
    )


def _title_looks_like_important(title: str | None) -> bool:
    if not title:
        return False
    return bool(
        re.search(
            r"\b(important|urgent|priority|boss|ceo|critical)\b",
            title.lower(),
        )
    )


def _infer_category(title: str | None, category: str | None, payload: dict[str, Any]) -> str | None:
    # Explicit Important signals win
    if payload.get("important_checked") is True:
        return "Important"
    if category == "Important":
        return "Important"
    if _title_looks_like_important(title):
        return "Important"

    if category in ("Appointment", "To Do"):
        # Still upgrade meeting+boss style To Do → Important when boss/meeting+boss
        if category == "To Do" and _title_looks_like_important(title):
            return "Important"
        if category == "To Do" and _title_looks_like_meeting(title):
            # "meeting with my boss" → Important (user Filofax mapping)
            if re.search(r"\b(boss|important|urgent)\b", (title or "").lower()):
                return "Important"
            return "Appointment"
        return category

    if _title_looks_like_meeting(title):
        if re.search(r"\b(boss|important|urgent)\b", (title or "").lower()):
            return "Important"
        return "Appointment"

    if category:
        return category
    return None


def normalize_vision_payload(
    payload: dict[str, Any],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Map model JSON → draft slots (label/date/time/category/notes)."""
    title = _clean_title(
        payload.get("entry_text") or payload.get("title") or payload.get("label")
    )
    notes = _clean_notes(payload.get("notes"))
    cat = _normalize_category(
        None if payload.get("category") is None else str(payload.get("category"))
    )
    cat = _infer_category(title, cat, payload)
    parsed_date = _compose_date(payload, today=today)
    parsed_time = _pick_time_from_payload(payload)

    draft = empty_draft()
    draft["label"] = title
    draft["notes"] = notes
    draft["category"] = cat
    draft["date"] = parsed_date.isoformat() if parsed_date else None
    draft["time"] = parsed_time.strftime("%H:%M") if parsed_time else None

    has_any = any(draft.get(k) for k in ("date", "time", "category", "label"))
    conf = _confidence(payload.get("confidence"), has_any=has_any)
    # Boost when composed from structured planner facts
    if payload.get("header_month") and payload.get("header_day") and draft.get("date"):
        conf = max(conf, 0.85)
    if payload.get("time_row") and draft.get("time"):
        conf = max(conf, 0.85)
    return {"draft": draft, "confidence": conf}


def build_extract_message(draft: dict[str, Any], miss: list[str]) -> str:
    bits: list[str] = []
    if draft.get("label"):
        bits.append(f'Title: "{draft["label"]}"')
    if draft.get("date"):
        bits.append(f"Date: {draft['date']}")
    if draft.get("time"):
        bits.append(f"Time: {draft['time']}")
    if draft.get("category"):
        bits.append(f"Category: {draft['category']}")
    if draft.get("notes"):
        bits.append(f"Notes: {draft['notes']}")

    if not bits:
        return (
            "I couldn't read a clear reminder from this photo. "
            "Try a clearer shot, or tell me the date and time."
        )
    summary = " · ".join(bits)
    if not miss:
        return f"Got it from the photo: {summary}. Looks complete — say yes to save, or edit any field."
    nxt = miss[0]
    ask = {
        "date": "What date should I use?",
        "time": "What time should it be?",
        "category": "Which category — To Do, Appointment, or Important?",
        "label": "What short title should we use?",
    }.get(nxt, f"Please provide {nxt}.")
    return f"Got it from the photo: {summary}. {ask}"


def _safe_focus_extract(
    service: AIService,
    image_bytes: bytes,
    *,
    timezone: str | None,
    focus: str,
) -> dict[str, Any] | None:
    try:
        return service.extract_from_image(image_bytes, timezone=timezone, focus=focus)
    except AIServiceError:
        return None
    except TypeError:
        return None


def _merge_focus_retries(
    service: AIService,
    image_bytes: bytes,
    draft: dict[str, Any],
    payload: dict[str, Any],
    *,
    timezone: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Focused vision passes for missing date/time (common LLaVA failures)."""
    merged = dict(payload)

    need_time = not draft.get("time") and bool(draft.get("label") or draft.get("date"))
    need_date = not draft.get("date") and bool(draft.get("label") or draft.get("time"))
    # Also retry date when header parts missing even if a (possibly wrong) date exists
    weak_date = draft.get("date") and not (
        payload.get("header_month") and payload.get("header_day")
    )

    if need_time:
        time_payload = _safe_focus_extract(
            service, image_bytes, timezone=timezone, focus="time"
        )
        if time_payload:
            for key in ("time", "time_row", "time_is_pm", "confidence"):
                if time_payload.get(key) not in (None, "", "null"):
                    merged[key] = time_payload.get(key)
            merged["_time_retry"] = time_payload

    if need_date or weak_date:
        date_payload = _safe_focus_extract(
            service, image_bytes, timezone=timezone, focus="date"
        )
        if date_payload:
            for key in (
                "header_month",
                "header_day",
                "calendar_year",
                "date",
                "confidence",
            ):
                if date_payload.get(key) not in (None, "", "null"):
                    merged[key] = date_payload.get(key)
            merged["_date_retry"] = date_payload

    normalized = normalize_vision_payload(merged)
    return normalized["draft"], merged


def extract_reminder_from_image(
    image_bytes: bytes,
    *,
    user_id: str,
    timezone: str | None = None,
    save_pending: bool = True,
    ai: AIService | None = None,
) -> ImageExtractResponse:
    """Run vision extract → normalize → optional draft for chat confirm."""
    service = ai or ai_service
    lang: LanguageInfo = default_language()
    try:
        payload = service.extract_from_image(image_bytes, timezone=timezone)
    except AIServiceError as exc:
        return ImageExtractResponse(
            ok=False,
            intent="unclear",
            language=lang,
            confidence=0.0,
            message=f"Could not process image: {exc}",
            title=None,
            date=None,
            time=None,
            category=None,
            notes=None,
            missing_fields=list(missing_fields(empty_draft())),
            requires_clarification=True,
            pending_event=None,
            input_mode="image",
        )

    normalized = normalize_vision_payload(payload)
    draft = normalized["draft"]
    conf = normalized["confidence"]

    draft, payload = _merge_focus_retries(
        service, image_bytes, draft, payload, timezone=timezone
    )
    if draft.get("time") or draft.get("date"):
        conf = max(conf, _confidence(payload.get("confidence"), has_any=True))
    # Re-normalize after merges already done inside retries; refresh conf from facts
    normalized = normalize_vision_payload(payload)
    draft = normalized["draft"]
    conf = max(conf, normalized["confidence"])

    miss = missing_fields(draft)
    nxt = next_missing(draft)
    message = build_extract_message(draft, miss)

    if save_pending and any(draft.get(k) for k in ("date", "time", "category", "label")):
        save_draft(user_id, draft)
        pending = draft
    else:
        pending = draft if any(draft.values()) else None

    needs_confirm = not miss and bool(pending)
    if needs_confirm and pending is not None:
        pending = {**pending, "_awaiting_confirm": True}
        if save_pending:
            save_draft(user_id, pending)

    return ImageExtractResponse(
        ok=True,
        intent="create_event",
        language=lang,
        confidence=conf,
        message=message,
        title=draft.get("label"),
        date=draft.get("date"),
        time=draft.get("time"),
        category=draft.get("category"),
        notes=draft.get("notes"),
        missing_fields=miss,
        needs_confirmation=needs_confirm,
        requires_clarification=bool(miss),
        pending_event=pending,
        suggested_replies=suggested_replies_for(
            nxt, needs_confirmation=needs_confirm
        ),
        input_mode="image",
        raw=payload if isinstance(payload, dict) else None,
    )
