"""``Expander`` — animated collapse/expand panel for "Advanced" sections.

The toggle is rendered as a multi-styled row (chevron + bold label +
muted preview) so the label/preview don't merge into a single phrase.
Click anywhere on the row to toggle.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, Qt, Signal,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from .. import theme as t


class _ExpanderToggle(QFrame):
    """Clickable header row: chevron · bold label · muted preview.

    The three pieces use separate styling so the eye reads "label" and
    "what's inside" as different things. Hover state lifts the row
    slightly to make the click affordance obvious.
    """

    clicked = Signal()

    def __init__(self, label: str, preview: str = "",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("expander-toggle")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QFrame#expander-toggle {{ "
            f"  background: transparent; "
            f"  border: 1px solid transparent; "
            f"  border-radius: {t.RADIUS_INPUT}px; "
            f"}}"
            f"QFrame#expander-toggle:hover {{ "
            f"  background: rgba(255, 255, 255, 0.03); "
            f"  border: 1px solid {t.BORDER_SUBTLE}; "
            f"}}"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(8)

        self._chev = QLabel("▸")
        self._chev.setStyleSheet(
            f"color: {t.TEXT_SECONDARY}; "
            f"font-size: 12px; font-weight: 700;"
        )
        row.addWidget(self._chev)

        self._label = QLabel(label)
        self._label.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: 13px; font-weight: 600;"
        )
        row.addWidget(self._label)

        self._preview = QLabel("")
        self._preview.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; "
            f"font-size: 13px;"
        )
        row.addWidget(self._preview)
        row.addStretch(1)

        self._preview_text = preview
        if preview:
            self._preview.setText(preview)
        else:
            self._preview.setVisible(False)

    def mousePressEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
            ev.accept()
            return
        super().mousePressEvent(ev)

    def set_open(self, open_: bool) -> None:
        self._chev.setText("▾" if open_ else "▸")
        # Hide the preview when expanded — the actual content speaks for
        # itself, so the hint becomes redundant.
        self._preview.setVisible(bool(self._preview_text) and not open_)


class Expander(QWidget):
    def __init__(self, label: str, preview: str = "",
                 parent: Optional[QWidget] = None):
        """``preview`` is an optional comma-separated subtitle rendered
        in muted secondary text after the label
        (``▸  Advanced  shape, button, mode``) so collapsed state hints
        at what's inside without the user having to click. Hidden when
        the expander is open.
        """
        super().__init__(parent)
        self._open = False
        self._preview = preview

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        self._toggle = _ExpanderToggle(label, preview, self)
        self._toggle.clicked.connect(self.toggle)
        self._label_text = label
        outer.addWidget(self._toggle)

        self._content = QWidget(self)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(t.SP_XS)
        self._content.setMaximumHeight(0)
        outer.addWidget(self._content)

        self._anim = QPropertyAnimation(self._content, b"maximumHeight", self)
        self._anim.setDuration(t.DUR_NORMAL)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def set_content(self, widget: QWidget) -> None:
        self._content_layout.addWidget(widget)

    def is_open(self) -> bool:
        return self._open

    def toggle(self) -> None:
        self.set_open(not self._open)

    def set_open(self, open_: bool) -> None:
        if open_ == self._open:
            return
        self._open = open_
        self._toggle.set_open(open_)
        target_h = self._content.sizeHint().height() if open_ else 0
        self._anim.stop()
        self._anim.setStartValue(self._content.maximumHeight())
        self._anim.setEndValue(target_h)
        self._anim.start()
