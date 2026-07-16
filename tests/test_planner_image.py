"""Planner CV highlight detection tests."""

from __future__ import annotations

from pathlib import Path

from backend.image_extract import normalize_vision_payload
from backend.planner_image import analyze_planner_image, detect_highlighted_time

MAY_IMG = Path(
    r"C:\Users\MASTER\.cursor\projects\e-python-ji\assets"
    r"\c__Users_MASTER_AppData_Roaming_Cursor_User_workspaceStorage_cd39a6b3a54ab42bf513818911ea9ad4_images"
    r"_Screenshot_2025-06-19_at_1.44.44_PM-ec1f5234-ce05-4184-9857-acdfae36e082.png"
)


def test_detect_highlight_on_may_sample():
    if not MAY_IMG.exists():
        return
    data = MAY_IMG.read_bytes()
    hit = detect_highlighted_time(data)
    assert hit is not None
    assert hit["time"] == "09:30"
    assert hit["has_time_highlight"] is True


def test_cv_overrides_llava_wrong_june_and_1100():
    """Model invents June 17 + 11:00; CV highlight + header facts win."""
    cv = {
        "has_time_highlight": True,
        "highlighted_time_row": "09:30",
        "time": "09:30",
        "confidence": 0.9,
    }
    out = normalize_vision_payload(
        {
            "has_handwritten_entry": False,
            "title": "meeting with boss",
            "header_month": "May",
            "header_day": 17,
            "calendar_year": 2025,
            "date": "2025-06-17",
            "time": "11:00",
            "time_row": "11:00",
            "category": "To Do",
            **cv,
            "confidence": 0.9,
        }
    )
    assert out["draft"]["date"] == "2025-05-17"
    assert out["draft"]["time"] == "09:30"
    assert out["draft"]["label"] is None
    assert out["draft"]["category"] == "Important"


def test_analyze_planner_image_wrapper():
    if not MAY_IMG.exists():
        return
    out = analyze_planner_image(MAY_IMG.read_bytes())
    assert out.get("time") == "09:30"
