"""Chatbox event stream — the primary FSM signal source.

Pipeline per frame:

    1. If `prev_frame` is given, `rv.feature.changed_in_roi` cheaply gates
       the work — if the chatbox ROI hasn't changed, return immediately.
    2. For every unique color in `chat_colors.toml`:
       a. One `rv.ocr.read` pass over the chat ROI filtered to that color.
       b. For each recognized line, check every event pattern that shares
          that color; emit the first match.

One OCR pass per unique color is the whole point of the color-coded
approach: instead of reading the entire chatbox and classifying by
content, we read only what a channel we care about emits. That keeps the
hot path small and false-positive-free.

Domain parsers for uptext and XP drops are stubbed in :mod:`rs3vision.uptext`
and :mod:`rs3vision.xp_drops` — they need per-user calibration that Phase 2
doesn't cover.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from . import _rs3vision
from .chat_config import ChatConfig, ChatEventSpec, load_chat_config
from .types import ChatEvent, Rect

# ────────────────────────────────────────────────────────────────
# Font caching — one Font instance per path, shared across calls.
# ────────────────────────────────────────────────────────────────

_font_cache: dict[Path, tuple[float, object]] = {}


def _cached_font(path: Path):
    """Load a font once per mtime; return the cached handle thereafter."""
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(
            f"chat font not found: {path}\n"
            f"Compile one with `python rs3vision-tools/compile_font.py --font <name>`."
        )
    mtime = path.stat().st_mtime
    cached = _font_cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    font = _rs3vision.ocr.load_font(str(path))
    _font_cache[path] = (mtime, font)
    return font


# ────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────


def chatbox_events(
    frame,
    prev_frame=None,
    config: Optional[ChatConfig] = None,
    diff_tile: int = 8,
) -> list[ChatEvent]:
    """Return the chatbox events visible in `frame`.

    If `prev_frame` is supplied, the function short-circuits when the
    chatbox ROI hasn't changed, returning an empty list without running
    OCR.

    `config` defaults to the bundled `chat_colors.toml` (hot-reloadable).
    """
    if config is None:
        config = load_chat_config()

    # Cheap gate: if the ROI didn't change, there's nothing new to parse.
    if prev_frame is not None:
        try:
            changed = _rs3vision.feature.changed_in_roi(
                prev_frame, frame, config.roi.as_tuple(), tile=diff_tile
            )
        except Exception:
            changed = True  # fall through on any error
        if not changed:
            return []

    font = _cached_font(config.font_path)
    roi_tuple = config.roi.as_tuple()
    out: list[ChatEvent] = []

    for color_bgr, specs in config.by_color().items():
        lines = _rs3vision.ocr.read(
            frame,
            font,
            tuple(color_bgr),
            cts=config.defaults.cts,
            tol=config.defaults.tol,
            roi=roi_tuple,
            hue_mod=config.defaults.hue_mod,
            sat_mod=config.defaults.sat_mod,
        )
        for line in lines:
            text: str = line["text"]
            for spec in specs:
                if spec.pattern.search(text):
                    bbox: Tuple[int, int, int, int] = line["bbox"]
                    out.append(
                        ChatEvent(
                            event=spec.emit,
                            text=text,
                            color_bgr=tuple(color_bgr),
                            bbox=Rect.from_tuple(bbox),
                            confidence=float(line["confidence"]),
                        )
                    )
                    break  # first pattern wins within a color
    return out


def clear_font_cache() -> None:
    """Drop the font mtime cache (tests, hot-reload debugging)."""
    _font_cache.clear()
