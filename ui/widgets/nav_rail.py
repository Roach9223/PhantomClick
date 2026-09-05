"""``NavRail``: vertical navigation rail for the landscape shell.

A fixed-width column on the left of the main window. Each entry is a
``NavItem`` (16 px SVG icon + uppercase label). Clicking emits
``currentChanged(id)``. The active item gets a SURFACE_HIGH fill, a 2 px
lime left rule, and primary text; idle items sit in secondary text.

``NavRail`` takes ``(id, icon_name, label)`` tuples; ``icon_name`` is a
registered name in :mod:`ui.icons`. When the name is unknown the page id
is tried, and as a last resort the string is shown as text, so a typo
degrades to a label instead of an exception.
"""

from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)

from .. import icons, theme as t


_ICON_PX = 16


class NavItem(QPushButton):
    def __init__(self, item_id: str, icon_name: str, label: str,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.item_id = item_id
        self._icon_name = icon_name if icons.has(icon_name) else None
        self.setObjectName("nav-item")
        self.setProperty("active", False)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCheckable(True)
        self.setAutoExclusive(False)

        row = QHBoxLayout(self)
        row.setContentsMargins(t.SP_MD, 0, t.SP_MD, 0)
        row.setSpacing(t.SP_SM + 2)

        self._glyph = QLabel()
        self._glyph.setFixedSize(_ICON_PX + 4, _ICON_PX + 4)
        self._glyph.setAlignment(Qt.AlignCenter)
        if self._icon_name is None:
            self._glyph.setText(icon_name)
        row.addWidget(self._glyph)

        self._label = QLabel(label.upper())
        font = self._label.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, t.LABEL_TRACKING)
        self._label.setFont(font)
        row.addWidget(self._label, 1)
        self._refresh_icon(False)

    def _refresh_icon(self, active: bool) -> None:
        if self._icon_name is None:
            return
        color = t.TEXT_PRIMARY if active else t.TEXT_SECONDARY
        self._glyph.setPixmap(icons.pixmap(self._icon_name, _ICON_PX, color))

    def set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self._refresh_icon(active)
        self.style().unpolish(self)
        self.style().polish(self)


class NavRail(QFrame):
    currentChanged = Signal(str)

    def __init__(self, items: List[Tuple[str, str, str]], parent: QWidget | None = None):
        """``items`` = list of ``(id, icon_name, label)`` tuples in display
        order; ``icon_name`` is a :mod:`ui.icons` name."""
        super().__init__(parent)
        self.setObjectName("nav-rail")
        self.setFixedWidth(t.NAV_RAIL_W)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(t.SP_SM, t.SP_LG, t.SP_SM, t.SP_SM)
        outer.setSpacing(2)

        self._items: dict[str, NavItem] = {}
        self._current_id: str | None = None
        for item_id, glyph, label in items:
            item = NavItem(item_id, _resolve_icon(item_id, glyph), label, self)
            item.clicked.connect(lambda _=False, i=item_id: self.set_current(i))
            outer.addWidget(item)
            self._items[item_id] = item

        outer.addStretch(1)

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


def _resolve_icon(item_id: str, icon_name: str) -> str:
    """Pick the icon for a nav item. A registered ``icon_name`` wins; else
    the page id is tried (every page has an icon of its own name); else
    the string comes back unchanged and ``NavItem`` renders it as text."""
    if icons.has(icon_name):
        return icon_name
    if icons.has(item_id):
        return item_id
    return icon_name
