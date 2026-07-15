"""Firestore persistence for collection `Reminders` (native Filofax app schema)."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.firebase_app import get_firestore, is_enabled


def collection_name() -> str:
    return os.getenv("FIRESTORE_REMINDERS_COLLECTION", "Reminders").strip() or "Reminders"


def reminder_timezone(name: str | None = None) -> ZoneInfo:
    raw = (name or "").strip() or os.getenv(
        "FIRESTORE_REMINDER_TIMEZONE", "Europe/Vienna"
    ).strip() or "Europe/Vienna"
    raw = raw.replace(" ", "_")
    try:
        return ZoneInfo(raw)
    except Exception:  # noqa: BLE001
        try:
            return ZoneInfo(
                os.getenv("FIRESTORE_REMINDER_TIMEZONE", "Europe/Vienna").strip()
                or "Europe/Vienna"
            )
        except Exception:  # noqa: BLE001
            return ZoneInfo("UTC")


@dataclass
class ReminderRecord:
    """API-shaped reminder (maps to EventOut)."""

    id: str
    user_id: str
    event_date: date
    event_time: Optional[time]
    label: str
    category: str
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_ms() -> int:
    return int(_now().timestamp() * 1000)


def _ymd(d: date) -> str:
    return f"{d.year:04d}{d.month:02d}{d.day:02d}"


def _month_str(d: date) -> str:
    return f"{d.month:02d}"


def _year_str(d: date) -> str:
    return f"{d.year:04d}"


def _event_local_dt(
    event_date: date, event_time: Optional[time], tz_name: str | None = None
) -> datetime:
    tz = reminder_timezone(tz_name)
    t = event_time or time(0, 0)
    return datetime(
        event_date.year,
        event_date.month,
        event_date.day,
        t.hour,
        t.minute,
        t.second,
        tzinfo=tz,
    )


def _to_millis(
    event_date: date, event_time: Optional[time] = None, tz_name: str | None = None
) -> int:
    return int(_event_local_dt(event_date, event_time, tz_name).timestamp() * 1000)


def _parse_ssdate(value: Any) -> date | None:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        try:
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        except ValueError:
            return None
    return None


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    parsed = _parse_ssdate(value)
    if parsed:
        return parsed
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_time(value: Any) -> time | None:
    if value is None or value == "":
        return None
    if isinstance(value, time) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    text = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _millis_to_local(ms: Any, tz_name: str | None = None) -> datetime | None:
    try:
        value = int(ms)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    # seconds vs millis
    if value < 10_000_000_000:
        value *= 1000
    return datetime.fromtimestamp(value / 1000.0, tz=reminder_timezone(tz_name))


def _parse_dt_from_millis(value: Any, tz_name: str | None = None) -> datetime:
    local = _millis_to_local(value, tz_name)
    if local:
        return local.astimezone(timezone.utc)
    return _now()


def build_native_reminder_doc(
    *,
    reminder_id: str,
    user_id: str,
    event_date: date,
    label: str,
    category: str,
    event_time: Optional[time] = None,
    notes: Optional[str] = None,
    insert_ms: int | None = None,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    """Exact mobile Filofax Firestore document shape."""
    tz = reminder_timezone(timezone_name)
    insert = insert_ms if insert_ms is not None else _now_ms()
    start_ms = _to_millis(event_date, event_time, tz.key)
    ymd = _ymd(event_date)
    title = label.strip()
    note_text = (notes if notes not in (None, "") else title) or ""
    return {
        "id": reminder_id,
        "image": "",
        "insertDate": insert,
        "isArchive": False,
        "isDairy": True,
        "isSent": False,
        "notes": note_text,
        "sdate": start_ms,
        "sdisplaydate": start_ms,
        "sdisplaymonth": _month_str(event_date),
        "sdisplayyear": _year_str(event_date),
        "smonth": _month_str(event_date),
        "ssdate": ymd,
        "ssdisplaydate": ymd,
        "status": False,
        "syear": _year_str(event_date),
        "timeZone": tz.key,
        "title": title,
        "type": category,
        "userId": user_id,
    }


def doc_to_record(doc_id: str, data: dict[str, Any]) -> ReminderRecord | None:
    user_id = str(data.get("userId") or data.get("user_id") or "").strip()
    label = str(data.get("title") or data.get("label") or "").strip()
    category = str(data.get("type") or data.get("category") or "").strip()
    tz_name = data.get("timeZone") or data.get("timezone")

    event_date = (
        _parse_ssdate(data.get("ssdate") or data.get("ssdisplaydate"))
        or _parse_date(data.get("date") or data.get("eventDate") or data.get("event_date"))
    )
    event_time = _parse_time(data.get("time") or data.get("eventTime") or data.get("event_time"))

    local = _millis_to_local(data.get("sdate") or data.get("sdisplaydate"), tz_name)
    if local:
        if event_date is None:
            event_date = local.date()
        if event_time is None and (local.hour or local.minute or local.second):
            event_time = local.time().replace(microsecond=0)

    if not user_id or not event_date or not label or not category:
        return None

    created = _parse_dt_from_millis(data.get("insertDate"), tz_name)
    rid = str(data.get("id") or doc_id).strip() or doc_id
    notes_raw = data.get("notes")
    notes = None if notes_raw in ("", None) else str(notes_raw)

    return ReminderRecord(
        id=rid,
        user_id=user_id,
        event_date=event_date,
        event_time=event_time,
        label=label,
        category=category,
        notes=notes,
        created_at=created,
        updated_at=created,
    )


def create_reminder(
    *,
    user_id: str,
    event_date: date,
    label: str,
    category: str,
    event_time: Optional[time] = None,
    notes: Optional[str] = None,
    timezone: Optional[str] = None,
) -> ReminderRecord:
    if not is_enabled():
        raise RuntimeError("Firebase is not configured")
    reminder_id = str(uuid.uuid4()).upper()
    payload = build_native_reminder_doc(
        reminder_id=reminder_id,
        user_id=user_id,
        event_date=event_date,
        label=label,
        category=category,
        event_time=event_time,
        notes=notes,
        timezone_name=timezone,
    )
    get_firestore().collection(collection_name()).document(reminder_id).set(payload)
    record = doc_to_record(reminder_id, payload)
    if record is None:
        now = _now()
        return ReminderRecord(
            id=reminder_id,
            user_id=user_id,
            event_date=event_date,
            event_time=event_time,
            label=label,
            category=category,
            notes=notes,
            created_at=now,
            updated_at=now,
        )
    return record


def get_reminder(reminder_id: str, user_id: str | None = None) -> ReminderRecord | None:
    if not is_enabled():
        raise RuntimeError("Firebase is not configured")
    snap = get_firestore().collection(collection_name()).document(str(reminder_id)).get()
    if not snap.exists:
        return None
    record = doc_to_record(snap.id, snap.to_dict() or {})
    if record is None:
        return None
    if user_id is not None and record.user_id != user_id:
        return None
    return record


def list_reminders_for_user(user_id: str, *, limit: int = 200) -> list[ReminderRecord]:
    """Fetch reminders where userId == URL/user path id."""
    if not is_enabled():
        raise RuntimeError("Firebase is not configured")
    db = get_firestore()
    coll = db.collection(collection_name())
    docs = list(coll.where("userId", "==", user_id).limit(limit).stream())
    if not docs:
        docs = list(coll.where("user_id", "==", user_id).limit(limit).stream())

    records: list[ReminderRecord] = []
    for snap in docs:
        rec = doc_to_record(snap.id, snap.to_dict() or {})
        if rec:
            records.append(rec)

    records.sort(
        key=lambda r: (
            r.event_date,
            r.event_time or time(23, 59, 59),
        )
    )
    return records[:limit]


def update_reminder(reminder_id: str, user_id: str, **fields: Any) -> ReminderRecord | None:
    existing = get_reminder(reminder_id, user_id)
    if not existing:
        return None

    event_date = fields.get("event_date", existing.event_date)
    event_time = existing.event_time
    if "event_time" in fields:
        event_time = fields["event_time"]
    label = fields.get("label", existing.label)
    category = fields.get("category", existing.category)
    notes = existing.notes
    if "notes" in fields:
        notes = fields["notes"]

    if not isinstance(event_date, date):
        event_date = existing.event_date

    # Preserve original insertDate when possible
    snap = get_firestore().collection(collection_name()).document(str(reminder_id)).get()
    raw = snap.to_dict() if snap.exists else {}
    insert_ms = None
    if isinstance(raw, dict) and raw.get("insertDate") is not None:
        try:
            insert_ms = int(raw["insertDate"])
        except (TypeError, ValueError):
            insert_ms = None

    tz_name = fields.get("timezone")
    if not tz_name and isinstance(raw, dict):
        tz_name = raw.get("timeZone") or raw.get("timezone")

    payload = build_native_reminder_doc(
        reminder_id=str(reminder_id),
        user_id=user_id,
        event_date=event_date,
        label=str(label),
        category=str(category),
        event_time=event_time if isinstance(event_time, time) or event_time is None else existing.event_time,
        notes=notes,
        insert_ms=insert_ms,
        timezone_name=tz_name,
    )
    get_firestore().collection(collection_name()).document(str(reminder_id)).set(payload)
    return doc_to_record(str(reminder_id), payload)


def delete_reminder(reminder_id: str, user_id: str) -> bool:
    existing = get_reminder(reminder_id, user_id)
    if not existing:
        return False
    get_firestore().collection(collection_name()).document(str(reminder_id)).delete()
    return True


def delete_all_for_user(user_id: str) -> int:
    records = list_reminders_for_user(user_id, limit=10_000)
    coll = get_firestore().collection(collection_name())
    for rec in records:
        coll.document(rec.id).delete()
    return len(records)


def search_reminders(user_id: str, filters: dict[str, Any]) -> list[ReminderRecord]:
    records = list_reminders_for_user(user_id, limit=500)
    out: list[ReminderRecord] = []
    for r in records:
        if filters.get("date"):
            if r.event_date != date.fromisoformat(str(filters["date"])[:10]):
                continue
        else:
            if filters.get("date_from") and r.event_date < date.fromisoformat(
                str(filters["date_from"])[:10]
            ):
                continue
            if filters.get("date_to") and r.event_date > date.fromisoformat(
                str(filters["date_to"])[:10]
            ):
                continue
        if filters.get("category") and r.category != filters["category"]:
            continue
        if filters.get("label"):
            needle = str(filters["label"]).lower()
            if needle not in r.label.lower():
                continue
        if filters.get("notes"):
            needle = str(filters["notes"]).lower()
            if needle not in (r.notes or "").lower():
                continue
        if filters.get("keyword"):
            needle = str(filters["keyword"]).lower()
            hay = f"{r.label} {r.notes or ''}".lower()
            if needle not in hay:
                continue
        out.append(r)
    return out[:200]
