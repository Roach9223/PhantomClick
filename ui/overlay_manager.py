"""``OverlayManager``, central coordinator for every on-screen overlay.

In the legacy Tk version this owned several throwaway toplevels for click
flashes plus three persistent overlay sets (main / step / hover). The
current Qt version mirrors that surface, but the actual overlay widgets
live in ``ui/overlays/`` and are imported lazily so the App can boot
without Win32 hooks initialized.

Cards call ``om.show_main(zone, color, opacity)`` etc.; this class handles
the actual widget lifetimes and refresh logic.

Window-locked zones are resolved here before they reach an overlay, and
``tick()`` (driven by the App's 100 ms timer) keeps the outline riding
along with the window while idle. The outline turns amber and stays at
the last known position while the window is lost or minimized.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from modules import zone_lock

from . import theme as t

if TYPE_CHECKING:
    from modules.zone_selector import Zone
    from .overlays.zone_overlay import ZoneOverlay


class OverlayManager:
    def __init__(self, app) -> None:
        self.app = app
        self._main: Optional["ZoneOverlay"] = None
        self._step_overlays: List["ZoneOverlay"] = []
        self._hover_overlays: List["ZoneOverlay"] = []
        # Source zones behind the visible overlays, so the tick can
        # re-resolve locked ones. Main: the stored (anchor-relative) zone
        # and the colour it was shown with. Steps: (overlay, step_id, zone).
        self._main_zone: Optional["Zone"] = None
        self._main_color: str = ""
        self._step_meta: List[tuple["ZoneOverlay", str, "Zone"]] = []
        self._last_drawn: dict[str, tuple] = {}

    # -- Lazy import so app boot doesn't fail if overlays have ctypes deps -

    def _ensure_main(self):
        from .overlays.zone_overlay import ZoneOverlay
        if self._main is None:
            self._main = ZoneOverlay()
        return self._main

    # Window lock helpers

    def _resolver(self):
        return getattr(self.app, "zone_locks", None)

    def _resolved(self, zone, key: str):
        """(zone_to_draw, ResolvedZone or None). Screen-locked zones come
        back unchanged so callers need no special case."""
        if zone is None or getattr(zone, "lock", None) is None:
            return zone, None
        r = self._resolver()
        res = r.resolve(zone, key) if r is not None else zone_lock.resolve(zone, {})
        return res.zone, res

    def _color_for(self, base_color: str, res) -> str:
        if res is not None and res.holding:
            return t.WARN
        return base_color

    # -- Main overlay (mode preview / single-zone clicker) ----------------

    def show_main(self, zone, color: str, opacity: float, *,
                  label: Optional[str] = None) -> None:
        ov = self._ensure_main()
        self._main_zone = zone
        self._main_color = color
        drawn, res = self._resolved(zone, "main")
        self._last_drawn["main"] = self._signature(drawn, res)
        ov.show_zone(drawn, self._color_for(color, res), opacity, label=label)

    def hide_main(self) -> None:
        if self._main is not None:
            self._main.hide_zone()

    # -- Step + hover overlay lists ---------------------------------------

    def refresh_step_overlays(self) -> None:
        """Rebuild on-screen step overlays from ``app._steps``.

        Step overlays only paint while Record mode is active so a user on
        the Click tab doesn't see Record-mode zones bleed onto their
        screen. ``_set_active_mode`` calls ``apply_visibility`` after the
        flip so switching tabs swaps which set of overlays is visible.
        """
        from .overlays.zone_overlay import ZoneOverlay
        for ov in self._step_overlays:
            ov.deleteLater()
        self._step_overlays = []
        self._step_meta = []
        cfg = self.app.cfg
        if not cfg.get("show_zone_overlay", True):
            return
        # Click mode owns its own single overlay (``_main``); skip step
        # overlays entirely so the two modes don't fight for screen real
        # estate.
        if self.app._active_mode != "recorder":
            return
        steps = self.app._steps
        if not any(s.zone is not None for s in steps):
            return
        for idx, step in enumerate(steps):
            if step.zone is None:
                continue
            ov = ZoneOverlay()
            drawn, res = self._resolved(step.zone, step.step_id)
            self._last_drawn[step.step_id] = self._signature(drawn, res)
            ov.show_zone(drawn, self._color_for(t.ZONE_DEFAULT_COLOR, res),
                         cfg["zone_opacity"], label=f"Step {idx+1}")
            self._step_overlays.append(ov)
            self._step_meta.append((ov, step.step_id, step.zone))

    def refresh_hover_overlays(self) -> None:
        from .overlays.zone_overlay import ZoneOverlay
        for ov in self._hover_overlays:
            ov.deleteLater()
        self._hover_overlays = []
        cfg = self.app.cfg
        zones = self.app._hover_zones
        if not cfg.get("show_zone_overlay", True):
            return
        for idx, z in enumerate(zones):
            ov = ZoneOverlay()
            label = "Hover" if len(zones) == 1 else f"Hover {idx+1}"
            ov.show_zone(z, cfg["hover_color"], cfg["hover_opacity"], label=label)
            self._hover_overlays.append(ov)

    # Window-lock follow tick

    @staticmethod
    def _signature(drawn, res) -> tuple:
        status = res.status if res is not None else "screen"
        try:
            return (status, drawn.aabb() if drawn is not None else None)
        except Exception:
            return (status, None)

    def tick(self) -> None:
        """Re-resolve every locked zone that has an overlay showing and
        move / recolor it when something changed. The resolver throttles
        to 10 Hz per key, so this stays cheap on the 100 ms tick."""
        cfg = self.app.cfg
        if not cfg.get("show_zone_overlay", True):
            return
        ov = self._main
        if (ov is not None and ov.isVisible() and self._main_zone is not None
                and getattr(self._main_zone, "lock", None) is not None):
            self._follow(ov, "main", self._main_zone, self._main_color or t.ZONE_DEFAULT_COLOR)
        for ov, step_id, zone in self._step_meta:
            if getattr(zone, "lock", None) is None or not ov.isVisible():
                continue
            self._follow(ov, step_id, zone, t.ZONE_DEFAULT_COLOR)

    def _follow(self, ov, key: str, zone, base_color: str) -> None:
        drawn, res = self._resolved(zone, key)
        sig = self._signature(drawn, res)
        if self._last_drawn.get(key) == sig:
            return
        self._last_drawn[key] = sig
        # While holding, the resolver hands back the last good geometry,
        # so only the colour changes and the outline stays where the
        # window was last seen.
        ov.update_zone(drawn if not (res is not None and res.holding) else None,
                       self._color_for(base_color, res))

    def lock_state(self, key: str = "main"):
        """Last ResolvedZone the tick produced for ``key``, or None."""
        r = self._resolver()
        if r is None:
            return None
        zone = None
        if key == "main":
            zone = self._main_zone if self._main_zone is not None else self.app._zone
        else:
            for _ov, sid, z in self._step_meta:
                if sid == key:
                    zone = z
        if zone is None:
            return None
        return r.resolve(zone, key)

    # -- Visibility toggle (the "show overlays" button) -------------------

    def apply_visibility(self) -> None:
        """Reconcile every overlay's visibility against the current
        ``_active_mode`` and the ``show_zone_overlay`` toggle.

        Click and Record each "own" their own overlay set: the click-mode
        single zone (``_main``) only paints in click mode, the per-step
        overlays only paint in record mode. Hover overlays always paint
        when enabled, they're a cross-mode behavior the cursor drifts
        toward in either mode. Called from ``_set_active_mode`` so a tab
        switch swaps which overlays appear on screen.
        """
        cfg = self.app.cfg
        show = bool(cfg.get("show_zone_overlay", True))
        if not show:
            self.hide_main()
            for ov in self._step_overlays:
                ov.hide_zone()
            for ov in self._hover_overlays:
                ov.hide_zone()
            return
        if self.app._active_mode == "clicker":
            if self.app._zone is not None:
                self.show_main(self.app._zone, t.ZONE_DEFAULT_COLOR, cfg["zone_opacity"])
            else:
                self.hide_main()
        else:
            # Record mode, main overlay belongs to click mode; hide it.
            self.hide_main()
        self.refresh_step_overlays()
        self.refresh_hover_overlays()

    def hide_for_drawing(self) -> None:
        """Hide every overlay so the ZoneDrawer can take the screen."""
        self.hide_main()
        for ov in self._hover_overlays + self._step_overlays:
            ov.hide_zone()

    # -- Throwaway click-marker flash -------------------------------------

    def flash_click_marker(self, target_x: int, target_y: int,
                           actual_x: int, actual_y: int, kind: str) -> None:
        from .overlays.click_marker import flash as flash_marker
        if not self.app.cfg.get("show_zone_overlay", True):
            return
        flash_marker(self.app, target_x, target_y, actual_x, actual_y, kind)
