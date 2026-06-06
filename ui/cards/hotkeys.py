"""``HotkeysPageBody`` — form-row body for the Hotkeys page.

Two :class:`SettingsGroup`s:

* **Global hotkeys** — Start / Stop rebindable rows + a locked Esc row.
  Each rebindable row carries a :class:`KeyChip` showing the current
  binding and a :class:`QuietAccentButton` ``Change``. Esc shows only
  the chip.
* **In-app shortcuts** — read-only reference rows pulled from the
  shared ``app.commands`` registry, so any new command with a
  ``shortcut`` field shows up automatically.

Rebind flow runs across two threads — pynput's listener captures the
next keypress and we marshal back to the Qt thread via
``QTimer.singleShot``. The flow itself is unchanged from the prior
``HotkeysCard`` implementation; only the chrome around it was
migrated to the design-system primitives.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from modules.hotkey_manager import name_to_display
from ui.config_io import save_config

from .. import theme as t
from ..widgets.empty_state import EmptyState
from ..widgets.group_header import GroupHeader
from ..widgets.ios_switch import IOSSwitch
from ..widgets.key_chip import KeyChip
from ..widgets.quiet_button import QuietAccentButton
from ..widgets.settings_group import SettingsGroup
from ..widgets.settings_row import SettingsRow


REBIND_TIMEOUT_MS = 8000

_REBINDABLE = (
    ("start", "Start clicking",
     "Begin clicking after the pre-start delay."),
    ("stop", "Halt clicking",
     "Stop the engine immediately."),
    ("capture", "Capture frame",
     "Freeze the current screen and drag a rectangle to save it as a "
     "snapshot in the active bundle's library."),
)


class HotkeysPageBody(QWidget):
    # Cross-thread marshal: the pynput listener fires capture callbacks
    # from a non-Qt thread. ``QTimer.singleShot(0, ...)`` is silently
    # dropped from threads with no event loop, so we use a queued-
    # connection signal instead — Qt routes the emit through the event
    # loop of whatever thread owns this widget (the main thread).
    _captureReceived = Signal(str, str)  # (action, name)

    def __init__(self, app):
        super().__init__()
        self.app = app
        self._timeouts: dict[str, QTimer] = {}
        self._chips: dict[str, KeyChip] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._captureReceived.connect(
            self._apply_capture, Qt.QueuedConnection,
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Global hotkeys ───────────────────────────────────────────
        outer.addWidget(GroupHeader("Global hotkeys"))
        global_group = SettingsGroup()

        for action, title, desc in _REBINDABLE:
            global_group.add_row(self._build_rebind_row(action, title, desc))

        global_group.add_row(self._build_locked_row(
            "Emergency stop",
            "Hard-locked for safety — cannot be rebound.",
            "Esc",
        ))
        outer.addWidget(global_group)

        outer.addSpacing(t.SP_XL)

        # ── Alerts ──────────────────────────────────────────────────
        outer.addWidget(GroupHeader("Alerts"))
        alerts_group = SettingsGroup()
        alerts_group.add_row(self._build_sound_on_stop_row())
        outer.addWidget(alerts_group)

        outer.addSpacing(t.SP_XL)

        # ── In-app shortcuts ────────────────────────────────────────
        outer.addWidget(GroupHeader("In-app shortcuts"))
        inapp_group = SettingsGroup()
        any_added = False
        for cmd_label, sc in self._collect_in_app_shortcuts():
            row = SettingsRow(cmd_label)
            row.set_control(KeyChip(sc))
            inapp_group.add_row(row)
            any_added = True
        if not any_added:
            inapp_group.add_widget(EmptyState(
                title="No app shortcuts registered",
                description=(
                    "Commands with keyboard bindings will show up here. "
                    "Open the command palette with Ctrl+K to browse them all."
                ),
            ))
        outer.addWidget(inapp_group)

        outer.addSpacing(t.SP_MD)

        # ── Footer hint ─────────────────────────────────────────────
        footer = QLabel(
            "Global hotkeys work even when a fullscreen game is focused. "
            "Esc is hard-locked for safety."
        )
        footer.setProperty("role", "footer-hint")
        footer.setWordWrap(True)
        outer.addWidget(footer)

    # -- Row builders ------------------------------------------------------

    def _build_rebind_row(self, action: str, title: str, desc: str) -> SettingsRow:
        row = SettingsRow(title, desc=desc)
        chip = KeyChip(name_to_display(self.app.cfg[f"hotkey_{action}"]))
        self._chips[action] = chip

        # Not locker-registered: rebinding a hotkey mid-run is safe — the
        # listener updates start_name/stop_name/capture_name atomically and
        # _on_press reads them on every keypress. Locking these buttons
        # during a run only matters if the user can't stop the bot via the
        # current Stop hotkey, in which case they NEED to rebind.
        btn = QuietAccentButton("Change")
        btn.setToolTip(
            f"Press any key to bind it as the global {action} hotkey."
        )
        btn.clicked.connect(lambda _=False, a=action: self.on_rebind(a))
        self._buttons[action] = btn

        # Compose chip + button as a single right-side cluster.
        cluster = QWidget()
        h = QHBoxLayout(cluster)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(t.SP_SM)
        h.addWidget(chip)
        h.addWidget(btn)
        row.set_control(cluster)
        return row

    def _build_locked_row(self, title: str, desc: str, key_text: str) -> SettingsRow:
        row = SettingsRow(title, desc=desc)
        row.set_control(KeyChip(key_text))
        return row

    def _build_sound_on_stop_row(self) -> SettingsRow:
        row = SettingsRow(
            "Sound on stop",
            desc=(
                "Plays a short Windows beep when the engine halts on its own "
                "(corner stop, crash, session-complete). Manual stops stay silent."
            ),
        )
        switch = IOSSwitch()
        switch.setChecked(bool(self.app.cfg.get("sound_on_stop", True)))
        switch.toggled.connect(self._on_sound_on_stop_toggled)
        row.set_control(switch)
        return row

    def _on_sound_on_stop_toggled(self, checked: bool) -> None:
        self.app.cfg["sound_on_stop"] = bool(checked)
        save_config(self.app.cfg)

    # -- In-app shortcut collection ---------------------------------------

    def _collect_in_app_shortcuts(self) -> list[tuple[str, str]]:
        """Return ``[(label, shortcut), ...]`` for every command that has
        a display shortcut and isn't one of the global engine actions
        (those live in Group 1). Ordered: command palette first, then by
        category in a stable display order."""
        skip = {"engine.start", "engine.stop", "engine.emergency"}
        out: list[tuple[str, str]] = []
        # Command palette is hard-coded; not part of app.commands by id.
        out.append(("Command palette", "Ctrl+K"))

        by_cat: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for cmd in self.app.commands:
            if cmd.id in skip:
                continue
            if not cmd.shortcut:
                continue
            by_cat[cmd.category].append((cmd.label, cmd.shortcut))
        for cat in ("Navigation", "Zone", "View"):
            out.extend(by_cat.get(cat, []))
        return out

    # -- Rebind flow (preserved from prior HotkeysCard) -------------------

    def on_rebind(self, action: str) -> None:
        self.cancel_rebind_timeout(action)
        btn = self._buttons[action]
        btn.setText("Press any key…")
        btn.setEnabled(False)
        self.app.hotkeys.capture_next(
            lambda name, a=action: self.on_key_captured(a, name),
        )
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda a=action: self.on_rebind_timeout(a))
        timer.start(REBIND_TIMEOUT_MS)
        self._timeouts[action] = timer

    def cancel_rebind_timeout(self, action: str) -> None:
        timer = self._timeouts.pop(action, None)
        if timer is not None:
            timer.stop()

    def on_rebind_timeout(self, action: str) -> None:
        self._timeouts.pop(action, None)
        self.app.hotkeys.cancel_capture()
        btn = self._buttons.get(action)
        if btn is not None:
            btn.setText("Change")
            btn.setEnabled(True)
        if hasattr(self.app, "toasts"):
            self.app.toasts.post(
                f"Rebind cancelled — {action.capitalize()} hotkey unchanged.",
                kind="info",
            )

    def on_key_captured(self, action: str, name: str) -> None:
        try:
            from utils.logger import get_logger
            get_logger().info(
                "rebind.on_key_captured action=%r name=%r — emitting signal",
                action, name,
            )
        except Exception:
            pass
        # Queued signal hops to the Qt main thread regardless of which
        # thread emits it. Replaces QTimer.singleShot — that path was
        # silently dropped because the pynput listener thread has no
        # Qt event loop, which Qt6 treats as undefined-behaviour and
        # discards.
        self._captureReceived.emit(action, name)

    def _apply_capture(self, action: str, name: str) -> None:
        try:
            from utils.logger import get_logger
            log = get_logger()
        except Exception:
            log = None
        if log is not None:
            log.info("rebind._apply_capture entering action=%r name=%r",
                     action, name)
        cfg = self.app.cfg
        # Cancel the timeout immediately — we got a key, the wait is over.
        self.cancel_rebind_timeout(action)
        if not name:
            if log is not None:
                log.info("rebind._apply_capture empty name → reset button")
            self._reset_button(action)
            return
        if name == "esc":
            if log is not None:
                log.info("rebind._apply_capture reject: esc reserved")
            if hasattr(self.app, "toasts"):
                self.app.toasts.post(
                    "Esc is reserved for emergency stop.",
                    kind="warn",
                )
            self._reset_button(action)
            return
        # Multi-action conflict check: walk every hotkey_* config key and
        # reject if `name` is already bound elsewhere.
        for k, v in cfg.items():
            if not str(k).startswith("hotkey_") or k == f"hotkey_{action}":
                continue
            if str(v).lower() == name.lower():
                other_action = str(k)[len("hotkey_"):]
                if log is not None:
                    log.info(
                        "rebind._apply_capture reject: %r already bound to %r",
                        name, other_action,
                    )
                if hasattr(self.app, "toasts"):
                    self.app.toasts.post(
                        f"'{name_to_display(name)}' is already bound to "
                        f"{other_action.capitalize()}.",
                        kind="warn",
                    )
                self._reset_button(action)
                return
        cfg[f"hotkey_{action}"] = name
        save_config(cfg)
        if action == "start":
            self.app.hotkeys.set_start(name)
        elif action == "stop":
            self.app.hotkeys.set_stop(name)
        elif action == "capture":
            self.app.hotkeys.set_capture(name)
        if log is not None:
            log.info(
                "rebind._apply_capture committed action=%r name=%r — chip updating",
                action, name,
            )
        self.update_label(action)

    def _reset_button(self, action: str) -> None:
        """Restore the Change button without posting a redundant toast.
        Used by the rejection paths in ``_apply_capture`` (which post
        their own specific toast)."""
        self.app.hotkeys.cancel_capture()
        btn = self._buttons.get(action)
        if btn is not None:
            btn.setText("Change")
            btn.setEnabled(True)

    def update_label(self, action: str) -> None:
        self.cancel_rebind_timeout(action)
        self._chips[action].set_text(
            name_to_display(self.app.cfg[f"hotkey_{action}"])
        )
        btn = self._buttons.get(action)
        if btn is not None:
            btn.setText("Change")
            btn.setEnabled(True)
        if hasattr(self.app, "action_bar"):
            self.app.action_bar.refresh_hint()

    def cancel_all(self) -> None:
        for action in list(self._timeouts):
            self.cancel_rebind_timeout(action)


# Back-compat alias so any straggling imports (or future palette
# routes) keep working under the old name.
HotkeysCard = HotkeysPageBody
