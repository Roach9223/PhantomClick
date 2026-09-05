"""``SettingsPageBody``, form-row body for the Settings page.

Two :class:`SettingsGroup`s built from the design-system primitives:

* **Display**, target-monitor selector. Lifts the v1 single-primary-
  monitor limitation: a user with a dual-monitor setup can keep the GUI
  on one screen while the engine targets the other for ambient features
  (post-click drift clamp, idle wander roam area, watchdog corner
  failsafe, tracker locate).
* **Diagnostics**, start/stop a mouse trace recording to a JSONL file.
  The button doubles as a status indicator; a sibling label shows the
  live event count while a trace is running.

Engine wiring (``app.cfg["target_monitor"]``, ``utils.mouse_trace``,
``app._push_config_to_clicker`` ) is preserved verbatim from the prior
:class:`SettingsCard`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ui.config_io import _config_dir, save_config
from utils import mouse_trace

from .. import icons, theme as t
from ..format import fmt_count
from ..screen_utils import screen_label
from ..widgets.group_header import GroupHeader
from ..widgets.ios_switch import IOSSwitch
from ..widgets.quiet_button import QuietAccentButton
from ..widgets.segmented import SegmentedControl
from ..widgets.settings_group import SettingsGroup
from ..widgets.settings_row import SettingsRow


class SettingsPageBody(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Display ──────────────────────────────────────────────────
        outer.addWidget(GroupHeader("Display"))
        display_group = SettingsGroup()
        display_group.add_row(self._build_monitor_row())
        outer.addWidget(display_group)

        outer.addSpacing(t.SP_XL)

        # ── Input ───────────────────────────────────────────────────
        # Backend that delivers KIND_KEY + key-timer keystrokes to the
        # OS. Lives here (not Behavior) because it's a system / I/O
        # concern, not a humanization knob. Auto suits nearly everyone
        # and needs no hardware; Serial HID (an Arduino) is the advanced
        # path for NXT-class anti-cheat, so its port row only appears
        # once that backend is picked.
        outer.addWidget(GroupHeader("Input"))
        input_group = SettingsGroup()
        self._key_input_row = self._build_key_input_row()
        input_group.add_row(self._key_input_row)
        self._serial_hid_row = self._build_serial_hid_port_row()
        input_group.add_row(self._serial_hid_row)
        self._input_group = input_group
        outer.addWidget(input_group)
        self._sync_serial_hid_row()

        outer.addSpacing(t.SP_XL)

        # ── Network ─────────────────────────────────────────────────
        # The only outbound HTTP the app can make (besides serving the
        # LAN Monitor page) lives behind this switch.
        outer.addWidget(GroupHeader("Network"))
        net_group = SettingsGroup()
        net_group.add_row(self._build_wiki_fetch_row())
        outer.addWidget(net_group)

        outer.addSpacing(t.SP_XL)

        # ── Diagnostics ─────────────────────────────────────────────
        outer.addWidget(GroupHeader("Diagnostics"))
        diag_group = SettingsGroup()
        diag_group.add_row(self._build_trace_row())
        outer.addWidget(diag_group)

        outer.addSpacing(t.SP_MD)

        # ── Footer hint ─────────────────────────────────────────────
        footer = QLabel(
            "Auto-detect follows your active zone; manual selection pins "
            "the engine to a screen, useful when the GUI and the game "
            "live on different monitors. Mouse traces save to the install "
            "directory and open in Explorer when you stop recording."
        )
        footer.setProperty("role", "footer-hint")
        footer.setWordWrap(True)
        outer.addWidget(footer)

        # Drives the live event-count display while a trace is running.
        self._trace_tick = QTimer(self)
        self._trace_tick.setInterval(250)
        self._trace_tick.timeout.connect(self._refresh_trace_status)
        self._refresh_trace_status()

    # -- Monitor row -------------------------------------------------------

    def _build_monitor_row(self) -> SettingsRow:
        row = SettingsRow(
            "Target monitor",
            desc=(
                "Which screen the engine treats as 'the screen' for "
                "post-click drift, idle wander, watchdog and tracker."
            ),
        )
        self.combo = QComboBox()
        self.combo.setCursor(Qt.PointingHandCursor)
        self.combo.setMinimumHeight(t.INPUT_H)
        self.combo.setMinimumWidth(260)
        self._populate_combo()
        self.combo.currentIndexChanged.connect(self._on_change)
        row.set_control(self.combo)
        return row

    def _populate_combo(self) -> None:
        """Fill the dropdown with 'Auto-detect' + one entry per attached
        screen. Re-callable on monitor plug/unplug events."""
        self.combo.blockSignals(True)
        self.combo.clear()

        screens = QGuiApplication.screens() or []
        primary = QGuiApplication.primaryScreen()

        # Resolve what "Auto-detect" picks right now so the user can see
        # whether it'd target the right monitor without switching.
        auto_label = "Auto-detect (zone's monitor)"
        if primary is not None:
            auto_label = f"Auto-detect, currently {screen_label(primary)}"
        self.combo.addItem(auto_label, userData="auto")

        for i, s in enumerate(screens):
            label = screen_label(s, index=i, is_primary=(s is primary))
            self.combo.addItem(label, userData=str(i))

        idx = self.app._explicit_target_screen_index()
        cur = "auto" if idx is None else str(idx)
        for i in range(self.combo.count()):
            if self.combo.itemData(i) == cur:
                self.combo.setCurrentIndex(i)
                break
        self.combo.blockSignals(False)

    def _on_change(self, _idx: int) -> None:
        self.app.set_target_monitor(self.combo.currentData() or "auto")

    def refresh_monitors(self) -> None:
        """Re-enumerate screens. Called from App on screenAdded/Removed."""
        self._populate_combo()

    # -- Key input rows ---------------------------------------------------

    def _build_key_input_row(self) -> SettingsRow:
        """Pick the keyboard-event backend for KIND_KEY steps + key
        timers. Auto suits 95% of users: SendInput everywhere unless
        the Interception driver is installed, then events go through
        the driver as hardware-flagged input. RuneScape NXT specifically
        rejects everything software-only including Interception, for
        that case ``Serial HID`` routes through an Arduino flashed as a
        USB keyboard (firmware in ``firmware/phantomhid``)."""
        valid = ("auto", "sendinput", "interception", "serial_hid")
        current = str(self.app.cfg.get("key_input_method", "auto") or "auto").lower()
        if current not in valid:
            current = "auto"

        seg = SegmentedControl(
            options=[
                ("auto", "Auto"),
                ("sendinput", "SendInput"),
                ("interception", "Interception"),
                ("serial_hid", "Serial HID"),
            ],
            value=current,
        )
        seg.setToolTip(
            "How keystrokes (Key steps, key timers, bots) reach Windows. "
            "Mouse clicks are not affected.\n\n"
            "Auto: works everywhere with no setup. Uses the Interception "
            "driver if you installed it, else the standard Windows path.\n"
            "SendInput: force the standard Windows path.\n"
            "Interception: force the hardware-flagged driver path.\n"
            "Serial HID (advanced): an Arduino Leonardo flashed with "
            "firmware/phantomhid acts as a real USB keyboard. Only needed "
            "for games such as RuneScape NXT that drop software keystrokes."
        )
        seg.valueChanged.connect(self._on_key_input_method_change)
        row = SettingsRow(
            "Keyboard backend",
            desc=(
                "Leave on Auto; it works with no extra hardware. Serial HID "
                "is an advanced option for games that block software "
                "keystrokes and needs an Arduino."
            ),
        )
        row.set_control(seg)
        return row

    def _build_serial_hid_port_row(self) -> SettingsRow:
        """COM-port picker for the Serial HID backend. Always shown so
        the user can pre-pick a port before switching the backend; only
        meaningful when serial_hid is the current backend, but harmless
        otherwise."""
        port_combo = QComboBox()
        port_combo.setMinimumWidth(220)
        port_combo.setToolTip(
            "COM port your Arduino enumerated as. Same one Arduino IDE "
            "used to upload the sketch. If the dropdown is empty, plug "
            "the board in and click Refresh (or restart PhantomClick)."
        )
        self._serial_hid_port_combo = port_combo
        self._populate_serial_hid_ports()
        port_combo.currentTextChanged.connect(self._on_serial_hid_port_change)
        row = SettingsRow(
            "Serial HID port",
            desc=(
                "COM port of the Arduino running PhantomHID (flash it from "
                "firmware/phantomhid first; the README there has the steps). "
                "Shown only while Serial HID is the backend."
            ),
        )
        row.set_control(port_combo)
        return row

    def _sync_serial_hid_row(self) -> None:
        """The port row is advanced-only: visible when Serial HID is the
        backend, hidden otherwise so most users never see it."""
        row = getattr(self, "_serial_hid_row", None)
        if row is None:
            return
        serial = str(self.app.cfg.get("key_input_method", "auto") or "auto").lower() == "serial_hid"
        if row.isVisible() != serial:
            row.setVisible(serial)
        # The last visible row drops its hairline.
        try:
            self._key_input_row.set_last(not serial)
            row.set_last(serial)
        except Exception:
            pass

    def _populate_serial_hid_ports(self) -> None:
        """Fill the COM-port dropdown from pyserial's port list. If
        pyserial isn't installed, leave only the saved value as a hint
        so the UI still works, the actual error surfaces at engine
        start through SerialHidBackend._init_error."""
        combo = getattr(self, "_serial_hid_port_combo", None)
        if combo is None:
            return
        saved = str(self.app.cfg.get("serial_hid_port", "") or "")
        combo.blockSignals(True)
        combo.clear()
        try:
            import serial.tools.list_ports as _lp  # type: ignore[import-not-found]
            ports = list(_lp.comports())
        except Exception:
            ports = []
        if not ports and saved:
            combo.addItem(saved)
        for p in ports:
            label = f"{p.device}, {p.description}" if p.description else p.device
            combo.addItem(label, userData=p.device)
        if saved:
            for i in range(combo.count()):
                if combo.itemData(i) == saved or combo.itemText(i).startswith(saved + " "):
                    combo.setCurrentIndex(i)
                    break
        combo.blockSignals(False)

    def _on_key_input_method_change(self, value: str) -> None:
        if value not in ("auto", "sendinput", "interception", "serial_hid"):
            return
        self.app.cfg["key_input_method"] = value
        save_config(self.app.cfg)
        self.app._push_config_to_clicker()
        self._sync_serial_hid_row()
        if value == "serial_hid":
            self._populate_serial_hid_ports()

    def _on_serial_hid_port_change(self, _label: str) -> None:
        combo = getattr(self, "_serial_hid_port_combo", None)
        if combo is None:
            return
        # Prefer userData (the bare device name); fall back to the visible
        # label if the dropdown was hand-populated (e.g. saved value with
        # no pyserial enumeration available).
        device = combo.currentData() or combo.currentText().split(", ")[0].strip()
        self.app.cfg["serial_hid_port"] = str(device or "")
        save_config(self.app.cfg)
        self.app._push_config_to_clicker()

    # ── Network row ──────────────────────────────────────────────────────

    def _build_wiki_fetch_row(self) -> SettingsRow:
        row = SettingsRow(
            "Fetch item icons from runescape.wiki",
            desc=(
                "Lets the AI item library download inventory icons. This "
                "makes outbound HTTP requests to runescape.wiki when you "
                "add an item and at bot start if an icon is missing from "
                "the local cache. Off means no request ever leaves this PC."
            ),
        )
        switch = IOSSwitch()
        switch.setChecked(bool(self.app.cfg.get("ai_wiki_fetch_enabled", False)))
        switch.toggled.connect(self._on_wiki_fetch_toggled)
        row.set_control(switch)
        return row

    def _on_wiki_fetch_toggled(self, checked: bool) -> None:
        self.app.cfg["ai_wiki_fetch_enabled"] = bool(checked)
        save_config(self.app.cfg)
        if hasattr(self.app, "toasts"):
            self.app.toasts.post(
                "Wiki fetch on: item icons will be downloaded when needed."
                if checked else
                "Wiki fetch off: only cached icons are used.",
                kind="info",
            )

    # -- Mouse trace row ---------------------------------------------------

    def _build_trace_row(self) -> SettingsRow:
        row = SettingsRow(
            "Mouse trace",
            desc=(
                "Capture every cursor write + click event to a JSONL file "
                "for diagnosing movement issues."
            ),
        )

        cluster = QWidget()
        h = QHBoxLayout(cluster)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(t.SP_SM)

        self.trace_status = QLabel("")
        self.trace_status.setProperty("role", "row-desc")
        self.trace_status.setStyleSheet(f"font-family: {t.FONT_MONO};")
        self.trace_status.setMinimumWidth(120)
        self.trace_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(self.trace_status)

        self.trace_btn = QuietAccentButton("Record")
        self.trace_btn.setIcon(icons.icon("record-dot", color=t.DANGER))
        self.trace_btn.setToolTip(
            "Start logging cursor + click events to "
            "mouse_trace_<ts>.jsonl in the install directory. "
            "Click again to stop."
        )
        self.trace_btn.clicked.connect(self._toggle_trace)
        h.addWidget(self.trace_btn)

        row.set_control(cluster)
        return row

    def _toggle_trace(self) -> None:
        if mouse_trace.is_enabled():
            self._stop_trace()
        else:
            self._start_trace()

    def _start_trace(self) -> None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = Path(_config_dir()) / f"mouse_trace_{ts}.jsonl"
        if mouse_trace.enable(str(path)):
            self.trace_btn.setText("Stop")
            self.trace_btn.setIcon(icons.icon("stop"))
            self._trace_tick.start()
            self._refresh_trace_status()
            if hasattr(self.app, "toasts"):
                self.app.toasts.post(
                    f"Recording mouse trace → {path.name}",
                    kind="info",
                )

    def _stop_trace(self) -> None:
        path = mouse_trace.disable()
        self._trace_tick.stop()
        self.trace_btn.setText("Record")
        self.trace_btn.setIcon(icons.icon("record-dot", color=t.DANGER))
        self._refresh_trace_status()
        if path is None:
            return
        if hasattr(self.app, "toasts"):
            self.app.toasts.post(
                f"Trace saved → {Path(path).name}",
                kind="success",
            )
        # Open the containing folder in Explorer so the user can grab the
        # file. /select highlights it.
        try:
            if sys.platform == "win32":
                subprocess.Popen(
                    ["explorer", "/select,", os.path.normpath(path)],
                    close_fds=True,
                )
        except Exception:
            pass

    def _refresh_trace_status(self) -> None:
        if mouse_trace.is_enabled():
            n = mouse_trace.event_count()
            self.trace_status.setText(f"{fmt_count(n)} events")
        else:
            self.trace_status.setText("idle")


# Back-compat alias: ui/app.py + commands.py still reference SettingsCard.
SettingsCard = SettingsPageBody
