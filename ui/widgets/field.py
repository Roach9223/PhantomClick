"""``Field`` — vertical row: label · value (top), control (middle), hint (bottom).

Used to wrap any single control in a consistent rhythm. The value widget
is optional — when present it sits right-aligned next to the label so
the eye reads ``Frequency      0.13`` like a meter.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme as t


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

        # Top row: label (semibold) · spacer · value (mono accent).
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(t.SP_SM)
        self.label = QLabel(label)
        self.label.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_FIELD_LABEL}px; "
            f"font-weight: 600;"
        )
        head.addWidget(self.label)
        head.addStretch(1)
        if value_widget is not None:
            head.addWidget(value_widget)
        outer.addLayout(head)

        # Control fills the field width.
        outer.addWidget(control)

        # Optional hint line under the control.
        if hint:
            self.hint = QLabel(hint)
            self.hint.setWordWrap(True)
            self.hint.setStyleSheet(
                f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_HINT}px;"
            )
            outer.addWidget(self.hint)


def value_label(initial: str = "") -> QLabel:
    """Convenience: a mono accent value display for use as ``Field``'s
    ``value_widget``."""
    lbl = QLabel(initial)
    lbl.setStyleSheet(
        f"color: {t.ACCENT}; "
        f"font-family: {t.FONT_MONO}; "
        f"font-size: {t.SIZE_FIELD_VALUE}px;"
    )
    lbl.setMinimumWidth(56)
    from PySide6.QtCore import Qt
    lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return lbl
