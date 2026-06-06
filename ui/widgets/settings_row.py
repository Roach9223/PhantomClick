"""``SettingsRow`` — single row inside a :class:`SettingsGroup`.

Layout::

    [leading?]  [label_block (left)]              [control(s) (right)]
                title + optional desc below

The optional ``leading`` widget is prepended (e.g. a :class:`ZoneThumbnail`
on a hover-zone row). The control area accepts one or more widgets via
:meth:`set_control` / :meth:`add_control`.

Hairline separator at the bottom is drawn via QSS on
``QFrame[role="settings-row"]``; the parent :class:`SettingsGroup` flips
the ``last`` attribute on the trailing row to suppress its border.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme as t


class SettingsRow(QFrame):
    def __init__(
        self,
        title: str,
        desc: Optional[str] = None,
        leading: Optional[QWidget] = None,
        parent: Optional[QWidget] = None,
        *,
        mono_desc: bool = False,
    ):
        """``mono_desc=True`` swaps the desc styling from the standard
        quiet-tertiary helper text to mono primary — used by Monitor's
        Phone URL row where the desc IS the value the user copies."""
        super().__init__(parent)
        self.setProperty("role", "settings-row")
        self.setMinimumHeight(t.ROW_HEIGHT_MIN)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(t.ROW_PAD_X, t.ROW_PAD_Y, t.ROW_PAD_X, t.ROW_PAD_Y)
        outer.setSpacing(t.SP_LG)

        if leading is not None:
            outer.addWidget(leading)

        label_col = QVBoxLayout()
        label_col.setContentsMargins(0, 0, 0, 0)
        label_col.setSpacing(2)

        self._title = QLabel(title)
        self._title.setProperty("role", "row-label")
        label_col.addWidget(self._title)

        self._desc: Optional[QLabel] = None
        if desc:
            self._desc = QLabel(desc)
            self._desc.setProperty("role", "mono" if mono_desc else "row-desc")
            self._desc.setWordWrap(True)
            if mono_desc:
                # The mono-desc is treated as a value the user might want
                # to drag-select (URL, key, hash). Standard desc is quiet
                # helper text; doesn't need selection.
                self._desc.setTextInteractionFlags(
                    Qt.TextSelectableByMouse
                )
            label_col.addWidget(self._desc)

        outer.addLayout(label_col, 1)

        self._control_layout = QHBoxLayout()
        self._control_layout.setContentsMargins(0, 0, 0, 0)
        self._control_layout.setSpacing(t.SP_SM)
        self._control_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        outer.addLayout(self._control_layout)

    # -- Control API -------------------------------------------------------

    def set_control(self, widget: QWidget) -> None:
        """Replace the right-side control(s) with ``widget``."""
        while self._control_layout.count():
            item = self._control_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self._control_layout.addWidget(widget)

    def add_control(self, widget: QWidget) -> None:
        """Append an additional control (e.g. value chip next to a slider)."""
        self._control_layout.addWidget(widget)

    # -- Desc API ----------------------------------------------------------

    def set_desc(self, text: str) -> None:
        """Update the desc text after construction. Used by rows whose
        desc is a live value (e.g. Monitor's Phone URL row, where the
        URL changes when the user regenerates the access token)."""
        if self._desc is not None:
            self._desc.setText(text)

    # -- Last-row marker ---------------------------------------------------

    def set_last(self, last: bool) -> None:
        """Toggle the ``last`` attribute so QSS hides the bottom hairline
        on the final row of a :class:`SettingsGroup`."""
        new = "true" if last else "false"
        if self.property("last") == new:
            return
        self.setProperty("last", new)
        self.style().unpolish(self)
        self.style().polish(self)

    # -- Wholesale enable/disable -----------------------------------------

    def set_row_enabled(self, enabled: bool) -> None:
        """Disable the row's control(s) without affecting the label tone.
        Used when a master toggle gates a group of dependent rows."""
        for i in range(self._control_layout.count()):
            w = self._control_layout.itemAt(i).widget()
            if w is not None:
                w.setEnabled(enabled)
