"""Session-scoped fatigue drift + break-burst scheduling.

All tuning values are parameters so the GUI can expose sliders for them.
"""

from __future__ import annotations

import random
import time


class Fatigue:
    def __init__(
        self,
        enabled: bool = True,
        break_bursts: bool = True,
        intensity: float = 0.25,
        break_min_clicks: int = 40,
        break_max_clicks: int = 70,
        break_min_duration: float = 30.0,
        break_max_duration: float = 90.0,
    ):
        self.enabled = enabled
        self.break_bursts = break_bursts
        self.intensity = max(0.0, float(intensity))
        self.break_min_clicks = max(1, int(break_min_clicks))
        self.break_max_clicks = max(self.break_min_clicks, int(break_max_clicks))
        self.break_min_duration = max(0.1, float(break_min_duration))
        self.break_max_duration = max(self.break_min_duration, float(break_max_duration))
        self.start_time = time.monotonic()
        self.click_count = 0
        self._next_break_at = self._roll_next_break()

    def _roll_next_break(self) -> int:
        return random.randint(self.break_min_clicks, self.break_max_clicks)

    def reset(self) -> None:
        self.start_time = time.monotonic()
        self.click_count = 0
        self._next_break_at = self._roll_next_break()

    def multiplier(self) -> float:
        """1.0 at session start, drifts up by `intensity` per hour (capped)."""
        if not self.enabled or self.intensity <= 0:
            return 1.0
        hours = (time.monotonic() - self.start_time) / 3600.0
        return min(1.0 + self.intensity * hours, 1.0 + self.intensity * 1.5)

    def overshoot_bonus(self) -> float:
        """Extra overshoot probability from fatigue (small)."""
        if not self.enabled:
            return 0.0
        return (self.multiplier() - 1.0) * 0.4

    def record_click(self) -> None:
        self.click_count += 1

    def maybe_break(self) -> float:
        """Returns a break duration in seconds if due, else 0.0."""
        if not (self.enabled and self.break_bursts):
            return 0.0
        if self.click_count >= self._next_break_at:
            self._next_break_at = self.click_count + self._roll_next_break()
            return random.uniform(self.break_min_duration, self.break_max_duration)
        return 0.0
