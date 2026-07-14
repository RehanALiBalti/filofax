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
    assert out["label"] is None  # label must be asked — never invent
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
    assert enriched["label"] == "Karachi Meeting"
    assert enriched["notes"] == "Karachi"
    assert enriched["date"] is None
    assert next_missing(enriched) == "date"


def test_reminder_request_does_not_auto_label():
    from backend.slot_fill import enrich_draft_from_message, empty_draft, is_fresh_create_request

    assert is_fresh_create_request("Hello can you add a reminder for me")
    assert not is_fresh_create_request("The category is to do")
    assert not is_fresh_create_request("todo")
    out = enrich_draft_from_message(empty_draft(), "Hello can you add a reminder for me", today=TODAY)
    assert out["date"] is None
    assert out["time"] is None
    assert out["category"] is None
    assert out["label"] is None
    assert next_missing(out) == "date"


def test_full_order_after_category_asks_label():
    from backend.slot_fill import enrich_draft_from_message, lock_confirmed_slots, next_missing

    draft = {
        "date": "2026-07-08",
        "time": "21:00",
        "category": None,
        "label": None,
    }
    filled = apply_slot_reply(pending=draft, message="todo", field="category", today=TODAY)
    enriched = enrich_draft_from_message(filled, "todo", today=TODAY)
    locked = lock_confirmed_slots(draft, enriched, allow_update={"category"})
    assert locked["category"] == "To Do"
    assert locked["label"] is None
    assert next_missing(locked) == "label"


def test_extract_label_card_check_from_sentence():
    from backend.slot_fill import _extract_label

    assert _extract_label("Can you please enable this event as a card check") == "Card Check"
    assert _extract_label("label is Dentist visit") == "Dentist Visit"
    assert _extract_label("call it Team Sync") == "Team Sync"
    assert _extract_label("card check") == "Card Check"

    draft = {
        "date": "2026-11-12",
        "time": "12:00",
        "category": "Appointment",
        "label": None,
    }
    out = apply_slot_reply(
        pending=draft,
        message="Can you please enable this event as a card check",
        field="label",
        today=TODAY,
    )
    assert out is not None
    assert out["label"] == "Card Check"


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


def test_multi_time_prefers_last_not_first():
    from backend.slot_fill import _parse_flexible_time

    msg = "time will be I think it's 9:00 p.m. 9:25 p.m. 9:25 p.m."
    assert _parse_flexible_time(msg) == "21:25"


def test_time_correction_skips_negated():
    from backend.slot_fill import _parse_flexible_time

    assert _parse_flexible_time("no it's 9:25 p.m. not 9:00 p.m. please update time") == "21:25"


def test_level_name_and_date_from_messy_create():
    from backend.slot_fill import enrich_draft_from_message, empty_draft, next_missing

    msg = (
        "yeah I want a reminder which level is testing was wear and no no you "
        "I think you understand wrong my level name is testing bus wear "
        "and the reminder date is 14 August 2027"
    )
    out = enrich_draft_from_message(empty_draft(), msg, today=TODAY)
    assert out["date"] == "2027-08-14"
    assert out["label"] == "Testing Bus Wear"
    assert next_missing(out) == "time"


def test_time_correction_while_asking_category():
    from backend.assistant import AssistantService
    from backend.database import SessionLocal
    from backend.draft_store import clear_draft, save_draft
    from backend.models import Event

    user = "test-time-correct"
    clear_draft(user)
    draft = {
        "date": "2027-08-14",
        "time": "21:00",
        "category": None,
        "label": "Testing Bus Wear",
        "notes": None,
    }
    save_draft(user, draft)
    svc = AssistantService(ai=None)
    db = SessionLocal()
    try:
        out = svc.handle_chat(
            db,
            message="no it's 9:25 p.m. not 9:00 p.m. please update time",
            user_id=user,
            pending_event=draft,
        )
        assert out.pending_event is not None
        assert out.pending_event["time"] == "21:25"
        assert out.missing_fields[0] == "category"
        assert "clearly" not in (out.message or "").lower()
        assert "9:25" in (out.message or "") or "9:25" in (out.message or "").lower() or "21:25" in str(
            out.pending_event
        )
    finally:
        db.query(Event).filter(Event.user_id == user).delete()
        db.commit()
        db.close()
        clear_draft(user)


def test_ok_category_not_smalltalk():
    from backend.assistant import _is_smalltalk, AssistantService
    from backend.database import SessionLocal
    from backend.draft_store import clear_draft, save_draft
    from backend.models import Event

    assert not _is_smalltalk("OK so the category is to do")

    user = "test-ok-cat"
    clear_draft(user)
    draft = {
        "date": "2026-08-20",
        "time": "22:00",
        "category": None,
        "label": None,
        "notes": None,
    }
    save_draft(user, draft)
    svc = AssistantService(ai=None)
    db = SessionLocal()
    try:
        out = svc.handle_chat(
            db,
            message="OK so the category is to do",
            user_id=user,
            pending_event=draft,
        )
        assert out.pending_event is not None
        assert out.pending_event["category"] == "To Do"
        assert "whenever you're ready" not in (out.message or "").lower()
    finally:
        db.query(Event).filter(Event.user_id == user).delete()
        db.commit()
        db.close()
        clear_draft(user)


def test_confirm_please_add_does_not_restart():
    from backend.assistant import AssistantService
    from backend.chat_style import is_affirmative
    from backend.database import SessionLocal
    from backend.draft_store import clear_draft, save_draft
    from backend.models import Event
    from backend.slot_fill import is_fresh_create_request

    msg = "Yeah it looks good please add in my reminder"
    assert is_affirmative(msg)
    assert not is_fresh_create_request(msg)

    user = "test-confirm-please-add"
    clear_draft(user)
    pending = {
        "date": "2026-08-20",
        "time": "22:00",
        "category": "Important",
        "label": "To Check My Laptop",
        "notes": None,
        "_awaiting_confirm": True,
    }
    save_draft(user, pending)
    svc = AssistantService(ai=None)
    db = SessionLocal()
    try:
        out = svc.handle_chat(
            db,
            message=msg,
            user_id=user,
            pending_event=pending,
        )
        assert out.event is not None
        assert out.event.label == "To Check My Laptop"
        assert "which date" not in (out.message or "").lower()
    finally:
        db.query(Event).filter(Event.user_id == user).delete()
        db.commit()
        db.close()
        clear_draft(user)


def test_category_sentence_does_not_become_label():
    from backend.slot_fill import absorb_user_message, missing_fields, next_missing

    draft = {
        "date": "2026-08-20",
        "time": "22:00",
        "category": None,
        "label": None,
        "notes": None,
    }
    out = absorb_user_message(
        draft, "OK so the category is to do", preferred_field="category", today=TODAY
    )
    assert out is not None
    assert out["category"] == "To Do"
    assert out["label"] is None
    assert missing_fields(out) == ["label"]
    assert next_missing(out) == "label"


def test_plain_title_still_fills_label():
    from backend.slot_fill import absorb_user_message, next_missing

    draft = {
        "date": "2026-08-20",
        "time": "22:00",
        "category": "To Do",
        "label": None,
        "notes": None,
    }
    out = absorb_user_message(
        draft, "Check my laptop", preferred_field="label", today=TODAY
    )
    assert out is not None
    assert out["label"] == "Check My Laptop"
    assert next_missing(out) is None


def test_absorb_any_order_while_asking_date():
    from backend.slot_fill import absorb_user_message, empty_draft, next_missing

    draft = empty_draft()
    # Asked date, but user dumps everything backwards
    out = absorb_user_message(
        draft,
        "name is Card Check, appointment at 5pm on 20 July 2027",
        preferred_field="date",
        today=TODAY,
    )
    assert out is not None
    assert out["date"] == "2027-07-20"
    assert out["time"] == "17:00"
    assert out["category"] == "Appointment"
    assert out["label"] == "Card Check"
    assert next_missing(out) is None


def test_label_ask_does_not_swallow_time():
    from backend.slot_fill import absorb_user_message, next_missing

    draft = {
        "date": "2027-08-14",
        "time": None,
        "category": "Appointment",
        "label": None,
        "notes": None,
    }
    # Preferred is label (last ask), but user gives time
    out = absorb_user_message(
        draft, "9:25 pm", preferred_field="label", today=TODAY
    )
    assert out is not None
    assert out["time"] == "21:25"
    assert out["label"] is None
    assert next_missing(out) == "label"


def test_category_first_then_still_asks_date():
    from backend.slot_fill import absorb_user_message, empty_draft, next_missing

    out = absorb_user_message(
        empty_draft(), "Important", preferred_field="date", today=TODAY
    )
    assert out is not None
    assert out["category"] == "Important"
    assert next_missing(out) == "date"
