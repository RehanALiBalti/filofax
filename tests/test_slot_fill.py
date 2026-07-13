"""Slot-fill unit tests — keep asking until fields are clear."""

from __future__ import annotations

from datetime import date

from backend.slot_fill import apply_slot_reply, missing_fields, next_missing


TODAY = date(2026, 7, 10)


def test_missing_order():
    draft = {"date": "2026-07-11", "time": None, "category": None, "label": None}
    assert missing_fields(draft) == ["time", "category", "label"]
    assert next_missing(draft) == "time"


def test_fill_time_variants():
    draft = {"date": "2026-07-11", "time": None, "category": None, "label": None}
    for msg, expected in (
        ("4 PM", "16:00"),
        ("4:00 pm", "16:00"),
        ("16:00", "16:00"),
        ("4 baje", "04:00"),
        ("sham 4 baje", "16:00"),
    ):
        out = apply_slot_reply(pending=draft, message=msg, field="time", today=TODAY)
        assert out is not None, msg
        assert out["time"] == expected, msg


def test_fill_category_and_reask_label():
    draft = {
        "date": "2026-07-11",
        "time": "16:00",
        "category": None,
        "label": None,
    }
    out = apply_slot_reply(pending=draft, message="Appointment", field="category", today=TODAY)
    assert out["category"] == "Appointment"
    assert next_missing(out) == "label"


def test_unclear_time_returns_none():
    draft = {"date": "2026-07-11", "time": None, "category": None, "label": None}
    assert apply_slot_reply(pending=draft, message="maybe later", field="time", today=TODAY) is None


def test_parse_nine_pm_from_sentence():
    from backend.slot_fill import enrich_draft_from_message, empty_draft

    msg = "Hello, I want to be here to remind you at 9 p.m."
    out = enrich_draft_from_message(empty_draft(), msg, today=TODAY)
    assert out["time"] == "21:00"
    assert out["label"] == "Reminder"
    assert next_missing(out) == "date"


def test_no_date_guess_when_only_time_and_place():
    from backend.slot_fill import (
        enrich_draft_from_message,
        empty_draft,
        scrub_invented_date,
    )

    msg = (
        "Hello, Assalamu alaikum. I want to add a meeting at 9 p.m. "
        "The place of meeting will be Karachi and the label will be Karachi meeting."
    )
    drafted = {
        "date": "2026-07-13",
        "time": "21:00",
        "label": "Karachi meeting",
        "category": None,
        "notes": "Karachi",
    }
    cleaned = scrub_invented_date(drafted, msg)
    assert cleaned["date"] is None
    assert cleaned["time"] == "21:00"
    enriched = enrich_draft_from_message(empty_draft(), msg, today=TODAY)
    assert enriched["time"] == "21:00"
    assert enriched["label"] == "Karachi meeting"
    assert enriched["notes"] == "Karachi"
    assert enriched["date"] is None
    assert next_missing(enriched) == "date"


def test_relative_date_kal():
    empty = {"date": None, "time": None, "category": None, "label": None}
    out = apply_slot_reply(pending=empty, message="kal", field="date", today=TODAY)
    assert out["date"] == "2026-07-11"
