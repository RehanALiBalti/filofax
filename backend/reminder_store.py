"""Firestore persistence for collection `myReminders` (per userId)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Optional

from backend.firebase_app import get_firestore, is_enabled


def collection_name() -> str:
    return os.getenv("FIRESTORE_REMINDERS_COLLECTION", "myReminders").strip() or "myReminders"


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


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
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


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    # Firestore Timestamp
    if hasattr(value, "to_datetime"):
        try:
            return value.to_datetime()
        except Exception:  # noqa: BLE001
            pass
    return _now()


def doc_to_record(doc_id: str, data: dict[str, Any]) -> ReminderRecord | None:
    user_id = str(data.get("userId") or data.get("user_id") or "").strip()
    event_date = _parse_date(data.get("date") or data.get("eventDate") or data.get("event_date"))
    label = str(data.get("label") or data.get("title") or "").strip()
    category = str(data.get("category") or data.get("type") or "").strip()
    if not user_id or not event_date or not label or not category:
        return None
    return ReminderRecord(
        id=doc_id,
        user_id=user_id,
        event_date=event_date,
        event_time=_parse_time(data.get("time") or data.get("eventTime") or data.get("event_time")),
        label=label,
        category=category,
        notes=(data.get("notes") if data.get("notes") not in ("", None) else None),
        created_at=_parse_dt(data.get("createdAt") or data.get("created_at")),
        updated_at=_parse_dt(data.get("updatedAt") or data.get("updated_at")),
    )


def _to_firestore_payload(
    *,
    user_id: str,
    event_date: date,
    label: str,
    category: str,
    event_time: Optional[time] = None,
    notes: Optional[str] = None,
    include_timestamps: bool = True,
) -> dict[str, Any]:
    from firebase_admin import firestore

    payload: dict[str, Any] = {
        "userId": user_id,
        "date": event_date.isoformat(),
        "time": event_time.strftime("%H:%M") if event_time else None,
        "label": label,
        "title": label,
        "category": category,
        "notes": notes,
        # snake_case mirrors for older clients
        "user_id": user_id,
        "event_date": event_date.isoformat(),
        "event_time": event_time.strftime("%H:%M:%S") if event_time else None,
    }
    if include_timestamps:
        payload["updatedAt"] = firestore.SERVER_TIMESTAMP
        payload["createdAt"] = firestore.SERVER_TIMESTAMP
    return payload


def create_reminder(
    *,
    user_id: str,
    event_date: date,
    label: str,
    category: str,
    event_time: Optional[time] = None,
    notes: Optional[str] = None,
) -> ReminderRecord:
    if not is_enabled():
        raise RuntimeError("Firebase is not configured")
    db = get_firestore()
    ref = db.collection(collection_name()).document()
    payload = _to_firestore_payload(
        user_id=user_id,
        event_date=event_date,
        label=label,
        category=category,
        event_time=event_time,
        notes=notes,
        include_timestamps=True,
    )
    ref.set(payload)
    snap = ref.get()
    data = snap.to_dict() or payload
    # SERVER_TIMESTAMP may not resolve until read; fill locally if needed
    record = doc_to_record(ref.id, data)
    if record is None:
        now = _now()
        return ReminderRecord(
            id=ref.id,
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
    # Prefer userId (mobile); also try user_id for mixed docs
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
    from firebase_admin import firestore

    existing = get_reminder(reminder_id, user_id)
    if not existing:
        return None

    patch: dict[str, Any] = {"updatedAt": firestore.SERVER_TIMESTAMP}
    if "event_date" in fields and fields["event_date"] is not None:
        d = fields["event_date"]
        if isinstance(d, date):
            patch["date"] = d.isoformat()
            patch["event_date"] = d.isoformat()
    if "event_time" in fields:
        t = fields["event_time"]
        if t is None:
            patch["time"] = None
            patch["event_time"] = None
        elif isinstance(t, time):
            patch["time"] = t.strftime("%H:%M")
            patch["event_time"] = t.strftime("%H:%M:%S")
    if "label" in fields and fields["label"] is not None:
        patch["label"] = fields["label"]
        patch["title"] = fields["label"]
    if "category" in fields and fields["category"] is not None:
        patch["category"] = fields["category"]
    if "notes" in fields:
        patch["notes"] = fields["notes"]

    get_firestore().collection(collection_name()).document(str(reminder_id)).update(patch)
    return get_reminder(reminder_id, user_id)


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
