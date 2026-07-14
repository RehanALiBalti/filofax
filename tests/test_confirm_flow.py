"""Soft-confirm save flow + chat_style helpers — no Ollama required."""

from __future__ import annotations

from backend.assistant import AssistantService
from backend.chat_style import is_affirmative, is_negative, greeting_message
from backend.database import SessionLocal
from backend.draft_store import clear_draft, save_draft
from backend.language import default_language
from backend.models import Event


COMPLETE = {
    "date": "2026-08-20",
    "time": "10:00",
    "category": "To Do",
    "label": "Card Check",
    "notes": None,
}


def _cleanup(user_id: str) -> None:
    clear_draft(user_id)
    db = SessionLocal()
    try:
        db.query(Event).filter(Event.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()


def test_affirmative_negative_phrases():
    assert is_affirmative("Yes")
    assert is_affirmative("haan")
    assert is_affirmative("theek hai")
    assert is_negative("no")
    assert is_negative("nahi")
    assert not is_affirmative("tomorrow at 5")


def test_greeting_anti_repeat_does_not_crash():
    lang = default_language()
    a = greeting_message(lang, user_id="style-a")
    b = greeting_message(lang, user_id="style-a")
    assert a and b
    assert isinstance(a, str)
    setup = "Let's set up the event"
    assert setup in a
    assert a.lower().startswith(("hey", "hi", "hello"))
    assert a.index(setup) > 0


def test_hello_how_are_you_gets_social_then_setup():
    from backend.assistant import _is_greeting

    assert _is_greeting("Hello how are you")
    assert _is_greeting("Hello how are youF")

    user = "test-greet-social"
    _cleanup(user)
    svc = AssistantService(ai=None)
    db = SessionLocal()
    try:
        out = svc.handle_chat(db, message="Hello how are you", user_id=user)
        assert out.ok
        assert "Let's set up the event" in out.message
        assert out.message.strip().lower().startswith(("hey", "hi", "hello"))
        assert out.requires_clarification
        assert out.pending_event is not None
        assert "date" in (out.missing_fields or [])
    finally:
        db.close()
        _cleanup(user)


def test_offer_confirm_then_yes_saves():
    user = "test-confirm-yes"
    _cleanup(user)
    svc = AssistantService(ai=None)
    pending = {**COMPLETE, "_awaiting_confirm": True}
    save_draft(user, pending)
    db = SessionLocal()
    try:
        offered = svc._offer_confirm(
            user_id=user,
            pending=COMPLETE,
            language=default_language(),
        )
        assert offered.needs_confirmation is True
        assert offered.intent == "confirm_event"
        assert offered.pending_event and offered.pending_event.get("_awaiting_confirm")

        saved = svc.handle_chat(
            db,
            message="yes",
            user_id=user,
            confirm=True,
            pending_event=pending,
        )
        assert saved.ok
        assert saved.event is not None
        assert saved.event.label == "Card Check"
        assert saved.needs_confirmation is False
    finally:
        db.close()
        _cleanup(user)


def test_confirm_no_discards():
    user = "test-confirm-no"
    _cleanup(user)
    svc = AssistantService(ai=None)
    pending = {**COMPLETE, "_awaiting_confirm": True}
    save_draft(user, pending)
    db = SessionLocal()
    try:
        out = svc.handle_chat(
            db,
            message="no",
            user_id=user,
            confirm=False,
            pending_event=pending,
        )
        assert out.intent == "cancel_event"
        assert out.event is None
        assert out.pending_event is None
        assert db.query(Event).filter(Event.user_id == user).count() == 0
    finally:
        db.close()
        _cleanup(user)


def test_complete_draft_asks_confirm_not_autosave():
    user = "test-confirm-ask"
    _cleanup(user)
    svc = AssistantService(ai=None)
    db = SessionLocal()
    try:
        out = svc._finish_or_ask(
            db,
            user,
            dict(COMPLETE),
            default_language(),
            0.99,
            None,
        )
        assert out.needs_confirmation is True
        assert out.event is None
        assert db.query(Event).filter(Event.user_id == user).count() == 0
    finally:
        db.close()
        _cleanup(user)
