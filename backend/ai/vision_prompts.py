"""Prompts for diary / planner photo → reminder JSON."""

from __future__ import annotations

VISION_PROMPT_VERSION = "v3"

# Ask for easy visual facts — Python composes final date/time/category.
VISION_SYSTEM_PROMPT = """You read a photo of a daily planner / diary page (often Blueline).
Return ONLY valid JSON. Do NOT invent. Prefer simple facts over formatted dates.

JSON schema:
{
  "entry_text": string|null,
  "header_month": string|null,
  "header_day": number|null,
  "header_weekday": string|null,
  "calendar_year": number|null,
  "time_row": string|null,
  "time_is_pm": boolean|null,
  "important_checked": boolean|null,
  "title": string|null,
  "date": "YYYY-MM-DD"|null,
  "time": "HH:MM"|null,
  "category": "To Do"|"Appointment"|"Important"|null,
  "notes": string|null,
  "confidence": number
}

HOW TO READ THE PAGE:
1) entry_text / title = handwritten or colored note only (e.g. "meeting with my boss").
   Ignore printed template words like June, Sunday, Important, weather labels.
2) header_month = large month name at top-left (e.g. "June").
3) header_day = large day number next to month (e.g. 22).
4) calendar_year = year from mini-calendars if shown (e.g. "June 2025" → 2025).
5) time_row = LEFT COLUMN printed time on the SAME horizontal line as the handwritten note
   (e.g. note beside 11:00 → "11:00"). This is mandatory when a note exists.
6) time_is_pm = true only if that row is clearly in the afternoon/evening half of the page.
7) important_checked = true only if the Important box has a mark/check.
8) Also fill date/time/category if you can, but entry_text + header_* + time_row matter most.
9) category:
   - Important box checked OR note like "boss" / "important" / "urgent" → "Important"
   - Else meeting/doctor/call/client → "Appointment"
   - Else task/errand → "To Do"
"""

VISION_TIME_FOCUS_PROMPT = """Focus ONLY on the handwritten/colored note on this planner.

The LEFT column prints times (7:00, 7:30, 8:00, … 11:00, …).
Which printed time is on the SAME row as the handwritten note?

Return ONLY JSON:
{"time_row": "HH:MM"|null, "time": "HH:MM"|null, "time_is_pm": boolean|null, "confidence": number}

Example: pink text "meeting with my boss" on the 11:00 line →
{"time_row": "11:00", "time": "11:00", "time_is_pm": false, "confidence": 0.92}
"""

VISION_DATE_FOCUS_PROMPT = """Focus ONLY on the date header of this planner page.

Read:
- large month name (e.g. June)
- large day number (e.g. 22)
- year from mini calendars if present (e.g. 2025)

Return ONLY JSON:
{
  "header_month": string|null,
  "header_day": number|null,
  "calendar_year": number|null,
  "date": "YYYY-MM-DD"|null,
  "confidence": number
}

Example: June + 22 + mini calendar June 2025 →
{"header_month": "June", "header_day": 22, "calendar_year": 2025, "date": "2025-06-22", "confidence": 0.95}
"""


def build_vision_user_prompt(*, today_iso: str, weekday: str, timezone: str | None = None) -> str:
    tz = (timezone or "").strip() or "UTC"
    return (
        f"Context only (do not use as the event date unless the page has no header): "
        f"today is {weekday}, {today_iso}. Timezone: {tz}.\n"
        "Extract planner facts as JSON. "
        "Priority fields: entry_text, header_month, header_day, calendar_year, time_row.\n"
        "Return JSON only."
    )
