"""Deck header: wordmark, session / status chips, the pane toggle, the
subsystem strip, utility icon buttons, START / STOP and the ESC reminder.

Exposes the same surface ``TopBar`` did so engine_bridge, the Hotkeys
card and commands keep working: ``start_btn``, ``stop_btn``, ``pill``
(a hidden :class:`StatusPill` whose ``tick()`` still runs so its
tooltip / labels stay current for anything that reads them),
``refresh_hint()``, ``on_toggle_overlay()`` and ``tick()``.

The subsystem strip (:class:`SubsystemStrip`) is the at-a-glance health
row: HID, CAP, HOT, LAN as coloured squares. Green is nominal, amber is
degraded, red is a fault, grey is off by design. Each square opens the
page where it is fixed.
"""

from __future__ import annotations

from typing import Optional

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout,
    QWidget,
)

from modules.clicker import ClickerState
from modules.hotkey_manager import name_to_display
from modules.zone_lock import HOLD_STATUSES
from ui.tooltip_fmt import tooltip

from ..widgets.status_pill import StatusPill
from . import common as c

HEADER_H = 52


# The pane is named after what it holds in each mode, not "editor": the
# Click pane is one-time setup, the Record pane is the step list, the AI
# pane is the bot picker.
PANE_LABELS = {
    "clicker": ("SETUP", "Click zone shape, window lock, on-screen outline and timing details."),
    "recorder": ("STEPS", "Add, order and configure the steps of the sequence."),
    "ai": ("BOT", "Pick a bot, set its tick rate and dry run; author tools live here too."),
}


class EditorToggle(QToolButton):
    """Checkable pane button: pencil icon plus a mode-specific label
    (SETUP / STEPS / BOT). It is the loudest control after START, since
    the pane is where a new user does everything: ice outline and text
    while closed, solid ice while open."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("deck-editor-toggle")
        self.setCheckable(True)
        self.setFont(c.label_font(c.SIZE_SM, QFont.Bold, 1.0))
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setFixedHeight(c.BUTTON_H)
        self.setMinimumWidth(118)
        self.setCursor(Qt.PointingHandCursor)
        self.set_mode("clicker")
        self.setStyleSheet(
            f"QToolButton#deck-editor-toggle {{ background: {c.SURFACE}; "
            f"border: 1px solid {c.ACCENT}; border-radius: {c.RADIUS_BUTTON}px; "
            f"color: {c.ACCENT}; padding: 0 12px 0 10px; }}"
            f"QToolButton#deck-editor-toggle:hover {{ background: {c.SURFACE_HIGH}; }}"
            f"QToolButton#deck-editor-toggle:checked {{ background: {c.ACCENT}; "
            f"border-color: {c.ACCENT}; color: {c.BG}; }}"
            f"QToolButton#deck-editor-toggle:checked:hover {{ background: {c.ACCENT}; }}"
        )
        self.toggled.connect(self._sync_icon)
        self._sync_icon(False)

    def _sync_icon(self, checked: bool) -> None:
        self.setIcon(c.icon_pixmap("edit", 14, c.BG if checked else c.ACCENT))

    def set_mode(self, mode: str) -> None:
        label, what = PANE_LABELS.get(mode, PANE_LABELS["clicker"])
        self.setText(label)
        self.setToolTip(tooltip(
            f"Show or hide the {label.lower()} pane beside the viewport. {what}",
            shortcut="Ctrl+E"))

    def set_open(self, open_: bool) -> None:
        """Reflect the pane state without re-emitting ``toggled``."""
        if self.isChecked() != bool(open_):
            self.blockSignals(True)
            self.setChecked(bool(open_))
            self.blockSignals(False)
            self._sync_icon(bool(open_))


class Chip(QFrame):
    def __init__(self, key: str, value: str = "", dot: bool = False,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("deck-chip")
        self.setStyleSheet(
            f"QFrame#deck-chip {{ background: {c.SURFACE}; border: 1px solid {c.BORDER}; "
            f"border-radius: 4px; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 3, 8, 3)
        row.setSpacing(8)
        self.dot: Optional[c.Dot] = None
        if dot:
            self.dot = c.Dot(c.STATUS_IDLE, 6)
            row.addWidget(self.dot)
        row.addWidget(c.MicroLabel(key, c.TEXT_MICRO))
        self.value = c.MonoLabel(value, c.TEXT_PRIMARY, c.SIZE_XS)
        row.addWidget(self.value)


# Subsystem levels and the colour each paints.
LEVEL_COLORS = {
    "ok": c.RUN,
    "warn": c.WARN,
    "fault": c.STOP,
    "off": c.STATUS_IDLE,
}


class _SubsystemCell(QFrame):
    clicked = Signal(str)

    def __init__(self, key: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.key = key
        self.setObjectName("deck-subsys")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "QFrame#deck-subsys { background: transparent; border: none; border-radius: 3px; }"
            f"QFrame#deck-subsys:hover {{ background: {c.SURFACE_HIGH}; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(5, 2, 6, 2)
        row.setSpacing(5)
        self.dot = c.Dot(c.STATUS_IDLE, 7)
        row.addWidget(self.dot)
        self.label = c.MicroLabel(key, c.TEXT_TERTIARY)
        row.addWidget(self.label)
        self._level = "off"

    def set_state(self, level: str, tip: str) -> None:
        color = LEVEL_COLORS.get(level, c.STATUS_IDLE)
        if level != self._level:
            self._level = level
            self.dot.set_color(color)
            self.label.set_color(c.TEXT_SECONDARY if level == "ok" else
                                 (color if level in ("warn", "fault") else c.TEXT_TERTIARY))
        if self.toolTip() != tip:
            self.setToolTip(tip)

    def level(self) -> str:
        return self._level

    def mousePressEvent(self, event):  # noqa: N802 (Qt name)
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.key)
            event.accept()
            return
        super().mousePressEvent(event)


class SubsystemStrip(QFrame):
    """``HID · CAP · HOT · LAN`` health squares. The shell's tick feeds
    :meth:`refresh`; a click routes to the page that fixes the subsystem."""

    KEYS = ("HID", "CAP", "HOT", "LAN")

    def __init__(self, app, shell, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app = app
        self.shell = shell
        self.setObjectName("deck-subsys-strip")
        self.setStyleSheet(
            f"QFrame#deck-subsys-strip {{ background: {c.SURFACE}; border: 1px solid {c.BORDER}; "
            f"border-radius: 4px; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 1, 3, 1)
        row.setSpacing(2)
        self.cells: dict[str, _SubsystemCell] = {}
        for key in self.KEYS:
            cell = _SubsystemCell(key)
            cell.clicked.connect(self._on_click)
            row.addWidget(cell)
            self.cells[key] = cell

    def _on_click(self, key: str) -> None:
        page = {"HID": "settings", "CAP": "settings", "HOT": "hotkeys", "LAN": "monitor"}.get(key)
        if page:
            try:
                self.shell.show_page(page)
            except Exception:
                pass

    def states(self) -> dict[str, str]:
        return {k: cell.level() for k, cell in self.cells.items()}

    def refresh(self) -> None:
        app = self.app
        # HID: the cached probe on the ENGINE STATUS panel, so the serial
        # port is not reopened every tick.
        ok, message = True, ""
        try:
            ok, message = self.shell.right.engine_status.hid_state()
        except Exception:
            pass
        method = str(app.cfg.get("key_input_method", "auto") or "auto").upper()
        if ok:
            self.cells["HID"].set_state("ok", f"Key input: {method}. {message or 'Ready.'}\nClick to open Settings.")
        else:
            self.cells["HID"].set_state("fault", f"Key input {method} is not available: {message}\n"
                                        "Click to open Settings and fix the backend or port.")
        # CAP: the viewport's capture worker.
        vp = getattr(self.shell, "viewport", None)
        if vp is None or not vp.is_capturing():
            self.cells["CAP"].set_state("off", "Screen capture is idle (viewport hidden).\nClick to open Settings.")
        elif getattr(vp, "_no_capture", False):
            self.cells["CAP"].set_state("fault", f"Screen capture failed: {getattr(vp, '_fail_reason', '') or 'no frames'}.\n"
                                        "Click to open Settings and check the target monitor.")
        elif vp.has_frame() and time.monotonic() - getattr(vp, "_last_frame_at", 0.0) < 3.0:
            self.cells["CAP"].set_state("ok", "Screen capture is live.\nClick to open Settings.")
        else:
            self.cells["CAP"].set_state("warn", "Screen capture is starting or stalled.\nClick to open Settings.")
        # HOT: the global hotkey listener thread.
        try:
            alive = bool(app.hotkeys.is_alive())
        except Exception:
            alive = False
        keys = " / ".join(name_to_display(str(app.cfg.get(k, ""))).upper()
                          for k in ("hotkey_start", "hotkey_stop", "hotkey_pause"))
        if alive:
            self.cells["HOT"].set_state("ok", f"Global hotkeys armed: {keys}. Esc always stops.\nClick to rebind.")
        else:
            self.cells["HOT"].set_state("fault", "Hotkey listener is not running. Restart the app if this persists.\nClick to open Hotkeys.")
        # LAN: the opt-in monitor server. Off is the normal state.
        server = getattr(app, "monitor_server", None)
        running = False
        if server is not None:
            probe = getattr(server, "is_running", False)
            try:
                running = bool(probe() if callable(probe) else probe)
            except Exception:
                running = False
        if running:
            try:
                url = str(server.lan_url())
            except Exception:
                url = ""
            self.cells["LAN"].set_state("ok", f"LAN monitor is streaming at {url}.\nClick to open the Monitor page.")
        else:
            self.cells["LAN"].set_state("off", "LAN monitor is off. Nothing leaves this PC.\nClick to open the Monitor page.")


class DeckHeader(QFrame):
    editorToggled = Signal(bool)   # True = open the editor pane

    def __init__(self, app, shell, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app = app
        self.shell = shell
        self.setObjectName("deck-header")
        self.setFixedHeight(HEADER_H)
        self.setStyleSheet(
            f"QFrame#deck-header {{ background: {c.BG}; border-bottom: 1px solid {c.BORDER}; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 6, 14, 6)
        row.setSpacing(12)

        # -- Wordmark -----------------------------------------------------
        from ui.app import APP_VERSION
        self.wordmark = QLabel("PhantomClick")
        self.wordmark.setFont(c.display_font(c.SIZE_TITLE, QFont.Bold))
        self.wordmark.setStyleSheet(f"color: {c.TEXT_PRIMARY}; background: transparent;")
        row.addWidget(self.wordmark)
        self.subtitle = QWidget()
        sub = QVBoxLayout(self.subtitle)
        sub.setContentsMargins(0, 3, 0, 3)
        sub.setSpacing(0)
        sub.addWidget(c.MicroLabel("HUMAN-LIKE CLICK ENGINE", c.TEXT_MICRO))
        sub.addWidget(c.MicroLabel(f"v{APP_VERSION}", c.TEXT_MICRO))
        row.addWidget(self.subtitle)

        self.mode_picker = QComboBox()
        for label, mode in (("Click", "clicker"), ("Record", "recorder"), ("AI", "ai")):
            self.mode_picker.addItem(label, mode)
        self.mode_picker.setAccessibleName("Automation mode")
        self.mode_picker.activated.connect(
            lambda i: shell._on_mode_requested(self.mode_picker.itemData(i)))
        row.addWidget(self.mode_picker)

        row.addStretch(1)

        # -- Center chips -------------------------------------------------
        self.session_chip = Chip("SESSION", getattr(app, "session_id", None) or c.session_id())
        row.addWidget(self.session_chip)
        self.status_chip = Chip("STATUS", "STANDBY", dot=True)
        row.addWidget(self.status_chip)

        row.addStretch(1)

        # -- Pane switch, subsystem strip, icon buttons ---------------------
        # The pane button leads the right-hand cluster so it reads as the
        # first thing to press, ahead of the health squares.
        self.editor_btn = EditorToggle()
        self.editor_btn.toggled.connect(self.editorToggled)
        row.addWidget(self.editor_btn)
        row.addSpacing(6)
        self.subsystems = SubsystemStrip(app, shell)
        row.addWidget(self.subsystems)
        self.monitor_btn = c.IconButton("monitor", tooltip=tooltip(
            "Open the Monitor page (LAN stream + phone control).", shortcut="Ctrl+4"))
        self.monitor_btn.clicked.connect(lambda: shell.show_page("monitor"))
        self.overlay_btn = c.IconButton("eye", tooltip=tooltip(
            "Show or hide on-screen zone outlines.", shortcut="Ctrl+H"))
        self.overlay_btn.clicked.connect(self.on_toggle_overlay)
        self.settings_btn = c.IconButton("settings", tooltip=tooltip(
            "Open settings.", shortcut="Ctrl+5"))
        self.settings_btn.clicked.connect(lambda: shell.show_page("settings"))
        self.fullscreen_btn = c.IconButton("expand", tooltip="Toggle fullscreen.")
        self.fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        for b in (self.monitor_btn, self.overlay_btn, self.settings_btn, self.fullscreen_btn):
            row.addWidget(b)
        self._sync_overlay_icon()

        # -- START / STOP -----------------------------------------------------
        # Fonts come from the stylesheet's QPushButton rule (Barlow).
        self.start_btn = QPushButton("START")
        self.start_btn.setProperty("variant", "primary")
        self.start_btn.setFixedHeight(c.BUTTON_H)
        self.start_btn.setMinimumWidth(92)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(app._on_start)
        row.addWidget(self.start_btn)

        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setProperty("variant", "danger")
        self.stop_btn.setFixedHeight(c.BUTTON_H)
        self.stop_btn.setMinimumWidth(92)
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.clicked.connect(app._on_stop)
        row.addWidget(self.stop_btn)
        self._start_tip = ""
        self.refresh_hint()

        self.esc_hint = c.MicroLabel("ESC STOPS", c.TEXT_TERTIARY)
        self.esc_hint.setToolTip(
            "Esc always stops everything, in any state. Hard-locked; cannot be rebound.")
        row.addWidget(self.esc_hint)

        # Hidden status pill keeps ticking for anything that reads it.
        self.pill = StatusPill(app)
        self.pill.hide()

    # -- Topbar-compatible surface -------------------------------------------

    def set_compact(self, compact: bool) -> None:
        self.subtitle.setVisible(not compact)
        self.session_chip.setVisible(not compact)
        self.mode_picker.setVisible(compact)

    def refresh_hint(self) -> None:
        cfg = self.app.cfg
        self._start_tip = tooltip(
            "Begin clicking. Waits for the Pre-start delay so you can "
            "alt-tab into the target window before the first click.",
            shortcut=name_to_display(cfg.get("hotkey_start", "f6")),
        )
        self.start_btn.setToolTip(self._start_tip)
        self.stop_btn.setToolTip(tooltip(
            "Stop now. Esc always stops, in any state.",
            shortcut=name_to_display(cfg.get("hotkey_stop", "f7")),
        ))

    def set_start_blocked(self, reason: str) -> None:
        """Dim START and put the reason on it while setup is incomplete;
        clear both once the engine may start."""
        idle = self.app._state_str == ClickerState.IDLE
        enabled = idle and not reason
        if self.start_btn.isEnabled() != enabled:
            self.start_btn.setEnabled(enabled)
        tip = f"Blocked: {reason}" if (reason and idle) else self._start_tip
        if self.start_btn.toolTip() != tip:
            self.start_btn.setToolTip(tip)

    def _sync_overlay_icon(self) -> None:
        on = bool(self.app.cfg.get("show_zone_overlay", True))
        self.overlay_btn.set_icon("eye" if on else "eye-off",
                                  c.ACCENT if on else c.TEXT_TERTIARY)

    def on_toggle_overlay(self) -> None:
        # App.set_overlay_visible saves, applies and calls back into
        # _sync_overlay_icon, so the icon and the editor switch agree.
        self.app.toggle_overlay_visible()

    def _toggle_fullscreen(self) -> None:
        win = self.window()
        if win.isFullScreen():
            win.showNormal()
        else:
            win.showFullScreen()

    def set_editor_open(self, open_: bool) -> None:
        self.editor_btn.set_open(open_)

    def set_view(self, view: str) -> None:
        """Compatibility: ``"editor"`` means the pane is open."""
        self.set_editor_open(view == "editor")

    def _session_text(self, running: bool) -> str:
        sid = getattr(self.app, "session_id", None) or c.session_id()
        if not running:
            return sid
        # Click / Record report their own uptime; a bot run falls back to
        # the START timestamp the App records.
        uptime = 0.0
        if self.app.clicker.state != ClickerState.IDLE:
            uptime = float(getattr(self.app.clicker, "session_uptime_seconds", 0.0) or 0.0)
        else:
            started = float(getattr(self.app, "_session_started_at", 0.0) or 0.0)
            if started > 0:
                uptime = time.monotonic() - started
        return f"{sid}  T+{c.format_hms(uptime)}"

    def tick(self) -> None:
        self.mode_picker.setCurrentIndex(max(0, self.mode_picker.findData(self.app._active_mode)))
        self.mode_picker.setEnabled(self.app._state_str == ClickerState.IDLE)
        try:
            self.pill.tick()
        except Exception:
            pass
        state = self.app._state_str
        running = state != ClickerState.IDLE
        paused = running and c.engine_paused(self.app)
        holding = False
        if running:
            # Engine is waiting for a window-locked zone's window to
            # come back. Amber, like HOLD, and it wins over HOLD because
            # a paused engine on a lost window still has no target.
            try:
                holding = self.app.clicker.target_status()[0] in HOLD_STATUSES
            except Exception:
                holding = False
        session_text = self._session_text(running)
        if self.session_chip.value.text() != session_text:
            self.session_chip.value.setText(session_text)
        if holding:
            text, color = "TARGET LOST", c.WARN
        elif paused:
            text, color = "HOLD", c.WARN
        elif state == ClickerState.IDLE:
            text, color = "STANDBY", c.STATUS_IDLE
        elif state == ClickerState.STARTING:
            text, color = "ARMING", c.WARN
        else:
            text, color = "RUNNING", c.RUN
        if self.status_chip.value.text() != text:
            self.status_chip.value.setText(text)
            self.status_chip.value.set_color(c.RUN if text == "RUNNING" else c.TEXT_PRIMARY)
        if self.status_chip.dot is not None:
            self.status_chip.dot.set_color(color)
        try:
            self.subsystems.refresh()
        except Exception:
            pass
