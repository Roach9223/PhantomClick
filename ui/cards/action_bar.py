"""Action bar — Start / Stop buttons + the hotkey hint line.

Pinned at the top of the window above the tabview; never scrolls. The
overlay-toggle and hotkey label live in the same row so the always-on
header stays a single visual block.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from modules.hotkey_manager import name_to_display
from ui.config_io import save_config
from ui.tooltip_fmt import tooltip

from .. import theme as t


class ActionBar(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(t.SP_SM)

        # Start / Stop row -----------------------------------------------
        btn_row = QHBoxLayout()
        btn_row.setSpacing(t.SP_SM)

        self.start_btn = QPushButton("▶  START")
        self.start_btn.setProperty("variant", "success")
        self.start_btn.setMinimumHeight(38)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(app._on_start)
        self.start_btn.setToolTip(tooltip(
            "Begin clicking. Waits for the Pre-start delay so you can "
            "alt-tab into the target window before the first click.",
            shortcut=name_to_display(app.cfg.get("hotkey_start", "f6")),
        ))

        self.stop_btn = QPushButton("■  STOP")
        self.stop_btn.setProperty("variant", "danger")
        self.stop_btn.setMinimumHeight(38)
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.clicked.connect(app._on_stop)
        self.stop_btn.setToolTip(tooltip(
            "Halt clicking immediately. Escape always emergency-stops "
            "regardless of state.",
            shortcut=name_to_display(app.cfg.get("hotkey_stop", "f7")),
        ))

        btn_row.addWidget(self.start_btn, 1)
        btn_row.addWidget(self.stop_btn, 1)
        outer.addLayout(btn_row)

        # Hotkey hint + overlay toggle row -------------------------------
        # Hint text uses tertiary color + small size so it recedes; the
        # overlay toggle is a quiet ghost button on the right.
        hint_row = QHBoxLayout()
        hint_row.setSpacing(t.SP_SM)

        self.hint_label = QLabel("")
        self.hint_label.setProperty("role", "tertiary")
        self.hint_label.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SMALL}px;"
        )
        hint_row.addWidget(self.hint_label, 1)

        self.overlay_btn = QPushButton(self._overlay_text())
        self.overlay_btn.setProperty("variant", "ghost")
        self.overlay_btn.setCursor(Qt.PointingHandCursor)
        self.overlay_btn.setStyleSheet(f"font-size: {t.SIZE_SMALL}px;")
        self.overlay_btn.setToolTip(tooltip(
            "Show or hide the translucent zone outlines drawn on screen. "
            "Doesn't change what the engine clicks — just hides the visual.",
            shortcut="Ctrl+H",
        ))
        self.overlay_btn.clicked.connect(self.on_toggle_overlay)
        hint_row.addWidget(self.overlay_btn)
        outer.addLayout(hint_row)

        self.refresh_hint()

    # -- Behavior ----------------------------------------------------------

    def _overlay_text(self) -> str:
        on = bool(self.app.cfg.get("show_zone_overlay", True))
        return f"👁  Overlays · {'ON' if on else 'OFF'}"

    def on_toggle_overlay(self) -> None:
        cfg = self.app.cfg
        new_val = not bool(cfg.get("show_zone_overlay", True))
        cfg["show_zone_overlay"] = new_val
        save_config(cfg)
        self.overlay_btn.setText(self._overlay_text())
        self.app.overlay_manager.apply_visibility()

    def refresh_hint(self) -> None:
        cfg = self.app.cfg
        s = name_to_display(cfg["hotkey_start"])
        t_ = name_to_display(cfg["hotkey_stop"])
        self.hint_label.setText(
            f"Hotkeys:  [{s}] Start  ·  [{t_}] Stop  ·  [Esc] Emergency"
        )
