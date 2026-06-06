"""Anti-clustering force repulsion for click targets.

Ported from PhantomClick's ``clicker.py``. The idea: humans don't
click the same pixel twice; they land *near* a target with a small
± spread. If you're just randomising the target uniformly, clicks
still cluster over time because the zone is fixed. This module
tracks the last N clicks and pushes new targets away from them with
a simple distance-weighted force.

Also includes the "exact-repeat prevention" nudge: if the new target
equals the previous click exactly, perturb it by ±1-2 px so no two
clicks ever land on the same integer pixel.
"""

from __future__ import annotations

import math
import random
from collections import deque
from typing import Deque, Optional, Tuple

from .config import HumanizerConfig


Point = Tuple[int, int]


class AntiCluster:
    """Stateful anti-clustering with a bounded recent-click history."""

    def __init__(self, cfg: HumanizerConfig) -> None:
        self._cfg = cfg
        self._recent: Deque[Point] = deque(maxlen=max(1, cfg.anti_cluster_history))
        self._last: Optional[Point] = None

    def reset(self) -> None:
        self._recent.clear()
        self._last = None

    # ────────────────────────────────────────────────────────────
    # Apply the repulsion + micro-jitter to a candidate target
    # ────────────────────────────────────────────────────────────
    def adjust(
        self,
        target: Point,
        bounds: Optional[Tuple[int, int, int, int]] = None,
    ) -> Point:
        """Return a slightly-shifted target.

        ``bounds`` (x1, y1, x2, y2) optionally clamps the output so
        we never push a click outside the detection ROI / screen.
        """
        if not (self._cfg.enabled and self._cfg.anti_cluster_enabled):
            return target

        tx, ty = float(target[0]), float(target[1])
        min_sep = self._cfg.anti_cluster_min_sep_px

        # Exact-repeat prevention — cheapest guard.
        if self._last is not None and (int(tx), int(ty)) == self._last:
            tx += random.uniform(-2.0, 2.0)
            ty += random.uniform(-2.0, 2.0)

        # Repel from each recent click within min_sep.
        for (px, py) in self._recent:
            dx, dy = tx - px, ty - py
            d = math.hypot(dx, dy)
            if d < 1e-3:
                # Coincident — push in a random direction.
                angle = random.uniform(0, 2 * math.pi)
                dx, dy = math.cos(angle), math.sin(angle)
                d = 1.0
            if d < min_sep:
                push = (min_sep - d) + 2.0
                tx += (dx / d) * push
                ty += (dy / d) * push

        # Micro-jitter on every click; biased smaller using a triangular
        # distribution so most jitters are tiny, occasional ones larger.
        jx = random.triangular(-self._cfg.anti_cluster_micro_jitter_px,
                                self._cfg.anti_cluster_micro_jitter_px, 0.0)
        jy = random.triangular(-self._cfg.anti_cluster_micro_jitter_px,
                                self._cfg.anti_cluster_micro_jitter_px, 0.0)
        tx += jx
        ty += jy

        if bounds is not None:
            x1, y1, x2, y2 = bounds
            tx = max(x1 + 1, min(x2 - 1, tx))
            ty = max(y1 + 1, min(y2 - 1, ty))

        return int(round(tx)), int(round(ty))

    def record(self, point: Point) -> None:
        """Mark that we just clicked at ``point`` — influences future adjusts."""
        self._recent.append((int(point[0]), int(point[1])))
        self._last = (int(point[0]), int(point[1]))
