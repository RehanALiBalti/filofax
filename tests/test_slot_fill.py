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


def test_ordinal_date_twentieth_july():
    from backend.slot_fill import enrich_draft_from_message, empty_draft, message_has_explicit_date

    assert message_has_explicit_date("20th July")
    assert message_has_explicit_date("July 20th")
    empty = {"date": None, "time": "21:00", "category": None, "label": None}
    out = apply_slot_reply(pending=empty, message="20th July", field="date", today=TODAY)
    assert out is not None
    assert out["date"] == "2026-07-20"
    enriched = enrich_draft_from_message(
        {"date": "2026-07-20", "time": "21:00", "category": None, "label": None},
        "20th July",
        today=TODAY,
    )
    assert enriched["date"] == "2026-07-20"
    from_msg = enrich_draft_from_message(empty_draft(), "20th July at 9pm", today=TODAY)
    assert from_msg["date"] == "2026-07-20"
    assert from_msg["time"] == "21:00"


def test_timer_is_nine_pm():
    draft = {"date": "2026-07-20", "time": None, "category": None, "label": None}
    out = apply_slot_reply(
        pending=draft, message="The timer is 9pm.", field="time", today=TODAY
    )
    assert out is not None
    assert out["time"] == "21:00"


def test_category_answer_keeps_existing_date():
    from backend.slot_fill import enrich_draft_from_message, next_missing

    draft = {
        "date": "2027-06-20",
        "time": "09:00",
        "category": None,
        "label": "Reminder",
    }
    out = apply_slot_reply(
        pending=draft,
        message="is important so please add in the important category.",
        field="category",
        today=TODAY,
    )
    assert out is not None
    assert out["category"] == "Important"
    enriched = enrich_draft_from_message(out, "is important so please add in the important category.", today=TODAY)
    assert enriched["date"] == "2027-06-20"
    assert enriched["time"] == "09:00"
    assert enriched["category"] == "Important"
    assert next_missing(enriched) is None or next_missing(enriched) == "label"
    # label already set
    assert next_missing(enriched) is None


def test_year_only_not_accepted_as_date():
    from backend.slot_fill import is_year_only_date

    assert is_year_only_date("2027")
    assert is_year_only_date("year 2027")
    empty = {"date": None, "time": None, "category": None, "label": None}
    assert apply_slot_reply(pending=empty, message="2027", field="date", today=TODAY) is None


def test_scrub_keeps_date_when_answering_other_field():
    from backend.slot_fill import enrich_draft_from_message

    draft = {
        "date": "2026-09-20",
        "time": "21:00",
        "category": None,
        "label": "Reminder",
    }
    out = enrich_draft_from_message(draft, "Important", today=TODAY)
    assert out["date"] == "2026-09-20"
    assert out["category"] == "Important"


def test_lock_keeps_date_after_time_answer():
    from backend.slot_fill import enrich_draft_from_message, lock_confirmed_slots, next_missing

    draft = {
        "date": "2026-07-05",
        "time": None,
        "category": None,
        "label": "Reminder",
    }
    filled = apply_slot_reply(pending=draft, message="9 pm", field="time", today=TODAY)
    # Simulate a buggy scrub wiping date
    wiped = dict(filled)
    wiped["date"] = None
    locked = lock_confirmed_slots(draft, wiped, allow_update={"time"})
    assert locked["date"] == "2026-07-05"
    assert locked["time"] == "21:00"
    assert next_missing(locked) == "category"

    # Full path like assistant
    path = enrich_draft_from_message(filled, "9 pm", today=TODAY)
    path = lock_confirmed_slots(draft, path, allow_update={"time"})
    assert path["date"] == "2026-07-05"
    assert next_missing(path) == "category"


def test_todo_keeps_date_and_time():
    from backend.slot_fill import enrich_draft_from_message, lock_confirmed_slots, next_missing

    draft = {
        "date": "2026-07-08",
        "time": "21:00",
        "category": None,
        "label": "Reminder",
    }
    filled = apply_slot_reply(pending=draft, message="todo", field="category", today=TODAY)
    enriched = enrich_draft_from_message(filled, "todo", today=TODAY)
    locked = lock_confirmed_slots(draft, enriched, allow_update={"category"})
    assert locked["date"] == "2026-07-08"
    assert locked["time"] == "21:00"
    assert locked["category"] == "To Do"
    assert next_missing(locked) is None
