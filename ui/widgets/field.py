"""``Field``: vertical row: label + value (top), control (middle), hint
(bottom).

Wraps any single control in a consistent rhythm. The label is an
uppercase tracked micro-label in TEXT_SECONDARY; the optional value widget
sits right-aligned next to it as a mono readout.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme as t


def micro_label(text: str, parent: Optional[QWidget] = None) -> QLabel:
    """Uppercase 10.5 px tracked field label in TEXT_SECONDARY."""
    lbl = QLabel(text.upper(), parent)
    lbl.setStyleSheet(
        f"color: {t.TEXT_SECONDARY}; "
        f"font-size: {t.SIZE_FIELD_LABEL}px; "
        f"font-weight: 600;"
    )
    font = lbl.font()
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, t.LABEL_TRACKING)
    lbl.setFont(font)
    return lbl


class Field(QWidget):
    def __init__(
        self,
        label: str,
        control: QWidget,
        value_widget: Optional[QWidget] = None,
        hint: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(t.SP_SM)
        self.label = micro_label(label)
        head.addWidget(self.label)
        head.addStretch(1)
        if value_widget is not None:
            head.addWidget(value_widget)
        outer.addLayout(head)

        outer.addWidget(control)

        if hint:
            self.hint = QLabel(hint)
            self.hint.setWordWrap(True)
            self.hint.setStyleSheet(
                f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_HINT}px;"
            )
            outer.addWidget(self.hint)


def value_label(initial: str = "") -> QLabel:
    """Convenience: a mono readout for use as ``Field``'s ``value_widget``.
    Primary text, not lime: a settled value is not a live state."""
    lbl = QLabel(initial)
    lbl.setStyleSheet(
        f"color: {t.TEXT_PRIMARY}; "
        f"font-family: {t.FONT_MONO}; "
        f"font-size: {t.SIZE_FIELD_VALUE}px;"
    )
    lbl.setMinimumWidth(56)
    lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return lbl
