"""``EmptyState`` — centered placeholder shown inside a :class:`SettingsGroup`
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
    motif — represents a "zone" without naming it explicitly."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(44, 44)

    def paintEvent(self, _event):  # noqa: N802 (Qt name)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(t.SURFACE_HIGH))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(self.rect(), 10, 10)
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
        layout.setAlignment(Qt.AlignCenter)

        icon = _EmptyStateIcon()
        layout.addWidget(icon, 0, Qt.AlignCenter)
        layout.addSpacing(12)

        title_lbl = QLabel(title)
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet(
            f"font-size: 14px; font-weight: 500; color: {t.TEXT_PRIMARY};"
        )
        layout.addWidget(title_lbl)
        layout.addSpacing(4)

        desc_lbl = QLabel(description)
        desc_lbl.setAlignment(Qt.AlignCenter)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(
            f"font-size: 12px; color: {t.TEXT_TERTIARY};"
        )
        layout.addWidget(desc_lbl)

        if cta_text and on_cta is not None:
            layout.addSpacing(14)
            btn = QPushButton(cta_text)
            btn.setProperty("role", "quiet-accent")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(on_cta)
            layout.addWidget(btn, 0, Qt.AlignCenter)
