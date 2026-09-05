"""Behavioural checks on the timing and path samplers.

These assert bounds, positivity and non-constancy, not exact
distributions, so the samplers can keep evolving without breaking the
suite. Nothing here moves the real mouse.
"""

from __future__ import annotations

import math
import random
import statistics

import pytest

from utils import humanizer

N = 2000


# ---- inter-click delay: humanizer._soft_range -----------------------------

@pytest.mark.parametrize("lo,hi", [(0.02, 0.08), (0.5, 1.0), (5.0, 20.0)])
def test_soft_range_stays_inside_its_documented_window(lo, hi):
    # _soft_range is documented to keep ~90% of draws in [lo, hi] and the
    # rest inside a soft window: no lower than 0.8*lo, no higher than
    # hi + 0.5*(hi - lo). Nothing may ever be non-positive.
    floor = lo * 0.80 - 1e-9
    ceiling = hi + (hi - lo) * 0.50 + 1e-9
    inside = 0
    for _ in range(N):
        v = humanizer._soft_range(lo, hi)
        assert v > 0
        assert floor <= v <= ceiling, v
        if lo <= v <= hi:
            inside += 1
    assert inside / N > 0.75


def test_soft_range_is_not_constant_when_lo_differs_from_hi():
    vals = [humanizer._soft_range(1.0, 3.0) for _ in range(N)]
    assert statistics.pvariance(vals) > 0
    assert len(set(round(v, 6) for v in vals)) > 100


def test_soft_range_degenerate_range_is_positive_and_bounded():
    for _ in range(200):
        v = humanizer._soft_range(2.0, 2.0)
        assert v > 0
        # Equal bounds may return exactly lo or a small jitter around it;
        # either way it has to stay close.
        assert 1.5 <= v <= 2.5


# ---- inter-click delay: Clicker._human_delay ------------------------------

def _make_clicker():
    from modules.clicker import Clicker
    from modules.stats import Stats
    return Clicker(Stats())


@pytest.mark.parametrize("realism", [0.0, 0.5, 1.0])
def test_clicker_human_delay_bounds(realism):
    c = _make_clicker()
    c.realism = realism
    lo, hi = 0.5, 1.5
    span = hi - lo
    # At low realism the sampler is plain uniform; otherwise it may
    # overshoot hi by at most half the span (scaled by realism).
    upper = hi if realism < 0.05 else hi + span * 0.5 * realism
    for _ in range(N):
        v = c._human_delay(lo, hi)
        assert v > 0
        assert lo - 1e-9 <= v <= upper + 1e-9, (realism, v)


def test_clicker_human_delay_not_constant():
    c = _make_clicker()
    c.realism = 0.6
    vals = [c._human_delay(0.5, 1.5) for _ in range(N)]
    assert statistics.pvariance(vals) > 0


def test_clicker_human_delay_equal_bounds_is_positive():
    c = _make_clicker()
    c.realism = 0.8
    for _ in range(200):
        v = c._human_delay(2.0, 2.0)
        assert v > 0
        assert 1.5 <= v <= 2.5


# ---- movement path: humanizer._wind_path -----------------------------------

def _perp_distance(p, a, b):
    """Distance from point p to the infinite line through a and b."""
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    norm = math.hypot(dx, dy)
    if norm == 0:
        return math.hypot(px - ax, py - ay)
    return abs(dy * px - dx * py + bx * ay - by * ax) / norm


def test_wind_path_is_never_a_straight_constant_speed_line():
    rng = random.Random(1234)
    for _ in range(50):
        start = (rng.uniform(0, 2500), rng.uniform(0, 1400))
        angle = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(250, 1200)
        end = (start[0] + dist * math.cos(angle), start[1] + dist * math.sin(angle))
        pts = humanizer._wind_path(start, end)

        assert len(pts) >= 3, "too few waypoints for a real move"
        # Terminates on the requested target.
        assert math.hypot(pts[-1][0] - end[0], pts[-1][1] - end[1]) < 1e-6

        walk = [start] + pts
        steps = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(walk, walk[1:])]
        steps = [s for s in steps if s > 0]
        assert len(steps) >= 3
        # Speed varies along the path.
        assert statistics.pvariance(steps) > 0
        # Not collinear: some waypoint sits visibly off the straight line.
        assert max(_perp_distance(p, start, end) for p in pts) > 0.5


def test_wind_path_trivial_move_returns_target():
    assert humanizer._wind_path((10.0, 10.0), (10.4, 10.2)) == [(10.4, 10.2)]


def test_ease_is_monotonic_and_pinned():
    prev = -1.0
    for i in range(101):
        t = i / 100
        v = humanizer._ease(t)
        assert v >= prev - 1e-9
        prev = v
    assert abs(humanizer._ease(0.0)) < 1e-6
    assert abs(humanizer._ease(1.0) - 1.0) < 1e-6


# ---- press-hold time -------------------------------------------------------

def test_hold_time_samples_are_positive_and_capped():
    # click() draws its press-hold from two log-normal humps: a quick
    # trigger in [0.020, 0.060] and a deliberate press in [0.060, 0.250].
    # Sample both the way click() does and check they stay sane.
    cap = 0.5
    for _ in range(N):
        quick = humanizer._soft_range(0.020, 0.060)
        slow = humanizer._soft_range(0.060, 0.250)
        assert 0 < quick < cap
        assert 0 < slow < cap
    # Fatigue only stretches holds; it must not make them non-positive.
    for fatigue in (1.0, 1.2, 1.5):
        v = humanizer._soft_range(0.060, 0.250) * fatigue
        assert 0 < v < cap
