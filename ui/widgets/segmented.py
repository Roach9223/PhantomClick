"""``SegmentedControl``: connected pick-one-of-N selector.

Deck styling: the cells sit inside one 6 px radius frame with 1 px dividers
between them. The selected cell fills SURFACE_PRESS and carries a 2 px lime
rule on its top edge (horizontal) or left edge (vertical). Lime here means
"selected", the one state it is allowed to mean.

The control stores values as string ids (e.g. "rect"), not indices, so
options can be reordered without breaking persisted config.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget,
)

from .. import theme as t


class SegmentedControl(QWidget):
    valueChanged = Signal(str)

    def __init__(
        self,
        options: List[Tuple[str, str]],
        value: str = "",
        parent: Optional[QWidget] = None,
        *,
        vertical: bool = False,
        tooltips: Optional[dict[str, str]] = None,
    ):
        """``options`` = list of (id, label) tuples in display order.
        ``tooltips`` maps an option id to the hover text for its cell."""
        super().__init__(parent)
        self.setObjectName("segmented")
        self._buttons: dict[str, QPushButton] = {}
        self._value: Optional[str] = None
        self._vertical = bool(vertical)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        frame = QFrame(self)
        frame.setObjectName("segmented-frame")
        row = QVBoxLayout(frame) if vertical else QHBoxLayout(frame)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        outer.addWidget(frame)
        outer.addStretch(1)

        for i, (opt_id, label) in enumerate(options):
            btn = QPushButton(label.upper(), frame)
            btn.setObjectName("segmented-btn")
            btn.setProperty("active", False)
            btn.setProperty("first", i == 0)
            if vertical:
                btn.setProperty("orientation", "vertical")
            btn.setCheckable(True)
            btn.setAutoExclusive(False)
            btn.setCursor(Qt.PointingHandCursor)
            if tooltips and opt_id in tooltips:
                btn.setToolTip(tooltips[opt_id])
            btn.setMinimumHeight(t.INPUT_H - 2)
            font = btn.font()
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, t.CONTROL_TRACKING)
            btn.setFont(font)
            btn.clicked.connect(lambda _=False, oid=opt_id: self.setValue(oid))
            row.addWidget(btn)
            self._buttons[opt_id] = btn

        initial = value if value in self._buttons else next(iter(self._buttons))
        self._apply_active(initial)
        self._value = initial

    def setValue(self, v: str, emit: bool = True) -> None:  # noqa: N802
        if v not in self._buttons or v == self._value:
            return
        self._apply_active(v)
        self._value = v
        if emit:
            self.valueChanged.emit(v)

    def value(self) -> str:
        return self._value or ""

    def _apply_active(self, v: str) -> None:
        for opt_id, btn in self._buttons.items():
            active = (opt_id == v)
            btn.setProperty("active", active)
            btn.setChecked(active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
