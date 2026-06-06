"""``OverlayManager`` — central coordinator for every on-screen overlay.

In the legacy Tk version this owned several throwaway toplevels for click
flashes plus three persistent overlay sets (main / step / hover). The
current Qt version mirrors that surface — but the actual overlay widgets
live in ``ui/overlays/`` and are imported lazily so the App can boot
without Win32 hooks initialized.

Cards call ``om.show_main(zone, color, opacity)`` etc.; this class handles
the actual widget lifetimes and refresh logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from .overlays.zone_overlay import ZoneOverlay


class OverlayManager:
    def __init__(self, app) -> None:
        self.app = app
        self._main: Optional["ZoneOverlay"] = None
        self._step_overlays: List["ZoneOverlay"] = []
        self._hover_overlays: List["ZoneOverlay"] = []

    # -- Lazy import so app boot doesn't fail if overlays have ctypes deps -

    def _ensure_main(self):
        from .overlays.zone_overlay import ZoneOverlay
        if self._main is None:
            self._main = ZoneOverlay()
        return self._main

    # -- Main overlay (mode preview / single-zone clicker) ----------------

    def show_main(self, zone, color: str, opacity: float, *,
                  label: Optional[str] = None) -> None:
        ov = self._ensure_main()
        ov.show_zone(zone, color, opacity, label=label)

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
            ov.show_zone(step.zone, cfg["zone_color"], cfg["zone_opacity"],
                         label=f"Step {idx+1}")
            self._step_overlays.append(ov)

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

    # -- Visibility toggle (the "show overlays" button) -------------------

    def apply_visibility(self) -> None:
        """Reconcile every overlay's visibility against the current
        ``_active_mode`` and the ``show_zone_overlay`` toggle.

        Click and Record each "own" their own overlay set: the click-mode
        single zone (``_main``) only paints in click mode, the per-step
        overlays only paint in record mode. Hover overlays always paint
        when enabled — they're a cross-mode behavior the cursor drifts
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
                self.show_main(self.app._zone, cfg["zone_color"], cfg["zone_opacity"])
            else:
                self.hide_main()
        else:
            # Record mode — main overlay belongs to click mode; hide it.
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
