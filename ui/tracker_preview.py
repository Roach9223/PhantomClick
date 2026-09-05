"""Tracker preview: live OpenCV match running for the active Track step
even while the engine is idle.

The App owns one ``TemplateTracker`` shared with the engine. This module
drives that tracker's ``locate()`` loop on a daemon thread, and ticks
the on-screen overlay via ``QTimer`` so the bounding box follows the
target. Color and label encode whether we're previewing (idle) or
actually tracking (engine running).

Coordinate spaces: the tracker works in PHYSICAL pixels (mss
``monitors[0]`` space). Step ``capture_rect`` values are converted here
when a legacy config still holds Qt DIPs, and the tracker's reported
position is converted back to DIPs before the overlay (a Qt widget) is
placed.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from modules.clicker import ClickerState
from modules.recorder import CAPTURE_SPACE_PHYSICAL, KIND_TRACK, RecorderStep
from modules.zone_selector import Zone

from . import theme as t


def physical_capture_rect(step: RecorderStep) -> Optional[tuple[int, int, int, int]]:
    """``capture_rect`` as ``(x1, y1, x2, y2)`` physical pixels, converting
    DIP-space rects from configs written before the space tag existed."""
    rect = step.capture_rect
    if not rect:
        return None
    x1, y1, x2, y2 = rect
    if getattr(step, "capture_rect_space", CAPTURE_SPACE_PHYSICAL) == CAPTURE_SPACE_PHYSICAL:
        return (int(x1), int(y1), int(x2), int(y2))
    from utils.dpi_cursor import dip_rect_to_physical
    px, py, pw, ph = dip_rect_to_physical(x1, y1, x2 - x1, y2 - y1)
    return (px, py, px + pw, py + ph)


class TrackerPreview:
    def __init__(self, app) -> None:
        self.app = app
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._preview_step_id: Optional[str] = None

    # -- Path helpers ------------------------------------------------------

    def resolve_template_path(self, rel_or_abs: str) -> Path:
        from ui.config_io import _config_dir
        p = Path(rel_or_abs)
        if not p.is_absolute():
            p = _config_dir() / p
        return p

    # -- Preview activation ------------------------------------------------

    def set_preview_step(self, step: RecorderStep) -> None:
        if step.kind != KIND_TRACK or not step.template_path or not step.capture_rect:
            return
        try:
            import cv2
            png = self.resolve_template_path(step.template_path)
            primary = cv2.imread(str(png))
        except Exception:
            primary = None
        if primary is None:
            return
        extras: list = []
        for ep in step.extra_template_paths or []:
            try:
                p = self.resolve_template_path(ep)
                eimg = cv2.imread(str(p))
                if eimg is not None:
                    extras.append(eimg)
            except Exception:
                pass
        rect = physical_capture_rect(step)
        self.app._tracker.set_templates(primary, extras, tuple(rect))
        self.apply_step_settings(step)
        self._preview_step_id = step.step_id
        self.ensure_loop()

    def apply_step_settings(self, step: RecorderStep) -> None:
        j = max(0.0, min(0.5, float(step.tracker_scale_jitter)))
        with self.app._tracker._lock:
            cfg = self.app._tracker.cfg
            cfg.match_threshold = float(step.tracker_threshold)
            cfg.search_radius = int(step.tracker_search_radius)
            cfg.full_rescan_on_loss = bool(step.tracker_full_rescan)
            cfg.scale_min = max(0.5, 1.0 - j)
            cfg.scale_max = min(1.5, 1.0 + j)
            cfg.scale_steps = 1 if j < 1e-3 else 5
            cfg.update_rate_hz = float(step.tracker_update_rate_hz)

    # -- Locate loop -------------------------------------------------------

    def ensure_loop(self) -> None:
        if not self.app._tracker.has_template():
            return
        t_ = self._thread
        if t_ is not None and t_.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _search_rect(self) -> Optional[tuple[int, int, int, int]]:
        """Physical ``(x, y, w, h)`` the preview should search, or None for
        the tracker's default (the whole virtual screen).

        An explicit Settings target monitor narrows the search to that
        screen, matching what the engine does. Auto stays whole-screen
        because ``target_screen_bounds()``'s auto follows the Click zone,
        which says nothing about where a Record target lives.
        """
        try:
            if self.app._explicit_target_screen_index() is None:
                return None
            from utils.dpi_cursor import dip_rect_to_physical
            return dip_rect_to_physical(*self.app.target_screen_bounds())
        except Exception:
            return None

    def _loop(self) -> None:
        # Re-evaluated each pass so a monitor change mid-session takes
        # effect without a restart.
        while not self._stop.is_set():
            if not self.app._tracker.has_template():
                break
            try:
                self.app._tracker.locate(search_rect=self._search_rect())
            except Exception:
                pass
            if self._stop.is_set() or not self.app._tracker.has_template():
                break
            rate = max(1.0, float(self.app._tracker.cfg.update_rate_hz))
            if self._stop.wait(1.0 / rate):
                break

    def stop_loop(self) -> None:
        """Stop the locate loop and wait for it to leave ``locate()``.

        The caller typically closes the tracker's mss handle next. A
        ``locate()`` already past the stop check would rebuild that handle
        on a dying thread, so we join (bounded, so a wedged grab cannot
        hang the GUI) before returning.
        """
        self._stop.set()
        th = self._thread
        if th is not None and th.is_alive() and th is not threading.current_thread():
            th.join(timeout=0.5)

    def seed_from_steps(self) -> None:
        for s in reversed(self.app._steps):
            if s.kind == KIND_TRACK and s.template_path and s.capture_rect:
                self.set_preview_step(s)
                return

    # -- Per-tick overlay sync -------------------------------------------

    def tick(self) -> None:
        app = self.app
        state = app._state_str
        if (app._active_mode != "recorder"
                or not app.cfg.get("show_zone_overlay", True)
                or not app._tracker.has_template()):
            return
        snap = app._tracker.snapshot_state()
        if snap.last_position is None:
            if state == ClickerState.IDLE:
                app.overlay_manager.hide_main()
            return
        # Tracker reports physical pixels; the overlay is a Qt widget and
        # wants DIPs. Same method as Clicker._tracker_zone: convert the
        # top-left and the centre (both interior points, so neither hits
        # the identity fallback on a monitor edge) and mirror the half
        # size to get the far corner.
        from utils.dpi_cursor import physical_to_dip
        cx, cy = snap.last_position
        tw, th = getattr(snap, "last_template_size", (0, 0))
        if tw <= 0 or th <= 0:
            tw, th = app._tracker.cfg.template_size
        if tw <= 0 or th <= 0:
            return
        x1, y1 = physical_to_dip(cx - tw // 2, cy - th // 2)
        cxd, cyd = physical_to_dip(cx, cy)
        x2 = cxd + (cxd - x1)
        y2 = cyd + (cyd - y1)
        if x2 <= x1 or y2 <= y1:
            return
        follow_zone = Zone.make_rect(x1, y1, x2, y2)
        score_pct = int(round(snap.last_score * 100))
        if state == ClickerState.IDLE:
            color = t.INFO if snap.is_locked else t.WARN
            label = (f"Preview · {score_pct}% match" if snap.is_locked
                     else f"Searching… last {score_pct}%")
        elif snap.is_locked:
            # Green: the engine is live on this target.
            color = t.RUN
            label = f"Tracking · {score_pct}% match"
        else:
            color = t.WARN
            label = f"Searching… last {score_pct}%"
        app.overlay_manager.show_main(
            follow_zone, color, app.cfg["zone_opacity"], label=label,
        )
