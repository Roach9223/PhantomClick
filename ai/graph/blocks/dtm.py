"""DTM — Deformable Template Matching blocks.

A DTM template is a handful of coloured points in a rigid relative
layout, loaded from a YAML file. The matcher looks for patterns in a
frame that fit that layout within the per-point tolerances. Much more
robust than single-colour matching for UI elements that share a colour
with the background.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ...algorithms import dtm as _dtm

from .base import Block, Param, Port


def _list_dtm_templates() -> list:
    """List .yaml/.yml files in templates/dtm/ for the dropdown."""
    pkg_root = Path(__file__).resolve().parent.parent.parent.parent
    folder = pkg_root / "templates" / "dtm"
    if not folder.exists():
        return []
    return sorted(
        p.name for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in (".yaml", ".yml")
    )


# ─────────────────────────────────────────────────────────────────
# Template cache
# ─────────────────────────────────────────────────────────────────

_TPL_CACHE: Dict[str, tuple] = {}  # path → (mtime, Template)


def _cached_template(path_spec: str):
    if not path_spec:
        return None
    p = Path(path_spec)
    if not p.is_absolute():
        pkg_root = Path(__file__).resolve().parent.parent.parent.parent
        local = pkg_root / "templates" / "dtm" / path_spec
        if local.exists():
            p = local
    p = p.resolve()
    if not p.exists():
        raise FileNotFoundError(f"DTM template not found: {path_spec!r} (looked at {p})")
    mtime = p.stat().st_mtime
    key = str(p)
    cached = _TPL_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    tpl = _dtm.load(p)
    _TPL_CACHE[key] = (mtime, tpl)
    return tpl


# ─────────────────────────────────────────────────────────────────
# Block
# ─────────────────────────────────────────────────────────────────


class FindDtmBlock(Block):
    identifier = "dtm.find"
    name = "Find DTM"
    category = "DTM"
    description = (
        "Find every position where a DTM template matches. A DTM "
        "template is a handful of coloured points arranged in a rigid "
        "layout — far more robust than single-colour matching for UI "
        "elements. Create templates from the visualizer with the "
        "'Create DTM from ROI' button."
    )
    example = (
        "Make a template: visualizer → drag around the UI element → "
        "🎯 Create DTM from ROI. Set template_path to its .yaml filename. "
        "Open the YAML to tune tolerances — tight anchor (cts=1, tol≤8), "
        "looser secondary points (cts=2, tol=10–15)."
    )
    color = (80, 60, 120)

    inputs = [
        Port("frame", kind="data"),
        Port("trigger", kind="trigger"),
    ]
    outputs = [
        Port("point", kind="data"),       # best anchor position or None
        Port("confidence", kind="data"),
        Port("found", kind="data"),
        Port("matches", kind="data"),     # list of (x, y, confidence)
        Port("done", kind="trigger"),
    ]
    params = [
        Param(
            "template_path",
            default="",
            kind="choice",
            choices_provider=_list_dtm_templates,
            description=(
                "DTM template file from rs3vision-studio/templates/dtm/. "
                "Use the visualizer's 'Create DTM from ROI' button to "
                "add new ones (restart Studio to refresh the dropdown)."
            ),
        ),
        Param(
            "roi",
            default="",
            kind="text",
            description="Optional ROI. Blank → uses Studio default ROI.",
        ),
        Param("max_matches", default=5, kind="int"),
        Param(
            "cluster_dist",
            default=4,
            kind="int",
            description="Merge anchor hits closer than this many pixels.",
        ),
    ]

    def execute(
        self, ctx, frame=None, template_path: str = "", roi: str = "",
        max_matches: int = 5, cluster_dist: int = 4, **_: Any,
    ) -> Dict[str, Any]:
        if frame is None:
            return {
                "point": None, "confidence": 0.0, "found": False,
                "matches": [], "done": True,
            }
        if not template_path:
            ctx.log(
                "dtm.find: template_path is empty. Build one via the "
                "visualizer's 'Create DTM from ROI' button, then set "
                "this to its filename (e.g. 'anvil.yaml')."
            )
            return {
                "point": None, "confidence": 0.0, "found": False,
                "matches": [], "done": True,
            }
        try:
            tpl = _cached_template(template_path)
        except FileNotFoundError as e:
            ctx.log(f"dtm.find: {e}")
            return {
                "point": None, "confidence": 0.0, "found": False,
                "matches": [], "done": True,
            }
        roi_tuple = ctx.resolve_roi(roi)
        matches = _dtm.find(
            frame,
            tpl,
            roi=roi_tuple,
            max_matches=int(max_matches),
            cluster_dist=int(cluster_dist),
        )
        if not matches:
            return {
                "point": None, "confidence": 0.0, "found": False,
                "matches": [], "done": True,
            }
        matches.sort(key=lambda m: m.confidence, reverse=True)
        best = matches[0]
        return {
            "point": (best.x, best.y),
            "confidence": float(best.confidence),
            "found": True,
            "matches": [(m.x, m.y, m.confidence) for m in matches],
            "done": True,
        }
