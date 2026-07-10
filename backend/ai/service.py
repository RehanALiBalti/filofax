"""Independent AI service: NLU → structured JSON only. No database access."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from pydantic import ValidationError

from backend.ai import ollama_client
from backend.ai.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
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

    def parse_message(self, message: str, *, today: date | None = None) -> AIResponse:
        today = today or date.today()
        user_prompt = build_user_prompt(
            message=message.strip(),
            today_iso=today.isoformat(),
            weekday=today.strftime("%A"),
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

    def health(self) -> dict[str, Any]:
        status = ollama_client.check_runtime()
        status["prompt_version"] = self.prompt_version
        return status


ai_service = AIService()
