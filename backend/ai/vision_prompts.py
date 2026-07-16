"""Prompts for diary / planner photo → reminder JSON."""

from __future__ import annotations

VISION_PROMPT_VERSION = "v5"

# Ask for easy visual facts — Python composes final date/time/category.
# NEVER put real sample titles/dates in few-shots — weak models copy them onto blank pages.
VISION_SYSTEM_PROMPT = """You read a photo of a daily planner / diary page (often Blueline).
Return ONLY valid JSON. Do NOT invent. Do NOT copy text from these instructions.

JSON schema:
{
  "has_handwritten_entry": boolean,
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
1) has_handwritten_entry = true ONLY if there is real handwriting or colored ink text
   written on a schedule line. A blank page, empty lines, or only a colored highlight
   with NO words → has_handwritten_entry=false, and entry_text/title/time_row/time/category
   must ALL be null.
2) entry_text / title = copy the handwritten/colored note words exactly when present.
   Ignore printed template: month names, day numbers, weekday banner, holiday names,
   Important label, weather icons, Blueline, QR, "Do not write over…".
3) header_month = large printed month (e.g. May). header_day = large printed day number.
4) calendar_year = year from mini-calendars when shown (e.g. June 2025 → 2025).
5) time_row = left-column printed time on the SAME row as handwritten text ONLY.
   Never invent a time for an empty row or a highlight with no text.
6) important_checked = true only if the Important box has a written mark/check.
7) category only when handwritten entry exists:
   boss/important/urgent → Important; meeting/doctor/call → Appointment; else To Do.
"""

VISION_TITLE_FOCUS_PROMPT = """Look at the schedule grid only.

Is there REAL handwritten or colored-ink WORDS on a time line?
- If YES: return those words in entry_text and title.
- If NO (blank lines, highlight only, no writing): has_handwritten_entry=false and
  entry_text=null, title=null.

Do NOT invent appointments. Do NOT reuse text from memory or instructions.

Return ONLY JSON:
{
  "has_handwritten_entry": boolean,
  "entry_text": string|null,
  "title": string|null,
  "confidence": number
}
"""

VISION_TIME_FOCUS_PROMPT = """Look at the handwritten/colored WORDS on the schedule (if any).

If there is NO handwritten text, return time_row=null and time=null.
If there IS handwritten text, return the left-column printed time on that same row.

Return ONLY JSON:
{"time_row": "HH:MM"|null, "time": "HH:MM"|null, "time_is_pm": boolean|null, "confidence": number}
"""

VISION_DATE_FOCUS_PROMPT = """Read ONLY the printed date header of this planner page.

Return the large month name, large day number, and year from mini-calendars if visible.

Return ONLY JSON:
{
  "header_month": string|null,
  "header_day": number|null,
  "calendar_year": number|null,
  "date": "YYYY-MM-DD"|null,
  "confidence": number
}
"""


def build_vision_user_prompt(*, today_iso: str, weekday: str, timezone: str | None = None) -> str:
    tz = (timezone or "").strip() or "UTC"
    return (
        f"Context only (not the event date unless the page has no header): "
        f"today is {weekday}, {today_iso}. Timezone: {tz}.\n"
        "If the schedule has no handwritten note, set has_handwritten_entry=false and "
        "leave entry_text, title, time, time_row, and category null. "
        "Still read header_month, header_day, calendar_year when printed.\n"
        "Return JSON only. Do not invent text."
    )
