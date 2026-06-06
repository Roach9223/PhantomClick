"""Command palette — Ctrl+K popup over the App window.

Frameless dialog with a search input on top and a custom-painted list of
matching commands below. Empty search shows every available command grouped
by category; typed input shows the top scored matches.

Keys: ``↑↓`` navigate, ``Enter`` executes the highlighted row, ``Esc`` closes,
``Tab/Shift+Tab`` also navigate. Click commits a row directly. Clicking
outside the palette (focus loss) closes it.

Architecture: single QDialog subclass + a custom list-of-rows widget. We
don't use QListWidget because we need per-row sub-labels (category + shortcut)
with the same paint style and the QStyledItemDelegate dance is more code.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QLineEdit, QSizePolicy, QVBoxLayout, QWidget,
)

from . import theme as t
from .commands import Command
from .widgets.fuzzy_match import score


_PALETTE_W = 520
_PALETTE_H_MAX = 440
_MAX_RESULTS = 14


class CommandPalette(QDialog):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self._commands: List[Command] = list(app.commands)
        self._rows: List[_Row] = []
        self._highlight: int = 0

        self.setObjectName("command-palette")
        self.setWindowFlags(
            Qt.Dialog | Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setModal(False)
        self.setMinimumWidth(_PALETTE_W)
        self.setMaximumWidth(_PALETTE_W)
        self.setMaximumHeight(_PALETTE_H_MAX)

        # Soft drop shadow so the palette reads as floating over Mica.
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 200))
        self.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._frame = QFrame(self)
        self._frame.setObjectName("palette-frame")
        frame_layout = QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(t.SP_SM, t.SP_SM, t.SP_SM, t.SP_SM)
        frame_layout.setSpacing(t.SP_XS)
        outer.addWidget(self._frame)

        self.search = QLineEdit(self._frame)
        self.search.setObjectName("palette-search")
        self.search.setPlaceholderText("Type a command…")
        self.search.setClearButtonEnabled(False)
        self.search.textChanged.connect(self._refresh)
        frame_layout.addWidget(self.search)

        self._list = _Rows(self)
        frame_layout.addWidget(self._list, 1)

        self._refresh("")
        self.search.installEventFilter(self)

    # -- Position over the App window ------------------------------------

    def reposition(self) -> None:
        anchor = self.app.geometry()
        x = anchor.x() + (anchor.width() - _PALETTE_W) // 2
        y = anchor.y() + 80
        self.move(max(0, x), max(0, y))

    def showEvent(self, event):  # noqa: N802 (Qt name)
        self.reposition()
        super().showEvent(event)
        self.search.setFocus()
        self.search.selectAll()

    # -- Filter + render -------------------------------------------------

    def _refresh(self, _text: str = "") -> None:
        query = self.search.text().strip()
        rows: List[Tuple[Optional[str], Command]] = []
        if not query:
            # Empty: group by category, declared order.
            seen_cat = set()
            for c in self._commands:
                if not c.available(self.app):
                    continue
                if c.category not in seen_cat:
                    rows.append((c.category, c))
                    seen_cat.add(c.category)
                else:
                    rows.append((None, c))
        else:
            scored: List[Tuple[int, Command]] = []
            for c in self._commands:
                if not c.available(self.app):
                    continue
                target = (
                    f"{c.label} {' '.join(c.keywords)} {c.category}"
                )
                s, _ = score(query, target)
                if s >= 0:
                    scored.append((s, c))
            scored.sort(key=lambda p: -p[0])
            rows = [(None, c) for _, c in scored[:_MAX_RESULTS]]
        self._list.set_rows(rows)
        self._highlight = 0
        self._list.set_highlight(0)

    # -- Keys ------------------------------------------------------------

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.search and event.type() == QEvent.KeyPress:
            if isinstance(event, QKeyEvent):
                key = event.key()
                if key in (Qt.Key_Down, Qt.Key_Tab):
                    self._move_highlight(1)
                    return True
                if key == Qt.Key_Up or (
                    key == Qt.Key_Backtab
                    or (key == Qt.Key_Tab and event.modifiers() & Qt.ShiftModifier)
                ):
                    self._move_highlight(-1)
                    return True
                if key in (Qt.Key_Return, Qt.Key_Enter):
                    self._activate()
                    return True
                if key == Qt.Key_Escape:
                    self.close()
                    return True
        return super().eventFilter(obj, event)

    def _move_highlight(self, delta: int) -> None:
        n = self._list.command_count()
        if n == 0:
            return
        # Highlight is across selectable rows only (skip category headers).
        self._highlight = max(0, min(n - 1, self._highlight + delta))
        self._list.set_highlight(self._highlight)

    def _activate(self) -> None:
        cmd = self._list.command_at(self._highlight)
        if cmd is None:
            return
        # Close *first*, then dispatch — closing while the action runs
        # avoids focus weirdness if the action spawns an overlay.
        self.close()
        try:
            cmd.action(self.app)
        except Exception:
            self.app.log.exception(f"command failed: {cmd.id}")

    # -- Auto-close on focus loss ----------------------------------------

    def event(self, ev):  # noqa: N802
        if ev.type() == QEvent.WindowDeactivate:
            self.close()
        return super().event(ev)


# ----------------------------------------------------------------------------


class _Row(QFrame):
    clicked = Signal()

    def __init__(self, label: str, shortcut: Optional[str], category: Optional[str],
                 parent=None):
        super().__init__(parent)
        self.setObjectName("palette-row")
        self.setProperty("highlighted", False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(36)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(t.SP_SM, 4, t.SP_SM, 4)
        layout.setSpacing(t.SP_SM)

        if category:
            cat_lbl = QLabel(category.upper())
            cat_lbl.setStyleSheet(
                f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SMALL}px; "
                f"font-family: {t.FONT_DISPLAY}; font-weight: 700; "
                f"letter-spacing: 1.4px; min-width: 64px;"
            )
            layout.addWidget(cat_lbl)

        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {t.TEXT_PRIMARY};")
        layout.addWidget(lbl, 1)

        if shortcut:
            sc = QLabel(shortcut)
            sc.setStyleSheet(
                f"color: {t.TEXT_TERTIARY}; font-family: {t.FONT_MONO}; "
                f"font-size: {t.SIZE_SMALL}px;"
            )
            layout.addWidget(sc)

    def mousePressEvent(self, event):  # noqa: N802
        self.clicked.emit()
        super().mousePressEvent(event)

    def set_highlighted(self, on: bool) -> None:
        self.setProperty("highlighted", on)
        self.style().unpolish(self)
        self.style().polish(self)


class _Header(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text.upper(), parent)
        self.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SMALL}px; "
            f"font-family: {t.FONT_DISPLAY}; font-weight: 700; "
            f"letter-spacing: 1.6px; padding: {t.SP_SM}px {t.SP_SM}px {t.SP_XS}px;"
        )


class _Rows(QFrame):
    """Container that hosts header labels + selectable rows in declared order."""

    def __init__(self, palette: CommandPalette):
        super().__init__(palette)
        self.palette = palette
        self.setObjectName("palette-rows")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._row_widgets: List[_Row] = []
        self._row_commands: List[Command] = []

    def set_rows(self, items: List[Tuple[Optional[str], Command]]) -> None:
        # Wipe existing children.
        while self._layout.count():
            it = self._layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        self._row_widgets.clear()
        self._row_commands.clear()
        for category_or_none, cmd in items:
            if category_or_none is not None:
                self._layout.addWidget(_Header(category_or_none))
            row = _Row(cmd.label, cmd.shortcut, None)
            row.clicked.connect(lambda c=cmd: self._on_clicked(c))
            self._layout.addWidget(row)
            self._row_widgets.append(row)
            self._row_commands.append(cmd)
        self._layout.addStretch(1)

    def set_highlight(self, idx: int) -> None:
        for i, row in enumerate(self._row_widgets):
            row.set_highlighted(i == idx)

    def command_count(self) -> int:
        return len(self._row_commands)

    def command_at(self, idx: int) -> Optional[Command]:
        if 0 <= idx < len(self._row_commands):
            return self._row_commands[idx]
        return None

    def _on_clicked(self, cmd: Command) -> None:
        # Find the index and route through palette so close + dispatch match.
        try:
            idx = self._row_commands.index(cmd)
        except ValueError:
            return
        self.palette._highlight = idx
        self.palette._activate()
