"""``TopBar``, pinned top toolbar for the landscape shell.

Single 52 px row spanning the full window width:
``BRAND  STATUS pill   [START] [STOP]  Esc to abort  [palette] [overlay]``
Icons come from :mod:`ui.icons`; there are no glyph literals here.

Owns the Start/Stop buttons (the App exposes them as ``app.start_btn`` /
``app.stop_btn`` aliases for engine_bridge / hotkeys to find), the
:class:`StatusPill` (whose ``tick()`` runs each frame), and a small set of
icon buttons on the right (command palette + overlay toggle).

The hotkey hint that used to live in the old ActionBar is gone, shortcuts
are now surfaced via tooltips on the Start/Stop buttons themselves.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton,
)

from modules.hotkey_manager import name_to_display
from ui.tooltip_fmt import tooltip

from . import icons, theme as t
from .widgets.status_pill import StatusPill


class TopBar(QFrame):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName("topbar")
        self.setFixedHeight(t.TOPBAR_H)

        row = QHBoxLayout(self)
        row.setContentsMargins(t.SP_LG, t.SP_SM, t.SP_LG, t.SP_SM)
        row.setSpacing(t.SP_LG)

        # -- Brand --------------------------------------------------------
        self.brand = QLabel("PHANTOMCLICK")
        self.brand.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; font-family: {t.FONT_DISPLAY}; "
            f"font-size: 16px; font-weight: 700; letter-spacing: 1.4px;"
        )
        row.addWidget(self.brand)

        # Spare horizontal space goes here so the pill + action buttons
        # stay grouped on the right edge, the prior Expanding pill ate
        # all the space and floated the status text in the middle of the
        # bar, disconnected from the controls it described.
        row.addStretch(1)

        # -- Status pill (state + zone summary + countdown) ---------------
        self.pill = StatusPill(app)
        self.pill.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        row.addWidget(self.pill)

        # -- Start / Stop -------------------------------------------------
        self.start_btn = QPushButton("START")
        self.start_btn.setIcon(icons.icon("play", 14, t.TEXT_ON_ACCENT))
        self.start_btn.setProperty("variant", "primary")
        self.start_btn.setMinimumHeight(36)
        self.start_btn.setMinimumWidth(110)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(app._on_start)
        self.start_btn.setToolTip(tooltip(
            "Begin clicking. Waits for the Pre-start delay so you can "
            "alt-tab into the target window before the first click.",
            shortcut=name_to_display(app.cfg.get("hotkey_start", "f6")),
        ))
        row.addWidget(self.start_btn)

        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setIcon(icons.icon("stop", 14, t.TEXT_PRIMARY))
        self.stop_btn.setProperty("variant", "danger")
        self.stop_btn.setMinimumHeight(36)
        self.stop_btn.setMinimumWidth(110)
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.clicked.connect(app._on_stop)
        self.stop_btn.setToolTip(tooltip(
            "Halt clicking immediately. Escape always emergency-stops "
            "regardless of state.",
            shortcut=name_to_display(app.cfg.get("hotkey_stop", "f7")),
        ))
        row.addWidget(self.stop_btn)

        # -- Esc emergency-stop hint --------------------------------------
        # Renders as a quiet inline hint right of STOP so the most
        # safety-critical hotkey in the app is always visible (was buried
        # in the nav-rail footer, where users never looked).
        self.esc_hint = QLabel("Esc to abort")
        self.esc_hint.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_XS}px; "
            f"padding: 0 6px;"
        )
        self.esc_hint.setToolTip(
            "Esc always emergency-stops, regardless of state. "
            "Hard-locked, cannot be rebound."
        )
        row.addWidget(self.esc_hint)

        # -- Icon buttons -------------------------------------------------
        self.palette_btn = QToolButton()
        self.palette_btn.setIcon(icons.icon("command", 16, t.TEXT_SECONDARY))
        self.palette_btn.setCursor(Qt.PointingHandCursor)
        self.palette_btn.setMinimumHeight(32)
        self.palette_btn.setMinimumWidth(48)
        self.palette_btn.setStyleSheet(
            f"background: {t.SURFACE_HIGH}; color: {t.TEXT_SECONDARY}; "
            f"border: 1px solid {t.BORDER}; border-radius: {t.RADIUS_BUTTON}px; "
            f"font-family: {t.FONT_MONO}; font-size: {t.SIZE_SMALL}px; "
            f"padding: 0 8px;"
        )
        self.palette_btn.setToolTip(tooltip(
            "Command palette, fuzzy-search every action.",
            shortcut="Ctrl+K",
        ))
        self.palette_btn.clicked.connect(app._open_palette)
        row.addWidget(self.palette_btn)

        self.overlay_btn = QToolButton()
        self._sync_overlay_icon()
        self.overlay_btn.setCursor(Qt.PointingHandCursor)
        self.overlay_btn.setMinimumHeight(32)
        self.overlay_btn.setStyleSheet(
            f"background: transparent; color: {t.TEXT_SECONDARY}; "
            f"border: 1px solid transparent; "
            f"border-radius: {t.RADIUS_BUTTON}px; padding: 0 10px; "
            f"font-size: {t.SIZE_SMALL}px;"
        )
        self.overlay_btn.setToolTip(tooltip(
            "Show or hide on-screen zone outlines.",
            shortcut="Ctrl+H",
        ))
        self.overlay_btn.clicked.connect(self.on_toggle_overlay)
        row.addWidget(self.overlay_btn)

    # -- Overlay toggle (migrated from old ActionBar) --------------------

    def _sync_overlay_icon(self) -> None:
        on = bool(self.app.cfg.get("show_zone_overlay", True))
        self.overlay_btn.setIcon(icons.icon("eye" if on else "eye-off", 16,
                                            t.ACCENT if on else t.TEXT_TERTIARY))

    def on_toggle_overlay(self) -> None:
        # App.set_overlay_visible saves, applies and calls back into
        # _sync_overlay_icon so every toggle surface agrees.
        self.app.toggle_overlay_visible()

    # -- Hotkey rebind hook ----------------------------------------------

    def refresh_hint(self) -> None:
        """Called by HotkeysCard after a rebind. We re-derive Start/Stop
        tooltips so they show the new key. No visible label to update."""
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

    def tick(self) -> None:
        self.pill.tick()
