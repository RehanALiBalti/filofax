"""Deterministic planner-page cues (highlight band → time) without trusting LLaVA invents."""

from __future__ import annotations

import io
from typing import Any

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[misc, assignment]

# Blueline-style day page: half-hour rows from 7:00 through 19:30
_SLOT_MINUTES = list(range(7 * 60, 19 * 60 + 31, 30))


def _is_highlighter_rgb(r: int, g: int, b: int) -> bool:
    """Light green / yellow highlighter wash on white paper."""
    if g > 155 and g >= r + 12 and g >= b + 8 and r > 130 and b > 110:
        return True
    if g > 175 and r < 210 and b < 200 and g > r and g > b:
        return True
    # soft yellow highlighter
    if r > 200 and g > 190 and b < 170 and r + g > 400:
        return True
    return False


def detect_highlighted_time(image_bytes: bytes) -> dict[str, Any] | None:
    """
    Find a highlighter band in the schedule area and map it to a clock time.
    Returns {"time": "HH:MM", "confidence": float, "has_time_highlight": True} or None.
    """
    if Image is None or not image_bytes:
        return None
    try:
        im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:  # noqa: BLE001
        return None

    w, h = im.size
    if w < 80 or h < 120:
        return None
    pixels = im.load()
    y0 = int(h * 0.28)
    y1 = int(h * 0.72)
    x0 = int(w * 0.06)
    x1 = int(w * 0.58)
    row_scores = [0] * h
    for y in range(y0, y1):
        score = 0
        for x in range(x0, x1):
            r, g, b = pixels[x, y]
            if _is_highlighter_rgb(r, g, b):
                score += 1
        row_scores[y] = score

    best_y = max(range(y0, y1), key=lambda y: row_scores[y])
    peak = row_scores[best_y]
    # Need a real band, not noise
    width = max(1, x1 - x0)
    if peak < max(8, width * 0.04):
        return None

    # Smooth: average peak neighborhood
    band = [yy for yy in range(max(y0, best_y - 4), min(y1, best_y + 5)) if row_scores[yy] > peak * 0.45]
    if not band:
        return None
    cy = sum(band) / len(band)
    frac = (cy - y0) / max(1.0, (y1 - y0))
    frac = max(0.0, min(1.0, frac))
    idx = int(round(frac * (len(_SLOT_MINUTES) - 1)))
    idx = max(0, min(len(_SLOT_MINUTES) - 1, idx))
    minutes = _SLOT_MINUTES[idx]
    hh, mm = divmod(minutes, 60)
    conf = min(0.95, 0.55 + peak / max(width, 1))
    return {
        "has_time_highlight": True,
        "highlighted_time_row": f"{hh:02d}:{mm:02d}",
        "time": f"{hh:02d}:{mm:02d}",
        "confidence": conf,
        "_cv_peak": peak,
        "_cv_y_frac": round(cy / h, 4),
    }


def crop_header_bytes(image_bytes: bytes) -> bytes | None:
    """Top portion of page (date header + mini calendars) for a focused date read."""
    if Image is None or not image_bytes:
        return None
    try:
        im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:  # noqa: BLE001
        return None
    w, h = im.size
    box = (0, 0, w, max(40, int(h * 0.26)))
    header = im.crop(box)
    buf = io.BytesIO()
    header.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def analyze_planner_image(image_bytes: bytes) -> dict[str, Any]:
    """CV cues that override weak vision-model hallucinations."""
    out: dict[str, Any] = {}
    hit = detect_highlighted_time(image_bytes)
    if hit:
        out.update(hit)
    return out
