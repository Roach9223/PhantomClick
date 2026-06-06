"""Aimless mouse drift between clicks.

When enabled, the cursor occasionally makes a short nearby move (no click)
during the wait window between clicks, to mimic a bored human shifting their
grip. Each drift picks a speed category (fast flick / medium glide / slow
lazy arc) and a matching curvature. Slow drifts often pass through an
intermediate waypoint for crescent / S-curve shapes.

Targets (and intermediate waypoints) are clamped to an expanded AABB around
the active zone so drifts never wander into the taskbar or adjacent windows.
"""

from __future__ import annotations

import math
import random
import threading
import time
from typing import Optional

from pynput.mouse import Controller

from . import dpi_cursor, humanizer

_mouse = Controller()


def _screen_bounds() -> tuple[int, int, int, int]:
    """Primary-monitor bounds, used as the fallback when no explicit
    target was passed in. Multi-monitor support comes from the caller
    threading bounds through ``wander(... screen_bounds=...)``."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        return (0, 0, w, h)
    except Exception:
        return (0, 0, 1920, 1080)


def _allowed_bounds(zone, padding: int,
                    screen_bounds: Optional[tuple[int, int, int, int]] = None,
                    ) -> tuple[int, int, int, int]:
    sb = screen_bounds if screen_bounds is not None else _screen_bounds()
    if zone is not None:
        zx1, zy1, zx2, zy2 = zone.aabb()
        bx1 = zx1 - padding
        by1 = zy1 - padding
        bx2 = zx2 + padding
        by2 = zy2 + padding
    else:
        bx1, by1, bx2, by2 = sb
    sx1, sy1, sx2, sy2 = sb
    return (max(bx1, sx1), max(by1, sy1), min(bx2, sx2), min(by2, sy2))


def _clamp(pt: tuple[float, float], bounds: tuple[int, int, int, int]) -> tuple[int, int]:
    # Margin matches humanizer.SAFE_MARGIN — keeps drifts strictly
    # outside the watchdog's 2-px corner zone (clicker.py::_watchdog_loop).
    m = humanizer.SAFE_MARGIN
    bx1, by1, bx2, by2 = bounds
    x = max(bx1 + m, min(bx2 - m, pt[0]))
    y = max(by1 + m, min(by2 - m, pt[1]))
    return (int(x), int(y))


def _pick_target(bounds: tuple[int, int, int, int]) -> tuple[int, int]:
    cx, cy = dpi_cursor.get_pos()
    dist = random.uniform(150, 300)
    angle = random.uniform(0, 2 * math.pi)
    tx = cx + dist * math.cos(angle)
    ty = cy + dist * math.sin(angle)
    return _clamp((tx, ty), bounds)


def wander(
    zone,
    padding: int,
    stop: Optional[threading.Event],
    fatigue: float = 1.0,
    screen_bounds: Optional[tuple[int, int, int, int]] = None,
) -> tuple[bool, float]:
    """Perform one aimless drift.

    ``screen_bounds`` is an optional ``(left, top, right, bottom)`` rect
    describing the monitor the engine should clamp drifts inside —
    threaded down from the Settings card's monitor selector so a multi-
    monitor user's drifts never leak across a bezel. When omitted, falls
    back to the primary-monitor heuristic.

    Returns (interrupted, elapsed_seconds) so the caller's wait-loop can
    deduct the actual time consumed (drifts now vary from ~0.08 s to ~1.6 s).
    """
    t0 = time.monotonic()
    bounds = _allowed_bounds(zone, padding, screen_bounds)
    final = _pick_target(bounds)

    # Speed category — 25% fast / 50% medium / 25% slow.
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

    duration *= max(1.0, fatigue)

    if random.random() < two_seg_prob:
        # Pick an intermediate waypoint offset perpendicular to the direct line.
        cx, cy = dpi_cursor.get_pos()
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

            if humanizer.drift(inter, stop, d1, c1):
                return True, time.monotonic() - t0
            if humanizer.drift(final, stop, d2, c2):
                return True, time.monotonic() - t0
            return False, time.monotonic() - t0

    interrupted = humanizer.drift(final, stop, duration, curvature)
    return interrupted, time.monotonic() - t0
