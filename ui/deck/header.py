"""Deck header: wordmark, session / status chips, the EDITOR pane toggle,
utility icon buttons, START / STOP and the ESC ABORT reminder.

Exposes the same surface ``TopBar`` did so engine_bridge, the Hotkeys
card and commands keep working: ``start_btn``, ``stop_btn``, ``pill``
(a hidden :class:`StatusPill` whose ``tick()`` still runs so its
tooltip / labels stay current for anything that reads them),
``refresh_hint()``, ``on_toggle_overlay()`` and ``tick()``.
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
    "clicker": ("SETUP", "Click area shape, window lock, on-screen outline and timing details."),
    "recorder": ("STEPS", "Add, order and configure the steps of the sequence."),
    "ai": ("BOT", "Pick a bot, set its tick rate and dry run; author tools live here too."),
}


class EditorToggle(QToolButton):
    """Checkable pane button: pencil icon plus a mode-specific label
    (SETUP / STEPS / BOT). Checked means the pane is open; lime border
    and text, since open is a state."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("deck-editor-toggle")
        self.setCheckable(True)
        self.setFont(c.micro_font())
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setFixedHeight(c.BUTTON_H)
        self.setMinimumWidth(92)
        self.setCursor(Qt.PointingHandCursor)
        self.set_mode("clicker")
        self.setStyleSheet(
            f"QToolButton#deck-editor-toggle {{ background: {c.SURFACE}; "
            f"border: 1px solid {c.BORDER}; border-radius: {c.RADIUS_BUTTON}px; "
            f"color: {c.TEXT_SECONDARY}; padding: 0 10px 0 8px; }}"
            f"QToolButton#deck-editor-toggle:hover {{ background: {c.SURFACE_HIGH}; "
            f"color: {c.TEXT_PRIMARY}; }}"
            f"QToolButton#deck-editor-toggle:checked {{ border-color: {c.ACCENT}; "
            f"color: {c.ACCENT}; }}"
        )
        self.toggled.connect(self._sync_icon)
        self._sync_icon(False)

    def _sync_icon(self, checked: bool) -> None:
        self.setIcon(c.icon_pixmap("edit", 14, c.ACCENT if checked else c.TEXT_SECONDARY))

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
        sub.setContentsMargins(0, 2, 0, 2)
        sub.setSpacing(0)
        sub.addWidget(c.MicroLabel("HUMAN-LIKE CLICK ENGINE", c.TEXT_MICRO))
        sub.addWidget(c.MicroLabel(f"v{APP_VERSION} · OPERATIONAL", c.TEXT_MICRO))
        row.addWidget(self.subtitle)

        self.mode_picker = QComboBox()
        for label, mode in (("Click", "clicker"), ("Record", "recorder"), ("AI", "ai")):
            self.mode_picker.addItem(label, mode)
        self.mode_picker.setAccessibleName("Automation mode")
        self.mode_picker.activated.connect(
            lambda i: shell._on_mode_requested(self.mode_picker.itemData(i)))
        row.addWidget(self.mode_picker)

        row.addStretch(1)

        # -- Center chips + view switch -----------------------------------
        self.session_chip = Chip("SESSION", getattr(app, "session_id", None) or c.session_id())
        row.addWidget(self.session_chip)
        self.editor_btn = EditorToggle()
        self.editor_btn.toggled.connect(self.editorToggled)
        row.addWidget(self.editor_btn)
        self.status_chip = Chip("STATUS", "STANDBY", dot=True)
        row.addWidget(self.status_chip)

        row.addStretch(1)

        # -- Icon buttons -------------------------------------------------
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
        self.start_btn = QPushButton("START")
        self.start_btn.setProperty("variant", "primary")
        self.start_btn.setFixedHeight(c.BUTTON_H)
        self.start_btn.setMinimumWidth(92)
        self.start_btn.setFont(c.mono_font(c.SIZE_SM, QFont.Bold))
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(app._on_start)
        row.addWidget(self.start_btn)

        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setProperty("variant", "danger")
        self.stop_btn.setFixedHeight(c.BUTTON_H)
        self.stop_btn.setMinimumWidth(92)
        self.stop_btn.setFont(c.mono_font(c.SIZE_SM, QFont.Bold))
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.clicked.connect(app._on_stop)
        row.addWidget(self.stop_btn)
        self.refresh_hint()

        self.esc_hint = c.MicroLabel("ESC ABORT", c.TEXT_TERTIARY)
        self.esc_hint.setToolTip(
            "Esc always emergency-stops, regardless of state. Hard-locked; cannot be rebound.")
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
        self.start_btn.setToolTip(tooltip(
            "Begin clicking. Waits for the Pre-start delay so you can "
            "alt-tab into the target window before the first click.",
            shortcut=name_to_display(cfg.get("hotkey_start", "f6")),
        ))
        self.stop_btn.setToolTip(tooltip(
            "Halt clicking immediately. Escape always emergency-stops "
            "regardless of state.",
            shortcut=name_to_display(cfg.get("hotkey_stop", "f7")),
        ))

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
            text, color = "ACTIVE", c.ACCENT
        if self.status_chip.value.text() != text:
            self.status_chip.value.setText(text)
        if self.status_chip.dot is not None:
            self.status_chip.dot.set_color(color)
