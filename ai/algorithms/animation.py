"""Animation detector — finds regions whose pixels are flickering
over a sliding window of recent frames.

Many RuneScape activity targets aren't static — fishing spots have
intermittent surface bubbles, hunter traps have movement when
something's caught, certain ore rocks pulse when a rare deposit is
present. Color matching alone misses them because the CTS hit hops
around frame-to-frame.

The detector keeps a small ring buffer of recent frames per ROI.
Per tick:

  1. Push the new frame into the buffer (drop the oldest if full).
  2. For every consecutive pair, compute :func:`rs3vision.feature.diff`
     to get the changed-tile rectangles between them.
  3. Aggregate changed tiles across the window — tiles that flickered
     in any pair are candidates.
  4. Cluster nearby candidates and return their centroids as click
     targets.

Stationary scene = no candidates. Constantly-changing scene (camera
panning) = too many candidates everywhere → nothing useful, the bot
should rely on a static target instead. The sweet spot is "small,
localized, periodic motion against a mostly-still backdrop" — exactly
what fishing-spot bubbles look like.

The state is per-detector instance (one per `find_animation_click`
step) so two animation steps with different ROIs don't interfere.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Tuple

import numpy as np


# Default sliding-window size. ~5 frames at 5 Hz = 1 second of history,
# which catches the typical fishing-spot bubble period without lagging
# response too much.
DEFAULT_WINDOW: int = 5

# Minimum tile-changed-pair count before we trust a candidate region.
# Filters out single-frame noise spikes and JPEG-compression flicker.
DEFAULT_MIN_FLICKERS: int = 2

# Tile size used by `rv.feature.diff`. 8 px is the rs3vision default
# and works well at 1080p+; smaller tiles are more sensitive but also
# noisier. Override per-detector if needed.
DEFAULT_TILE: int = 8


@dataclass
class AnimationCandidate:
    """One detected flickering region."""
    centroid: Tuple[int, int]                # absolute screen px
    bbox: Tuple[int, int, int, int]          # (x, y, w, h) absolute
    flicker_count: int                       # how many pair-diffs fired


@dataclass
class AnimationState:
    """Result of one ``AnimationDetector.tick(frame)`` call."""
    candidates: List[AnimationCandidate] = field(default_factory=list)
    frame_count: int = 0                     # how many frames are in history
    elapsed_ms: float = 0.0


class AnimationDetector:
    """Sliding-window animation detector for one ROI.

    Construct once per step that needs animation detection; call
    :meth:`tick` every frame with the current capture and the (now
    constant) ROI. The detector handles the ring-buffer bookkeeping
    and returns fresh candidates each tick.
    """

    def __init__(
        self,
        roi: Tuple[int, int, int, int],
        *,
        window: int = DEFAULT_WINDOW,
        min_flickers: int = DEFAULT_MIN_FLICKERS,
        tile: int = DEFAULT_TILE,
    ) -> None:
        self.roi = tuple(int(v) for v in roi)
        self.window = max(2, int(window))
        self.min_flickers = max(1, int(min_flickers))
        self.tile = max(2, int(tile))
        self._buffer: Deque[np.ndarray] = deque(maxlen=self.window)

    def reset(self) -> None:
        self._buffer.clear()

    def tick(self, frame: np.ndarray) -> AnimationState:
        """Push ``frame`` into the buffer and return any animation
        candidates detected within the ROI right now.

        The first ``window`` ticks return empty candidates because we
        need at least 2 frames to diff. Once warmed up, every tick
        returns candidates aggregated across the window.
        """
        import time
        t0 = time.perf_counter()
        if frame is None:
            return AnimationState(elapsed_ms=0.0)
        x, y, w, h = self.roi
        fh, fw = frame.shape[:2]
        x = max(0, min(x, fw - 1))
        y = max(0, min(y, fh - 1))
        w = max(4, min(w, fw - x))
        h = max(4, min(h, fh - y))

        # Crop to ROI so the diff only considers our region. Copy so
        # we don't keep a reference to the giant frame in the buffer.
        crop = np.ascontiguousarray(frame[y:y + h, x:x + w]).copy()
        self._buffer.append(crop)

        if len(self._buffer) < 2:
            return AnimationState(frame_count=len(self._buffer))

        # Aggregate flickering tiles across every consecutive pair in
        # the window. Each pair returns rectangles in ROI-local coords;
        # we accumulate hit counts per (rx, ry, rw, rh) tuple.
        try:
            import rs3vision as rv
            tile = self.tile
            counts: dict[Tuple[int, int, int, int], int] = {}
            buf = list(self._buffer)
            for i in range(1, len(buf)):
                prev = buf[i - 1]
                curr = buf[i]
                changed, _h = rv.feature.diff(prev, curr, tile=tile)
                for rect in changed:
                    key = tuple(int(v) for v in rect)
                    counts[key] = counts.get(key, 0) + 1
        except Exception:
            counts = {}

        # Filter low-count tiles and convert to absolute screen coords.
        candidates: List[AnimationCandidate] = []
        for (rx, ry, rw, rh), c in counts.items():
            if c < self.min_flickers:
                continue
            cx = x + rx + rw // 2
            cy = y + ry + rh // 2
            candidates.append(AnimationCandidate(
                centroid=(cx, cy),
                bbox=(x + rx, y + ry, rw, rh),
                flicker_count=c,
            ))

        # Cluster nearby candidates into one (so a single fishing spot
        # doesn't return ten neighbouring tiles). Greedy O(N²) merge —
        # candidates are typically <30 so this is cheap.
        merged = _merge_close(candidates, max_dist=tile * 4)
        merged.sort(key=lambda c: -c.flicker_count)

        elapsed = (time.perf_counter() - t0) * 1000.0
        return AnimationState(
            candidates=merged,
            frame_count=len(self._buffer),
            elapsed_ms=elapsed,
        )


def _merge_close(
    cands: List[AnimationCandidate], *, max_dist: int,
) -> List[AnimationCandidate]:
    """Merge candidates whose centroids are within ``max_dist`` px.

    Keeps the centroid of whichever cluster had the most flickers.
    """
    if not cands:
        return []
    out: List[AnimationCandidate] = []
    used = [False] * len(cands)
    for i, ci in enumerate(cands):
        if used[i]:
            continue
        cluster = [ci]
        used[i] = True
        for j in range(i + 1, len(cands)):
            if used[j]:
                continue
            cj = cands[j]
            dx = ci.centroid[0] - cj.centroid[0]
            dy = ci.centroid[1] - cj.centroid[1]
            if (dx * dx + dy * dy) <= max_dist * max_dist:
                cluster.append(cj)
                used[j] = True
        # Pick the centroid with the highest flicker count.
        best = max(cluster, key=lambda c: c.flicker_count)
        # Aggregate flicker count.
        total = sum(c.flicker_count for c in cluster)
        # Bounding box that covers all members.
        x0 = min(c.bbox[0] for c in cluster)
        y0 = min(c.bbox[1] for c in cluster)
        x1 = max(c.bbox[0] + c.bbox[2] for c in cluster)
        y1 = max(c.bbox[1] + c.bbox[3] for c in cluster)
        out.append(AnimationCandidate(
            centroid=best.centroid,
            bbox=(x0, y0, x1 - x0, y1 - y0),
            flicker_count=total,
        ))
    return out
