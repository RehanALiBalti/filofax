"""Firestore reminder document mapping (no live Firebase required)."""

from __future__ import annotations

from datetime import date, time

from backend.reminder_store import doc_to_record


def test_doc_to_record_camel_case():
    rec = doc_to_record(
        "abc123",
        {
            "userId": "user-1",
            "date": "2026-08-20",
            "time": "10:00",
            "label": "Doctor",
            "category": "Appointment",
            "notes": None,
        },
    )
    assert rec is not None
    assert rec.id == "abc123"
    assert rec.user_id == "user-1"
    assert rec.event_date == date(2026, 8, 20)
    assert rec.event_time == time(10, 0)
    assert rec.label == "Doctor"


def test_doc_to_record_title_alias():
    rec = doc_to_record(
        "x",
        {
            "userId": "u",
            "date": "2026-01-01",
            "title": "Pay bills",
            "category": "To Do",
        },
    )
    assert rec is not None
    assert rec.label == "Pay bills"
