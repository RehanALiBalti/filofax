"""Event / reminder persistence — Firebase `myReminders` when configured, else SQLite."""

from __future__ import annotations

from datetime import date, time
from typing import Any, Optional, Union

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.firebase_app import is_enabled as firebase_enabled
from backend.models import Event
from backend.reminder_store import ReminderRecord
from backend import reminder_store

ReminderLike = Union[Event, ReminderRecord]


def create_event(
    db: Session | None,
    *,
    user_id: str,
    event_date: date,
    label: str,
    category: str,
    event_time: Optional[time] = None,
    notes: Optional[str] = None,
) -> ReminderLike:
    if firebase_enabled():
        return reminder_store.create_reminder(
            user_id=user_id,
            event_date=event_date,
            label=label,
            category=category,
            event_time=event_time,
            notes=notes,
        )
    assert db is not None
    event = Event(
        user_id=user_id,
        event_date=event_date,
        event_time=event_time,
        label=label,
        category=category,
        notes=notes,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def get_event(
    db: Session | None, event_id: int | str, user_id: str | None = None
) -> ReminderLike | None:
    if firebase_enabled():
        return reminder_store.get_reminder(str(event_id), user_id)
    assert db is not None
    try:
        eid = int(event_id)
    except (TypeError, ValueError):
        return None
    stmt = select(Event).where(Event.id == eid)
    if user_id is not None:
        stmt = stmt.where(Event.user_id == user_id)
    return db.scalar(stmt)


def list_events(db: Session | None, user_id: str, *, limit: int = 100) -> list[ReminderLike]:
    if firebase_enabled():
        return list(reminder_store.list_reminders_for_user(user_id, limit=limit))
    assert db is not None
    stmt = (
        select(Event)
        .where(Event.user_id == user_id)
        .order_by(Event.event_date.asc(), Event.event_time.asc().nulls_last())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def update_event(db: Session | None, event: ReminderLike, **fields: Any) -> ReminderLike:
    if firebase_enabled():
        assert isinstance(event, ReminderRecord)
        updated = reminder_store.update_reminder(event.id, event.user_id, **fields)
        if updated is None:
            raise ValueError("Reminder not found")
        return updated
    assert db is not None and isinstance(event, Event)
    for key, value in fields.items():
        if value is not None or key == "notes" or key == "event_time":
            if key in {"event_date", "event_time", "label", "category", "notes"}:
                setattr(event, key, value)
    db.commit()
    db.refresh(event)
    return event


def delete_event(db: Session | None, event: ReminderLike) -> None:
    if firebase_enabled():
        assert isinstance(event, ReminderRecord)
        reminder_store.delete_reminder(event.id, event.user_id)
        return
    assert db is not None and isinstance(event, Event)
    db.delete(event)
    db.commit()


def delete_all_events(db: Session | None, user_id: str) -> int:
    if firebase_enabled():
        return reminder_store.delete_all_for_user(user_id)
    assert db is not None
    events = list_events(db, user_id, limit=10_000)
    count = len(events)
    for event in events:
        db.delete(event)
    db.commit()
    return count


def search_events(
    db: Session | None, user_id: str, filters: dict[str, Any]
) -> list[ReminderLike]:
    if firebase_enabled():
        return list(reminder_store.search_reminders(user_id, filters))
    assert db is not None
    clauses = [Event.user_id == user_id]

    if filters.get("date"):
        clauses.append(Event.event_date == date.fromisoformat(filters["date"]))
    else:
        if filters.get("date_from"):
            clauses.append(Event.event_date >= date.fromisoformat(filters["date_from"]))
        if filters.get("date_to"):
            clauses.append(Event.event_date <= date.fromisoformat(filters["date_to"]))

    if filters.get("category"):
        clauses.append(Event.category == filters["category"])

    if filters.get("label"):
        clauses.append(Event.label.ilike(f"%{filters['label']}%"))

    if filters.get("notes"):
        clauses.append(Event.notes.ilike(f"%{filters['notes']}%"))

    keyword = filters.get("keyword")
    if keyword:
        like = f"%{keyword}%"
        clauses.append(or_(Event.label.ilike(like), Event.notes.ilike(like)))

    stmt = (
        select(Event)
        .where(and_(*clauses))
        .order_by(Event.event_date.asc(), Event.event_time.asc().nulls_last())
        .limit(200)
    )
    return list(db.scalars(stmt))
