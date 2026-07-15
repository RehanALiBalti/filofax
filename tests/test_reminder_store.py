"""Firestore reminder document mapping (native Filofax schema)."""

from __future__ import annotations

from datetime import date, time

from backend.reminder_store import build_native_reminder_doc, doc_to_record


def test_doc_to_record_legacy_camel_case():
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


def test_doc_to_record_native_app_schema():
    rec = doc_to_record(
        "001D9B1E-5494-4E43-9584-E027599BBC93",
        {
            "id": "001D9B1E-5494-4E43-9584-E027599BBC93",
            "image": "",
            "insertDate": 1763326219904,
            "isArchive": True,
            "isDairy": True,
            "isSent": True,
            "notes": "Dämmerschoppen MV",
            "sdate": 1780117200000,
            "sdisplaydate": 1780117200000,
            "sdisplaymonth": "05",
            "sdisplayyear": "2026",
            "smonth": "05",
            "ssdate": "20260530",
            "ssdisplaydate": "20260530",
            "status": False,
            "syear": "2026",
            "timeZone": "Europe/Vienna",
            "title": "Dämmerschoppen MV",
            "type": "To Do",
            "userId": "9Ty4Hx2dcfZ68dW3vNG4EF3QtKT2",
        },
    )
    assert rec is not None
    assert rec.id == "001D9B1E-5494-4E43-9584-E027599BBC93"
    assert rec.user_id == "9Ty4Hx2dcfZ68dW3vNG4EF3QtKT2"
    assert rec.event_date == date(2026, 5, 30)
    assert rec.label == "Dämmerschoppen MV"
    assert rec.category == "To Do"
    assert rec.notes == "Dämmerschoppen MV"


def test_build_native_reminder_doc_shape():
    doc = build_native_reminder_doc(
        reminder_id="AAA-BBB",
        user_id="uid-1",
        event_date=date(2026, 5, 30),
        label="Pakistan",
        category="To Do",
        event_time=time(21, 0),
        notes=None,
        insert_ms=1763326219904,
        timezone_name="Asia/Karachi",
    )
    assert doc["id"] == "AAA-BBB"
    assert doc["image"] == ""
    assert doc["insertDate"] == 1763326219904
    assert doc["isArchive"] is False
    assert doc["isDairy"] is True
    assert doc["isSent"] is False
    assert doc["status"] is False
    assert doc["notes"] == "Pakistan"
    assert doc["title"] == "Pakistan"
    assert doc["type"] == "To Do"
    assert doc["userId"] == "uid-1"
    assert doc["ssdate"] == "20260530"
    assert doc["ssdisplaydate"] == "20260530"
    assert doc["smonth"] == "05"
    assert doc["syear"] == "2026"
    assert doc["sdisplaymonth"] == "05"
    assert doc["sdisplayyear"] == "2026"
    assert isinstance(doc["sdate"], int)
    assert doc["sdate"] == doc["sdisplaydate"]
    assert doc["timeZone"] == "Asia/Karachi"
