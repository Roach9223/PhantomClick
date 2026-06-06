"""Color blocks — thin wrappers around rs3vision's CTS primitives."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import rs3vision as rv

from .base import Block, Param, Port


class FindColorBlock(Block):
    identifier = "color.find"
    name = "Find Color"
    category = "Color"
    description = (
        "Scan a frame for a target color using CTS; returns the centroid of "
        "the largest matching cluster plus a 'found' boolean."
    )
    example = (
        "Click yellow UI elements: target=0xFFFF00, cts=2, tol=25, "
        "min_cluster_size=20. Wire `point` → Click's `point`, `found` → "
        "If/Else's `condition`."
    )
    color = (110, 100, 40)

    inputs = [
        Port("frame", kind="data"),
        Port("trigger", kind="trigger"),
    ]
    outputs = [
        Port("point", kind="data"),    # (x, y) or None
        Port("count", kind="data"),    # int pixel count
        Port("found", kind="data"),    # bool
        Port("done", kind="trigger"),
    ]
    # NOTE: avoid NodeGraphQt-reserved property names (color, name, pos,
    # type_, id, width, height, …). We use "target" for the target colour.
    params = [
        Param(
            "target",
            default="0xFFFF00",
            kind="color_hex",
            description="Target color as 0xRRGGBB hex.",
        ),
        Param(
            "cts",
            default="2",
            kind="choice",
            choices=["1", "2", "3"],
            description="CTS mode. 2 = HSL (best for antialiased text).",
        ),
        Param(
            "tol",
            default=20.0,
            kind="float",
            description="Tolerance (higher = more permissive).",
        ),
        Param(
            "roi",
            default="",
            kind="text",
            description="Optional ROI as x,y,w,h (blank = whole frame).",
        ),
        Param(
            "cluster_dist",
            default=4,
            kind="int",
            description="Chebyshev distance for merging pixel clusters.",
        ),
        Param(
            "min_cluster_size",
            default=5,
            kind="int",
            description="Ignore clusters smaller than this many pixels.",
        ),
    ]

    def execute(
        self,
        ctx,
        frame=None,
        target: Optional[int] = None,
        cts: Any = 2,
        tol: float = 20.0,
        roi: str = "",
        cluster_dist: int = 4,
        min_cluster_size: int = 5,
        **_: Any,
    ) -> Dict[str, Any]:
        if frame is None:
            return {"point": None, "count": 0, "found": False, "done": True}
        target_bgr = _hex_to_bgr(target) if target is not None else (0, 255, 255)
        cts_int = int(cts) if not isinstance(cts, int) else cts

        roi_tuple = ctx.resolve_roi(roi)
        hits = rv.color.find(
            frame, target_bgr, cts=cts_int, tol=float(tol), roi=roi_tuple
        )
        # Cluster to find the largest blob.
        points = [(x, y) for x, y, _ in hits]
        clusters = rv.tpa.cluster(points, dist=int(cluster_dist)) if points else []
        clusters = [c for c in clusters if len(c) >= int(min_cluster_size)]
        if not clusters:
            return {
                "point": None,
                "count": len(hits),
                "found": False,
                "done": True,
            }
        biggest = max(clusters, key=len)
        cx, cy = rv.tpa.centroid(biggest)
        return {
            "point": (int(round(cx)), int(round(cy))),
            "count": len(hits),
            "found": True,
            "done": True,
        }


class CountColorBlock(Block):
    identifier = "color.count"
    name = "Count Color"
    category = "Color"
    description = "Count how many pixels match the target color (fast CTS scan)."
    color = (110, 100, 40)

    inputs = [
        Port("frame", kind="data"),
        Port("trigger", kind="trigger"),
    ]
    outputs = [
        Port("count", kind="data"),       # int
        Port("confidence", kind="data"),  # float
        Port("done", kind="trigger"),
    ]
    params = [
        Param("target", default="0xFFFF00", kind="color_hex"),
        Param("cts", default="2", kind="choice", choices=["1", "2", "3"]),
        Param("tol", default=20.0, kind="float"),
        Param(
            "roi", default="", kind="text",
            description="Optional ROI as x,y,w,h (blank = whole frame).",
        ),
    ]

    def execute(
        self, ctx, frame=None, target: Optional[int] = None,
        cts: Any = 2, tol: float = 20.0, roi: str = "", **_: Any,
    ) -> Dict[str, Any]:
        if frame is None:
            return {"count": 0, "confidence": 0.0, "done": True}
        target_bgr = _hex_to_bgr(target) if target is not None else (0, 255, 255)
        roi_tuple = ctx.resolve_roi(roi)
        count, conf = rv.color.count(
            frame, target_bgr, cts=int(cts), tol=float(tol), roi=roi_tuple
        )
        return {"count": int(count), "confidence": float(conf), "done": True}


class FindAllColorsBlock(Block):
    identifier = "color.find_all"
    name = "Find All Clusters"
    category = "Color"
    description = (
        "Like Find Color but returns EVERY cluster that passed the size "
        "filter, sorted by size (biggest first)."
    )
    color = (110, 100, 40)

    inputs = [
        Port("frame", kind="data"),
        Port("trigger", kind="trigger"),
    ]
    outputs = [
        Port("clusters", kind="data"),    # list[list[(x, y)]]
        Port("count", kind="data"),       # int, total matched pixels
        Port("done", kind="trigger"),
    ]
    params = [
        Param("target", default="0xFFFF00", kind="color_hex"),
        Param("cts", default="2", kind="choice", choices=["1", "2", "3"]),
        Param("tol", default=20.0, kind="float"),
        Param("roi", default="", kind="text"),
        Param("cluster_dist", default=4, kind="int"),
        Param("min_cluster_size", default=5, kind="int"),
    ]

    def execute(
        self, ctx, frame=None, target: Optional[int] = None,
        cts: Any = 2, tol: float = 20.0, roi: str = "",
        cluster_dist: int = 4, min_cluster_size: int = 5, **_: Any,
    ) -> Dict[str, Any]:
        if frame is None:
            return {"clusters": [], "count": 0, "done": True}
        target_bgr = _hex_to_bgr(target) if target is not None else (0, 255, 255)
        roi_tuple = ctx.resolve_roi(roi)
        hits = rv.color.find(
            frame, target_bgr, cts=int(cts), tol=float(tol), roi=roi_tuple
        )
        points = [(x, y) for x, y, _ in hits]
        clusters = rv.tpa.cluster(points, dist=int(cluster_dist)) if points else []
        clusters = [c for c in clusters if len(c) >= int(min_cluster_size)]
        clusters.sort(key=len, reverse=True)
        return {
            "clusters": clusters,
            "count": len(hits),
            "done": True,
        }


def _hex_to_bgr(hex_rgb: int) -> Tuple[int, int, int]:
    if hex_rgb is None:
        return (0, 255, 255)
    r = (hex_rgb >> 16) & 0xFF
    g = (hex_rgb >> 8) & 0xFF
    b = hex_rgb & 0xFF
    return (b, g, r)


def _parse_roi(s: str) -> Optional[Tuple[int, int, int, int]]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        parts = [int(p.strip()) for p in s.split(",")]
    except ValueError:
        return None
    if len(parts) != 4:
        return None
    return tuple(parts)  # type: ignore[return-value]
