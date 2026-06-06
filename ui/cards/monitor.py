"""``MonitorCard`` — UI for the Monitor tab (LAN screen + remote control).

Two opt-in toggles, layered for safety:
1. **Enable streaming** starts the local HTTP server. Required for any
   remote interaction.
2. **Allow remote control** additionally permits POST /control/* — start,
   stop, and Close-RuneScape from the phone. Off by default; the
   safer view-only mode is the default once streaming is on.

Internally built from the design-system primitives:
:class:`SettingsGroup` + :class:`SettingsRow`. The card chrome (header
title + StatePill) is preserved as a :class:`Card`, which sets it apart
from the form-row pages (Hover, Hotkeys, Settings, …) that render flat
without a Card. The card grows a 3 px teal ``[listening="true"]`` left
stripe whenever the server is running, mirroring the active-state cue
on nav-rail items and expanded step cards.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox, QWidget,
)

from ui.config_io import save_config

from .. import theme as t
from ..screen_utils import screen_label
from ..widgets.card import Card
from ..widgets.ios_switch import IOSSwitch
from ..widgets.section_label import SectionLabel
from ..widgets.settings_group import SettingsGroup
from ..widgets.settings_row import SettingsRow
from ..widgets.state_pill import StatePill


def _slider_with_value(slider: QSlider) -> QWidget:
    """Pack a QSlider + a small mono value chip into a row container.

    Used by the FPS / Quality rows so SettingsRow's right-hand control
    area gets a single widget. The value chip is bound to the slider's
    valueChanged so the caller doesn't have to wire it explicitly.
    """
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(t.SP_SM)
    row.addWidget(slider, 1)
    chip = QLabel(str(slider.value()))
    chip.setMinimumWidth(28)
    chip.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    chip.setStyleSheet(
        f"font-family: {t.FONT_MONO}; color: {t.TEXT_SECONDARY};"
    )
    slider.valueChanged.connect(lambda v: chip.setText(str(int(v))))
    row.addWidget(chip)
    host.setMinimumWidth(220)
    return host


class MonitorCard(Card):
    def __init__(self, app):
        super().__init__("Monitor")
        self.app = app

        self.pill = StatePill("Off", tone="neutral")
        self.add_to_header(self.pill)

        body = self.body_layout()
        body.setSpacing(t.SP_SM)

        # ── Phone URL ────────────────────────────────────────────────
        body.addWidget(SectionLabel("Phone URL"))

        url_group = SettingsGroup()

        self.copy_btn = QPushButton("📋  Copy URL")
        self.copy_btn.setMinimumHeight(t.BUTTON_H)
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(self._on_copy)

        self.regen_btn = QPushButton("↻  Regenerate")
        self.regen_btn.setProperty("variant", "warn-outline")
        self.regen_btn.setMinimumHeight(t.BUTTON_H)
        self.regen_btn.setCursor(Qt.PointingHandCursor)
        self.regen_btn.setToolTip(
            "Rotate the access token. Old links stop working immediately."
        )
        self.regen_btn.clicked.connect(self._on_regenerate)

        self.url_row = SettingsRow(
            "Phone URL",
            desc=self._format_url(),
            mono_desc=True,
        )
        self.url_row.set_control(self.copy_btn)
        self.url_row.add_control(self.regen_btn)
        url_group.add_row(self.url_row)
        body.addWidget(url_group)

        body.addSpacing(t.SP_LG)

        # ── Server ───────────────────────────────────────────────────
        body.addWidget(SectionLabel("Server"))

        server_group = SettingsGroup()

        self.enable_switch = IOSSwitch()
        self.enable_switch.setChecked(bool(app.cfg.get("monitor_enabled", False)))
        self.enable_switch.toggled.connect(self._on_enable_toggled)
        enable_row = SettingsRow(
            "Enable streaming",
            desc="Starts the local HTTP server so the phone URL works.",
        )
        enable_row.set_control(self.enable_switch)
        server_group.add_row(enable_row)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(int(app.cfg.get("monitor_port", 8765)))
        self.port_spin.setFixedWidth(96)
        self.port_spin.setKeyboardTracking(False)
        self.port_spin.valueChanged.connect(self._on_port_change)
        port_row = SettingsRow(
            "Port",
            desc="HTTP port the server binds. Restart on change.",
        )
        port_row.set_control(self.port_spin)
        server_group.add_row(port_row)

        self.monitor_combo = QComboBox()
        self.monitor_combo.setCursor(Qt.PointingHandCursor)
        self.monitor_combo.setMinimumWidth(220)
        self._populate_monitor_combo()
        # Make sure cfg has a resolved rect even on first launch (before the
        # user touches the combo).
        if app.cfg.get("monitor_capture_rect") is None:
            self._sync_capture_rect_from_cfg()
        self.monitor_combo.currentIndexChanged.connect(self._on_monitor_change)
        mon_row = SettingsRow(
            "Capture monitor",
            desc="Which screen the phone sees.",
        )
        mon_row.set_control(self.monitor_combo)
        server_group.add_row(mon_row)

        # 60 fps cap matches what most phone displays can render; actual
        # achieved fps depends on source resolution + quality + CPU,
        # which is fine — the slider expresses the *target*.
        self.fps_slider = QSlider(Qt.Horizontal)
        self.fps_slider.setRange(5, 60)
        self.fps_slider.setValue(int(app.cfg.get("monitor_fps", 15)))
        self.fps_slider.valueChanged.connect(self._on_fps_change)
        fps_row = SettingsRow(
            "FPS",
            desc="Target frames per second (5–60). Phones rarely render past 30.",
        )
        fps_row.set_control(_slider_with_value(self.fps_slider))
        server_group.add_row(fps_row)

        # Sentinel value 0 = "native (no downscale)". Anything else is a
        # width cap; aspect ratio preserved on resize.
        self.res_combo = QComboBox()
        self.res_combo.setCursor(Qt.PointingHandCursor)
        self.res_combo.setMinimumWidth(180)
        for label, val in [
            ("720p (1280 wide)", 1280),
            ("1080p (1920 wide)", 1920),
            ("1440p (2560 wide)", 2560),
            ("Native (no downscale)", 0),
        ]:
            self.res_combo.addItem(label, userData=val)
        cur_max = int(app.cfg.get("monitor_max_width", 1920))
        for i in range(self.res_combo.count()):
            if int(self.res_combo.itemData(i)) == cur_max:
                self.res_combo.setCurrentIndex(i)
                break
        self.res_combo.currentIndexChanged.connect(self._on_resolution_change)
        res_row = SettingsRow(
            "Resolution",
            desc="Width cap; aspect ratio is preserved.",
        )
        res_row.set_control(self.res_combo)
        server_group.add_row(res_row)

        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(40, 95)
        self.quality_slider.setValue(int(app.cfg.get("monitor_jpeg_quality", 85)))
        self.quality_slider.valueChanged.connect(self._on_quality_change)
        quality_row = SettingsRow(
            "Quality",
            desc="JPEG quality (40–95). Lower = smaller frames.",
        )
        quality_row.set_control(_slider_with_value(self.quality_slider))
        server_group.add_row(quality_row)

        body.addWidget(server_group)

        body.addSpacing(t.SP_LG)

        # ── Phone controls ───────────────────────────────────────────
        body.addWidget(SectionLabel("Phone controls"))

        phone_group = SettingsGroup()

        self.remote_switch = IOSSwitch()
        self.remote_switch.setChecked(
            bool(app.cfg.get("monitor_remote_control_enabled", False))
        )
        self.remote_switch.toggled.connect(self._on_remote_toggled)
        remote_row = SettingsRow(
            "Allow remote control",
            desc="Lets the phone Start, Stop, and Close RuneScape on this PC.",
        )
        remote_row.set_control(self.remote_switch)
        phone_group.add_row(remote_row)

        body.addWidget(phone_group)

        # ── Warning ──────────────────────────────────────────────────
        # Plain WARN-toned text below the groups. Bare facts; user already
        # opted in by toggling.
        self.warn_label = QLabel("")
        self.warn_label.setWordWrap(True)
        self.warn_label.setStyleSheet(
            f"color: {t.WARN}; font-size: {t.SIZE_SM}px; "
            f"padding-top: {t.SP_SM}px;"
        )
        body.addWidget(self.warn_label)

        self._refresh_pill()
        self._refresh_warning()

    # -- Public hooks (called by App after server state changes) -----------

    def refresh(self) -> None:
        """Re-pull state from the server + cfg. Called after any user
        action that might mutate the URL (token regen, port change)."""
        self.url_row.set_desc(self._format_url())
        self._refresh_pill()
        self._refresh_warning()

    # -- Internal ----------------------------------------------------------

    def _format_url(self) -> str:
        try:
            return self.app.monitor_server.lan_url()
        except AttributeError:
            return "—"

    def _set_listening(self, listening: bool) -> None:
        new = "true" if listening else "false"
        if self.property("listening") == new:
            return
        self.setProperty("listening", new)
        self.style().unpolish(self)
        self.style().polish(self)

    def _refresh_pill(self) -> None:
        srv = getattr(self.app, "monitor_server", None)
        if srv is None:
            self.pill.set_state("Off", "neutral")
            self._set_listening(False)
            return
        if srv.last_error:
            self.pill.set_state("Error", "neutral")
            self._set_listening(False)
            return
        if srv.is_running:
            port = int(self.app.cfg.get("monitor_port", 8765))
            self.pill.set_state(f"Listening: {port}", "accent")
            self._set_listening(True)
        else:
            self.pill.set_state("Off", "neutral")
            self._set_listening(False)

    def _refresh_warning(self) -> None:
        cfg = self.app.cfg
        if cfg.get("monitor_remote_control_enabled", False):
            self.warn_label.setText(
                "⚠  Remote control is enabled — anyone on your network with this "
                "URL can see your screen AND start, stop, and close RuneScape on "
                "your PC. Disable when not monitoring."
            )
        elif cfg.get("monitor_enabled", False):
            self.warn_label.setText(
                "⚠  Anyone on your network with this URL can see your screen. "
                "Disable when not monitoring."
            )
        else:
            self.warn_label.setText("")

    def _on_enable_toggled(self, checked: bool) -> None:
        cfg = self.app.cfg
        cfg["monitor_enabled"] = bool(checked)
        save_config(cfg)
        srv = self.app.monitor_server
        if checked:
            ok = srv.start()
            if not ok:
                # Roll back the toggle so the UI reflects the failure;
                # the StatePill shows "Error" and the toast tells the user why.
                self.enable_switch.blockSignals(True)
                self.enable_switch.setChecked(False)
                self.enable_switch.blockSignals(False)
                cfg["monitor_enabled"] = False
                save_config(cfg)
                self.app.toasts.post(
                    f"Couldn't start monitor server: {srv.last_error}",
                    kind="warn",
                )
        else:
            srv.stop()
        self.refresh()

    def _on_port_change(self, value: int) -> None:
        cfg = self.app.cfg
        cfg["monitor_port"] = int(value)
        save_config(cfg)
        srv = self.app.monitor_server
        if srv.is_running:
            ok = srv.start()  # restart on new port (start() stops first)
            if not ok:
                self.app.toasts.post(
                    f"Couldn't bind port {value}: {srv.last_error}",
                    kind="warn",
                )
        self.refresh()

    def _on_fps_change(self, value: int) -> None:
        # Capture loop reads cfg every iteration; no restart needed.
        cfg = self.app.cfg
        cfg["monitor_fps"] = int(value)
        save_config(cfg)

    def _on_quality_change(self, value: int) -> None:
        # Capture loop reads cfg every iteration; no restart needed.
        cfg = self.app.cfg
        cfg["monitor_jpeg_quality"] = int(value)
        save_config(cfg)

    def _on_resolution_change(self, _idx: int) -> None:
        cfg = self.app.cfg
        cfg["monitor_max_width"] = int(self.res_combo.currentData() or 1920)
        save_config(cfg)

    # -- Monitor selector helpers -----------------------------------------

    def _populate_monitor_combo(self) -> None:
        self.monitor_combo.blockSignals(True)
        self.monitor_combo.clear()

        screens = QGuiApplication.screens() or []
        primary = QGuiApplication.primaryScreen()

        # First entry: "Primary" — sticks to whichever monitor the OS marks
        # as primary at any given moment, so unplug/replug doesn't break the
        # selection.
        primary_label = "Primary"
        if primary is not None:
            primary_label = f"Primary — {screen_label(primary)}"
        self.monitor_combo.addItem(primary_label, userData="primary")

        for i, s in enumerate(screens):
            label = screen_label(s, index=i, is_primary=(s is primary))
            self.monitor_combo.addItem(label, userData=str(i))

        cur = str(self.app.cfg.get("monitor_capture_index", "primary"))
        for i in range(self.monitor_combo.count()):
            if self.monitor_combo.itemData(i) == cur:
                self.monitor_combo.setCurrentIndex(i)
                break
        self.monitor_combo.blockSignals(False)

    def _resolve_screen_geometry(self, choice: str):
        """Return a Qt geometry rect for the user's choice, or None if the
        choice is stale (e.g. monitor 2 was selected then unplugged)."""
        screens = QGuiApplication.screens() or []
        if choice == "primary":
            primary = QGuiApplication.primaryScreen()
            return primary.geometry() if primary is not None else None
        try:
            idx = int(choice)
        except (TypeError, ValueError):
            return None
        if 0 <= idx < len(screens):
            return screens[idx].geometry()
        return None

    def _sync_capture_rect_from_cfg(self) -> None:
        """Resolve the cfg's monitor_capture_index → geometry and write it
        back into cfg["monitor_capture_rect"]. Called from __init__ on first
        launch and from _on_monitor_change when the user picks a different
        monitor."""
        choice = str(self.app.cfg.get("monitor_capture_index", "primary"))
        geom = self._resolve_screen_geometry(choice)
        if geom is None and choice != "primary":
            # Stale index — fall back to primary and persist the fallback so
            # the dropdown agrees with reality next time.
            self.app.cfg["monitor_capture_index"] = "primary"
            geom = self._resolve_screen_geometry("primary")
        if geom is None:
            self.app.cfg["monitor_capture_rect"] = None
        else:
            self.app.cfg["monitor_capture_rect"] = {
                "left": int(geom.x()),
                "top": int(geom.y()),
                "width": int(geom.width()),
                "height": int(geom.height()),
            }
        save_config(self.app.cfg)

    def _on_monitor_change(self, _idx: int) -> None:
        choice = str(self.monitor_combo.currentData() or "primary")
        self.app.cfg["monitor_capture_index"] = choice
        self._sync_capture_rect_from_cfg()
        # Capture loop reads the rect from cfg every frame; no server
        # restart needed — the next grab() picks up the new region.

    def _on_remote_toggled(self, checked: bool) -> None:
        cfg = self.app.cfg
        cfg["monitor_remote_control_enabled"] = bool(checked)
        save_config(cfg)
        self._refresh_warning()

    def _on_copy(self) -> None:
        url = self._format_url()
        QGuiApplication.clipboard().setText(url)
        self.app.toasts.post("URL copied to clipboard", kind="info")

    def _on_regenerate(self) -> None:
        srv = self.app.monitor_server
        srv.regenerate_token()
        self.refresh()
        self.app.toasts.post("Token rotated — old links no longer work",
                             kind="info")
