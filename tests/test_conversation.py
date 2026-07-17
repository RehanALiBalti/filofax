"""Conversational chat vs event slot filling."""

from __future__ import annotations

from backend.assistant import AssistantService
from backend.conversation import is_conversational_message
from backend.database import SessionLocal
from backend.draft_store import clear_draft, save_draft
from backend.models import Event
from backend.slot_fill import absorb_user_message, apply_slot_reply, empty_draft


def _cleanup(user_id: str) -> None:
    clear_draft(user_id)
    db = SessionLocal()
    try:
        db.query(Event).filter(Event.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()


def test_conversational_question_not_label():
    assert is_conversational_message("what are you doing right now")
    draft = empty_draft()
    assert apply_slot_reply(pending=draft, message="what are you doing right now", field="label") is None
    assert absorb_user_message(draft, "what are you doing right now", preferred_field="date") is None


def test_decline_clears_empty_draft():
    user = "test-decline-chat"
    _cleanup(user)
    save_draft(user, empty_draft())
    svc = AssistantService(ai=None)
    db = SessionLocal()
    try:
        out = svc.handle_chat(
            db,
            message="I don't like to set up event I am free can you talk with me",
            user_id=user,
            pending_event=empty_draft(),
        )
        assert out.ok
        assert out.intent == "clarify"
        assert out.pending_event is None
        assert "Let's set up the event" not in out.message
        msg = out.message.lower()
        assert any(w in msg for w in ("chat", "talk", "skip", "whenever", "schedule something"))
    finally:
        db.close()
        _cleanup(user)


def test_greeting_does_not_force_setup():
    user = "test-greet-no-setup"
    _cleanup(user)
    svc = AssistantService(ai=None)
    db = SessionLocal()
    try:
        out = svc.handle_chat(db, message="hello", user_id=user)
        assert out.ok
        assert "Let's set up the event" not in (out.message or "")
        assert out.pending_event is None
    finally:
        db.close()
        _cleanup(user)


def test_set_up_event_ask_not_title():
    user = "test-setup-not-title"
    _cleanup(user)
    svc = AssistantService(ai=None)
    db = SessionLocal()
    try:
        # Stale empty draft from an old greeting must not swallow this as a title
        save_draft(user, empty_draft())
        out = svc.handle_chat(
            db,
            message="can you set up event for me",
            user_id=user,
            pending_event=empty_draft(),
        )
        assert out.ok
        assert out.intent == "create_event"
        assert out.pending_event is not None
        assert out.pending_event.get("label") in (None, "", "null")
        assert "Nice name" not in (out.message or "")
        assert "can you set up event for me" not in (out.message or "").lower()
        assert "date" in (out.message or "").lower() or "time" in (out.message or "").lower()
    finally:
        db.close()
        _cleanup(user)


def test_casual_chat_after_greeting_not_event_title():
    user = "test-casual-after-greet"
    _cleanup(user)
    svc = AssistantService(ai=None)
    db = SessionLocal()
    try:
        greet = svc.handle_chat(db, message="how are you", user_id=user)
        assert "Let's set up the event" not in (greet.message or "")

        out = svc.handle_chat(
            db,
            message="what are you doing right now",
            user_id=user,
            pending_event=greet.pending_event,
        )
        assert out.ok
        assert out.pending_event is None or out.pending_event.get("label") is None
        assert "What Are You Doing" not in (out.message or "")
        assert "Let's set up the event" not in (out.message or "")
    finally:
        db.close()
        _cleanup(user)


def test_love_message_not_date():
    user = "test-love-chat"
    _cleanup(user)
    draft = {
        "date": None,
        "time": None,
        "category": None,
        "label": "What Are You Doing Right",
        "notes": None,
    }
    save_draft(user, draft)
    svc = AssistantService(ai=None)
    db = SessionLocal()
    try:
        out = svc.handle_chat(
            db,
            message="my love I am talking with you only not set up your name",
            user_id=user,
            pending_event=draft,
        )
        assert out.ok
        assert out.pending_event is None
        assert "15 Jul" not in (out.message or "")
        assert "What time" not in (out.message or "")
    finally:
        db.close()
        _cleanup(user)
