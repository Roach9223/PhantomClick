"""``EmptyState``, centered placeholder shown inside a :class:`SettingsGroup`
when the group has nothing to render.

Three stacked elements: a 44 px abstract icon, a primary title, and a
secondary description. Optionally a quiet-accent CTA button below. Used
by the Hover page when no zones exist; the form-page successors will
adopt the same primitive.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .. import theme as t


class _EmptyStateIcon(QWidget):
    """Minimal 44×44 abstract icon: rounded panel with a centered rect
    motif, represents a "zone" without naming it explicitly."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(44, 44)

    def paintEvent(self, _event):  # noqa: N802 (Qt name)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(t.SURFACE_HIGH))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(self.rect(), t.RADIUS_CARD, t.RADIUS_CARD)
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor(t.TEXT_DISABLED))
        p.drawRoundedRect(11, 15, 22, 14, 2, 2)


class EmptyState(QFrame):
    def __init__(
        self,
        title: str,
        description: str,
        cta_text: Optional[str] = None,
        on_cta: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(t.SP_LG, 36, t.SP_LG, 36)
        layout.setSpacing(0)
        # No layout-level AlignCenter: with it Qt hands the wrapped
        # description its one-line height and clips the last line. Each
        # widget centres itself instead.
        layout.addStretch(1)

        icon = _EmptyStateIcon()
        layout.addWidget(icon, 0, Qt.AlignHCenter)
        layout.addSpacing(12)

        title_lbl = QLabel(title)
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet(
            f"font-size: {t.SIZE_LG}px; font-weight: 600; color: {t.TEXT_PRIMARY};"
        )
        layout.addWidget(title_lbl, 0, Qt.AlignHCenter)
        layout.addSpacing(4)

        desc_lbl = QLabel(description)
        desc_lbl.setAlignment(Qt.AlignCenter)
        desc_lbl.setWordWrap(True)
        # Fixed width: a centred word-wrapped label otherwise shrinks to
        # its narrowest hint and wraps into more lines than it has room for.
        desc_lbl.setFixedWidth(380)
        desc_lbl.setStyleSheet(
            f"font-size: {t.SIZE_BODY}px; color: {t.TEXT_TERTIARY};"
        )
        # A wrapped label inside a stretch-padded column reports its one
        # line height and Qt clips the rest; measure the wrapped block.
        from PySide6.QtGui import QFont, QFontMetrics
        f = QFont(desc_lbl.font())
        f.setPixelSize(t.SIZE_BODY)
        wrapped = QFontMetrics(f).boundingRect(0, 0, 380, 1000, Qt.TextWordWrap | Qt.AlignCenter, description)
        desc_lbl.setFixedHeight(wrapped.height() + 6)
        layout.addWidget(desc_lbl, 0, Qt.AlignHCenter)

        if cta_text and on_cta is not None:
            layout.addSpacing(14)
            btn = QPushButton(cta_text)
            # The one thing to do on an empty page reads as the primary.
            btn.setProperty("variant", "primary")
            btn.setMinimumHeight(32)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(on_cta)
            layout.addWidget(btn, 0, Qt.AlignHCenter)
        layout.addStretch(1)
