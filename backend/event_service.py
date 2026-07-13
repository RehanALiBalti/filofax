"""Event persistence and search — no AI calls here."""

from __future__ import annotations

from datetime import date, time
from typing import Any, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.models import Event


def create_event(
    db: Session,
    *,
    user_id: str,
    event_date: date,
    label: str,
    category: str,
    event_time: Optional[time] = None,
    notes: Optional[str] = None,
) -> Event:
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


def get_event(db: Session, event_id: int, user_id: str | None = None) -> Event | None:
    stmt = select(Event).where(Event.id == event_id)
    if user_id is not None:
        stmt = stmt.where(Event.user_id == user_id)
    return db.scalar(stmt)


def list_events(db: Session, user_id: str, *, limit: int = 100) -> list[Event]:
    stmt = (
        select(Event)
        .where(Event.user_id == user_id)
        .order_by(Event.event_date.asc(), Event.event_time.asc().nulls_last())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def update_event(db: Session, event: Event, **fields: Any) -> Event:
    for key, value in fields.items():
        if value is not None or key == "notes" or key == "event_time":
            if key in {"event_date", "event_time", "label", "category", "notes"}:
                setattr(event, key, value)
    db.commit()
    db.refresh(event)
    return event


def delete_event(db: Session, event: Event) -> None:
    db.delete(event)
    db.commit()


def delete_all_events(db: Session, user_id: str) -> int:
    events = list_events(db, user_id, limit=10_000)
    count = len(events)
    for event in events:
        db.delete(event)
    db.commit()
    return count


def search_events(db: Session, user_id: str, filters: dict[str, Any]) -> list[Event]:
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
