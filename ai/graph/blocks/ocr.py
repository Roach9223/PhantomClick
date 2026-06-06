"""OCR blocks — read text from frames using compiled .rvf fonts.

The font is specified by path as a block parameter. The runtime context
caches the loaded Font object by (path, mtime) so repeated ticks of the
same script reuse a single load.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import rs3vision as rv

from .base import Block, Param, Port


_OCR_COLOR = (100, 70, 40)


class ReadTextBlock(Block):
    identifier = "ocr.read"
    name = "Read Text"
    category = "OCR"
    description = (
        "Recognise text in a frame ROI using a compiled .rvf font. "
        "Returns a list of lines + a joined string."
    )
    example = (
        "Build a font first via rs3vision-tools/ (corpus → extract → "
        "label → compile). Set font_path to 'plain_11.rvf' or similar, "
        "target to the text colour, and roi to the chatbox rectangle."
    )
    color = _OCR_COLOR

    inputs = [
        Port("frame", kind="data"),
        Port("trigger", kind="trigger"),
    ]
    outputs = [
        Port("lines", kind="data"),       # list of dicts (per-line detail)
        Port("text", kind="data"),        # joined string
        Port("line_count", kind="data"),  # int
        Port("done", kind="trigger"),
    ]
    params = [
        Param(
            "font_path",
            default="",
            kind="text",
            description=(
                "Path to a compiled .rvf font. Relative paths resolve against "
                "rs3vision/templates/fonts/."
            ),
        ),
        Param(
            "target",
            default="0xFFFFFF",
            kind="color_hex",
            description="Target text color as 0xRRGGBB.",
        ),
        Param("cts", default="2", kind="choice", choices=["1", "2", "3"]),
        Param("tol", default=20.0, kind="float"),
        Param(
            "roi",
            default="",
            kind="text",
            description="Optional ROI as x,y,w,h (blank = whole frame).",
        ),
    ]

    def execute(
        self, ctx, frame=None, font_path: str = "", target: Optional[int] = None,
        cts: Any = 2, tol: float = 20.0, roi: str = "", **_: Any,
    ) -> Dict[str, Any]:
        if frame is None:
            return {"lines": [], "text": "", "line_count": 0, "done": True}
        if not font_path:
            ctx.log(
                "ocr.read: no font_path set. Compile a font first with "
                "rs3vision-tools/compile_font.py, then set font_path to "
                "the resulting .rvf (e.g. 'plain_11.rvf')."
            )
            return {"lines": [], "text": "", "line_count": 0, "done": True}
        try:
            font = _cached_font(font_path)
        except FileNotFoundError as e:
            ctx.log(f"ocr.read: {e}")
            return {"lines": [], "text": "", "line_count": 0, "done": True}
        except Exception as e:
            ctx.log(f"ocr.read: font load failed: {e}")
            return {"lines": [], "text": "", "line_count": 0, "done": True}

        target_bgr = _hex_to_bgr(target) if target is not None else (255, 255, 255)
        roi_tuple = ctx.resolve_roi(roi)
        try:
            lines = rv.ocr.read(
                frame, font, target_bgr, cts=int(cts), tol=float(tol), roi=roi_tuple
            )
        except Exception as e:
            ctx.log(f"ocr.read: recognition failed: {e}")
            return {"lines": [], "text": "", "line_count": 0, "done": True}

        joined = " ".join(l.get("text", "") for l in lines).strip()
        return {
            "lines": list(lines),
            "text": joined,
            "line_count": len(lines),
            "done": True,
        }


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


_FONT_CACHE: Dict[str, Tuple[float, Any]] = {}  # (mtime, font_handle)


def _cached_font(path_spec: str):
    """Resolve `path_spec` and load the font, caching by (resolved_path, mtime).

    Relative paths resolve against the installed rs3vision package's
    templates/fonts/ directory first, then against the current working
    directory.
    """
    from pathlib import Path
    import rs3vision

    p = Path(path_spec)
    if not p.is_absolute():
        bundled = (
            Path(rs3vision.__file__).resolve().parent / "templates" / "fonts" / path_spec
        )
        if bundled.exists():
            p = bundled
    p = p.resolve()
    if not p.exists():
        raise FileNotFoundError(
            f"font not found: {path_spec!r}. Looked at {p}. "
            f"Compile one with rs3vision-tools/compile_font.py."
        )
    mtime = p.stat().st_mtime
    key = str(p)
    cached = _FONT_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    font = rv.ocr.load_font(str(p))
    _FONT_CACHE[key] = (mtime, font)
    return font


def _hex_to_bgr(hex_rgb: int) -> Tuple[int, int, int]:
    if hex_rgb is None:
        return (255, 255, 255)
    r = (hex_rgb >> 16) & 0xFF
    g = (hex_rgb >> 8) & 0xFF
    b = hex_rgb & 0xFF
    return (b, g, r)


def _parse_roi(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        parts = [int(x.strip()) for x in s.split(",")]
    except ValueError:
        return None
    return tuple(parts) if len(parts) == 4 else None
