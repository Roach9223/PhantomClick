"""``Expander``: collapse/expand panel for "Advanced" sections.

The toggle row is a chevron icon (from :mod:`ui.icons`), a label, and a
muted preview. Click anywhere on the row to toggle. Height moves over
120 ms linear; that is the deck's animation ceiling.

Never bake a chevron character into the label string; the toggle draws
its own.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, Qt, Signal,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from .. import icons, theme as t


_CHEVRON_PX = 14


class _ExpanderToggle(QFrame):
    """Clickable header row: chevron icon, label, muted preview."""

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
            f"  background: {t.SURFACE_HIGH}; "
            f"  border: 1px solid {t.BORDER}; "
            f"}}"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 5, 8, 5)
        row.setSpacing(8)

        self._chev = QLabel()
        self._chev.setFixedSize(_CHEVRON_PX, _CHEVRON_PX)
        self._chev.setStyleSheet("background: transparent;")
        row.addWidget(self._chev)

        self._label = QLabel(label)
        self._label.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_BODY}px; font-weight: 600;"
        )
        row.addWidget(self._label)

        self._preview = QLabel("")
        self._preview.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; "
            f"font-size: {t.SIZE_SM}px;"
        )
        row.addWidget(self._preview)
        row.addStretch(1)

        self._preview_text = preview
        if preview:
            self._preview.setText(preview)
        else:
            self._preview.setVisible(False)
        self.set_open(False)

    def mousePressEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
            ev.accept()
            return
        super().mousePressEvent(ev)

    def set_open(self, open_: bool) -> None:
        name = "chevron-down" if open_ else "chevron-right"
        self._chev.setPixmap(icons.pixmap(name, _CHEVRON_PX, t.TEXT_SECONDARY))
        self._preview.setVisible(bool(self._preview_text) and not open_)


class Expander(QWidget):
    def __init__(self, label: str, preview: str = "",
                 parent: Optional[QWidget] = None):
        """``preview`` is an optional subtitle rendered in muted text after
        the label so the collapsed state hints at what's inside. Hidden
        when the expander is open."""
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
        self._anim.setEasingCurve(QEasingCurve.Linear)
        self._anim.finished.connect(self._finish_animation)

    def _finish_animation(self) -> None:
        # An open panel must follow wrapping text and later child additions.
        # Keeping its pre-layout sizeHint as a permanent cap crushed controls.
        self._content.setMaximumHeight(16777215 if self._open else 0)

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
        if not self.isVisible():
            self._anim.stop()
            self._finish_animation()
            return
        target_h = self._content.sizeHint().height() if open_ else 0
        self._anim.stop()
        self._anim.setStartValue(self._content.height())
        self._anim.setEndValue(target_h)
        self._anim.start()
