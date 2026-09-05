"""``StatusDot``: the 6 px square indicator beside a status label.

Deck rule: state changes are instant. The dot swaps colour with no
animation and no halo. Lime = active, amber = starting / paused, idle grey
otherwise.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from .. import theme as t


class StatusDot(QWidget):
    def __init__(self, parent=None, size: int = 6):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size + 4, size + 4)
        self._color = QColor(t.STATUS_IDLE)

    def set_state(self, state: str) -> None:
        """state: 'idle' | 'starting' | 'active' | 'paused'."""
        target = {
            "idle": t.STATUS_IDLE,
            "starting": t.STATUS_PAUSED,
            "paused": t.STATUS_PAUSED,
            "active": t.STATUS_ACTIVE,
        }.get(state, t.STATUS_IDLE)
        new = QColor(target)
        if new != self._color:
            self._color = new
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt method name)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        x = (self.width() - self._size) // 2
        y = (self.height() - self._size) // 2
        p.drawRect(x, y, self._size, self._size)
