"""Session-scoped fatigue drift + break-burst scheduling.

Ported from PhantomClick's ``utils/fatigue.py``. One :class:`Fatigue`
instance lives for the duration of a script run — it's reset every
time the Studio presses Play. The multiplier starts at 1.0 and drifts
up linearly with elapsed time; it's capped at
``1.0 + intensity × 1.5`` so even a many-hour run doesn't balloon
times into the absurd.

Break bursts are click-counted, not time-counted: the next break is
due after a uniform random number of clicks between
``break_min_clicks`` and ``break_max_clicks``. When due,
:meth:`maybe_break` returns a duration in seconds; the runtime sleeps
that long before the next action. The counter then rolls a fresh
threshold.
"""

from __future__ import annotations

import random
import time
from typing import Optional

from .config import HumanizerConfig


class Fatigue:
    """Mutable fatigue state machine. Thread-safe for single-writer use
    (our runtime only touches it from the worker thread).
    """

    def __init__(self, cfg: HumanizerConfig) -> None:
        self._cfg = cfg
        self.start_time = time.monotonic()
        self.click_count = 0
        self._next_break_at = self._roll_next_break()

    # ── rolling next-break threshold ─────────────────────
    def _roll_next_break(self) -> int:
        lo = max(1, self._cfg.break_min_clicks)
        hi = max(lo, self._cfg.break_max_clicks)
        return random.randint(lo, hi)

    def reset(self) -> None:
        """Called by the runtime on Play so each run starts fresh."""
        self.start_time = time.monotonic()
        self.click_count = 0
        self._next_break_at = self._roll_next_break()

    # ── live queries ─────────────────────────────────────
    def multiplier(self) -> float:
        """Scale factor applied to move durations, click holds, pauses."""
        if not (self._cfg.enabled and self._cfg.fatigue_enabled) or self._cfg.fatigue_intensity <= 0:
            return 1.0
        hours = (time.monotonic() - self.start_time) / 3600.0
        cap = 1.0 + self._cfg.fatigue_intensity * 1.5
        return min(1.0 + self._cfg.fatigue_intensity * hours, cap)

    def overshoot_bonus(self) -> float:
        """Extra overshoot probability contributed by fatigue drift."""
        if not (self._cfg.enabled and self._cfg.fatigue_enabled):
            return 0.0
        return (self.multiplier() - 1.0) * 0.4

    # ── click accounting ─────────────────────────────────
    def record_click(self) -> None:
        self.click_count += 1

    def maybe_break(self) -> float:
        """Returns a break duration in seconds if due, else 0.0.

        Callers should sleep (interruptibly) for the returned duration
        before issuing the next input event. Rolls a fresh threshold
        on every trigger so two consecutive breaks never line up.
        """
        if not (self._cfg.enabled and self._cfg.break_bursts_enabled):
            return 0.0
        if self.click_count < self._next_break_at:
            return 0.0
        self._next_break_at = self.click_count + self._roll_next_break()
        return random.uniform(
            self._cfg.break_min_duration_s,
            self._cfg.break_max_duration_s,
        )

    # ── introspection for Dashboard / MCP ────────────────
    def snapshot(self) -> dict:
        """Return a plain-dict snapshot for UI / MCP consumption."""
        return {
            "enabled": bool(self._cfg.enabled and self._cfg.fatigue_enabled),
            "multiplier": round(self.multiplier(), 3),
            "elapsed_s": round(time.monotonic() - self.start_time, 1),
            "click_count": self.click_count,
            "next_break_at_click": self._next_break_at,
            "clicks_until_break": max(0, self._next_break_at - self.click_count),
        }
