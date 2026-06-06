"""Between-click aimless drift.

Ported from PhantomClick's ``utils/idle_wanderer.py``. When enabled,
the auto-clicker occasionally makes a short *no-click* drift during
the wait window between clicks — mimics a bored human shifting their
grip while waiting for a monster to die / a fire to start / etc.

Three speed tiers (25% fast flick / 50% medium glide / 25% slow lazy
arc). Slow drifts occasionally pass through an intermediate waypoint
offset perpendicular to the direct line, which produces crescent /
S-curve shapes rather than predictable single arcs.

Targets are clamped to an expanded AABB around the active zone so a
drift never wanders into the taskbar or an adjacent window.
"""

from __future__ import annotations

import math
import random
import time
from typing import Callable, Optional, Tuple

from .config import HumanizerConfig
from .mouse_api import MouseAPI
from .paths import _ease, _sleep_interruptible, bezier_path, walk
from .safeguards import _screen_bounds


def _allowed_bounds(
    zone: Optional[Tuple[int, int, int, int]], padding: int
) -> Tuple[int, int, int, int]:
    """Compute an AABB the drift must stay inside.

    ``zone`` is ``(x, y, w, h)`` in screen pixels or None (⇒ whole monitor).
    Drifts are clamped to this rect expanded by ``padding`` on each side,
    then intersected with the primary monitor's bounds so we never escape
    onto a virtual monitor edge.
    """
    screen = _screen_bounds() or (0, 0, 1920, 1080)
    sx, sy, sw, sh = screen
    sx1, sy1, sx2, sy2 = sx, sy, sx + sw, sy + sh
    if zone is not None:
        zx, zy, zw, zh = zone
        bx1 = zx - padding
        by1 = zy - padding
        bx2 = zx + zw + padding
        by2 = zy + zh + padding
    else:
        bx1, by1, bx2, by2 = sx1, sy1, sx2, sy2
    return (max(bx1, sx1), max(by1, sy1), min(bx2, sx2), min(by2, sy2))


def _clamp(pt: Tuple[float, float], bounds: Tuple[int, int, int, int]) -> Tuple[int, int]:
    bx1, by1, bx2, by2 = bounds
    x = max(bx1 + 2, min(bx2 - 2, pt[0]))
    y = max(by1 + 2, min(by2 - 2, pt[1]))
    return (int(x), int(y))


def _pick_target(
    mouse: MouseAPI, bounds: Tuple[int, int, int, int]
) -> Tuple[int, int]:
    """Pick a random point 150–300 px from the current cursor, clamped."""
    cx, cy = mouse.get_position()
    dist = random.uniform(150, 300)
    angle = random.uniform(0, 2 * math.pi)
    tx = cx + dist * math.cos(angle)
    ty = cy + dist * math.sin(angle)
    return _clamp((tx, ty), bounds)


# ─────────────────────────────────────────────────────────────────
# Drift — curved arc to target over `duration` seconds, no click
# ─────────────────────────────────────────────────────────────────


def _drift(
    mouse: MouseAPI,
    end: Tuple[int, int],
    duration: float,
    curvature: float,
    cfg: HumanizerConfig,
    is_stopped: Optional[Callable[[], bool]],
) -> bool:
    """Quadratic-Bezier smooth drift. Returns True if interrupted."""
    start = mouse.get_position()
    sx, sy = float(start[0]), float(start[1])
    ex, ey = float(end[0]), float(end[1])
    dx, dy = ex - sx, ey - sy
    dist = math.hypot(dx, dy)
    if dist < 1.0:
        return bool(is_stopped and is_stopped())

    # Control point offset perpendicular to the direct line.
    perp_x, perp_y = -dy / dist, dx / dist
    sign = random.choice([-1, 1])
    off_mag = curvature * dist * random.uniform(0.3, 0.7) * sign
    cx = sx + dx * 0.5 + perp_x * off_mag
    cy = sy + dy * 0.5 + perp_y * off_mag

    steps = max(20, int(dist / 4))
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        it = 1.0 - t
        x = it * it * sx + 2 * it * t * cx + t * t * ex
        y = it * it * sy + 2 * it * t * cy + t * t * ey
        pts.append((x, y))
    return walk(mouse, pts, max(0.02, duration), cfg, is_stopped)


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────


def wander(
    mouse: MouseAPI,
    zone: Optional[Tuple[int, int, int, int]],
    padding: int,
    cfg: HumanizerConfig,
    fatigue_mult: float = 1.0,
    is_stopped: Optional[Callable[[], bool]] = None,
) -> Tuple[bool, float]:
    """Perform one aimless drift.

    Returns ``(interrupted, elapsed_seconds)`` so the caller's wait-loop
    can deduct the actual time consumed. Drifts vary from ~80 ms to
    ~1.6 s depending on the speed tier roll.
    """
    t0 = time.monotonic()
    bounds = _allowed_bounds(zone, padding)
    final = _pick_target(mouse, bounds)

    # Speed tier — 25% fast / 50% medium / 25% slow.
    roll = random.random()
    if roll < 0.25:
        duration = random.uniform(0.08, 0.20)
        curvature = random.uniform(0.0, 0.2)
        two_seg_prob = 0.0
    elif roll < 0.75:
        duration = random.uniform(0.30, 0.75)
        curvature = random.uniform(0.2, 0.5)
        two_seg_prob = 0.15
    else:
        duration = random.uniform(0.80, 1.60)
        curvature = random.uniform(0.4, 0.9)
        two_seg_prob = 0.45

    duration *= max(1.0, fatigue_mult)

    if random.random() < two_seg_prob:
        # S-curve: pick an intermediate waypoint perpendicular to the direct line.
        cx, cy = mouse.get_position()
        dx, dy = final[0] - cx, final[1] - cy
        dist = math.hypot(dx, dy)
        if dist > 10:
            perp_x, perp_y = -dy / dist, dx / dist
            sign = random.choice([-1, 1])
            off = random.uniform(0.20, 0.50) * dist * sign
            mx = (cx + final[0]) / 2 + perp_x * off
            my = (cy + final[1]) / 2 + perp_y * off
            inter = _clamp((mx, my), bounds)

            d1 = duration * random.uniform(0.4, 0.6)
            d2 = max(0.08, duration - d1)
            c1 = curvature * random.uniform(0.7, 1.0)
            c2 = curvature * random.uniform(0.7, 1.0)
            if _drift(mouse, inter, d1, c1, cfg, is_stopped):
                return True, time.monotonic() - t0
            if _drift(mouse, final, d2, c2, cfg, is_stopped):
                return True, time.monotonic() - t0
            return False, time.monotonic() - t0

    interrupted = _drift(mouse, final, duration, curvature, cfg, is_stopped)
    return interrupted, time.monotonic() - t0
