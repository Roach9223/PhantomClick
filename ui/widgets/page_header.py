"""Page headers.

``PageHeader`` is the H1 + subtitle + bottom rule used by the config pages
in the settings drawer and on the classic shell.

``EditorHeader`` is the compact version the deck's editor pane uses for
the three mode editors (Click, Record, AI): an uppercase tracked title on
one line, a one-line hint under it, a hairline below. It sits beside the
live viewport, so it stays short and never repeats what the MODES panel
already says.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

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


class EditorHeader(QFrame):
    """Compact editor-pane header: ``TITLE`` (uppercase, tracked, primary)
    with an optional trailing widget on the same line, a hint beneath."""

    def __init__(
        self,
        title: str,
        hint: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("page-header")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(t.SP_XS, t.SP_XS, t.SP_XS, t.SP_SM)
        layout.setSpacing(2)

        self.title_row = QHBoxLayout()
        self.title_row.setContentsMargins(0, 0, 0, 0)
        self.title_row.setSpacing(t.SP_SM)
        self._title = QLabel(title.upper())
        self._title.setProperty("role", "card-header")
        font = self._title.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, t.PANEL_HEADER_TRACKING)
        self._title.setFont(font)
        self.title_row.addWidget(self._title)
        self.title_row.addStretch(1)
        layout.addLayout(self.title_row)

        self._hint = QLabel(hint)
        self._hint.setProperty("role", "hint")
        self._hint.setWordWrap(True)
        self._hint.setVisible(bool(hint))
        layout.addWidget(self._hint)

    def add_trailing(self, widget: QWidget) -> QWidget:
        """Park a control (count chip, add button) at the right end of
        the title line."""
        self.title_row.addWidget(widget)
        return widget

    def set_title(self, title: str) -> None:
        self._title.setText(title.upper())

    def set_hint(self, hint: str) -> None:
        self._hint.setText(hint)
        self._hint.setVisible(bool(hint))
