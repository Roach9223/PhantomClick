"""``PresetCard``, one-line preset button used by ``TimingCard``.

Name on the left, range on the right, one control height tall so four of
them fit a 2 x 2 grid inside the deck's editor pane. Checkable: the active
preset carries the lime border (lime means selected here, nothing else).

QSS for ``QPushButton#preset-card`` lives in :mod:`ui.qss`; the inner
labels carry their own style because a child QLabel inside a checkable
QPushButton doesn't reliably inherit the parent's pseudo-state.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from .. import theme as t


class PresetCard(QPushButton):
    def __init__(
        self,
        name: str,
        range_text: str,
        lo_seconds: float,
        hi_seconds: float,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("preset-card")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        # A QPushButton that hosts a layout does not size to it; pin the
        # height so the labels are never clipped by a short grid cell.
        self.setFixedHeight(t.BUTTON_H + 2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(f"Set the interval to {range_text}.")

        self.lo_seconds = float(lo_seconds)
        self.hi_seconds = float(hi_seconds)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)

        self._name_lbl = QLabel(name.upper())
        self._name_lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; font-size: {t.SIZE_SM}px; font-weight: 600;"
        )
        font = self._name_lbl.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        self._name_lbl.setFont(font)
        layout.addWidget(self._name_lbl)
        layout.addStretch(1)

        self._range_lbl = QLabel(range_text)
        self._range_lbl.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_XS}px;"
        )
        layout.addWidget(self._range_lbl)
