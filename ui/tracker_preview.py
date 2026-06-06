"""Tracker preview — live OpenCV match running for the active Track step
even while the engine is idle.

The App owns one ``TemplateTracker`` shared with the engine. This module
drives that tracker's ``locate()`` loop on a daemon thread, and ticks
the on-screen overlay via ``QTimer`` so the bounding box follows the
target. Color and label encode whether we're previewing (idle) or
actually tracking (engine running).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from modules.clicker import ClickerState
from modules.recorder import KIND_TRACK, RecorderStep
from modules.zone_selector import Zone

from . import theme as t


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
        self.app._tracker.set_templates(primary, extras, tuple(step.capture_rect))
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

    def _loop(self) -> None:
        sw, sh = self.app.monitor_w, self.app.monitor_h
        while not self._stop.is_set():
            if not self.app._tracker.has_template():
                break
            try:
                self.app._tracker.locate(sw, sh)
            except Exception:
                pass
            if self._stop.is_set() or not self.app._tracker.has_template():
                break
            rate = max(1.0, float(self.app._tracker.cfg.update_rate_hz))
            if self._stop.wait(1.0 / rate):
                break

    def stop_loop(self) -> None:
        self._stop.set()

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
        cx, cy = snap.last_position
        tw, th = app._tracker.cfg.template_size
        follow_zone = Zone.make_rect(cx - tw // 2, cy - th // 2,
                                     cx - tw // 2 + tw,
                                     cy - th // 2 + th)
        score_pct = int(round(snap.last_score * 100))
        if state == ClickerState.IDLE:
            color = t.INFO if snap.is_locked else t.WARN
            label = (f"Preview · {score_pct}% match" if snap.is_locked
                     else f"Searching… last {score_pct}%")
        elif snap.is_locked:
            color = app.cfg["zone_color"]
            label = f"Tracking · {score_pct}% match"
        else:
            color = t.WARN
            label = f"Searching… last {score_pct}%"
        app.overlay_manager.show_main(
            follow_zone, color, app.cfg["zone_opacity"], label=label,
        )
