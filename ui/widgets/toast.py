"""``Toast``: small transient notification.

Rectangular SURFACE_HIGH panel, 1 px BORDER, a 2 px left rule in the kind
colour (lime success, amber warn, red danger, neutral info), mono text.
Appears instantly, dwells, then is removed. No fade: the deck does not
animate opacity.

Mounted as a frameless child of the main window's central widget so it
floats above content but doesn't escape the window.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

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
            "error": t.DANGER,
        }.get(kind, t.INFO)
        self.setStyleSheet(f"""
            QWidget#toast {{
                background: {t.SURFACE_HIGH};
                border: 1px solid {t.BORDER_STRONG};
                border-left: 2px solid {accent};
                border-radius: {t.RADIUS_BUTTON}px;
            }}
            QLabel {{
                color: {t.TEXT_PRIMARY};
                font-family: {t.FONT_MONO};
                font-size: {t.SIZE_SM}px;
                background: transparent;
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(t.SP_MD, t.SP_SM, t.SP_MD, t.SP_SM)
        self._label = QLabel(text)
        layout.addWidget(self._label)

        self._dwell = QTimer(self)
        self._dwell.setSingleShot(True)
        self._dwell.timeout.connect(self._dismiss)

    def _dismiss(self) -> None:
        self.hide()
        self.deleteLater()

    def show_for(self, duration_ms: Optional[int] = None) -> None:
        self.show()
        self._dwell.start(duration_ms or t.DUR_TOAST)


class ToastHost(QWidget):
    """Container parented to the App's central widget. Stacks toasts at the
    bottom-right of its area."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(t.SP_LG, t.SP_LG, t.SP_LG, t.SP_LG)
        self._layout.addStretch(1)
        self.setStyleSheet("background: transparent;")

    def post(self, text: str, *, kind: str = "info",
             duration_ms: Optional[int] = None) -> None:
        toast = Toast(self, text, kind=kind)
        self._layout.addWidget(toast, alignment=Qt.AlignBottom)
        toast.show_for(duration_ms)
