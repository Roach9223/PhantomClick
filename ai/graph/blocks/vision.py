"""Vision blocks: screen capture."""

from __future__ import annotations

from typing import Any, Dict

import numpy as np

from .base import Block, Param, Port


class CaptureBlock(Block):
    identifier = "vision.capture"
    name = "Capture Screen"
    category = "Vision"
    description = "Grab a screenshot of the selected monitor (BGR numpy array)."
    example = (
        "Leave monitor_override blank to use the Studio's Target Monitor "
        "dropdown. Wire the `frame` output to any color/OCR/bitmap/DTM "
        "block's `frame` input."
    )
    color = (40, 80, 110)

    inputs = [Port("trigger", kind="trigger")]
    outputs = [
        Port("frame", kind="data"),
        Port("done", kind="trigger"),
    ]
    params = [
        Param(
            "monitor_override",
            default="",
            kind="text",
            description=(
                "Blank = use the Studio's Target Monitor setting. Advanced: "
                "put an mss index here (0 = all, 1 = primary, 2 = secondary…) "
                "to force this one capture block onto a different display."
            ),
        ),
    ]

    def execute(
        self, ctx, monitor_override: str = "", **_: Any
    ) -> Dict[str, Any]:
        override = str(monitor_override).strip()
        if override:
            try:
                monitor = int(override)
            except ValueError:
                ctx.log(
                    f"vision.capture: bad monitor_override {override!r}; "
                    f"using Studio default #{ctx.default_monitor} instead."
                )
                monitor = ctx.default_monitor
        else:
            monitor = ctx.default_monitor
        try:
            frame = ctx.capture(monitor=int(monitor))
        except Exception as e:
            ctx.log(
                f"vision.capture: grab failed ({type(e).__name__}: {e}). "
                "Script continues but no frame is emitted this tick."
            )
            return {"frame": None, "done": True}
        return {"frame": frame, "done": True}
