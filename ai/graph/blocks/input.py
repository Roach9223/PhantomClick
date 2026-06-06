"""Input blocks — click, move, type, keypress, auto-click. Uses the backend
declared in the script header (post_message | real)."""

from __future__ import annotations

import random
import time
from typing import Any, Dict, Optional, Tuple

from .base import Block, Param, Port


_INPUT_COLOR = (80, 50, 100)


class ClickBlock(Block):
    identifier = "input.click"
    name = "Click"
    category = "Input"
    description = "Move the cursor to a point and click (via the active input backend)."
    example = (
        "Most common wiring: Find Color's `point` → Click's `point`, "
        "If/Else's `true` trigger → Click's `trigger`. Enable the toolbar "
        "Dry-run toggle first to log clicks without firing them."
    )
    color = _INPUT_COLOR

    inputs = [
        Port("point", kind="data"),
        Port("trigger", kind="trigger"),
    ]
    outputs = [Port("done", kind="trigger")]
    params = [
        Param(
            "button",
            default="left",
            kind="choice",
            choices=["left", "right", "middle"],
            description="Mouse button.",
        ),
        Param(
            "phase",
            default="",
            kind="text",
            description=(
                "Optional phase label for the Dashboard chip — e.g. 'clicking', "
                "'excavating'. Leave blank to not change phase."
            ),
        ),
    ]

    def execute(
        self, ctx, point: Any = None, button: str = "left", phase: str = "", **_: Any
    ) -> Dict[str, Any]:
        if point is None:
            ctx.log("input.click: no point provided — skipped.")
            return {}
        x, y = int(point[0]), int(point[1])
        if getattr(ctx, "dry_run", False):
            ctx.log(f"🧪 [dry-run] would click {button} at ({x}, {y})")
            out: Dict[str, Any] = {"done": True}
            if phase:
                out["phase"] = phase
            return out
        try:
            ctx.input_backend.click(x, y, button=button)
        except NotImplementedError as e:
            ctx.log(f"input.click: backend not ready — {e}")
            ctx.request_stop("input backend not implemented")
            return {}
        ctx.log(f"click {button} at ({x}, {y})")
        out = {"done": True}
        if phase:
            out["phase"] = phase
        return out


class MoveToBlock(Block):
    identifier = "input.move_to"
    name = "Move Cursor"
    category = "Input"
    description = "Move the cursor to a point without clicking."
    color = _INPUT_COLOR

    inputs = [
        Port("point", kind="data"),
        Port("trigger", kind="trigger"),
    ]
    outputs = [Port("done", kind="trigger")]
    params = []

    def execute(self, ctx, point: Any = None, **_: Any) -> Dict[str, Any]:
        if point is None:
            ctx.log("input.move_to: no point provided — skipped.")
            return {}
        x, y = int(point[0]), int(point[1])
        if getattr(ctx, "dry_run", False):
            ctx.log(f"🧪 [dry-run] would move to ({x}, {y})")
            return {"done": True}
        try:
            ctx.input_backend.move(x, y)
        except NotImplementedError as e:
            ctx.log(f"input.move_to: backend not ready — {e}")
            ctx.request_stop("input backend not implemented")
            return {}
        return {"done": True}


class PressKeyBlock(Block):
    identifier = "input.press_key"
    name = "Press Key"
    category = "Input"
    description = "Press a single key (e.g. 'space', 'enter', 'a'). Uses active input backend."
    color = _INPUT_COLOR

    inputs = [Port("trigger", kind="trigger")]
    outputs = [Port("done", kind="trigger")]
    params = [
        Param(
            "key",
            default="space",
            kind="text",
            description="Key name per the backend (pyautogui conventions — 'space', 'enter', 'a'…).",
        ),
    ]

    def execute(self, ctx, key: str = "space", **_: Any) -> Dict[str, Any]:
        if getattr(ctx, "dry_run", False):
            ctx.log(f"🧪 [dry-run] would press key: {key!r}")
            return {"done": True}
        try:
            ctx.input_backend.press_key(key)
        except NotImplementedError as e:
            ctx.log(f"input.press_key: backend not ready — {e}")
            ctx.request_stop("input backend not implemented")
            return {}
        ctx.log(f"key press: {key!r}")
        return {"done": True}


# ─────────────────────────────────────────────────────────────────
# Auto-click — PhantomClick-style end-to-end one-node autoclicker
# ─────────────────────────────────────────────────────────────────


def _pick_zone_point(zone: Tuple[int, int, int, int], gaussian: bool) -> Tuple[int, int]:
    """Pick a point inside a zone rect ``(x, y, w, h)``.

    ``gaussian=True`` biases toward the zone centre (µ = centre,
    σ = w/6 or h/6 — keeps ~99.7% of draws inside the zone). Clamps
    to the zone boundary on the rare tail.
    """
    x, y, w, h = zone
    if w <= 0 or h <= 0:
        return int(x), int(y)
    if gaussian:
        cx = x + w / 2.0
        cy = y + h / 2.0
        sx = max(1.0, w / 6.0)
        sy = max(1.0, h / 6.0)
        px = int(round(max(x, min(x + w - 1, random.gauss(cx, sx)))))
        py = int(round(max(y, min(y + h - 1, random.gauss(cy, sy)))))
        return px, py
    return random.randint(int(x), int(x + w - 1)), random.randint(int(y), int(y + h - 1))


class AutoClickBlock(Block):
    identifier = "input.auto_click"
    name = "Auto-Click"
    category = "Input"
    description = (
        "Click repeatedly at a point (or random inside a zone) until a limit "
        "is hit. Uses the humanizer — Wind/Hooke paths, fatigue drift, "
        "anti-clustering, optional idle-wander drifts between clicks."
    )
    example = (
        "Minimum wiring: flow.on_start.trigger → input.auto_click.trigger, "
        "with ``mode=point`` + a literal point, or ``mode=zone`` + a zone "
        "rect. Pair with the Dry-run toggle for the first test."
    )
    color = _INPUT_COLOR

    inputs = [
        Port("point", kind="data"),    # required when mode=point
        Port("zone", kind="data"),     # required when mode=zone; [x, y, w, h]
        Port("trigger", kind="trigger"),
    ]
    outputs = [
        Port("clicks", kind="data"),   # int — clicks fired this execution
        Port("done", kind="trigger"),
    ]
    params = [
        Param(
            "mode",
            default="point",
            kind="choice",
            choices=["point", "zone"],
            description=(
                "point = click at the provided point every iteration. "
                "zone = pick a random point inside the provided zone rect "
                "[x, y, w, h] each iteration."
            ),
        ),
        Param(
            "interval_min_ms",
            default=400,
            kind="int",
            description="Minimum wait between clicks (milliseconds).",
        ),
        Param(
            "interval_max_ms",
            default=900,
            kind="int",
            description="Maximum wait between clicks (milliseconds).",
        ),
        Param(
            "duration_s",
            default=0,
            kind="int",
            description="Stop after this many seconds. 0 = until stopped / max_clicks hit.",
        ),
        Param(
            "max_clicks",
            default=0,
            kind="int",
            description="Stop after this many clicks. 0 = unlimited.",
        ),
        Param(
            "button",
            default="left",
            kind="choice",
            choices=["left", "right", "middle"],
            description="Mouse button.",
        ),
        Param(
            "idle_wander",
            default=True,
            kind="bool",
            description=(
                "Occasionally drift the cursor between clicks with no click "
                "(fast/medium/slow tiers). Requires the humanizer's real backend."
            ),
        ),
        Param(
            "idle_wander_prob",
            default=0.25,
            kind="float",
            description="Chance per wait window of performing an idle drift (0..1).",
        ),
        Param(
            "gaussian_zone_bias",
            default=True,
            kind="bool",
            description=(
                "For zone mode, bias click targets toward the zone centre using "
                "a Gaussian distribution (σ = dim/6). Off = uniform random."
            ),
        ),
        Param(
            "phase",
            default="autoclicking",
            kind="text",
            description="Phase label shown on the Dashboard chip during this block.",
        ),
    ]

    def execute(
        self,
        ctx,
        point: Any = None,
        zone: Any = None,
        mode: str = "point",
        interval_min_ms: int = 400,
        interval_max_ms: int = 900,
        duration_s: int = 0,
        max_clicks: int = 0,
        button: str = "left",
        idle_wander: bool = True,
        idle_wander_prob: float = 0.25,
        gaussian_zone_bias: bool = True,
        phase: str = "autoclicking",
        **_: Any,
    ) -> Dict[str, Any]:
        # Input validation up front — fail loud so a misconfigured block
        # doesn't quietly spin forever.
        interval_min_ms = max(1, int(interval_min_ms))
        interval_max_ms = max(interval_min_ms, int(interval_max_ms))
        duration_s = max(0, int(duration_s))
        max_clicks = max(0, int(max_clicks))

        zone_rect: Optional[Tuple[int, int, int, int]] = None
        if mode == "zone":
            if not (isinstance(zone, (list, tuple)) and len(zone) == 4):
                ctx.log(
                    "input.auto_click: mode=zone requires `zone` input to be "
                    "a 4-tuple [x, y, w, h]."
                )
                return {"clicks": 0}
            zone_rect = (int(zone[0]), int(zone[1]), int(zone[2]), int(zone[3]))
        else:  # mode == "point"
            if point is None:
                ctx.log("input.auto_click: mode=point requires `point` input.")
                return {"clicks": 0}

        dry_run = bool(getattr(ctx, "dry_run", False))
        backend = ctx.input_backend
        wander_fn = getattr(backend, "wander", None) if idle_wander else None

        start = time.monotonic()
        end = start + duration_s if duration_s > 0 else None

        ctx.log(
            f"▶ auto_click mode={mode} interval={interval_min_ms}-{interval_max_ms}ms "
            f"duration={duration_s}s max_clicks={max_clicks or '∞'} "
            f"idle_wander={idle_wander} dry_run={dry_run}"
        )

        clicks = 0
        while not ctx.should_stop():
            # Duration / max-clicks termination.
            if end is not None and time.monotonic() >= end:
                ctx.log(f"auto_click: duration reached after {clicks} click(s).")
                break
            if max_clicks > 0 and clicks >= max_clicks:
                ctx.log(f"auto_click: max_clicks={max_clicks} reached.")
                break

            # Pick the target.
            if mode == "zone":
                assert zone_rect is not None
                tx, ty = _pick_zone_point(zone_rect, gaussian_zone_bias)
            else:
                tx, ty = int(point[0]), int(point[1])

            # Fire.
            if dry_run:
                ctx.log(f"🧪 [dry-run] auto_click would click {button} at ({tx}, {ty})")
            else:
                try:
                    backend.click(tx, ty, button=button)
                except NotImplementedError as e:
                    ctx.log(f"auto_click: backend not ready — {e}")
                    ctx.request_stop("input backend not implemented")
                    return {"clicks": clicks}
            clicks += 1

            if ctx.should_stop():
                break

            # Inter-click wait, optionally consumed in part by an idle-wander.
            wait_s = random.uniform(interval_min_ms, interval_max_ms) / 1000.0
            if (
                wander_fn is not None
                and not dry_run
                and random.random() < idle_wander_prob
            ):
                try:
                    # `wander` burns ~0.08-1.6 s; whatever it consumed we don't
                    # need to wait further for, so no extra bookkeeping.
                    interrupted = wander_fn(zone=zone_rect, padding=30)
                    if interrupted:
                        break
                except Exception as e:
                    ctx.log(f"auto_click: idle-wander failed — {type(e).__name__}: {e}")
            # Regular sleep, sliced so Stop / Esc break through fast.
            deadline = time.monotonic() + wait_s
            while time.monotonic() < deadline:
                if ctx.should_stop():
                    break
                remaining = deadline - time.monotonic()
                time.sleep(min(0.05, remaining))

        ctx.log(f"■ auto_click finished: {clicks} click(s) fired.")
        out: Dict[str, Any] = {"clicks": clicks, "done": True}
        if phase:
            out["phase"] = phase
        return out
