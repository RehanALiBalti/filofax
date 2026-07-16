"""Normalize vision-model output into Filofax reminder fields."""

from __future__ import annotations

from typing import Any

from backend.ai.service import AIService, AIServiceError, ai_service
from backend.chat_style import suggested_replies_for
from backend.draft_store import save_draft
from backend.language import default_language
from backend.models import ImageExtractResponse, LanguageInfo
from backend.slot_fill import empty_draft, missing_fields, next_missing
from backend.validators import _normalize_category, _parse_date, _parse_time


def _clean_title(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().strip("\"'")
    if not text or text.lower() in {"null", "none", "n/a", "-"}:
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


def normalize_vision_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Map model JSON → draft slots (label/date/time/category/notes)."""
    title = _clean_title(payload.get("title") or payload.get("label"))
    notes = _clean_notes(payload.get("notes"))
    cat = _normalize_category(
        None if payload.get("category") is None else str(payload.get("category"))
    )
    parsed_date = _parse_date(
        None if payload.get("date") is None else str(payload.get("date"))
    )
    parsed_time = _parse_time(
        None if payload.get("time") is None else str(payload.get("time"))
    )

    draft = empty_draft()
    draft["label"] = title
    draft["notes"] = notes
    draft["category"] = cat
    draft["date"] = parsed_date.isoformat() if parsed_date else None
    draft["time"] = parsed_time.strftime("%H:%M") if parsed_time else None

    has_any = any(draft.get(k) for k in ("date", "time", "category", "label"))
    conf = _confidence(payload.get("confidence"), has_any=has_any)
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
