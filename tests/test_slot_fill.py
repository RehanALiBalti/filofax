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
        ("4 baje", "04:00"),  # no am/pm → 24h hour as given
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


def test_relative_date_kal():
    empty = {"date": None, "time": None, "category": None, "label": None}
    out = apply_slot_reply(pending=empty, message="kal", field="date", today=TODAY)
    assert out["date"] == "2026-07-11"
