"""UX copy helpers — summary, soft retry, chips."""

from __future__ import annotations

from backend.chat_style import (
    draft_so_far_line,
    progress_ask_message,
    suggested_replies_for,
)
from backend.language import default_language


def test_draft_so_far_line():
    lang = default_language()
    line = draft_so_far_line(
        {
            "date": "2027-08-14",
            "time": "21:25",
            "category": "Appointment",
            "label": None,
        },
        lang,
        user_id="ux-test",
    )
    assert "14 Aug" in line or "Aug" in line
    assert "9:25" in line or "21:25" in line
    assert "Appointment" in line


def test_progress_includes_summary_and_ask():
    lang = default_language()
    msg = progress_ask_message(
        filled_field="time",
        filled_value="21:25",
        next_field="category",
        language=lang,
        event={
            "date": "2027-08-14",
            "time": "21:25",
            "category": None,
            "label": "Testing Bus Wear",
        },
        corrected=True,
        user_id="ux-test-2",
    )
    lower = msg.lower()
    assert "9:25" in msg or "updated" in lower or "no worries" in lower
    assert "so far" in lower or "got:" in lower or "ab tak" in lower
    assert "category" in lower or "to do" in lower


def test_suggested_replies_chips():
    assert "Today" in suggested_replies_for("date")
    assert "Appointment" in suggested_replies_for("category")
    assert "Yes, save" in suggested_replies_for(None, needs_confirmation=True)
    assert "Change time" in suggested_replies_for(None, needs_confirmation=True)
