"""``KeyChip``: visual key cap for hotkey display.

Mono uppercase text inside a bordered rectangle on the panel colour.
Looks like a key, reads like a value. Text is TEXT_PRIMARY; lime is not
used here because a bound key is not a live state.
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
        self.setMinimumHeight(26)
        self.setMinimumWidth(44)
        self.setStyleSheet(
            f"background: {t.SURFACE_PANEL}; "
            f"color: {t.TEXT_PRIMARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_KEY_CHIP}px; "
            f"font-weight: 600; "
            f"border: 1px solid {t.BORDER_STRONG}; "
            f"border-radius: {t.RADIUS_INPUT}px; "
            f"padding: 3px 10px;"
        )

    def set_text(self, text: str) -> None:
        self.setText(text.upper() if text else "")
