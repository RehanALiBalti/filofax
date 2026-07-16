"""AI runtime client — provider/model come only from config/env."""

from __future__ import annotations

import base64
from typing import Any

import requests
from langchain_ollama import ChatOllama

from backend.config import (
    AI_MODEL,
    AI_PROVIDER,
    OLLAMA_TIMEOUT_SECONDS,
    VISION_MODEL,
    VISION_TIMEOUT_SECONDS,
    ai_base_url,
)


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


def generate_from_image(
    prompt: str,
    image_bytes: bytes,
    *,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int = 600,
) -> str:
    """
    Call Ollama /api/chat with a vision model and one image (base64).
    Works with llava, bakllava, qwen2-vl, moondream, etc.
    """
    if AI_PROVIDER not in ("ollama", ""):
        raise RuntimeError(
            f"Unsupported AI_PROVIDER={AI_PROVIDER!r}; vision currently needs ollama."
        )
    vision_model = (model or VISION_MODEL).strip()
    if not vision_model:
        raise RuntimeError("VISION_MODEL is empty")
    if not image_bytes:
        raise ValueError("Empty image")

    b64 = base64.b64encode(image_bytes).decode("ascii")
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append(
        {
            "role": "user",
            "content": prompt,
            "images": [b64],
        }
    )
    payload = {
        "model": vision_model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1, "num_predict": max_tokens},
    }
    base = ai_base_url()
    res = requests.post(
        f"{base}/api/chat",
        json=payload,
        timeout=VISION_TIMEOUT_SECONDS,
    )
    res.raise_for_status()
    data = res.json()
    content = ""
    msg = data.get("message") or {}
    if isinstance(msg, dict):
        content = msg.get("content") or ""
    if not content:
        content = data.get("response") or ""
    return str(content).strip()


def check_runtime() -> dict[str, Any]:
    try:
        base = ai_base_url()
        res = requests.get(f"{base}/api/tags", timeout=min(5.0, OLLAMA_TIMEOUT_SECONDS))
        res.raise_for_status()
        models = [m.get("name", "") for m in res.json().get("models", [])]
        has_model = any(AI_MODEL in m or m.startswith(AI_MODEL) for m in models)
        has_vision = any(VISION_MODEL in m or m.startswith(VISION_MODEL) for m in models)
        return {
            "ok": True,
            "provider": AI_PROVIDER,
            "model": AI_MODEL,
            "vision_model": VISION_MODEL,
            "base_url": base,
            "model_available": has_model,
            "vision_model_available": has_vision,
            "models": models,
            "via": "langchain-ollama",
        }
    except requests.RequestException as exc:
        return {
            "ok": False,
            "provider": AI_PROVIDER,
            "model": AI_MODEL,
            "vision_model": VISION_MODEL,
            "base_url": ai_base_url(),
            "error": str(exc),
        }


def check_ollama() -> dict[str, Any]:
    """Backward-compatible alias."""
    return check_runtime()
