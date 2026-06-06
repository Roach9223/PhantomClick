"""Bitmap (template) matching blocks — backed by
`rs3vision_studio.algorithms.bitmap`.

Give it a reference PNG of what you're looking for and a tolerance; it
reports every position in the frame where the PNG appears within that
tolerance. Good for UI sprites, recognisable game icons, etc.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ...algorithms import bitmap as _bmp

from .base import Block, Param, Port


def _list_bitmap_templates() -> list:
    """List .png files in templates/bitmap/ for the dropdown."""
    pkg_root = Path(__file__).resolve().parent.parent.parent.parent
    folder = pkg_root / "templates" / "bitmap"
    if not folder.exists():
        return []
    return sorted(
        p.name for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() == ".png"
    )


# ─────────────────────────────────────────────────────────────────
# BITMAP CACHE — loads PNGs once per (path, mtime).
# ─────────────────────────────────────────────────────────────────

_BMP_CACHE: Dict[str, tuple] = {}  # path → (mtime, ndarray)


def _cached_bitmap(path_spec: str):
    if not path_spec:
        return None
    p = Path(path_spec)
    if not p.is_absolute():
        # Relative → look in the Studio's templates/bitmap dir first.
        pkg_root = Path(__file__).resolve().parent.parent.parent.parent
        local = pkg_root / "templates" / "bitmap" / path_spec
        if local.exists():
            p = local
    p = p.resolve()
    if not p.exists():
        raise FileNotFoundError(f"bitmap not found: {path_spec!r} (looked at {p})")
    mtime = p.stat().st_mtime
    key = str(p)
    cached = _BMP_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    img = _bmp.load_png(p)
    _BMP_CACHE[key] = (mtime, img)
    return img


# ─────────────────────────────────────────────────────────────────
# Block
# ─────────────────────────────────────────────────────────────────


class FindBitmapBlock(Block):
    identifier = "bitmap.find"
    name = "Find Bitmap"
    category = "Bitmap"
    description = (
        "Find a reference PNG template in the current frame. Returns the "
        "top-left pixel of the best match plus a confidence in [0, 1]. "
        "Uses a CTS1 anchor prefilter so it's fast on 4K scenes."
    )
    example = (
        "Save a sprite: visualizer → drag around it → 💾 Save ROI as bitmap. "
        "Set bitmap_path to the filename. tolerance=5 for crisp UI, 10–15 "
        "for mild AA. `point` output is the match's CENTRE, ready to click."
    )
    color = (90, 70, 120)

    inputs = [
        Port("frame", kind="data"),
        Port("trigger", kind="trigger"),
    ]
    outputs = [
        Port("point", kind="data"),     # (x, y) or None
        Port("confidence", kind="data"),
        Port("found", kind="data"),     # bool
        Port("matches", kind="data"),   # list of (x, y, confidence)
        Port("done", kind="trigger"),
    ]
    params = [
        Param(
            "bitmap_path",
            default="",
            kind="choice",
            choices_provider=_list_bitmap_templates,
            description=(
                "PNG template from rs3vision-studio/templates/bitmap/. "
                "Save new ones from the visualizer with Save-ROI-as-Bitmap "
                "(restart Studio to refresh the dropdown)."
            ),
        ),
        Param(
            "tolerance",
            default=5,
            kind="int",
            description=(
                "Per-channel max pixel difference (0 = exact, 10-15 for "
                "mild anti-aliasing, higher for lossy scenes)."
            ),
        ),
        Param(
            "roi",
            default="",
            kind="text",
            description="Optional ROI. Blank → uses Studio default ROI.",
        ),
        Param("max_matches", default=10, kind="int"),
    ]

    def execute(
        self, ctx, frame=None, bitmap_path: str = "", tolerance: int = 5,
        roi: str = "", max_matches: int = 10, **_: Any,
    ) -> Dict[str, Any]:
        if frame is None:
            return {
                "point": None, "confidence": 0.0, "found": False,
                "matches": [], "done": True,
            }
        if not bitmap_path:
            ctx.log(
                "bitmap.find: bitmap_path is empty. Save a PNG via the "
                "visualizer's 'Save ROI as bitmap' button and set this to "
                "its filename."
            )
            return {
                "point": None, "confidence": 0.0, "found": False,
                "matches": [], "done": True,
            }
        try:
            bitmap = _cached_bitmap(bitmap_path)
        except FileNotFoundError as e:
            ctx.log(f"bitmap.find: {e}")
            return {
                "point": None, "confidence": 0.0, "found": False,
                "matches": [], "done": True,
            }
        roi_tuple = ctx.resolve_roi(roi)

        matches = _bmp.find(
            frame,
            bitmap,
            tolerance=int(tolerance),
            roi=roi_tuple,
            max_matches=int(max_matches),
        )
        if not matches:
            return {
                "point": None, "confidence": 0.0, "found": False,
                "matches": [], "done": True,
            }
        # Sort best → worst.
        matches.sort(key=lambda m: m.confidence, reverse=True)
        best = matches[0]
        bh, bw = bitmap.shape[:2]
        # Return centre-point of the match so it's click-ready.
        cx = best.x + bw // 2
        cy = best.y + bh // 2
        return {
            "point": (cx, cy),
            "confidence": float(best.confidence),
            "found": True,
            "matches": [(m.x, m.y, m.confidence) for m in matches],
            "done": True,
        }
