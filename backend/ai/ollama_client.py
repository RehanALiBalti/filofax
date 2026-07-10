"""AI runtime client — provider/model come only from config/env."""

from __future__ import annotations

from typing import Any

import requests
from langchain_ollama import ChatOllama

from backend.config import AI_MODEL, AI_PROVIDER, OLLAMA_TIMEOUT_SECONDS, ai_base_url


def get_chat_llm(*, temperature: float = 0.1, max_tokens: int = 800) -> ChatOllama:
    if AI_PROVIDER not in ("ollama", ""):
        # Future providers plug in here without touching business logic.
        raise RuntimeError(f"Unsupported AI_PROVIDER={AI_PROVIDER!r}; currently only 'ollama' is wired.")
    return ChatOllama(
        model=AI_MODEL,
        base_url=ai_base_url(),
        temperature=temperature,
        num_predict=max_tokens,
    )


def generate_text(prompt: str, *, system: str | None = None, max_tokens: int = 800) -> str:
    llm = get_chat_llm(max_tokens=max_tokens)
    if system:
        from langchain_core.messages import HumanMessage, SystemMessage

        response = llm.invoke([SystemMessage(content=system), HumanMessage(content=prompt)])
    else:
        response = llm.invoke(prompt)
    content = getattr(response, "content", str(response))
    return (content or "").strip()


def check_runtime() -> dict[str, Any]:
    try:
        base = ai_base_url()
        res = requests.get(f"{base}/api/tags", timeout=min(5.0, OLLAMA_TIMEOUT_SECONDS))
        res.raise_for_status()
        models = [m.get("name", "") for m in res.json().get("models", [])]
        has_model = any(AI_MODEL in m or m.startswith(AI_MODEL) for m in models)
        return {
            "ok": True,
            "provider": AI_PROVIDER,
            "model": AI_MODEL,
            "base_url": base,
            "model_available": has_model,
            "models": models,
            "via": "langchain-ollama",
        }
    except requests.RequestException as exc:
        return {
            "ok": False,
            "provider": AI_PROVIDER,
            "model": AI_MODEL,
            "base_url": ai_base_url(),
            "error": str(exc),
        }


def check_ollama() -> dict[str, Any]:
    """Backward-compatible alias."""
    return check_runtime()
