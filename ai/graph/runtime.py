"""Bot runtime context.

Holds shared per-run state passed to each rule body via the
``contextvars`` machinery in :mod:`ai.bot.api`. Originally this module
also hosted ``RuntimeWorker`` / ``RuntimeController`` for the visual
graph editor; that surface was dropped when the Studio chrome was
removed during the PhantomClick merge — only :class:`RuntimeContext`
remains, since :class:`ai.bot.runner.BotRunner` builds one per run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

import mss
import numpy as np

from ..input import InputBackend


@dataclass
class RuntimeContext:
    """Shared state passed to each block's `execute()` and to bot rules."""

    log_fn: Callable[[str], None]
    input_backend: "Optional[InputBackend]"
    default_monitor: int = 1
    default_roi: Optional[tuple] = None
    dry_run: bool = False
    _stop_flag: List[bool] = field(default_factory=lambda: [False])
    _stop_reason: List[str] = field(default_factory=lambda: [""])
    _mss: Any = None  # lazy mss.mss()
    # Per-tick parsed world state. The bot worker rebuilds this on
    # every tick (just after frame capture, before the contextvars
    # binding) so ``api.world()`` resolves to it. Stays None for
    # graph blocks that don't run inside the bot loop.
    world: Any = None
    # User-calibrated ROIs for the awareness layer (inventory, orbs,
    # minimap). Populated by the bot worker from BotRunner.play()'s
    # ``world_calibration`` kwarg, which the App fills from config.json.
    _world_calibration: dict = field(default_factory=dict)

    def resolve_roi(self, roi_str: str):
        s = (roi_str or "").strip()
        if not s:
            return self.default_roi
        try:
            parts = [int(x.strip()) for x in s.split(",")]
        except ValueError:
            return self.default_roi
        return tuple(parts) if len(parts) == 4 else self.default_roi

    def log(self, msg: str) -> None:
        self.log_fn(msg)

    def should_stop(self) -> bool:
        return self._stop_flag[0]

    def request_stop(self, reason: str = "") -> None:
        self._stop_flag[0] = True
        self._stop_reason[0] = reason
        self.log(f"stop requested: {reason}")

    def stop_reason(self) -> str:
        return self._stop_reason[0]

    def capture(self, monitor: int = 1) -> np.ndarray:
        first = self._mss is None
        if first:
            try:
                self._mss = mss.mss()
            except Exception as e:
                self.log(f"[capture] mss.mss() failed: {type(e).__name__}: {e}")
                raise
            mons = self._mss.monitors
            self.log(f"[capture] mss detected {len(mons)} monitor(s):")
            for i, m in enumerate(mons):
                self.log(
                    f"           #{i}: {m.get('width')}×{m.get('height')} "
                    f"@ ({m.get('left')},{m.get('top')})"
                )

        if monitor < 0 or monitor >= len(self._mss.monitors):
            self.log(f"[capture] monitor={monitor} out of range; falling back to 1")
            monitor = 1 if len(self._mss.monitors) > 1 else 0

        mon = self._mss.monitors[monitor]
        try:
            raw = self._mss.grab(mon)
        except Exception as e:
            self.log(
                f"[capture] mss.grab(monitor={monitor}) failed: "
                f"{type(e).__name__}: {e}"
            )
            raise
        arr = np.asarray(raw, dtype=np.uint8)[:, :, :3]
        if not arr.flags["C_CONTIGUOUS"]:
            arr = np.ascontiguousarray(arr)
        if first:
            self.log(
                f"[capture] first grab OK: monitor={monitor} "
                f"shape={arr.shape} dtype={arr.dtype}"
            )
        return arr
