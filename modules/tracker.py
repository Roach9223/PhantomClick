"""Template-matching object tracker for the Track mode.

The user draws a rectangle around an object on screen; we capture those pixels
as the *template*, then locate that template on subsequent screen frames using
OpenCV's normalized cross-correlation (TM_CCOEFF_NORMED) with a small
multi-scale search to tolerate minor zoom / animation. Last position is kept
between frames so most ticks search a small region around it; if the score
drops below threshold we optionally rescan the whole screen.

This module is fully synchronous and Tk-free; the click engine spins it in its
own thread and the GUI reads ``state`` snapshots via the shared lock.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

import cv2
import mss
import numpy as np


# --- public dataclasses --------------------------------------------------- #

@dataclass
class TrackerConfig:
    template: Optional[np.ndarray] = None              # primary BGR pixels
    template_size: Tuple[int, int] = (0, 0)            # (w, h) of the primary
    capture_rect: Optional[Tuple[int, int, int, int]] = None
    # Additional "views" of the same target — used for objects that look
    # different from different angles (NPCs, etc.). Same target, same click;
    # the matcher tries each one and uses whichever scores highest.
    extras: list = field(default_factory=list)         # list[np.ndarray]
    extra_sizes: list = field(default_factory=list)    # list[(w, h)]
    search_radius: int = 250                            # px around last_position; <=0 = full screen
    full_rescan_on_loss: bool = True
    match_threshold: float = 0.65                       # normalized score threshold
    update_rate_hz: float = 20.0
    scale_min: float = 0.85
    scale_max: float = 1.15
    scale_steps: int = 5


@dataclass
class TrackerState:
    last_position: Optional[Tuple[int, int]] = None    # match centre in screen coords
    last_score: float = 0.0
    is_locked: bool = False
    last_update_ts: float = 0.0
    # Which template won the last match: 0 = primary, 1..N = cfg.extras[i-1].
    # Engine reads this to size the click box correctly when the matched
    # view has a different aspect ratio than the primary.
    last_template_idx: int = 0
    last_template_size: Tuple[int, int] = (0, 0)


# --- tracker --------------------------------------------------------------- #

class TemplateTracker:
    """Multi-scale template tracker. Thread-safe for one writer (the locate
    loop) and many readers (the GUI tick + click loop)."""

    def __init__(self, cfg: Optional[TrackerConfig] = None):
        self.cfg = cfg if cfg is not None else TrackerConfig()
        self.state = TrackerState()
        self._lock = threading.Lock()
        # Persistent mss handle. Each ``mss.mss()`` allocates a Windows
        # device context; the preview loop calls ``locate()`` ~20 Hz, so
        # constructing+closing per call burns ~72k DC handles per hour.
        # Cache one and reuse — only torn down via ``close()``.
        self._sct = None
        self._sct_lock = threading.Lock()

    def _get_sct(self):
        """Lazily build (and re-build after close) the persistent mss
        handle. Engineering trade: a tiny lock serializes screen grabs
        across the preview thread + engine thread, but mss.grab is
        already a fast OS call so the contention is negligible at
        20-30 Hz."""
        with self._sct_lock:
            if self._sct is None:
                self._sct = mss.mss()
            return self._sct

    def close(self) -> None:
        """Release the cached mss handle. Idempotent; safe to call from
        ``Clicker.stop()`` and the App's ``closeEvent``. Subsequent
        ``locate()`` calls will lazily allocate a fresh handle."""
        with self._sct_lock:
            if self._sct is not None:
                try:
                    self._sct.close()
                except Exception:
                    pass
                self._sct = None

    # -- public API --------------------------------------------------------

    def has_template(self) -> bool:
        with self._lock:
            return self.cfg.template is not None and self.cfg.template_size[0] > 0

    def set_template(self, image: np.ndarray, capture_rect: Tuple[int, int, int, int]) -> None:
        """Adopt a single primary template (e.g. loaded from PNG on startup).

        Clears any previously-set extra views.
        """
        self.set_templates(image, [], capture_rect)

    def set_templates(
        self,
        primary: np.ndarray,
        extras: list,
        capture_rect: Tuple[int, int, int, int],
    ) -> None:
        """Adopt a primary template plus zero-or-more alternate views.

        Each extra is matched independently every frame; whichever template
        scores highest wins. Extras let the user track a target that looks
        different from different angles (e.g. an NPC's front vs. side).
        """
        x1, y1, x2, y2 = capture_rect
        with self._lock:
            self.cfg.template = primary
            self.cfg.template_size = (primary.shape[1], primary.shape[0])
            self.cfg.capture_rect = (x1, y1, x2, y2)
            self.cfg.extras = list(extras)
            self.cfg.extra_sizes = [(img.shape[1], img.shape[0])
                                      for img in self.cfg.extras]
            self.state.last_position = ((x1 + x2) // 2, (y1 + y2) // 2)
            self.state.is_locked = False
            self.state.last_score = 0.0
            self.state.last_template_idx = 0
            self.state.last_template_size = self.cfg.template_size

    def capture_from_screen(self, x1: int, y1: int, x2: int, y2: int) -> bool:
        """Snapshot the screen rect now and adopt it as the template.

        Returns False if the rect is too small (<8 px on either axis) or the
        capture failed.
        """
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        w, h = x2 - x1, y2 - y1
        if w < 8 or h < 8:
            return False
        try:
            sct = self._get_sct()
            with self._sct_lock:
                shot = sct.grab({"left": x1, "top": y1, "width": w, "height": h})
            img = np.array(shot)[:, :, :3]  # BGRA -> BGR
        except Exception:
            # If the cached handle has gone bad (rare — Windows DC reset on
            # display change), drop it so the next call rebuilds. Don't
            # propagate; the caller treats False as "couldn't capture."
            self.close()
            return False
        self.set_template(img.copy(), (x1, y1, x2, y2))
        return True

    def snapshot_state(self) -> TrackerState:
        """Read-only copy of current state for cross-thread use."""
        with self._lock:
            return TrackerState(
                last_position=self.state.last_position,
                last_score=self.state.last_score,
                is_locked=self.state.is_locked,
                last_update_ts=self.state.last_update_ts,
                last_template_idx=self.state.last_template_idx,
                last_template_size=self.state.last_template_size,
            )

    def reset(self) -> None:
        """Forget last position so the next locate() does a full-screen scan."""
        with self._lock:
            self.state.last_position = None
            self.state.is_locked = False
            self.state.last_score = 0.0

    # -- core tick ---------------------------------------------------------

    def locate(self, screen_w: int, screen_h: int) -> Optional[Tuple[int, int]]:
        """Find the target now. Returns (cx, cy) on success or None if no
        template matches above threshold even after a full-screen rescan.

        Iterates over the primary template plus all extras and keeps the
        single best (template, scale, position) across the whole set."""
        with self._lock:
            primary = self.cfg.template
            primary_size = self.cfg.template_size
            extras = list(self.cfg.extras)
            extra_sizes = list(self.cfg.extra_sizes)
            radius = self.cfg.search_radius
            anchor = self.state.last_position
            threshold = float(self.cfg.match_threshold)
            scale_min = float(self.cfg.scale_min)
            scale_max = float(self.cfg.scale_max)
            scale_steps = int(self.cfg.scale_steps)
            allow_full = bool(self.cfg.full_rescan_on_loss)

        if primary is None or primary_size[0] == 0:
            return None

        # Bundle (template, w, h, idx) for the matcher so the result can
        # tell us which template scored best.
        candidates: list = [(primary, primary_size[0], primary_size[1], 0)]
        for i, img in enumerate(extras):
            if img is None:
                continue
            sz = extra_sizes[i] if i < len(extra_sizes) else (img.shape[1], img.shape[0])
            candidates.append((img, sz[0], sz[1], i + 1))

        # 1) Local search around last_position.
        result = self._match_in_region(
            candidates, anchor, radius,
            screen_w, screen_h, scale_min, scale_max, scale_steps, threshold,
        )

        # 2) Full-screen fallback if we missed and the user hasn't disabled it.
        if result is None and (allow_full or anchor is None):
            result = self._match_in_region(
                candidates, None, -1,
                screen_w, screen_h, scale_min, scale_max, scale_steps, threshold,
            )

        now = time.monotonic()
        if result is None:
            with self._lock:
                self.state.is_locked = False
                self.state.last_score = 0.0
                self.state.last_update_ts = now
            return None

        cx, cy, score, tmpl_idx, tmpl_w, tmpl_h = result
        with self._lock:
            self.state.last_position = (cx, cy)
            self.state.last_score = score
            self.state.is_locked = True
            self.state.last_update_ts = now
            self.state.last_template_idx = tmpl_idx
            self.state.last_template_size = (tmpl_w, tmpl_h)
        return (cx, cy)

    # -- internals ---------------------------------------------------------

    def _match_in_region(
        self,
        candidates: list,           # list[(template, tw, th, idx)]
        anchor: Optional[Tuple[int, int]],
        radius: int,
        sw: int,
        sh: int,
        scale_min: float,
        scale_max: float,
        scale_steps: int,
        threshold: float,
    ) -> Optional[Tuple[int, int, float, int, int, int]]:
        """Try every candidate template (multi-scale) inside the search rect
        and return the single best match across the whole set, or None.

        Return tuple: (cx, cy, score, template_idx, template_w, template_h).
        """
        if not candidates:
            return None
        # Search rect must be big enough for the LARGEST template otherwise
        # matchTemplate fails for that one. We capture the screen once and
        # reuse it across all templates.
        max_tw = max(t[1] for t in candidates)
        max_th = max(t[2] for t in candidates)

        if anchor is None or radius <= 0:
            sx1, sy1, sx2, sy2 = 0, 0, sw, sh
        else:
            cx, cy = anchor
            r = max(radius, max_tw, max_th)
            sx1 = max(0, cx - r)
            sy1 = max(0, cy - r)
            sx2 = min(sw, cx + r)
            sy2 = min(sh, cy + r)
        rw, rh = sx2 - sx1, sy2 - sy1
        if rw < max_tw or rh < max_th:
            return None

        try:
            sct = self._get_sct()
            with self._sct_lock:
                shot = sct.grab({"left": sx1, "top": sy1, "width": rw, "height": rh})
            screen = np.array(shot)[:, :, :3]
        except Exception:
            # Cached handle has gone bad — drop it and bail. Next tick
            # rebuilds it lazily; one missed frame is acceptable.
            self.close()
            return None

        if scale_steps <= 1 or abs(scale_max - scale_min) < 1e-6:
            scales = [1.0]
        else:
            scales = list(np.linspace(scale_min, scale_max, max(2, int(scale_steps))))

        # (score, mx, my, scale, idx, tw, th)
        best: Tuple[float, int, int, float, int, int, int] = (-1.0, 0, 0, 1.0, 0, 0, 0)
        for template, tw, th, idx in candidates:
            for scale in scales:
                tw_s = max(4, int(round(tw * scale)))
                th_s = max(4, int(round(th * scale)))
                if tw_s > screen.shape[1] or th_s > screen.shape[0]:
                    continue
                tmpl = template if abs(scale - 1.0) < 1e-3 else cv2.resize(
                    template, (tw_s, th_s), interpolation=cv2.INTER_AREA,
                )
                try:
                    res = cv2.matchTemplate(screen, tmpl, cv2.TM_CCOEFF_NORMED)
                except cv2.error:
                    continue
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val > best[0]:
                    best = (float(max_val), int(max_loc[0]), int(max_loc[1]),
                            float(scale), idx, tw, th)

        score, mx, my, scale, idx, tw, th = best
        if score < threshold:
            return None
        cx = sx1 + mx + int(round(tw * scale * 0.5))
        cy = sy1 + my + int(round(th * scale * 0.5))
        return (cx, cy, score, idx, tw, th)
