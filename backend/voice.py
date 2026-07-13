"""Local voice transcription via faster-whisper (self-hosted, no paid STT API)."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from backend.config import (
    VOICE_ENABLED,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
    WHISPER_LANGUAGE,
    WHISPER_MODEL,
)

logger = logging.getLogger("filofax.voice")

_model = None
_model_error: str | None = None


class VoiceTranscriptionError(Exception):
    """Raised when audio cannot be transcribed."""


def whisper_status() -> dict[str, Any]:
    if not VOICE_ENABLED:
        return {"enabled": False, "ok": False, "error": "VOICE_ENABLED=false"}
    if _model_error:
        return {
            "enabled": True,
            "ok": False,
            "model": WHISPER_MODEL,
            "device": WHISPER_DEVICE,
            "error": _model_error,
        }
    return {
        "enabled": True,
        "ok": True,
        "model": WHISPER_MODEL,
        "device": WHISPER_DEVICE,
        "loaded": _model is not None,
        "language": WHISPER_LANGUAGE or "auto",
    }


def _load_model():
    global _model, _model_error
    if _model is not None:
        return _model
    if not VOICE_ENABLED:
        raise VoiceTranscriptionError("Voice is disabled on this server.")
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        _model_error = "faster-whisper is not installed"
        raise VoiceTranscriptionError(
            "Voice transcription package missing. Install: pip install faster-whisper"
        ) from exc
    try:
        logger.info(
            "Loading Whisper model=%s device=%s compute=%s",
            WHISPER_MODEL,
            WHISPER_DEVICE,
            WHISPER_COMPUTE_TYPE,
        )
        _model = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
        _model_error = None
        return _model
    except Exception as exc:  # noqa: BLE001
        _model_error = str(exc)
        raise VoiceTranscriptionError(f"Failed to load Whisper model: {exc}") from exc


def transcribe_audio_bytes(data: bytes, *, filename: str = "audio.webm") -> dict[str, Any]:
    if not data:
        raise VoiceTranscriptionError("Empty audio upload.")

    suffix = Path(filename).suffix.lower() or ".webm"
    if suffix not in {".webm", ".wav", ".mp3", ".m4a", ".ogg", ".mpeg", ".mp4", ".flac"}:
        suffix = ".webm"

    model = _load_model()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        path = tmp.name

    try:
        segments, info = model.transcribe(
            path,
            language=WHISPER_LANGUAGE,
            beam_size=1,
            vad_filter=True,
        )
        parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
        text = " ".join(parts).strip()
        if not text:
            raise VoiceTranscriptionError(
                "Could not understand the voice note. Please try again or type your message."
            )
        return {
            "transcript": text,
            "language": getattr(info, "language", None),
            "language_probability": getattr(info, "language_probability", None),
            "duration": getattr(info, "duration", None),
        }
    except VoiceTranscriptionError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Transcription failed")
        raise VoiceTranscriptionError(f"Transcription failed: {exc}") from exc
    finally:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass
