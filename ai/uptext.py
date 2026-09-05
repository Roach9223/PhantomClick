"""Shared uptext reader.

The RS3 NXT client draws an action tooltip right below the cursor when
hovering an interactable: "Chop down Willow", "Bank banker", "Talk to
Lumbridge Guide". The action verb is white; the target noun is yellow.
This module isolates a cursor-anchored ROI out of a frame and hands it
to the rs3vision Rust core's OCR engine using the shipped
``plain_11.rvf`` font.

Calling code:

- ``UptextReader.read_from_frame(frame, cursor_xy)``: ``cursor_xy`` is
  the cursor position in FRAME pixels (the bot api converts from the
  live screen cursor through the run's frame mapper). This is the path
  the bot loop uses.
- ``UptextReader.read_now()``: convenience for tooling outside a bot
  run. Grabs the whole virtual desktop and reads at the live cursor.

When the font isn't built yet, both paths return ``{error: ...}`` with
instructions pointing at ``rs3vision-tools/build_uptext_font.py``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from .fonts import UPTEXT_FONT_PATH, uptext_font_ready


# Default capture region anchored to the cursor. Tuned for 3840x2160
# at RS3 NXT default UI scale.
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

    # ────────────────────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────────────────────
    def ready(self) -> bool:
        """True when the font is on disk and OCR will actually run."""
        return self._font_path.exists()

    def read_now(self) -> Dict[str, Any]:
        """Capture the virtual desktop and read at the live cursor.

        Outside a bot run there is no frame mapper, so monitor index 0
        (the whole desktop) is used: its origin is the desktop origin
        and the cursor position maps in with one subtraction.
        """
        if not self.ready():
            return self._missing_font()
        from .input.frame_source import MssFrameSource, cursor_screen_xy
        src = MssFrameSource(0)
        try:
            frame = src.grab()
            ox, oy = src.origin()
        except Exception as e:
            return {"error": f"couldn't capture desktop: {type(e).__name__}: {e}"}
        finally:
            src.close()
        cx, cy = cursor_screen_xy()
        return self.read_from_frame(frame, (cx - ox, cy - oy))

    def read_from_frame(
        self, frame: Any, cursor_xy: Tuple[int, int]
    ) -> Dict[str, Any]:
        """Read uptext from an already-captured frame.

        ``cursor_xy`` must be in the frame's own pixel space.
        """
        if not self.ready():
            return self._missing_font()
        x, y, w, h = self._cursor_roi(cursor_xy)
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

    # ────────────────────────────────────────────────────────────
    # Internals
    # ────────────────────────────────────────────────────────────
    def _cursor_roi(
        self, cursor: Tuple[int, int]
    ) -> Tuple[int, int, int, int]:
        cx, cy = int(cursor[0]), int(cursor[1])
        return (cx + self._x_off, cy + self._y_off, self._width, self._height)

    def _ocr(self, region: Any, cursor_xy: Tuple[int, int]) -> Dict[str, Any]:
        try:
            import rs3vision as rv
            text, confidence = _call_rs3v_ocr(rv, self._font_path, region)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            return {
                "error": f"uptext OCR failed: {err}",
                "cursor_xy": list(cursor_xy),
                "confidence": 0.0,
            }

        action, target = _split_uptext(text)
        x, y, w, h = self._cursor_roi(cursor_xy)
        return {
            "text": text,
            "action": action,
            "target": target,
            "cursor_xy": list(cursor_xy),
            "confidence": float(confidence),
            "roi": f"{x},{y},{w},{h}",
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


def _call_rs3v_ocr(rv, font_path: Path, region: Any) -> Tuple[str, float]:
    """Call whichever OCR entry point the rs3vision bindings expose.

    Keeps the uptext reader decoupled from exact binding names; if the
    API shifts we try a couple of common shapes.
    """
    ocr_mod = getattr(rv, "ocr", None)
    if ocr_mod is not None:
        for fn_name in ("read", "read_text", "ocr"):
            fn = getattr(ocr_mod, fn_name, None)
            if fn is None:
                continue
            try:
                result = fn(region, str(font_path))
            except TypeError:
                try:
                    result = fn(region, font=str(font_path))
                except TypeError:
                    continue
            return _unpack_ocr_result(result)
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
        return " ".join(str(x) for x in result), 0.0
    return str(result or ""), 0.0


_UPTEXT_SEP = re.compile(r"\s+")


def _split_uptext(text: str) -> Tuple[str, str]:
    """Heuristically split ``"Chop down Willow"`` into action + target.

    The RS3 client's action text is typically 1 to 3 words (verbs like
    "Chop down", "Attack", "Talk to", "Open"); the target is the
    remainder. Without a per-verb whitelist the cheap heuristic is:
    last word is the target, everything else is the action. Lines
    after the first (the "+N options" suffix) are dropped.
    """
    if not text:
        return "", ""
    first_line = text.splitlines()[0].strip()
    parts = _UPTEXT_SEP.split(first_line)
    if len(parts) <= 1:
        return first_line, ""
    return " ".join(parts[:-1]), parts[-1]
