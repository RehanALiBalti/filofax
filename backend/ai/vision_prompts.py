"""Prompts for diary / planner photo → reminder JSON."""

from __future__ import annotations

VISION_PROMPT_VERSION = "v6"

# Ask for easy visual facts — Python composes final date/time/category.
# NEVER put real sample titles/dates in few-shots — weak models copy them onto blank pages.
VISION_SYSTEM_PROMPT = """You read a photo of a daily planner / diary page (often Blueline).
Return ONLY valid JSON. Do NOT invent. Do NOT copy text from these instructions.

JSON schema:
{
  "has_handwritten_entry": boolean,
  "has_time_highlight": boolean,
  "entry_text": string|null,
  "header_month": string|null,
  "header_day": number|null,
  "header_weekday": string|null,
  "calendar_year": number|null,
  "time_row": string|null,
  "highlighted_time_row": string|null,
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
1) has_handwritten_entry = true ONLY if there is real handwriting or colored ink WORDS
   on a schedule line. Blank lines or a colored highlight with NO words → false.
   When false: entry_text, title, and category must be null.
2) has_time_highlight = true if a schedule ROW is marked with a colored highlighter
   band (green/yellow/pink wash) even when no text is written on that row.
3) entry_text / title = handwritten/colored note words only when present.
   Ignore printed template: month, day number, weekday, holiday name, Important label,
   weather, Blueline, QR.
4) header_month = large printed month. header_day = large printed day number.
5) calendar_year = year printed on mini-calendars (e.g. "June 2025" → 2025).
   ALWAYS use that year for date. Do not guess an older year like 2023.
6) time_row = left-column time next to handwritten words (when present).
7) highlighted_time_row = left-column time on the highlighted row when has_time_highlight
   is true (e.g. green band across the 9:30 line → "9:30"). Set time to the same value.
   This is valid EVEN when has_handwritten_entry is false.
8) important_checked = true only if Important box has a mark.
9) category only when handwritten entry exists.
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

VISION_TIME_FOCUS_PROMPT = """Look at the schedule time column.

Pick a time from EITHER:
A) Left-column time on the same row as handwritten/colored WORDS, OR
B) Left-column time on a row with a colored HIGHLIGHTER band (green/yellow/pink)
   even if that row has no text.

If neither exists, return nulls.

Return ONLY JSON:
{
  "has_time_highlight": boolean,
  "time_row": "HH:MM"|null,
  "highlighted_time_row": "HH:MM"|null,
  "time": "HH:MM"|null,
  "time_is_pm": boolean|null,
  "confidence": number
}
"""

VISION_DATE_FOCUS_PROMPT = """Read ONLY the printed date header of this planner page.

Return the large month name, large day number, and year from mini-calendars if visible.
Year MUST come from mini-calendars when shown (e.g. June 2025 / July 2025 → 2025).
Do not invent years like 2023.

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
        "If there is no handwritten note, has_handwritten_entry=false and "
        "entry_text/title/category=null.\n"
        "If a time row is highlighted (colored band), set has_time_highlight=true and "
        "highlighted_time_row to that left-column time (e.g. 9:30).\n"
        "Read header_month, header_day, calendar_year from the page.\n"
        "Return JSON only. Do not invent text."
    )
