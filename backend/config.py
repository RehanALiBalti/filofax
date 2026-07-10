"""Application configuration."""

from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("FILOFAX_DATA_DIR", str(APP_ROOT / "data")))
DATABASE_URL = os.getenv(
    "FILOFAX_DATABASE_URL",
    f"sqlite:///{(DATA_DIR / 'filofax.db').as_posix()}",
)

# Provider/model are env-only — never hardcode in business logic.
AI_PROVIDER = os.getenv("AI_PROVIDER", "ollama").strip().lower()
AI_MODEL = os.getenv("AI_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5:7b"))
AI_BASE_URL = os.getenv(
    "AI_BASE_URL",
    os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
).rstrip("/")
# Legacy alias still accepted
OLLAMA_URL = os.getenv("OLLAMA_URL", f"{AI_BASE_URL}/api/generate")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))

DEFAULT_USER_ID = os.getenv("FILOFAX_DEFAULT_USER_ID", "default")
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "FILOFAX_CORS_ORIGINS",
        "http://localhost:5175,http://127.0.0.1:5175,http://localhost:3000",
    ).split(",")
    if o.strip()
]

ALLOWED_CATEGORIES = ("To Do", "Appointment", "Important")
REQUIRED_CREATE_FIELDS = ("date", "label", "category")


def ai_base_url() -> str:
    """Resolve the AI runtime base URL (provider-agnostic)."""
    url = (AI_BASE_URL or "").rstrip("/")
    if url:
        return url
    legacy = OLLAMA_URL.rstrip("/")
    if legacy.endswith("/api/generate"):
        return legacy[: -len("/api/generate")]
    if legacy.endswith("/api/chat"):
        return legacy[: -len("/api/chat")]
    return legacy


def ollama_base_url() -> str:
    """Backward-compatible alias for ai_base_url()."""
    return ai_base_url()
