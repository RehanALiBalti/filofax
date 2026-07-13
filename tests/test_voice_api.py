"""Voice endpoint unit tests — mock STT, no Whisper download."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.models import AssistantResponse, LanguageInfo


client = TestClient(app)


def test_voice_endpoint_runs_assistant():
    fake_assistant = AssistantResponse(
        ok=True,
        intent="create_event",
        language=LanguageInfo(code="en", name="English", is_mixed=False),
        confidence=0.9,
        message="What date should I set for the event?",
        missing_fields=["date"],
        requires_clarification=True,
        pending_event={"date": None, "time": None, "label": None, "category": None},
    )

    with patch(
        "backend.main.transcribe_audio_bytes",
        return_value={"transcript": "Add a meeting tomorrow"},
    ), patch(
        "backend.main.assistant_service.handle_chat",
        return_value=fake_assistant,
    ):
        res = client.post(
            "/api/assistant/voice",
            files={"audio": ("note.webm", b"fake-audio-bytes", "audio/webm")},
            data={"user_id": "default"},
        )

    assert res.status_code == 200
    body = res.json()
    assert body["transcript"] == "Add a meeting tomorrow"
    assert body["input_mode"] == "voice"
    assert body["missing_fields"] == ["date"]


def test_voice_rejects_empty_audio():
    res = client.post(
        "/api/assistant/voice",
        files={"audio": ("note.webm", b"", "audio/webm")},
        data={"user_id": "default"},
    )
    assert res.status_code == 422
