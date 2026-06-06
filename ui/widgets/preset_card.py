"""``PresetCard`` — two-line preset button used by ``TimingCard``.

Replaces the previous pill-shape so presets read as "tap to apply this
whole timing window" rather than as a chip in a selector. Stacks a bold
name above a smaller range string. Checkable so the active preset
highlights with the accent border.

QSS for ``QPushButton#preset-card`` lives in :mod:`ui.qss`; the inner
labels carry their own style here because a child QLabel inside a
checkable QPushButton doesn't reliably inherit the parent's pseudo-state.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

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
        self.setMinimumHeight(40)

        self.lo_seconds = float(lo_seconds)
        self.hi_seconds = float(hi_seconds)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(1)

        self._name_lbl = QLabel(name)
        self._name_lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; font-size: 11px; font-weight: 500;"
        )
        layout.addWidget(self._name_lbl)

        self._range_lbl = QLabel(range_text)
        self._range_lbl.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: 10px;"
        )
        layout.addWidget(self._range_lbl)
