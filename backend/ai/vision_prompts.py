"""Prompts for diary / planner photo → reminder JSON."""

from __future__ import annotations

VISION_PROMPT_VERSION = "v2"

VISION_SYSTEM_PROMPT = """You extract reminder fields from a photo of a diary, daily planner, sticky note, or handwritten page.
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
1) Read only what is visible. Do NOT invent fields.
2) title = the handwritten / colored note text (short). Example: "meeting with my boss".
3) date = page header date as YYYY-MM-DD. Use mini-calendars for the year when shown
   (e.g. May 2025 / June 2025 → year 2025). Month name + day number → that date.
4) TIME IS CRITICAL on daily planners (Blueline, Filofax, etc.):
   - Left column lists clock rows: 7:00, 7:30, 8:00, … 
   - The event time is the LEFT-COLUMN row where the handwritten note is written.
   - Example: pink/handwritten text sitting on the "11:00" line → time "11:00"
     (or "11:00" morning → 11:00; if the planner is clearly PM schedule and marked 11, still use the printed row).
   - Do NOT leave time null if a note sits clearly next to a printed time.
   - Convert to 24-hour HH:MM (11:00 stays 11:00; 3:30pm → 15:30; 7:30 on evening half → 19:30 if the row is the PM block labeled that way).
5) category exact: "To Do" | "Appointment" | "Important".
   meeting/boss/doctor/call → Appointment; task/errand → To Do; if page has Important box checked → Important.
6) notes = extra text not used as title (optional).
7) confidence 0.0–1.0.
8) Empty page with no handwritten entry → all null, low confidence.
"""

VISION_TIME_FOCUS_PROMPT = """Focus ONLY on the time for the handwritten/colored diary entry.

Daily planners print times in a LEFT column (7:00, 7:30, 8:00, …).
Find which printed time ROW the note sits on. That row IS the event time.

Return ONLY JSON:
{"time": "HH:MM"|null, "confidence": number}

Examples:
- Note on the 11:00 line → {"time": "11:00", "confidence": 0.9}
- Note on 3:30 (afternoon block) → {"time": "15:30", "confidence": 0.85}
If truly unclear, {"time": null, "confidence": 0.2}.
"""


def build_vision_user_prompt(*, today_iso: str, weekday: str, timezone: str | None = None) -> str:
    tz = (timezone or "").strip() or "UTC"
    return (
        f"Today is {weekday}, {today_iso}. User timezone: {tz}.\n"
        "This is often a Blueline-style daily planner page.\n"
        "1) Read the handwritten/colored entry for the TITLE.\n"
        "2) Read the header month + day (+ year from mini calendars) for DATE.\n"
        "3) Match the entry to the LEFT time-column row for TIME (do not skip time).\n"
        "4) Infer category (meeting → Appointment).\n"
        "Return JSON only."
    )
