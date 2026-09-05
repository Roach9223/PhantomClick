"""Bot runtime context.

Holds shared per-run state passed to each rule body via the
``contextvars`` machinery in :mod:`ai.bot.api`. Originally this module
also hosted ``RuntimeWorker`` / ``RuntimeController`` for the visual
graph editor; that surface was dropped when the Studio chrome was
removed during the PhantomClick merge. Only :class:`RuntimeContext`
remains, since :class:`ai.bot.runner.BotRunner` builds one per run.

The context also owns the run's :class:`FrameSource` and the
frame <-> screen mapper. Every capture and every coordinate
translation in ai/ goes through the methods here, so swapping mss for
a capture card in Phase 2 is a one-line change in the runner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple

import numpy as np

from ..input import InputBackend
from ..input.frame_source import FrameMapper, MssFrameSource


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
    # Where frames come from. The runner installs its source before the
    # first tick; when nothing is installed, ``capture()`` builds an
    # MssFrameSource for ``default_monitor`` on first use.
    frame_source: Any = None
    _mapper: FrameMapper = field(default_factory=FrameMapper)
    # Per-tick parsed world state. The bot worker rebuilds this on
    # every tick (just after frame capture, before the contextvars
    # binding) so ``api.world()`` resolves to it.
    world: Any = None
    # User-calibrated ROIs for the awareness layer (inventory, orbs,
    # minimap), in screen pixels. Populated by the bot worker from
    # BotRunner.play()'s ``world_calibration`` kwarg.
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

    # ── Frame source + coordinate mapping ───────────────────────────
    def set_frame_source(self, source: Any) -> None:
        self.frame_source = source
        self._sync_origin()

    def _sync_origin(self) -> None:
        src = self.frame_source
        if src is None:
            return
        try:
            self._mapper.set_origin(src.origin())
        except Exception:
            self._mapper.set_origin((0, 0))

    def _ensure_source(self) -> Any:
        if self.frame_source is None:
            self.set_frame_source(MssFrameSource(int(self.default_monitor)))
        return self.frame_source

    def frame_origin(self) -> Tuple[int, int]:
        """Screen coordinate of frame pixel (0, 0)."""
        self._ensure_source()
        return self._mapper.origin

    def frame_to_screen(self, pt) -> Tuple[int, int]:
        self._ensure_source()
        return self._mapper.frame_to_screen(pt)

    def screen_to_frame(self, pt) -> Tuple[int, int]:
        self._ensure_source()
        return self._mapper.screen_to_frame(pt)

    def screen_rect_to_frame(self, rect):
        """Translate an (x, y, w, h) screen rect into frame pixels.
        None passes through so callers can forward optional ROIs."""
        if rect is None:
            return None
        self._ensure_source()
        return self._mapper.screen_rect_to_frame(rect)

    def frame_rect_to_screen(self, rect):
        if rect is None:
            return None
        self._ensure_source()
        return self._mapper.frame_rect_to_screen(rect)

    def capture(self, monitor: Optional[int] = None) -> np.ndarray:
        """Grab a fresh frame from the run's frame source.

        ``monitor`` is honoured only when it differs from the source's
        own monitor (legacy graph blocks with a per-block override); in
        that case a one-off MssFrameSource is used and its pixels are
        NOT in the run's frame coordinate space.
        """
        src = self._ensure_source()
        if monitor is not None:
            own = getattr(src, "monitor_index", None)
            if own is not None and int(monitor) != int(own):
                tmp = MssFrameSource(int(monitor))
                try:
                    frame = tmp.grab()
                finally:
                    tmp.close()
                if frame is None:
                    raise RuntimeError(f"capture failed for monitor {monitor}")
                return frame
        frame = src.grab()
        if frame is None:
            raise RuntimeError("frame source returned no frame")
        self._sync_origin()
        return frame
