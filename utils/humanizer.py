"""Human-like mouse movement and clicking.

Path generation uses a Wind/Hooke algorithm: a virtual particle pulled
toward the target by a spring-like "gravity" force while being buffeted
by randomized "wind" gusts. Much more organic wobble than fixed-control-
point Bezier curves. A Bezier fallback is kept for tuning comparisons.
"""

from __future__ import annotations

import math
import random
import threading
import time
from typing import Optional

from pynput.mouse import Button, Controller

from . import dpi_cursor, mouse_trace

_mouse = Controller()

USE_WIND = True  # flip to False to A/B test against Bezier fallback

# Watchdog corner-stop fires when cursor lands in any of the four 3x3
# corner zones (modules/clicker.py::_watchdog_loop:435 — `x<=bx+2 AND
# y<=by+2` etc.). We only need to nudge cursor positions OUT of those
# corner zones — every other position (including edge positions like
# y=0 with x=500) is fine and must be left untouched, otherwise zones
# near the screen edge lose accuracy. SAFE_MARGIN sits 1 px outside the
# watchdog's threshold so the absolute final pixel after sway/tremor
# never lands on the trigger boundary.
SAFE_MARGIN = 4  # exposed for callers that need a literal margin (e.g. clicker.py)
_CORNER_THRESHOLD = 2  # matches watchdog
_CORNER_PUSH = 3       # 1 px past the watchdog boundary
_safe_bounds: Optional[tuple[int, int, int, int]] = None  # (x1, y1, x2, y2)


def set_safe_bounds(bounds: Optional[tuple[int, int, int, int]]) -> None:
    """Engine pushes ``(bx, by, bw, bh)`` (left, top, width, height) **in
    DIPs** to define the safe rect. Stored as physical pixels so the
    ``_clamp_to_safe`` comparison (which receives physical-pixel inputs
    from :func:`drift` / :func:`move` after :func:`dpi_cursor.dip_to_physical`)
    is in matching coordinate space.

    On a non-100%-scaled monitor, conflating DIPs and physical px makes the
    clamp shrink the usable area by the scale factor — e.g. on a 150%
    monitor the cursor would never reach the right ~33% of the screen.

    Pass ``None`` to clear (no clamping)."""
    global _safe_bounds
    if bounds is None:
        _safe_bounds = None
        return
    bx, by, bw, bh = bounds
    if bw <= 0 or bh <= 0:
        _safe_bounds = None
        return
    # Convert each corner DIP→physical. Using both corners (rather than a
    # uniform DPR multiply) handles multi-monitor where the rect spans
    # screens with different DPRs — though in practice the engine only
    # passes single-screen rects.
    px1, py1 = dpi_cursor.dip_to_physical(int(bx), int(by))
    px2, py2 = dpi_cursor.dip_to_physical(int(bx + bw), int(by + bh))
    _safe_bounds = (int(px1), int(py1), int(px2), int(py2))


def _clamp_to_safe(x: float, y: float) -> tuple[float, float]:
    """Push (x, y) out of any active corner zone, leaving non-corner
    positions unchanged. The clamp is intentionally narrow — only the
    four 3×3 corner squares are restricted. Edge positions (like y=0
    with x=500) are unaffected so click zones drawn near a screen edge
    keep their full usable area."""
    if _safe_bounds is None:
        return (x, y)
    bx1, by1, bx2, by2 = _safe_bounds
    near_left = x <= bx1 + _CORNER_THRESHOLD
    near_right = x >= bx2 - _CORNER_THRESHOLD
    near_top = y <= by1 + _CORNER_THRESHOLD
    near_bottom = y >= by2 - _CORNER_THRESHOLD
    in_corner = (near_left or near_right) and (near_top or near_bottom)
    if not in_corner:
        return (x, y)
    nx = x
    ny = y
    if near_left:
        nx = bx1 + _CORNER_PUSH
    elif near_right:
        nx = bx2 - _CORNER_PUSH
    if near_top:
        ny = by1 + _CORNER_PUSH
    elif near_bottom:
        ny = by2 - _CORNER_PUSH
    return (nx, ny)


def _sleep(stop: Optional[threading.Event], seconds: float) -> bool:
    """Interruptible sleep. Returns True if stop was set (caller should bail)."""
    if seconds <= 0:
        return bool(stop and stop.is_set())
    if stop is None:
        time.sleep(seconds)
        return False
    return stop.wait(seconds)


def _ease(t: float) -> float:
    """Asymmetric human-reach profile: fast accel, long decel.

    Peak velocity around t=0.30 (matches Fitts-law reaching motion).
    Quadratic ease-in to t=0.30, cubic ease-out for the long approach.
    """
    t = max(0.0, min(1.0, t))
    if t < 0.30:
        return (t / 0.30) ** 2 * 0.18
    u = (t - 0.30) / 0.70
    return 0.18 + (1.0 - 0.18) * (1.0 - (1.0 - u) ** 3)


def _wind_path(start: tuple[float, float], end: tuple[float, float]) -> list[tuple[float, float]]:
    """Generate a Wind/Hooke path from start to end.

    Returns a list of (x, y) waypoints the caller will walk through with timing.
    The particle accelerates toward end (gravity) while wind pushes it sideways.
    Damping prevents runaway oscillation. When close, wind and gravity scale
    down so the last few pixels are smooth.
    """
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    dist = math.hypot(dx, dy)
    if dist < 1.0:
        return [(ex, ey)]

    # Tuned empirically — these feel "human" in side-by-side comparisons.
    gravity = 7.0
    wind_strength = min(10.0, dist / 15.0)
    damping = 3.0
    # Cap step at 60 px/frame so the cursor can't blow past the target
    # in a single render frame on long cross-screen moves. With ~16 ms
    # walk cadence that's still ~3750 px/sec — plenty fast for a
    # deliberate human reach without producing the bouncing overshoot
    # the unbounded version did.
    max_step = max(3.0, min(60.0, dist / 20.0))
    # Last `proximity_zone` px before the target gets progressively
    # heavier damping so velocity collapses before the cursor arrives.
    # Without this, equilibrium velocity (~22 px/step) carries the
    # particle hundreds of pixels past the target before reversing.
    proximity_zone = max(50.0, dist * 0.08)

    x, y = sx, sy
    vx, vy = 0.0, 0.0
    wind_x, wind_y = 0.0, 0.0
    points: list[tuple[float, float]] = []
    guard = 0

    while True:
        guard += 1
        if guard > 2000:
            break
        rx = ex - x
        ry = ey - y
        remaining = math.hypot(rx, ry)
        if remaining < 1.0:
            break
        # Early termination: close to target AND moving toward it (so no
        # more oscillation expected). Stops the simulation generating
        # bounce-around-target waypoints, which the walker would
        # otherwise faithfully render as visible cursor jitter.
        if remaining < 4.0 and (vx * rx + vy * ry) >= 0.0:
            break

        # Wind drifts: high-freq perturbation near start, calms down near end.
        # Squared so the last ~8% of the path is essentially calm — combined
        # with the tremor decay in _walk(), the landing pixel is precise.
        near_raw = min(1.0, remaining / max(dist, 1.0))
        near = near_raw * near_raw
        w = wind_strength * near
        wind_x = wind_x / math.sqrt(5) + (random.random() * 2 - 1) * w / math.sqrt(5)
        wind_y = wind_y / math.sqrt(5) + (random.random() * 2 - 1) * w / math.sqrt(5)

        # Gravity pulls toward target.
        gx = gravity * rx / remaining
        gy = gravity * ry / remaining

        vx += gx + wind_x
        vy += gy + wind_y

        # Proximity-based damping. Inside `proximity_zone`, ramp up
        # extra damping linearly toward the target. At the target,
        # we apply 35% extra velocity decay per step — combined with
        # base damping that's ~41% per step, which collapses
        # equilibrium velocity from ~22 px/step to ~6 px/step inside
        # the landing zone. Eliminates the dramatic overshoot.
        close_factor = 0.0
        if remaining < proximity_zone:
            close_factor = 1.0 - (remaining / proximity_zone)
        decay = (damping / 50.0) + (close_factor * 0.35)
        vx *= (1.0 - decay)
        vy *= (1.0 - decay)

        # Clamp step length.
        speed = math.hypot(vx, vy)
        if speed > max_step:
            vx = vx / speed * max_step
            vy = vy / speed * max_step

        x += vx
        y += vy
        points.append((x, y))

    points.append((ex, ey))
    return points


def _bezier_path(start: tuple[float, float], end: tuple[float, float]) -> list[tuple[float, float]]:
    """Cubic Bezier fallback with two randomized control points."""
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    dist = max(1.0, math.hypot(dx, dy))
    # Control points offset perpendicular to the line by up to ~15% of distance.
    perp_x, perp_y = -dy / dist, dx / dist
    off1 = random.uniform(-0.15, 0.15) * dist
    off2 = random.uniform(-0.15, 0.15) * dist
    c1 = (sx + dx * 0.33 + perp_x * off1, sy + dy * 0.33 + perp_y * off1)
    c2 = (sx + dx * 0.66 + perp_x * off2, sy + dy * 0.66 + perp_y * off2)
    steps = max(15, int(dist / 6))
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        it = 1 - t
        x = it**3 * sx + 3 * it**2 * t * c1[0] + 3 * it * t**2 * c2[0] + t**3 * ex
        y = it**3 * sy + 3 * it**2 * t * c1[1] + 3 * it * t**2 * c2[1] + t**3 * ey
        pts.append((x, y))
    return pts


def _walk_phys(points: list[tuple[float, float]], duration: float, stop: Optional[threading.Event]) -> bool:
    """Walk the path over `duration` seconds with asymmetric ease + tremor.

    Tremor model: low-freq sinusoidal sway (1.5-3 Hz, 0.8-1.6 px) plus
    an Ornstein-Uhlenbeck (correlated random walk) component that
    mimics real hand tremor's ~5-12 Hz spectrum instead of the ~100 Hz
    buzz that independent per-frame Gaussian samples would produce.
    Tremor envelope is sin² over the walk so the cursor starts calm,
    builds wobble in transit, and settles calm at the landing pixel.

    Returns True if stop was set mid-walk.
    """
    if not points:
        return False
    n = len(points)
    t0 = time.monotonic()
    last_idx = -1

    # Per-walk tremor parameters — randomized so two consecutive moves
    # don't share the same sway phase / freq.
    sway_phase_x = random.uniform(0.0, 2 * math.pi)
    sway_phase_y = random.uniform(0.0, 2 * math.pi)
    sway_freq_x = random.uniform(1.5, 3.0)
    sway_freq_y = random.uniform(1.5, 3.0)
    # Mix of calm (~30% of moves) and normal (~70%) moves so the tremor
    # itself isn't a constant pattern — a steady hand is also human.
    if random.random() < 0.30:
        sway_amp = random.uniform(0.0, 0.4)
        tremor_sigma = 0.20
    else:
        sway_amp = random.uniform(0.8, 1.6)
        tremor_sigma = 0.55

    # OU process state. Each tick: x ← α·x + σ·√(1-α²)·N(0,1).
    # α near 1 → low-freq drift (smooth); α near 0 → white noise (buzz).
    # α = 0.88 at our 5-10 ms tick gives a correlation time ~50 ms,
    # putting the dominant frequency around 6-8 Hz — within the
    # physiological hand-tremor band. Amplitude inflated vs. the old
    # white-noise σ because OU's stationary std equals σ (we use σ as
    # the per-step injection scale, but since α reduces variance by
    # √(1-α²), the effective wobble feels right at ~0.55 px).
    ou_alpha = 0.88
    ou_inj = math.sqrt(1.0 - ou_alpha * ou_alpha)
    trem_x = 0.0
    trem_y = 0.0

    while True:
        elapsed = time.monotonic() - t0
        progress = elapsed / duration if duration > 0 else 1.0
        if progress >= 1.0:
            break
        # Always advance the OU state, even when we don't redraw, so the
        # tremor's temporal correlation isn't tied to the path-step
        # cadence (otherwise long moves with sparse waypoints would
        # alias the tremor frequency).
        trem_x = ou_alpha * trem_x + ou_inj * random.gauss(0.0, tremor_sigma)
        trem_y = ou_alpha * trem_y + ou_inj * random.gauss(0.0, tremor_sigma)
        eased = _ease(progress)
        idx = min(n - 1, int(eased * n))
        if idx != last_idx:
            px, py = points[idx]
            # Symmetric envelope — calm at start (just leaving rest),
            # peak wobble mid-flight, calm at landing. sin²(πt) is 0 at
            # both ends, 1 at midpoint, and smooth-derivative throughout
            # so there's no visible step into or out of the tremor.
            envelope = math.sin(math.pi * progress) ** 2
            sway_x = sway_amp * math.sin(2 * math.pi * sway_freq_x * elapsed + sway_phase_x)
            sway_y = sway_amp * math.sin(2 * math.pi * sway_freq_y * elapsed + sway_phase_y)
            jx = (sway_x + trem_x) * envelope
            jy = (sway_y + trem_y) * envelope
            cx, cy = _clamp_to_safe(px + jx, py + jy)
            dpi_cursor.set_pos_physical(cx, cy)
            last_idx = idx
        # 5-10ms step cadence, randomized.
        step = random.uniform(0.005, 0.010)
        if _sleep(stop, step):
            return True
    # Final landing point (no tremor).
    fx, fy = points[-1]
    cfx, cfy = _clamp_to_safe(fx, fy)
    dpi_cursor.set_pos_physical(cfx, cfy)
    return bool(stop and stop.is_set())


def move(
    end: tuple[int, int],
    stop: Optional[threading.Event] = None,
    fatigue: float = 1.0,
    overshoot_enabled: bool = True,
    overshoot_probability: float = 0.15,
) -> bool:
    """Move the physical cursor to `end` with human-like curves.

    ``end`` is in DIPs (engine's coordinate space). All path math is
    done in physical Win32 pixels so that a move spanning two monitors
    with different DPI scales doesn't teleport at the bezel — DIPs are
    not uniform across mixed-DPR monitors, so a wind path drifting
    past one monitor's right edge in DIP space can land on a
    non-existent screen and warp to identity-mapped physical coords.

    Returns True if interrupted.
    """
    # Read + write in physical px throughout. The DIP→physical
    # conversion happens once at entry for the target.
    start_phys = dpi_cursor.get_pos_physical()
    sx, sy = float(start_phys[0]), float(start_phys[1])
    end_phys = dpi_cursor.dip_to_physical(float(end[0]), float(end[1]))
    ex, ey = _clamp_to_safe(float(end_phys[0]), float(end_phys[1]))
    dist = math.hypot(ex - sx, ey - sy)
    if dist < 1.0:
        return bool(stop and stop.is_set())

    # Fitts-law-style log scaling: ~155ms tiny → ~540ms screen-wide.
    # Tuned so 10px≈155ms, 100px≈260ms, 500px≈410ms, 1500px≈540ms.
    base = 0.12 + 0.095 * math.log2(1.0 + dist / 60.0)
    duration = base * random.uniform(0.82, 1.20) * fatigue

    do_overshoot = (overshoot_enabled and dist > 40
                    and random.random() < (overshoot_probability + (fatigue - 1.0) * 0.4))

    if mouse_trace.is_enabled():
        # Log DIPs (caller-facing) plus physical (what the engine
        # actually traverses) so analyzers can reconcile both.
        sx_dip, sy_dip = dpi_cursor.physical_to_dip(sx, sy)
        mouse_trace.event(
            "move_start",
            sx=int(round(sx_dip)), sy=int(round(sy_dip)),
            ex=int(round(end[0])), ey=int(round(end[1])),
            sxp=int(round(sx)), syp=int(round(sy)),
            exp=int(round(ex)), eyp=int(round(ey)),
            dist=round(dist, 1),
            dur=round(duration, 4),
            fat=round(fatigue, 3),
            ovs=bool(do_overshoot),
        )

    # Settle pause: 0-50ms scaled by distance, fires only ~40% of the time.
    # Constant settle pauses become their own mechanical pattern — randomize
    # whether the human "verifies aim" or just clicks straight away.
    if random.random() < 0.40:
        settle = min(0.050, dist / 4000.0) * random.uniform(0.5, 1.3)
    else:
        settle = 0.0

    if do_overshoot:
        # Target 3-12px past end along the approach vector — in physical
        # px so the visual overshoot distance is consistent across DPRs.
        over = random.uniform(3, 12)
        ux, uy = (ex - sx) / dist, (ey - sy) / dist
        overshoot_pt = _clamp_to_safe(ex + ux * over, ey + uy * over)
        path = _wind_path((sx, sy) , overshoot_pt) if USE_WIND else _bezier_path((sx, sy), overshoot_pt)
        if _walk_phys(path, duration, stop):
            mouse_trace.event("move_end", interrupted=True, phase="overshoot")
            return True
        # Small pause as the human realizes they overshot.
        if _sleep(stop, random.uniform(0.020, 0.060)):
            mouse_trace.event("move_end", interrupted=True, phase="overshoot_pause")
            return True
        # Short corrective hop back.
        cur_phys = dpi_cursor.get_pos_physical()
        correct_path = _wind_path((float(cur_phys[0]), float(cur_phys[1])), (ex, ey)) if USE_WIND else _bezier_path((float(cur_phys[0]), float(cur_phys[1])), (ex, ey))
        if _walk_phys(correct_path, max(0.04, duration * 0.35), stop):
            mouse_trace.event("move_end", interrupted=True, phase="overshoot_correct")
            return True
        if settle > 0.005 and _sleep(stop, settle):
            mouse_trace.event("move_end", interrupted=True, phase="settle")
            return True
        mouse_trace.event("move_end", interrupted=False, phase="overshoot_done")
        return False
    else:
        path = _wind_path((sx, sy), (ex, ey)) if USE_WIND else _bezier_path((sx, sy), (ex, ey))
        if _walk_phys(path, duration, stop):
            mouse_trace.event("move_end", interrupted=True, phase="walk")
            return True
        if settle > 0.005 and _sleep(stop, settle):
            mouse_trace.event("move_end", interrupted=True, phase="settle")
            return True
        mouse_trace.event("move_end", interrupted=False)
        return False


def drift(
    end: tuple[int, int],
    stop: Optional[threading.Event],
    duration: float,
    curvature: float = 0.4,
    clamp: bool = True,
) -> bool:
    """Smooth curved drift to `end` over `duration` seconds. No click.

    Used by idle_wanderer for aimless between-click movement. The path is a
    single quadratic Bezier whose control point is pushed perpendicular to
    the direct line by `curvature * dist * U(0.3, 0.7)` with a random sign,
    so the arc can bow either direction.

    ``clamp`` defaults True. Pass False to bypass the corner-zone clamp —
    needed for hover-zone visits whose target may sit on a different
    monitor than the engine's primary safe rect (which would otherwise be
    pushed back inside the safe rect, leaving the zone unreachable).

    Returns True if interrupted.
    """
    # Same physical-px discipline as :func:`move`: read + write in
    # physical px so a drift that crosses monitors with different DPRs
    # stays smooth instead of teleporting at the bezel.
    start_phys = dpi_cursor.get_pos_physical()
    sx, sy = float(start_phys[0]), float(start_phys[1])
    end_phys = dpi_cursor.dip_to_physical(float(end[0]), float(end[1]))
    if clamp:
        ex, ey = _clamp_to_safe(float(end_phys[0]), float(end_phys[1]))
    else:
        ex, ey = float(end_phys[0]), float(end_phys[1])
    dx, dy = ex - sx, ey - sy
    dist = math.hypot(dx, dy)
    if dist < 1.0:
        return bool(stop and stop.is_set())

    perp_x, perp_y = -dy / dist, dx / dist
    sign = random.choice([-1, 1])
    off_mag = curvature * dist * random.uniform(0.3, 0.7) * sign
    cx = sx + dx * 0.5 + perp_x * off_mag
    cy = sy + dy * 0.5 + perp_y * off_mag

    steps = max(20, int(dist / 4))
    pts: list[tuple[float, float]] = []
    for i in range(1, steps + 1):
        t = i / steps
        it = 1.0 - t
        x = it * it * sx + 2 * it * t * cx + t * t * ex
        y = it * it * sy + 2 * it * t * cy + t * t * ey
        pts.append((x, y))

    if mouse_trace.is_enabled():
        sx_dip, sy_dip = dpi_cursor.physical_to_dip(sx, sy)
        mouse_trace.event(
            "drift_start",
            sx=int(round(sx_dip)), sy=int(round(sy_dip)),
            ex=int(round(end[0])), ey=int(round(end[1])),
            sxp=int(round(sx)), syp=int(round(sy)),
            exp=int(round(ex)), eyp=int(round(ey)),
            dist=round(dist, 1), dur=round(max(0.02, duration), 4),
            curv=round(curvature, 3),
        )
    interrupted = _walk_phys(pts, max(0.02, duration), stop)
    mouse_trace.event("drift_end", interrupted=bool(interrupted))
    return interrupted


def click(
    button: str = "left",
    mode: str = "single",
    stop: Optional[threading.Event] = None,
    fatigue: float = 1.0,
) -> bool:
    """Perform a click with randomized pre-click pause and press-hold duration.

    Returns True if interrupted before completion.
    """
    btn = Button.right if button == "right" else Button.left

    # Pause after cursor arrives, before first press.
    if _sleep(stop, random.uniform(0.020, 0.080) * fatigue):
        return True

    def _one_click() -> bool:
        _mouse.press(btn)
        # Bimodal press-hold so the histogram has two humps instead of a
        # narrow band — quick-trigger taps (~10%) live alongside deliberate
        # presses (~90%). Detectors that fingerprint a clean uniform[40,120]
        # cluster see a much messier distribution.
        if random.random() < 0.10:
            hold = random.uniform(0.020, 0.060) * fatigue   # quick trigger
        else:
            hold = random.uniform(0.060, 0.250) * fatigue   # deliberate press
        mouse_trace.event("press", btn=button, hold=round(hold, 4))
        if _sleep(stop, hold):
            _mouse.release(btn)
            mouse_trace.event("release", btn=button, interrupted=True)
            return True
        _mouse.release(btn)
        mouse_trace.event("release", btn=button)
        return False

    if _one_click():
        return True

    if mode == "double":
        # Wider inter-click gap so the second-click cadence isn't a clean
        # band either. Real users vary 40-180ms here.
        if _sleep(stop, random.uniform(0.040, 0.180)):
            return True
        if _one_click():
            return True

    return False
