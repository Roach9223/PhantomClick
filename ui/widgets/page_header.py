"""``PageHeader`` — H1 + subtitle + bottom rule, dropped at the top of every page.

Single responsibility: anchor the page so the user always knows where they
are without having to read the nav rail. The bottom rule comes from QSS
on ``QFrame#page-header`` and matches DIVIDER_PAGE so it reads as a hairline.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from .. import theme as t


class PageHeader(QFrame):
    def __init__(
        self,
        title: str,
        subtitle: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("page-header")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(3)

        self._title = QLabel(title)
        self._title.setProperty("role", "page-title")
        layout.addWidget(self._title)

        self._subtitle = QLabel(subtitle)
        self._subtitle.setProperty("role", "page-subtitle")
        layout.addWidget(self._subtitle)

    def set_title(self, title: str) -> None:
        self._title.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle.setText(subtitle)
