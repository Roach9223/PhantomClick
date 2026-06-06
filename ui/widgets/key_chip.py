"""``KeyChip`` — visual key cap for hotkey display.

Mono uppercase text inside a bordered, slightly elevated rectangle.
Looks like a keyboard key, reads like a value.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from .. import theme as t


class KeyChip(QLabel):
    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(text.upper() if text else "", parent)
        self.setObjectName("key-chip")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(28)
        self.setMinimumWidth(48)
        # Padding so single-letter keys still feel like keys.
        self.setStyleSheet(
            f"background: {t.SURFACE_HIGH}; "
            f"color: {t.ACCENT}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_KEY_CHIP}px; "
            f"font-weight: 700; "
            f"letter-spacing: 0.5px; "
            f"border: 1px solid {t.BORDER_STRONG}; "
            f"border-radius: {t.RADIUS_INPUT}px; "
            f"padding: 4px 12px;"
        )

    def set_text(self, text: str) -> None:
        self.setText(text.upper() if text else "")
