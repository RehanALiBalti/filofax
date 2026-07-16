"""Image extract — normalize vision JSON without calling Ollama."""

from __future__ import annotations

from backend.draft_store import clear_draft
from backend.image_extract import extract_reminder_from_image, normalize_vision_payload


class _FakeVisionAI:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def extract_from_image(self, image_bytes: bytes, *, timezone: str | None = None):
        assert image_bytes
        return dict(self.payload)


def test_normalize_vision_payload_maps_fields():
    out = normalize_vision_payload(
        {
            "title": "Doctor visit",
            "date": "2026-07-20",
            "time": "3:30 PM",
            "category": "appointment",
            "notes": "Bring reports",
            "confidence": 0.91,
        }
    )
    draft = out["draft"]
    assert draft["label"] == "Doctor visit"
    assert draft["date"] == "2026-07-20"
    assert draft["time"] == "15:30"
    assert draft["category"] == "Appointment"
    assert draft["notes"] == "Bring reports"
    assert out["confidence"] == 0.91


def test_extract_complete_sets_confirm():
    user = "test-img-complete"
    clear_draft(user)
    ai = _FakeVisionAI(
        {
            "title": "Gym",
            "date": "2026-08-01",
            "time": "18:00",
            "category": "To Do",
            "notes": None,
            "confidence": 0.88,
        }
    )
    result = extract_reminder_from_image(
        b"fake-image-bytes",
        user_id=user,
        timezone="Europe/Vienna",
        ai=ai,  # type: ignore[arg-type]
    )
    assert result.ok
    assert result.title == "Gym"
    assert result.date == "2026-08-01"
    assert result.time == "18:00"
    assert result.category == "To Do"
    assert result.missing_fields == []
    assert result.needs_confirmation is True
    assert result.pending_event is not None
    assert result.pending_event.get("_awaiting_confirm") is True
    assert result.input_mode == "image"
    clear_draft(user)


def test_extract_partial_asks_missing():
    user = "test-img-partial"
    clear_draft(user)
    ai = _FakeVisionAI(
        {
            "title": "Call bank",
            "date": "2026-07-22",
            "time": None,
            "category": "Important",
            "notes": None,
            "confidence": 0.7,
        }
    )
    result = extract_reminder_from_image(
        b"fake-image-bytes",
        user_id=user,
        ai=ai,  # type: ignore[arg-type]
    )
    assert result.ok
    assert result.title == "Call bank"
    assert "time" in result.missing_fields
    assert result.requires_clarification is True
    assert result.needs_confirmation is False
    assert "time" in (result.message or "").lower() or "What time" in (result.message or "")
    clear_draft(user)


def test_extract_empty_image_content():
    user = "test-img-empty"
    clear_draft(user)
    ai = _FakeVisionAI(
        {
            "title": None,
            "date": None,
            "time": None,
            "category": None,
            "notes": None,
            "confidence": 0.1,
        }
    )
    result = extract_reminder_from_image(
        b"fake-image-bytes",
        user_id=user,
        ai=ai,  # type: ignore[arg-type]
    )
    assert result.ok
    assert result.title is None
    assert result.pending_event is None
    assert "couldn't read" in (result.message or "").lower()
    clear_draft(user)
