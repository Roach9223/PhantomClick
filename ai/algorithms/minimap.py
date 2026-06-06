"""Minimap reader — player-position click target, motion detection,
and run-energy orb percentage.

The minimap is a fixed-size HUD region in the top-right of the NXT
client. The player avatar is always rendered at the centre of the
minimap (the world scrolls around the player), which makes a few
classes of detection cheap:

- **Player click target** is just the centre of the minimap ROI. Use
  it for "click on yourself to stop walking" or "click somewhere on
  the minimap to walk there".
- **Motion detection** is a frame-diff over the whole minimap. When
  the player is walking the surrounding terrain shifts; standing
  still produces near-zero diff (the orbs / compass twitch a bit but
  nothing larger). The runner's ``on_player_moved_unexpectedly``
  trigger reads from this.
- **Run-energy** lives in the top-right corner orb. Counts saturated
  pixels in the orb sub-region; calibrated max_fill at 100% scales
  to a percentage.

The reader is *stateful* — to compute motion it needs the previous
tick's minimap crop. Construct one :class:`MinimapTracker` per worker
and call :meth:`tick` once per frame.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


# ── Constants ──────────────────────────────────────────────────────

# Run-energy orb sub-region within the minimap ROI, expressed as
# fractions of the ROI's width / height. The orb sits in the top-right
# corner of the minimap area in NXT layout.
_ORB_FRACTION_X = 0.78
_ORB_FRACTION_Y = 0.0
_ORB_FRACTION_W = 0.22
_ORB_FRACTION_H = 0.18

# Saturation threshold — pixels whose (max-channel - min-channel)
# exceeds this are "coloured", everything else is grey/dark UI. The
# run-energy orb's fill is bright orange-yellow, well above this floor.
_SAT_THRESHOLD = 50

# Motion detection: pixels whose per-channel BGR delta from the
# previous frame exceeds this are "moved." Tuned to absorb JPEG and
# anti-alias jitter while still catching real terrain shifts.
_MOTION_PIXEL_THRESHOLD = 18

# Heuristic "tile-equivalent" scale factor: motion_score * this ≈
# tiles walked since the last tick. At 5 Hz tick + ~1 tile/0.6s
# typical RS walk speed, one tile of motion produces ~3-5% pixel
# diff. Multiplying by 30 gives a 0..30 range usable as a threshold
# in the on_player_moved trigger's ``tiles`` parameter.
_TILE_SCALE = 30.0


# ── Public types ──────────────────────────────────────────────────


@dataclass(frozen=True)
class MinimapState:
    """One tick's parsed minimap snapshot."""

    roi: Tuple[int, int, int, int]      # (x, y, w, h) used for the scan
    player_xy_screen: Tuple[int, int]   # absolute screen px — minimap centre
    motion_score: float                 # 0..1 fraction of pixels changed
    motion_tiles: float                 # motion_score × _TILE_SCALE
    run_energy_pct: Optional[float]     # 0..100 or None if uncalibrated
    run_energy_raw_filled: int          # signature pixel count this tick
    elapsed_ms: float

    # ── Convenience aliases used by WorldState / triggers ──────
    @property
    def player_xy(self) -> Tuple[int, int]:
        """Alias for the absolute screen-space player click target."""
        return self.player_xy_screen


# ── Tracker (holds previous-frame state for diffs) ────────────────


class MinimapTracker:
    """Per-bot stateful minimap reader.

    Construct once at bot start, call :meth:`tick` once per frame
    with the current capture and the calibrated ROI. The tracker
    holds the previous frame's minimap crop internally so motion
    detection works without external state plumbing.
    """

    def __init__(self, *, run_energy_max_fill: int = 0) -> None:
        self._prev_crop: Optional[np.ndarray] = None
        self._prev_roi: Optional[Tuple[int, int, int, int]] = None
        self.run_energy_max_fill = int(run_energy_max_fill or 0)

    def reset(self) -> None:
        self._prev_crop = None
        self._prev_roi = None

    def tick(
        self,
        frame: np.ndarray,
        roi: Tuple[int, int, int, int],
    ) -> Optional[MinimapState]:
        """Read the minimap from ``frame`` at ``roi``. Returns ``None``
        when the ROI is invalid; otherwise a fresh :class:`MinimapState`."""
        t0 = time.perf_counter()
        if frame is None or roi is None:
            return None
        x, y, w, h = (int(v) for v in roi)
        fh, fw = frame.shape[:2]
        x = max(0, min(x, fw - 1))
        y = max(0, min(y, fh - 1))
        w = max(8, min(w, fw - x))
        h = max(8, min(h, fh - y))

        crop = np.ascontiguousarray(frame[y:y + h, x:x + w])

        # Motion: per-pixel BGR delta vs. previous crop. Skip when
        # this is the first tick OR the ROI changed (recalibration).
        motion_score = 0.0
        if (self._prev_crop is not None
                and self._prev_crop.shape == crop.shape
                and self._prev_roi == (x, y, w, h)):
            diff = np.abs(crop.astype(np.int16) - self._prev_crop.astype(np.int16))
            moved = (diff.max(axis=2) >= _MOTION_PIXEL_THRESHOLD)
            motion_score = float(moved.mean())
        self._prev_crop = crop.copy()
        self._prev_roi = (x, y, w, h)

        # Run-energy orb — sub-region of the minimap ROI.
        ox = int(round(w * _ORB_FRACTION_X))
        oy = int(round(h * _ORB_FRACTION_Y))
        ow = max(8, int(round(w * _ORB_FRACTION_W)))
        oh = max(8, int(round(h * _ORB_FRACTION_H)))
        ox2 = min(w, ox + ow)
        oy2 = min(h, oy + oh)
        orb = crop[oy:oy2, ox:ox2]
        run_filled = _count_saturated(orb)
        if self.run_energy_max_fill > 0:
            pct = max(0.0, min(100.0, (run_filled / float(self.run_energy_max_fill)) * 100.0))
        else:
            pct = None

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return MinimapState(
            roi=(x, y, w, h),
            player_xy_screen=(x + w // 2, y + h // 2),
            motion_score=motion_score,
            motion_tiles=motion_score * _TILE_SCALE,
            run_energy_pct=pct,
            run_energy_raw_filled=run_filled,
            elapsed_ms=elapsed_ms,
        )


# ── Calibration helper ────────────────────────────────────────────


def calibrate_run_energy_max_fill(
    frame: np.ndarray,
    roi: Tuple[int, int, int, int],
) -> int:
    """Capture the run-energy orb's saturated-pixel count at 100%.

    Called by the AI tab's "Calibrate Minimap ROI" handler immediately
    after the user draws the minimap rect — assumes the player is at
    100% run-energy. Stored as part of the bundle's calibration so
    runtime percentages are meaningful.
    """
    if frame is None or roi is None:
        return 0
    x, y, w, h = (int(v) for v in roi)
    fh, fw = frame.shape[:2]
    x = max(0, min(x, fw - 1))
    y = max(0, min(y, fh - 1))
    w = max(8, min(w, fw - x))
    h = max(8, min(h, fh - y))
    crop = frame[y:y + h, x:x + w]
    ox = int(round(w * _ORB_FRACTION_X))
    oy = int(round(h * _ORB_FRACTION_Y))
    ow = max(8, int(round(w * _ORB_FRACTION_W)))
    oh = max(8, int(round(h * _ORB_FRACTION_H)))
    orb = crop[oy:oy + oh, ox:ox + ow]
    return _count_saturated(orb)


# ── Back-compat: legacy module-level scan() ───────────────────────


def scan(
    frame: np.ndarray,
    roi: Tuple[int, int, int, int],
) -> Optional[MinimapState]:
    """Stateless one-shot scan used by WorldState's lazy fallback path
    when no :class:`MinimapTracker` is installed on the runtime context.

    Without a tracker there's no previous frame, so ``motion_score``
    will always be 0. Bots that depend on movement detection should
    rely on the runner-installed tracker via ``ctx.minimap_state``.
    """
    one_shot = MinimapTracker()
    return one_shot.tick(frame, roi)


# ── Internals ─────────────────────────────────────────────────────


def _count_saturated(region: np.ndarray) -> int:
    """Count pixels in ``region`` whose channel spread exceeds the
    saturation floor. Cheap proxy for "bright coloured pixel." Used
    to measure the run-energy orb's filled portion.
    """
    if region is None or region.size == 0:
        return 0
    arr = region.astype(np.int16)
    spread = arr.max(axis=2) - arr.min(axis=2)
    return int((spread >= _SAT_THRESHOLD).sum())
