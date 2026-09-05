"""Settings drawer: a non-modal tool window holding the config pages.

The pages themselves are the existing Hover / Behavior / Hotkeys /
Timers / Stats / Monitor / Settings / Help widgets, reparented into a
``QStackedWidget`` here. Nothing about them changes, so the WidgetLocker
registrations they made at construction keep working.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QListWidget, QListWidgetItem, QStackedWidget,
    QVBoxLayout, QWidget,
)

from . import common as c

PAGE_ORDER = (
    ("hover", "Hover"),
    ("behavior", "Behavior"),
    ("hotkeys", "Hotkeys"),
    ("timers", "Timers"),
    ("stats", "Stats"),
    ("monitor", "Monitor"),
    ("settings", "Settings"),
    ("help", "Help"),
)


class SettingsDrawer(QDialog):
    def __init__(self, app, pages: dict[str, QWidget], parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.Tool | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.app = app
        self.setObjectName("deck-settings-drawer")
        self.setWindowTitle("SETTINGS")
        self.setModal(False)
        self.resize(1040, 720)
        self.setMinimumSize(800, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body, 1)

        self.list = QListWidget()
        self.list.setObjectName("deck-drawer-nav")
        self.list.setFixedWidth(168)
        self.list.setFont(c.mono_font(c.SIZE_SM, QFont.DemiBold))
        self.list.setFrameShape(QListWidget.NoFrame)
        self.list.setStyleSheet(
            f"QListWidget#deck-drawer-nav {{ background: {c.SURFACE}; color: {c.TEXT_SECONDARY}; "
            f"border-right: 1px solid {c.BORDER}; outline: none; padding: 8px 0; }}"
            f"QListWidget#deck-drawer-nav::item {{ height: 34px; padding-left: 14px; "
            f"border-left: 2px solid transparent; }}"
            f"QListWidget#deck-drawer-nav::item:selected {{ background: {c.SURFACE_HIGH}; "
            f"color: {c.TEXT_PRIMARY}; border-left: 2px solid {c.ACCENT}; }}"
        )
        body.addWidget(self.list)

        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)

        self._ids: list[str] = []
        for page_id, label in PAGE_ORDER:
            page = pages.get(page_id)
            if page is None:
                continue
            item = QListWidgetItem(label.upper())
            item.setData(Qt.UserRole, page_id)
            self.list.addItem(item)
            self.stack.addWidget(page)
            self._ids.append(page_id)
        self.list.currentRowChanged.connect(self.stack.setCurrentIndex)
        if self._ids:
            self.list.setCurrentRow(0)

    def page_ids(self) -> list[str]:
        return list(self._ids)

    def current_page_id(self) -> Optional[str]:
        row = self.list.currentRow()
        return self._ids[row] if 0 <= row < len(self._ids) else None

    def open_page(self, page_id: str) -> None:
        if page_id in self._ids:
            self.list.setCurrentRow(self._ids.index(page_id))
        if not self.isVisible():
            parent = self.parentWidget()
            if parent is not None:
                # Land centred over the main window instead of wherever the
                # window manager last left a tool window.
                g = parent.frameGeometry()
                self.move(g.center().x() - self.width() // 2,
                          g.center().y() - self.height() // 2)
            self.show()
        self.raise_()
        self.activateWindow()
