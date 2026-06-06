"""Shared uptext reader — used by both the playbook evaluator and the
``uptext_read`` MCP tool.

The RS3 NXT client draws an action tooltip right below the cursor when
hovering an interactable — "Chop down Willow", "Bank banker", "Talk to
Lumbridge Guide", etc. The action verb is white; the target noun is
yellow. This module isolates a cursor-anchored ROI, captures it, and
hands it to the rs3vision Rust core's OCR engine using the shipped
``plain_11.rvf`` font.

Calling code:

- ``UptextReader.read_now()`` → ``{text, action, target, cursor_xy,
   confidence, roi}`` using the live cursor position + a fresh capture.
- ``UptextReader.read_from_frame(frame, cursor_xy)`` → same shape but
   from an already-captured frame. Used by the playbook evaluator so
   each tick doesn't double-capture.

When the font isn't built yet, both paths return ``{error: ...}`` with
instructions pointing at ``rs3vision-tools/build_uptext_font.py``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from .fonts import UPTEXT_FONT_PATH, uptext_font_ready
from .humanize.mouse_api import PynputMouse


# Default capture region anchored to the cursor. Tuned for 3840×2160
# at RS3 NXT default UI scale. Override via HumanizerConfig-like knobs
# if the user's resolution differs significantly.
DEFAULT_WIDTH = 420
DEFAULT_HEIGHT = 58
DEFAULT_X_OFF = 2
DEFAULT_Y_OFF = 14


class UptextReader:
    """Reads the RS3 uptext rendered near the cursor."""

    def __init__(
        self,
        *,
        font_path: Optional[Path] = None,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        x_off: int = DEFAULT_X_OFF,
        y_off: int = DEFAULT_Y_OFF,
    ) -> None:
        self._font_path = Path(font_path) if font_path else UPTEXT_FONT_PATH
        self._width = int(width)
        self._height = int(height)
        self._x_off = int(x_off)
        self._y_off = int(y_off)
        self._mouse = PynputMouse()

    # ────────────────────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────────────────────
    def ready(self) -> bool:
        """True when the font is on disk and OCR will actually run."""
        return self._font_path.exists()

    def read_now(self) -> Dict[str, Any]:
        """Capture + read the uptext at the current cursor position."""
        if not self.ready():
            return self._missing_font()
        cursor = self._mouse.get_position()
        frame = _grab_roi(*self._cursor_roi(cursor))
        if frame is None:
            return {"error": "couldn't capture cursor-anchored ROI"}
        return self._ocr(frame, cursor)

    def read_from_frame(
        self, frame: Any, cursor_xy: Optional[Tuple[int, int]] = None
    ) -> Dict[str, Any]:
        """Read uptext from an already-captured full frame.

        ``frame`` is the whole target monitor; we slice the cursor-anchored
        ROI out of it. ``cursor_xy`` defaults to the live cursor — handy
        for the evaluator which needs frame + cursor agreement.
        """
        if not self.ready():
            return self._missing_font()
        if cursor_xy is None:
            cursor_xy = self._mouse.get_position()
        x, y, w, h = self._cursor_roi(cursor_xy)
        # The frame is full-monitor, so slice directly.
        try:
            h_img, w_img = frame.shape[:2]
        except Exception:
            return {"error": "invalid frame"}
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(w_img, x + w)
        y2 = min(h_img, y + h)
        if x2 <= x1 or y2 <= y1:
            return {"error": "cursor ROI outside frame"}
        region = np.ascontiguousarray(frame[y1:y2, x1:x2])
        return self._ocr(region, cursor_xy)

    def cursor_roi_str(self) -> str:
        """Return the current cursor ROI as a comma-string for ``ocr.read.roi``."""
        x, y, w, h = self._cursor_roi(self._mouse.get_position())
        return f"{x},{y},{w},{h}"

    # ────────────────────────────────────────────────────────────
    # Internals
    # ────────────────────────────────────────────────────────────
    def _cursor_roi(
        self, cursor: Tuple[int, int]
    ) -> Tuple[int, int, int, int]:
        cx, cy = int(cursor[0]), int(cursor[1])
        return (cx + self._x_off, cy + self._y_off, self._width, self._height)

    def _ocr(self, region: Any, cursor_xy: Tuple[int, int]) -> Dict[str, Any]:
        # Try the rs3vision Rust bindings first — if the font exists we
        # can call the fast path.
        try:
            import rs3vision as rv
            # The exact OCR API depends on the binding. We try two known
            # names and fall back to the ocr.read block as a last resort.
            text, confidence = _call_rs3v_ocr(rv, self._font_path, region)
        except Exception as e:
            text, confidence = "", 0.0
            err = f"{type(e).__name__}: {e}"
            return {
                "error": f"uptext OCR failed: {err}",
                "cursor_xy": list(cursor_xy),
                "confidence": 0.0,
            }

        action, target = _split_uptext(text)
        return {
            "text": text,
            "action": action,
            "target": target,
            "cursor_xy": list(cursor_xy),
            "confidence": float(confidence),
            "roi": self.cursor_roi_str(),
        }

    def _missing_font(self) -> Dict[str, Any]:
        return {
            "error": (
                f"uptext font not built yet: {self._font_path} missing. "
                "Press F9 while hovering ~20 different RS3 targets to seed "
                "the corpus, then run rs3vision-tools/build_uptext_font.py."
            ),
            "font_path": str(self._font_path),
            "ready": False,
        }


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def _grab_roi(x: int, y: int, w: int, h: int):
    """Grab a single-region screenshot via mss. Returns a BGR ndarray."""
    try:
        import mss
        with mss.mss() as sct:
            raw = sct.grab({"left": int(x), "top": int(y), "width": int(w), "height": int(h)})
            arr = np.asarray(raw, dtype=np.uint8)[:, :, :3]
            return np.ascontiguousarray(arr)
    except Exception:
        return None


def _call_rs3v_ocr(rv, font_path: Path, region: Any) -> Tuple[str, float]:
    """Call whichever OCR entry point the rs3vision bindings expose.

    Keeps the uptext reader decoupled from exact binding names — if the
    API shifts we try a couple of common shapes.
    """
    # Preferred path: rv.ocr.read(frame, font_path, ...)
    ocr_mod = getattr(rv, "ocr", None)
    if ocr_mod is not None:
        for fn_name in ("read", "read_text", "ocr"):
            fn = getattr(ocr_mod, fn_name, None)
            if fn is None:
                continue
            try:
                # Try a few signatures — start simplest.
                result = fn(region, str(font_path))
            except TypeError:
                try:
                    result = fn(region, font=str(font_path))
                except TypeError:
                    continue
            return _unpack_ocr_result(result)
    # Last resort: use the existing ocr.read block; it wraps the same
    # rv path but with ctx. For the MCP tool we don't have a ctx handy,
    # so raise.
    raise RuntimeError("rs3vision OCR entry point not found (binding mismatch)")


def _unpack_ocr_result(result: Any) -> Tuple[str, float]:
    """Normalise the OCR binding's return shape to ``(text, confidence)``."""
    if isinstance(result, dict):
        text = str(result.get("text") or "")
        conf = float(result.get("confidence") or result.get("score") or 0.0)
        return text, conf
    if isinstance(result, tuple) and len(result) >= 1:
        text = str(result[0] or "")
        conf = float(result[1]) if len(result) > 1 else 0.0
        return text, conf
    if isinstance(result, (list,)) and result:
        # List of lines — join with spaces.
        return " ".join(str(x) for x in result), 0.0
    return str(result or ""), 0.0


_UPTEXT_SEP = re.compile(r"\s+")


def _split_uptext(text: str) -> Tuple[str, str]:
    """Heuristically split ``"Chop down Willow"`` into action + target.

    The RS3 client's action text is typically 1–3 words (verbs like
    "Chop down", "Attack", "Talk to", "Open"); the target is the
    remainder. Without a per-verb whitelist the cheap heuristic is:
    last word is the target, everything else is the action.

    For the "+N options" suffix the client sometimes appends, drop
    lines / tokens after the first newline.
    """
    if not text:
        return "", ""
    first_line = text.splitlines()[0].strip()
    parts = _UPTEXT_SEP.split(first_line)
    if len(parts) <= 1:
        return first_line, ""
    # Heuristic: pull off the last token as target.
    return " ".join(parts[:-1]), parts[-1]
