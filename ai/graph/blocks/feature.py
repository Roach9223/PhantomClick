"""Frame-delta / change-detection blocks."""

from __future__ import annotations

from typing import Any, Dict

import rs3vision as rv

from .base import Block, Param, Port


class DiffBlock(Block):
    identifier = "feature.diff"
    name = "Frame Diff"
    category = "Feature"
    description = (
        "Compare two frames by 8×8 tile byte-equality. Outputs a list of "
        "changed rectangles + an FNV-1a hash of the current frame."
    )
    color = (40, 100, 100)

    inputs = [
        Port("prev", kind="data"),
        Port("curr", kind="data"),
        Port("trigger", kind="trigger"),
    ]
    outputs = [
        Port("changed", kind="data"),   # list of (x, y, w, h)
        Port("hash", kind="data"),      # int
        Port("any_change", kind="data"),  # bool — shortcut for if_else
        Port("done", kind="trigger"),
    ]
    params = [
        Param("tile", default=8, kind="int", description="Tile size in pixels."),
    ]

    def execute(
        self, ctx, prev=None, curr=None, tile: int = 8, **_: Any
    ) -> Dict[str, Any]:
        if prev is None or curr is None:
            return {"changed": [], "hash": 0, "any_change": False, "done": True}
        try:
            changed, h = rv.feature.diff(prev, curr, tile=int(tile))
        except ValueError as e:
            ctx.log(f"feature.diff: {e}")
            return {"changed": [], "hash": 0, "any_change": False, "done": True}
        return {
            "changed": list(changed),
            "hash": int(h),
            "any_change": bool(changed),
            "done": True,
        }
