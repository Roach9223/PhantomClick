"""``SettingsGroup`` — rounded panel that contains :class:`SettingsRow`
instances stacked vertically with managed hairline separators.

Manages the ``last`` flag on its rows so the trailing row's bottom border
disappears automatically. Non-row widgets (e.g. an :class:`EmptyState`)
can be added via :meth:`add_widget` to bypass the separator logic.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from .settings_row import SettingsRow


class SettingsGroup(QFrame):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setProperty("role", "settings-group")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._rows: List[SettingsRow] = []

    def add_row(self, row: SettingsRow) -> SettingsRow:
        for prev in self._rows:
            prev.set_last(False)
        self._rows.append(row)
        row.set_last(True)
        self._layout.addWidget(row)
        return row

    def add_widget(self, widget: QWidget) -> QWidget:
        """Append a non-row widget (e.g. an :class:`EmptyState`).
        Bypasses the row-separator bookkeeping."""
        self._layout.addWidget(widget)
        return widget

    def set_active(self, active: bool) -> None:
        """Toggle the ``[active="true"]`` attribute. Used by master-
        switch groups (Behavior's Idle wander, Fatigue, …) to surface
        a 3 px teal left stripe when their master is on. Mirrors the
        active-state pattern used by Record's expanded step cards and
        Monitor's listening card."""
        new = "true" if active else "false"
        if self.property("active") == new:
            return
        self.setProperty("active", new)
        self.style().unpolish(self)
        self.style().polish(self)

    def clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._rows = []
