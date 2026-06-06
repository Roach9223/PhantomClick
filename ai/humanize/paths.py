"""Path generation + walking — Wind/Hooke particle sim and Bezier fallback.

Ported from PhantomClick's ``utils/humanizer.py``. The Wind/Hooke
algorithm models the cursor as a particle with:

- Gravity pulling it toward the target (magnitude ``gravity``).
- Wind gusts randomising its sideways velocity; gusts calm down as the
  target approaches so the landing is smooth.
- Velocity damping so the particle doesn't oscillate wildly.
- A per-step speed clamp so the cursor doesn't teleport.

A Bezier fallback is kept for A/B tuning comparisons; the
:class:`HumanizerConfig.bezier_fallback` flag flips between them.

All timing uses an injected :func:`sleep_interruptible` so the Studio's
``ctx.should_stop()`` flag kills a walk immediately (no waiting for the
path to finish).
"""

from __future__ import annotations

import math
import random
import time
from typing import Callable, List, Optional, Tuple

from .config import HumanizerConfig
from .mouse_api import MouseAPI


# Short alias for readability.
Point = Tuple[float, float]


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def _ease(t: float) -> float:
    """Symmetric ease-in-out curve: cosine-shaped, smooth endpoints."""
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))


def _sleep_interruptible(
    seconds: float, is_stopped: Optional[Callable[[], bool]]
) -> bool:
    """Sleep for ``seconds``, breaking early if ``is_stopped()`` becomes true.

    Returns True when the stop flag tripped — caller should bail.
    Polls every 20 ms, which is finer than any of our inter-click
    timings but cheap enough not to burn CPU.
    """
    if seconds <= 0:
        return bool(is_stopped and is_stopped())
    if is_stopped is None:
        time.sleep(seconds)
        return False
    end = time.monotonic() + seconds
    while True:
        if is_stopped():
            return True
        remaining = end - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.02, remaining))


# ─────────────────────────────────────────────────────────────────
# Path generators
# ─────────────────────────────────────────────────────────────────


def wind_path(start: Point, end: Point) -> List[Point]:
    """Wind/Hooke particle-sim path. Returns waypoints including the endpoint.

    The tuning constants below were inherited from PhantomClick and
    are deliberately not exposed as :class:`HumanizerConfig` fields —
    they describe the *shape* of the curve, not the *feel*. The feel
    is controlled by walk duration + jitter config.
    """
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    dist = math.hypot(dx, dy)
    if dist < 1.0:
        return [(ex, ey)]

    gravity = 7.0
    wind_strength = min(10.0, dist / 15.0)
    damping = 3.0
    max_step = max(3.0, dist / 20.0)

    x, y = sx, sy
    vx, vy = 0.0, 0.0
    wind_x, wind_y = 0.0, 0.0
    points: List[Point] = []
    sqrt5 = math.sqrt(5)
    damp_factor = 1.0 - damping / 50.0

    # Hard cap so a broken tuning doesn't spin forever.
    for _ in range(2000):
        remaining = math.hypot(ex - x, ey - y)
        if remaining < 1.0:
            break

        near = min(1.0, remaining / max(dist, 1.0))
        w = wind_strength * near
        wind_x = wind_x / sqrt5 + (random.random() * 2 - 1) * w / sqrt5
        wind_y = wind_y / sqrt5 + (random.random() * 2 - 1) * w / sqrt5

        gx = gravity * (ex - x) / remaining
        gy = gravity * (ey - y) / remaining

        vx += gx + wind_x
        vy += gy + wind_y
        vx *= damp_factor
        vy *= damp_factor

        speed = math.hypot(vx, vy)
        if speed > max_step:
            vx = vx / speed * max_step
            vy = vy / speed * max_step

        x += vx
        y += vy
        points.append((x, y))

    points.append((ex, ey))
    return points


def bezier_path(start: Point, end: Point) -> List[Point]:
    """Cubic Bezier with two perpendicular control-point offsets.

    Simpler path shape; useful as an A/B baseline while tuning.
    """
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    dist = max(1.0, math.hypot(dx, dy))
    perp_x, perp_y = -dy / dist, dx / dist
    off1 = random.uniform(-0.15, 0.15) * dist
    off2 = random.uniform(-0.15, 0.15) * dist
    c1 = (sx + dx * 0.33 + perp_x * off1, sy + dy * 0.33 + perp_y * off1)
    c2 = (sx + dx * 0.66 + perp_x * off2, sy + dy * 0.66 + perp_y * off2)
    steps = max(15, int(dist / 6))
    pts: List[Point] = []
    for i in range(1, steps + 1):
        t = i / steps
        it = 1 - t
        x = it**3 * sx + 3 * it**2 * t * c1[0] + 3 * it * t**2 * c2[0] + t**3 * ex
        y = it**3 * sy + 3 * it**2 * t * c1[1] + 3 * it * t**2 * c2[1] + t**3 * ey
        pts.append((x, y))
    return pts


# ─────────────────────────────────────────────────────────────────
# Walker
# ─────────────────────────────────────────────────────────────────


def walk(
    mouse: MouseAPI,
    points: List[Point],
    duration: float,
    cfg: HumanizerConfig,
    is_stopped: Optional[Callable[[], bool]] = None,
) -> bool:
    """Walk the cursor along ``points`` over ``duration`` seconds.

    Applies ease-in-out progress and ±``path_jitter_px`` wobble on each
    waypoint. Returns True if interrupted mid-walk.
    """
    if not points:
        return False
    n = len(points)
    t0 = time.monotonic()
    last_idx = -1
    while True:
        elapsed = time.monotonic() - t0
        progress = elapsed / duration if duration > 0 else 1.0
        if progress >= 1.0:
            break
        eased = _ease(progress)
        idx = min(n - 1, int(eased * n))
        if idx != last_idx:
            px, py = points[idx]
            jx = random.uniform(-cfg.path_jitter_px, cfg.path_jitter_px)
            jy = random.uniform(-cfg.path_jitter_px, cfg.path_jitter_px)
            mouse.set_position(int(round(px + jx)), int(round(py + jy)))
            last_idx = idx
        step = random.uniform(cfg.step_cadence_lo_s, cfg.step_cadence_hi_s)
        if _sleep_interruptible(step, is_stopped):
            return True
    # Snap to exact endpoint with no jitter — guarantees click lands on target.
    fx, fy = points[-1]
    mouse.set_position(int(round(fx)), int(round(fy)))
    return bool(is_stopped and is_stopped())


# ─────────────────────────────────────────────────────────────────
# High-level operations
# ─────────────────────────────────────────────────────────────────


def human_move(
    mouse: MouseAPI,
    end: Tuple[int, int],
    cfg: HumanizerConfig,
    fatigue_mult: float = 1.0,
    is_stopped: Optional[Callable[[], bool]] = None,
) -> bool:
    """Move cursor to ``end`` with humanized curve + optional overshoot.

    ``fatigue_mult`` scales both duration and overshoot probability.
    Returns True if interrupted.
    """
    start = mouse.get_position()
    sx, sy = float(start[0]), float(start[1])
    ex, ey = float(end[0]), float(end[1])
    dist = math.hypot(ex - sx, ey - sy)
    if dist < 1.0:
        return bool(is_stopped and is_stopped())

    base = cfg.move_base_s + min(cfg.move_max_extra_s, dist / 2500.0)
    duration = base * random.uniform(cfg.move_jitter_lo, cfg.move_jitter_hi) * fatigue_mult

    overshoot_prob = cfg.overshoot_probability + (fatigue_mult - 1.0) * 0.4
    do_overshoot = (
        cfg.overshoot_enabled
        and dist > 40
        and random.random() < overshoot_prob
    )

    path_fn = bezier_path if cfg.bezier_fallback else wind_path

    if do_overshoot:
        over = random.uniform(cfg.overshoot_min_px, cfg.overshoot_max_px)
        ux, uy = (ex - sx) / dist, (ey - sy) / dist
        overshoot_pt = (ex + ux * over, ey + uy * over)
        if walk(mouse, path_fn((sx, sy), overshoot_pt), duration, cfg, is_stopped):
            return True
        if _sleep_interruptible(
            random.uniform(cfg.overshoot_pause_lo_s, cfg.overshoot_pause_hi_s),
            is_stopped,
        ):
            return True
        cur = mouse.get_position()
        correct = path_fn((float(cur[0]), float(cur[1])), (ex, ey))
        return walk(
            mouse,
            correct,
            max(0.04, duration * cfg.overshoot_correction_scale),
            cfg,
            is_stopped,
        )
    return walk(mouse, path_fn((sx, sy), (ex, ey)), duration, cfg, is_stopped)


def human_drag(
    mouse: MouseAPI,
    start: Tuple[int, int],
    end: Tuple[int, int],
    cfg: HumanizerConfig,
    *,
    button: str = "middle",
    duration: Optional[float] = None,
    fatigue_mult: float = 1.0,
    is_stopped: Optional[Callable[[], bool]] = None,
) -> bool:
    """Press ``button``, walk from ``start`` to ``end``, release.

    Used for middle-click camera drags in RS3, but generic enough for
    any click-and-drag UI action. Honours the same humanizer config
    (path jitter, step cadence) as :func:`human_move`, so dragged
    movements feel the same as non-drag ones.

    Returns True if interrupted mid-drag.
    """
    import math
    import random as _r
    sx, sy = float(start[0]), float(start[1])
    ex, ey = float(end[0]), float(end[1])

    # Move to the start first (humanized).
    if human_move(mouse, (int(sx), int(sy)), cfg, fatigue_mult, is_stopped):
        return True

    # Brief settle pause before press (mimics human grip).
    if _sleep_interruptible(
        _r.uniform(cfg.pre_click_pause_lo_s, cfg.pre_click_pause_hi_s) * fatigue_mult,
        is_stopped,
    ):
        return True

    mouse.press(button)
    try:
        dist = math.hypot(ex - sx, ey - sy)
        if duration is None:
            base = cfg.move_base_s + min(cfg.move_max_extra_s, dist / 2500.0)
            duration = base * _r.uniform(cfg.move_jitter_lo, cfg.move_jitter_hi) * fatigue_mult
        path_fn = bezier_path if cfg.bezier_fallback else wind_path
        points = path_fn((sx, sy), (ex, ey))
        if walk(mouse, points, duration, cfg, is_stopped):
            return True
        # Small pause after landing, before release.
        if _sleep_interruptible(
            _r.uniform(0.030, 0.080) * fatigue_mult, is_stopped
        ):
            return True
    finally:
        mouse.release(button)
    return False


def human_click(
    mouse: MouseAPI,
    button: str,
    cfg: HumanizerConfig,
    fatigue_mult: float = 1.0,
    mode: str = "single",
    is_stopped: Optional[Callable[[], bool]] = None,
) -> bool:
    """Perform a click at the cursor's current position.

    Separate from :func:`human_move` so callers can compose
    "move then click" with optional delays in between. Returns True
    if interrupted.
    """
    if _sleep_interruptible(
        random.uniform(cfg.pre_click_pause_lo_s, cfg.pre_click_pause_hi_s) * fatigue_mult,
        is_stopped,
    ):
        return True

    def _one() -> bool:
        mouse.press(button)
        hold = random.uniform(cfg.click_hold_lo_s, cfg.click_hold_hi_s) * fatigue_mult
        stopped = _sleep_interruptible(hold, is_stopped)
        mouse.release(button)
        return stopped

    if _one():
        return True
    if mode == "double":
        if _sleep_interruptible(
            random.uniform(cfg.double_click_gap_lo_s, cfg.double_click_gap_hi_s),
            is_stopped,
        ):
            return True
        if _one():
            return True
    return False
