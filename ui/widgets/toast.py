"""``Toast`` — small transient notification that fades in, dwells, fades out.

Used for things that don't deserve a full dialog: "Replaced Advanced values
for this dial position", "Step duplicated", etc. Stacks vertically; auto-
dismisses after :data:`theme.DUR_TOAST` ms.

Mounted as a frameless child of the main window's central widget so it
floats above content but doesn't escape the window.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation, QTimer, Qt,
)
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget,
)

from .. import theme as t


class Toast(QWidget):
    def __init__(self, parent: QWidget, text: str, *, kind: str = "info"):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        accent = {
            "info": t.INFO,
            "warn": t.WARN,
            "success": t.START,
            "danger": t.DANGER,
        }.get(kind, t.INFO)
        self.setStyleSheet(f"""
            QWidget#toast {{
                background: {t.SURFACE_HIGH};
                border: 1px solid {accent};
                border-left: 3px solid {accent};
                border-radius: {t.RADIUS_INPUT}px;
            }}
            QLabel {{ color: {t.TEXT_PRIMARY}; font-size: {t.SIZE_SMALL}px; }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(t.SP_MD, t.SP_SM, t.SP_MD, t.SP_SM)
        self._label = QLabel(text)
        layout.addWidget(self._label)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)

        self._fade_in = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade_in.setDuration(t.DUR_FAST)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.OutCubic)

        self._fade_out = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade_out.setDuration(t.DUR_NORMAL)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.InCubic)
        self._fade_out.finished.connect(self.deleteLater)

        self._dwell = QTimer(self)
        self._dwell.setSingleShot(True)
        self._dwell.timeout.connect(self._fade_out.start)

    def show_for(self, duration_ms: Optional[int] = None) -> None:
        self.show()
        self._fade_in.start()
        self._dwell.start(duration_ms or t.DUR_TOAST)


class ToastHost(QWidget):
    """Container parented to the App's central widget. Stacks toasts at the
    bottom-right of its area and forwards them up the z-order automatically."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(t.SP_LG, t.SP_LG, t.SP_LG, t.SP_LG)
        # Stretch so toasts pile to the right edge.
        self._layout.addStretch(1)
        self.setStyleSheet("background: transparent;")

    def post(self, text: str, *, kind: str = "info",
             duration_ms: Optional[int] = None) -> None:
        toast = Toast(self, text, kind=kind)
        self._layout.addWidget(toast, alignment=Qt.AlignBottom)
        toast.show_for(duration_ms)
