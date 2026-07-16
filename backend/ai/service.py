"""Independent AI service: NLU → structured JSON only. No database access."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from pydantic import ValidationError

from backend.ai import ollama_client
from backend.ai.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from backend.ai.vision_prompts import (
    VISION_DATE_FOCUS_PROMPT,
    VISION_PROMPT_VERSION,
    VISION_SYSTEM_PROMPT,
    VISION_TIME_FOCUS_PROMPT,
    build_vision_user_prompt,
)
from backend.config import VISION_MODEL
from backend.language import normalize_language
from backend.models import AIResponse


class AIServiceError(Exception):
    """Raised when the model returns unusable output."""


_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(cleaned)
    if not match:
        raise AIServiceError("AI did not return valid JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise AIServiceError(f"AI returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AIServiceError("AI JSON root must be an object")
    return data


class AIService:
    """
    Thin adapter over a local LLM.

    Swap models via AI_PROVIDER / AI_MODEL / AI_BASE_URL — no business logic changes.
    Language coverage follows whatever the configured model understands.
    """

    prompt_version = PROMPT_VERSION

    def parse_message(
        self,
        message: str,
        *,
        today: date | None = None,
        conversation_context: dict[str, Any] | None = None,
    ) -> AIResponse:
        today = today or date.today()
        user_prompt = build_user_prompt(
            message=message.strip(),
            today_iso=today.isoformat(),
            weekday=today.strftime("%A"),
            conversation_context=conversation_context,
        )
        try:
            raw_text = ollama_client.generate_text(
                user_prompt,
                system=SYSTEM_PROMPT,
                max_tokens=800,
            )
        except Exception as exc:  # noqa: BLE001 — surface as service error
            raise AIServiceError(f"AI runtime call failed: {exc}") from exc

        if raw_text.startswith("Error calling Ollama"):
            raise AIServiceError(raw_text)

        payload = _extract_json_object(raw_text)
        try:
            parsed = AIResponse.model_validate(payload)
        except ValidationError as exc:
            raise AIServiceError(f"AI JSON failed schema validation: {exc}") from exc
        # Normalize language object; never reject unknown codes.
        parsed.language = normalize_language(parsed.language)
        parsed.raw = payload
        return parsed

    def extract_from_image(
        self,
        image_bytes: bytes,
        *,
        today: date | None = None,
        timezone: str | None = None,
        focus: str | None = None,
    ) -> dict[str, Any]:
        """Vision model → raw JSON dict with title/date/time/category/notes."""
        today = today or date.today()
        if focus == "time":
            system = VISION_TIME_FOCUS_PROMPT
            user_prompt = (
                "Look at the handwritten note on this planner page. "
                "Which left-column time row is it on? Return JSON with time_row/time."
            )
            max_tokens = 120
        elif focus == "date":
            system = VISION_DATE_FOCUS_PROMPT
            user_prompt = (
                "Read only the planner header date: month name, day number, and year "
                "from mini calendars. Return JSON."
            )
            max_tokens = 160
        else:
            system = VISION_SYSTEM_PROMPT
            user_prompt = build_vision_user_prompt(
                today_iso=today.isoformat(),
                weekday=today.strftime("%A"),
                timezone=timezone,
            )
            max_tokens = 800
        try:
            raw_text = ollama_client.generate_from_image(
                user_prompt,
                image_bytes,
                system=system,
                model=VISION_MODEL,
                max_tokens=max_tokens,
            )
        except Exception as exc:  # noqa: BLE001
            raise AIServiceError(f"Vision model call failed: {exc}") from exc

        if not raw_text:
            raise AIServiceError("Vision model returned empty response")
        if raw_text.startswith("Error calling Ollama"):
            raise AIServiceError(raw_text)

        payload = _extract_json_object(raw_text)
        payload["_prompt_version"] = VISION_PROMPT_VERSION
        payload["_focus"] = focus or "full"
        payload["_raw_text"] = raw_text
        return payload

    def health(self) -> dict[str, Any]:
        status = ollama_client.check_runtime()
        status["prompt_version"] = self.prompt_version
        status["vision_prompt_version"] = VISION_PROMPT_VERSION
        status["vision_model"] = VISION_MODEL
        return status


ai_service = AIService()
