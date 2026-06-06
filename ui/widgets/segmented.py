"""``SegmentedControl`` — pill-shaped horizontal pick-one-of-N selector.

Replaces QRadioButton groups for fixed small option sets (zone shape,
button type, click mode, hover selection mode). Active option paints in
accent; idle options sit on the surface color.

The control stores values as string ids (e.g. "rect"), not indices, so
options can be reordered without breaking persisted config.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QWidget

from .. import theme as t


class SegmentedControl(QWidget):
    valueChanged = Signal(str)

    def __init__(
        self,
        options: List[Tuple[str, str]],
        value: str = "",
        parent: Optional[QWidget] = None,
    ):
        """``options`` = list of (id, label) tuples in display order."""
        super().__init__(parent)
        self.setObjectName("segmented")
        self._buttons: dict[str, QPushButton] = {}
        self._value: Optional[str] = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        frame = QFrame(self)
        frame.setObjectName("segmented-frame")
        row = QHBoxLayout(frame)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(2)
        outer.addWidget(frame)
        outer.addStretch(1)

        for opt_id, label in options:
            btn = QPushButton(label, frame)
            btn.setObjectName("segmented-btn")
            btn.setProperty("active", False)
            btn.setCheckable(True)
            btn.setAutoExclusive(False)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(t.INPUT_H - 4)
            btn.clicked.connect(lambda _=False, oid=opt_id: self.setValue(oid))
            row.addWidget(btn)
            self._buttons[opt_id] = btn

        # Apply the initial value (default to first option if not given).
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
