"""Prompts for diary / planner photo → reminder JSON."""

from __future__ import annotations

VISION_PROMPT_VERSION = "v1"

VISION_SYSTEM_PROMPT = """You extract reminder fields from a photo of a diary, planner, sticky note, or handwritten page.
Return ONLY valid JSON (no markdown, no commentary).

JSON schema:
{
  "title": string|null,
  "date": "YYYY-MM-DD"|null,
  "time": "HH:MM"|null,
  "category": "To Do"|"Appointment"|"Important"|null,
  "notes": string|null,
  "confidence": number
}

HARD RULES:
1) Read only what is visible. Do NOT invent title, date, time, category, or notes.
2) title = short event name / heading (1–8 words). Not the whole page dump.
3) date = calendar date on the page as YYYY-MM-DD. If year missing, use context year.
4) time = 24-hour HH:MM when a clock time is visible (e.g. 3:30pm → 15:30). No default time.
5) category must be exactly one of: "To Do", "Appointment", "Important". Map synonyms
   (meeting/doctor → Appointment; task/todo → To Do; urgent/priority → Important).
   If unclear, null.
6) notes = extra readable text that is not the title (optional).
7) confidence = 0.0–1.0 how sure you are overall.
8) If the image has no reminder content, all fields null and confidence low.
"""


def build_vision_user_prompt(*, today_iso: str, weekday: str, timezone: str | None = None) -> str:
    tz = (timezone or "").strip() or "UTC"
    return (
        f"Today is {weekday}, {today_iso}. User timezone: {tz}.\n"
        "Extract title, date, time, category, and notes from this diary/planner photo.\n"
        "Return JSON only."
    )
