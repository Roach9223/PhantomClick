"""Real-time stats tracker. Thread-safe; GUI polls snapshot() on a timer."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional


class Stats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._start: Optional[float] = None
        self._total: int = 0
        self._last_pos: Optional[tuple[int, int]] = None
        self._intervals: deque[float] = deque(maxlen=60)
        self._last_click_time: Optional[float] = None

    def reset(self) -> None:
        with self._lock:
            self._start = time.monotonic()
            self._total = 0
            self._last_pos = None
            self._intervals.clear()
            self._last_click_time = None

    def record(self, pos: tuple[int, int]) -> None:
        with self._lock:
            now = time.monotonic()
            if self._start is None:
                self._start = now
            if self._last_click_time is not None:
                self._intervals.append(now - self._last_click_time)
            self._last_click_time = now
            self._total += 1
            self._last_pos = pos

    def snapshot(self) -> dict:
        with self._lock:
            now = time.monotonic()
            elapsed = (now - self._start) if self._start else 0.0
            avg_interval = sum(self._intervals) / len(self._intervals) if self._intervals else 0.0
            # Clicks per minute from the rolling window of intervals.
            cpm = (60.0 / avg_interval) if avg_interval > 0 else 0.0
            return {
                "total": self._total,
                "elapsed": elapsed,
                "avg_interval": avg_interval,
                "cpm": cpm,
                "last_pos": self._last_pos,
            }


def format_elapsed(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"
