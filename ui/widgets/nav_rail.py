"""``NavRail`` — vertical navigation rail for the landscape shell.

A fixed-width column on the left of the main window. Each entry is a
``NavItem`` (icon glyph + label). Clicking emits ``currentChanged(id)``.
The active item paints a coral left-edge stripe + accent text; idle items
sit muted on the surface color.

The rail also hosts a tertiary "Esc = Emergency stop" footer so users
remember the safety key without it taking topbar real estate.
"""

from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)

from .. import theme as t


class NavItem(QPushButton):
    def __init__(self, item_id: str, glyph: str, label: str,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.item_id = item_id
        self.setObjectName("nav-item")
        self.setProperty("active", False)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCheckable(True)
        self.setAutoExclusive(False)
        # We do our own layout inside the button so we get perfect glyph
        # alignment regardless of font metrics.
        row = QHBoxLayout(self)
        row.setContentsMargins(t.SP_MD, 0, t.SP_MD, 0)
        row.setSpacing(t.SP_SM)
        self._glyph = QLabel(glyph)
        self._glyph.setFixedWidth(20)
        self._glyph.setAlignment(Qt.AlignCenter)
        self._label = QLabel(label)
        row.addWidget(self._glyph)
        row.addWidget(self._label, 1)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)


class NavRail(QFrame):
    currentChanged = Signal(str)

    def __init__(self, items: List[Tuple[str, str, str]], parent: QWidget | None = None):
        """``items`` = list of (id, glyph, label) tuples in display order."""
        super().__init__(parent)
        self.setObjectName("nav-rail")
        self.setFixedWidth(t.NAV_RAIL_W)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(t.SP_SM, t.SP_LG, t.SP_SM, t.SP_SM)
        outer.setSpacing(t.SP_XS)

        self._items: dict[str, NavItem] = {}
        self._current_id: str | None = None
        for item_id, glyph, label in items:
            item = NavItem(item_id, glyph, label, self)
            item.clicked.connect(lambda _=False, i=item_id: self.set_current(i))
            outer.addWidget(item)
            self._items[item_id] = item

        outer.addStretch(1)
        # The legacy "Esc · Emergency stop" footer was removed — the
        # topbar now carries an "Esc to abort" hint right next to the
        # STOP button where users actually look for it.

    def set_current(self, item_id: str) -> None:
        if item_id not in self._items or item_id == self._current_id:
            return
        if self._current_id is not None:
            self._items[self._current_id].set_active(False)
        self._items[item_id].set_active(True)
        self._current_id = item_id
        self.currentChanged.emit(item_id)

    def current_id(self) -> str | None:
        return self._current_id
