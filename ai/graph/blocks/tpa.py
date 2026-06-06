"""Point-array blocks — thin wrappers over rs3vision's tpa primitives."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import rs3vision as rv

from .base import Block, Param, Port


_TPA_COLOR = (100, 70, 110)


class ClusterBlock(Block):
    identifier = "tpa.cluster"
    name = "Cluster Points"
    category = "TPA"
    description = "Group points into clusters by Chebyshev distance."
    color = _TPA_COLOR

    inputs = [
        Port("points", kind="data"),
        Port("trigger", kind="trigger"),
    ]
    outputs = [
        Port("clusters", kind="data"),
        Port("count", kind="data"),     # number of clusters
        Port("done", kind="trigger"),
    ]
    params = [
        Param("dist", default=4, kind="int", description="Max neighbour distance."),
    ]

    def execute(
        self, ctx, points=None, dist: int = 4, **_: Any
    ) -> Dict[str, Any]:
        pts: List[Tuple[int, int]] = list(points or [])
        clusters = rv.tpa.cluster(pts, dist=int(dist)) if pts else []
        return {"clusters": clusters, "count": len(clusters), "done": True}


class BoundsBlock(Block):
    identifier = "tpa.bounds"
    name = "Bounds"
    category = "TPA"
    description = "Compute the axis-aligned bounding rectangle of a point set."
    color = _TPA_COLOR

    inputs = [
        Port("points", kind="data"),
        Port("trigger", kind="trigger"),
    ]
    outputs = [
        Port("bbox", kind="data"),     # (x, y, w, h) or None
        Port("done", kind="trigger"),
    ]
    params = []

    def execute(self, ctx, points=None, **_: Any) -> Dict[str, Any]:
        if not points:
            return {"bbox": None, "done": True}
        bbox = rv.tpa.bounds(list(points))
        return {"bbox": bbox, "done": True}


class CentroidBlock(Block):
    identifier = "tpa.centroid"
    name = "Centroid"
    category = "TPA"
    description = "Compute the arithmetic centroid of a point set."
    color = _TPA_COLOR

    inputs = [
        Port("points", kind="data"),
        Port("trigger", kind="trigger"),
    ]
    outputs = [
        Port("point", kind="data"),    # (cx, cy) rounded to ints, or None
        Port("done", kind="trigger"),
    ]
    params = []

    def execute(self, ctx, points=None, **_: Any) -> Dict[str, Any]:
        if not points:
            return {"point": None, "done": True}
        c = rv.tpa.centroid(list(points))
        if c is None:
            return {"point": None, "done": True}
        cx, cy = c
        return {"point": (int(round(cx)), int(round(cy))), "done": True}


class FilterSizeBlock(Block):
    identifier = "tpa.filter_size"
    name = "Filter Cluster Size"
    category = "TPA"
    description = "Keep only clusters whose size is in [min, max] pixels."
    color = _TPA_COLOR

    inputs = [
        Port("clusters", kind="data"),
        Port("trigger", kind="trigger"),
    ]
    outputs = [
        Port("clusters", kind="data"),
        Port("done", kind="trigger"),
    ]
    params = [
        Param("min_size", default=5, kind="int"),
        Param("max_size", default=100000, kind="int"),
    ]

    def execute(
        self, ctx, clusters=None, min_size: int = 5, max_size: int = 100000, **_: Any
    ) -> Dict[str, Any]:
        cl = list(clusters or [])
        kept = rv.tpa.filter_size(cl, int(min_size), int(max_size))
        return {"clusters": kept, "done": True}
