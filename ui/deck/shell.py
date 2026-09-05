"""``DeckShell``: the command-deck main surface.

Header on top, then three columns: the left status column, the centre
splitter and the right telemetry column. The centre splitter holds the
viewport over the control deck on its left and the EDITOR PANE on its
right: the active mode's full editor page (Click page, Record tab, AI
page; each already scrolls on its own), so clicks and steps are edited
on the same screen as the live view. The header's EDITOR button shows or
hides the pane; ``deck_editor_open`` and ``deck_splitter`` persist it.
Config pages live in the :class:`SettingsDrawer`.

Also provides :class:`NavShim`, a stand-in for the old ``NavRail`` so
code that still calls ``app.nav_rail.set_current(id)`` (hover card,
palette commands on the classic shell) lands in the right place: mode
ids switch the mode, everything else opens the drawer.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QObject, QRect, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QLabel, QPushButton, QFrame, QHBoxLayout, QScrollArea, QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from modules.clicker import ClickerState
from ui.config_io import DEFAULTS

from . import common as c
from .columns import LeftColumn, RightColumn
from .control_deck import ControlDeck
from .header import DeckHeader
from .settings_drawer import SettingsDrawer
from .viewport import Viewport

WINDOW_W_DEFAULT = 1440
WINDOW_H_DEFAULT = 900
WINDOW_W_MIN = 960
WINDOW_H_MIN = 640
# Splitter floors in logical px: the viewport keeps its rulers and
# readouts legible, the editor pane keeps the step cards usable. The
# editors are built for the pane's floor, so nothing in them clips there.
VIEWPORT_MIN_W = 420
EDITOR_PANE_MIN_W = 540
_SPLIT_DEFAULT = (56, 44)

_MODE_BY_PAGE = {"click": "clicker", "record": "recorder", "ai": "ai"}
_PAGE_BY_MODE = {v: k for k, v in _MODE_BY_PAGE.items()}


def initial_geometry(cfg: dict) -> QRect:
    """Where the deck window opens.

    The saved ``window_x / y / w / h`` rect is reused only when it still
    touches a connected screen; a monitor that has since been unplugged
    (or a negative-x display that moved) must not leave the window off
    screen. Otherwise: 80% of the available area of the screen under the
    cursor, centred there, never below the minimum.
    """
    screens = list(QGuiApplication.screens())
    x, y = cfg.get("window_x"), cfg.get("window_y")
    try:
        w, h = int(cfg.get("window_w") or 0), int(cfg.get("window_h") or 0)
    except (TypeError, ValueError):
        w, h = 0, 0
    if x is not None and y is not None and w > 0 and h > 0:
        try:
            rect = QRect(int(x), int(y), max(w, WINDOW_W_MIN), max(h, WINDOW_H_MIN))
        except (TypeError, ValueError):
            rect = QRect()
        if rect.isValid() and any(rect.intersects(s.geometry()) for s in screens):
            return rect
    screen = None
    try:
        screen = QGuiApplication.screenAt(QCursor.pos())
    except Exception:
        screen = None
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        return QRect(0, 0, WINDOW_W_MIN, WINDOW_H_MIN)
    avail = screen.availableGeometry()
    w = max(WINDOW_W_MIN, int(avail.width() * 0.8))
    h = max(WINDOW_H_MIN, int(avail.height() * 0.8))
    return QRect(avail.x() + (avail.width() - w) // 2,
                 avail.y() + (avail.height() - h) // 2, w, h)


class NavShim(QObject):
    currentChanged = Signal(str)

    def __init__(self, shell: "DeckShell"):
        super().__init__(shell)
        self._shell = shell
        self._current: Optional[str] = None

    def set_current(self, item_id: str) -> None:
        self._shell.show_page(item_id)
        self._current = item_id
        self.currentChanged.emit(item_id)

    def current_id(self) -> Optional[str]:
        return self._current


class DeckShell(QWidget):
    def __init__(self, app, mode_pages: dict[str, QWidget],
                 config_pages: dict[str, QWidget], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("deck-shell")
        self.setStyleSheet(f"QWidget#deck-shell {{ background: {c.BG}; }}")
        self.nav = NavShim(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = DeckHeader(app, self)
        self.header.editorToggled.connect(self.set_editor_open)
        root.addWidget(self.header)

        self.readiness_bar = QWidget()
        readiness_row = QHBoxLayout(self.readiness_bar)
        readiness_row.setContentsMargins(14, 4, 14, 4)
        self.readiness_label = QLabel()
        self.readiness_label.setWordWrap(True)
        self.readiness_label.setStyleSheet(f"color: {c.TEXT_SECONDARY};")
        readiness_row.addWidget(self.readiness_label, 1)
        self.setup_btn = QPushButton("Open setup")
        self.setup_btn.clicked.connect(lambda: self.show_page(_PAGE_BY_MODE[self.app._active_mode]))
        readiness_row.addWidget(self.setup_btn)
        root.addWidget(self.readiness_bar)
        self.readiness_bar.hide()

        body = QHBoxLayout()
        body.setContentsMargins(10, 10, 10, 10)
        body.setSpacing(10)
        root.addLayout(body, 1)

        self.left = LeftColumn(app)
        self.left.modes.modeRequested.connect(self._on_mode_requested)
        body.addWidget(self.left)

        # Centre: viewport + control deck on the left of a splitter, the
        # editor pane on the right. The handle is as wide as the column
        # gap and painted like it, so the split reads as one more gutter.
        self.center = QSplitter(Qt.Horizontal)
        self.center.setObjectName("deck-splitter")
        self.center.setHandleWidth(10)
        self.center.setStyleSheet(
            "QSplitter#deck-splitter::handle { background: transparent; }")
        self.deck_page = QWidget()
        self.deck_page.setMinimumWidth(VIEWPORT_MIN_W)
        deck_col = QVBoxLayout(self.deck_page)
        deck_col.setContentsMargins(0, 0, 0, 0)
        deck_col.setSpacing(10)
        self.viewport = Viewport(app)
        deck_col.addWidget(self.viewport, 1)
        self.control_deck = ControlDeck(app)
        self.control_scroll = QScrollArea()
        self.control_scroll.setWidgetResizable(True)
        self.control_scroll.setFrameShape(QFrame.NoFrame)
        self.control_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.control_scroll.setFixedHeight(188)
        self.control_scroll.setWidget(self.control_deck)
        deck_col.addWidget(self.control_scroll)
        self.center.addWidget(self.deck_page)

        self.editor_pane = QFrame()
        self.editor_pane.setObjectName("deck-editor-pane")
        self.editor_pane.setMinimumWidth(EDITOR_PANE_MIN_W)
        self.editor_pane.setStyleSheet(
            f"QFrame#deck-editor-pane {{ background: {c.SURFACE}; "
            f"border: 1px solid {c.BORDER}; border-radius: {c.RADIUS_CARD}px; }}")
        pane_col = QVBoxLayout(self.editor_pane)
        pane_col.setContentsMargins(4, 4, 4, 4)
        pane_col.setSpacing(0)
        # The mode pages each wrap their own QScrollArea (ClickPage,
        # SimplePage, AIPage), so the pane adds no second scroller.
        self.editor = QStackedWidget()
        self._editor_index: dict[str, int] = {}
        for page_id in ("click", "record", "ai"):
            page = mode_pages.get(page_id)
            if page is not None:
                self._editor_index[page_id] = self.editor.addWidget(page)
        pane_col.addWidget(self.editor, 1)
        self.center.addWidget(self.editor_pane)

        # Dragging the handle past the viewport floor collapses it (and
        # stops capture); the pane is hidden through its button instead.
        self.center.setCollapsible(0, True)
        self.center.setCollapsible(1, False)
        self.center.setStretchFactor(0, _SPLIT_DEFAULT[0])
        self.center.setStretchFactor(1, _SPLIT_DEFAULT[1])
        self.center.splitterMoved.connect(self._on_splitter_moved)
        # Until the user drags the handle the split stays 56 / 44 at any
        # window size; Qt's own redistribution drifts from that.
        self.center.installEventFilter(self)
        body.addWidget(self.center, 1)

        self.right = RightColumn(app)
        body.addWidget(self.right)

        self.drawer = SettingsDrawer(app, config_pages, parent=app)

        # Restore the pane state without writing config: nothing changed yet.
        self._splitter_sizes: Optional[list[int]] = self._stored_splitter_sizes()
        self._editor_open = bool(app.cfg.get(
            "deck_editor_open", DEFAULTS.get("deck_editor_open", True)))
        self.editor_pane.setVisible(self._editor_open)
        self.header.set_editor_open(self._editor_open)
        self._sync_editor_page()
        # A fresh Record or AI mode opens straight onto its pane.
        self._auto_open_for_mode(app._active_mode)

    def _adapt_layout(self) -> None:
        """Give setup space first; telemetry returns when there is room."""
        width = self.width()
        self.right.setVisible(width >= (1660 if self._editor_open else 1220))
        self.left.setVisible(width >= (1380 if self._editor_open else 1100))
        stacked = self._editor_open and width < 1060
        self.center.setOrientation(Qt.Vertical if stacked else Qt.Horizontal)
        self.deck_page.setMinimumWidth(0 if stacked else VIEWPORT_MIN_W)
        self.deck_page.setVisible(not stacked or not self._editor_open)
        self.header.set_compact(width < 1380)
        self._apply_splitter_sizes()
        self._sync_capture()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_editor_open"):
            self._adapt_layout()

    # -- Editor pane -----------------------------------------------------------------

    def _stored_splitter_sizes(self) -> Optional[list[int]]:
        raw = self.app.cfg.get("deck_splitter")
        try:
            sizes = [int(v) for v in raw]
        except (TypeError, ValueError):
            return None
        if len(sizes) != 2 or min(sizes) <= 0:
            return None
        return sizes

    def _apply_splitter_sizes(self) -> None:
        """Stored sizes when the user has dragged the handle, else 56 / 44
        of the current width."""
        if not self._editor_open:
            return
        if self._splitter_sizes:
            self.center.setSizes(self._splitter_sizes)
            return
        total = self.center.width() - self.center.handleWidth()
        if total <= 0:
            return
        a, b = _SPLIT_DEFAULT
        left = int(total * a / (a + b))
        self.center.setSizes([left, total - left])

    def eventFilter(self, obj, event):  # noqa: N802 (Qt name)
        if obj is self.center and event.type() == QEvent.Resize:
            if self._editor_open and not self._splitter_sizes:
                self._apply_splitter_sizes()
        return super().eventFilter(obj, event)

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        sizes = self.center.sizes()
        if self._editor_open and len(sizes) == 2 and min(sizes) > 0:
            self._splitter_sizes = [int(v) for v in sizes]
            self.app.cfg["deck_splitter"] = list(self._splitter_sizes)
            # Debounced: a drag fires this per pixel.
            self.app.save_config_later()
        self._sync_capture()

    def set_editor_open(self, open_: bool) -> None:
        open_ = bool(open_)
        if open_ != self._editor_open:
            # Sizes are only remembered once the user has dragged the
            # handle (splitterMoved); an untouched split stays 62 / 38.
            self._editor_open = open_
            self.editor_pane.setVisible(open_)
            if open_:
                self._apply_splitter_sizes()
            self.app.cfg["deck_editor_open"] = open_
            self.app.save_config_later()
        self.header.set_editor_open(open_)
        self._adapt_layout()
        self._sync_capture()

    def editor_open(self) -> bool:
        return self._editor_open

    def _viewport_collapsed(self) -> bool:
        sizes = self.center.sizes()
        return bool(sizes) and sizes[0] <= 0

    def _sync_capture(self) -> None:
        """Capture runs while the viewport can be seen: window shown and
        the splitter not dragged to zero. The editor pane being open does
        not stop it; the viewport is still on screen beside it."""
        if self.isVisible() and self.deck_page.isVisible() and not self._viewport_collapsed():
            self.viewport.start()
        else:
            self.viewport.stop()

    # -- View / mode (compatibility wrappers) ----------------------------------------

    def set_view(self, view: str) -> None:
        """``"editor"`` opens the pane, ``"deck"`` closes it."""
        self.set_editor_open(view == "editor")

    def toggle_editor(self) -> None:
        self.set_editor_open(not self._editor_open)

    def current_view(self) -> str:
        return "editor" if self._editor_open else "deck"

    def _sync_editor_page(self) -> None:
        mode = self.app._active_mode
        page_id = _PAGE_BY_MODE.get(mode, "click")
        idx = self._editor_index.get(page_id)
        if idx is not None:
            self.editor.setCurrentIndex(idx)
        self.header.editor_btn.set_mode(mode)
        self.left.modes.refresh()

    def _pane_needed(self, mode: str) -> bool:
        """True when the mode cannot do anything until the pane is used:
        Record with no steps, AI with no bot picked. Click never needs it;
        the deck's REDRAW ZONE and NO ZONE row cover an empty click mode."""
        app = self.app
        if mode == "recorder":
            return not app._steps
        if mode == "clicker":
            return app._zone is None
        if mode == "ai":
            cfg = app.cfg
            return not (str(cfg.get("ai_bot_slug") or "").strip()
                        or bool(cfg.get("ai_use_user_bot"))
                        or str(cfg.get("ai_active_bundle") or "").strip())
        return False

    def _auto_open_for_mode(self, mode: str) -> None:
        if self._pane_needed(mode) and not self._editor_open:
            self.set_editor_open(True)

    def _on_mode_requested(self, mode: str) -> None:
        if self.app._state_str != ClickerState.IDLE and mode != self.app._active_mode:
            self.app.toasts.post("Stop the engine before switching modes.", kind="warn")
            return
        self.set_mode(mode)

    def set_mode(self, mode: str) -> None:
        if mode not in _PAGE_BY_MODE:
            return
        # nav_section is written first so _set_active_mode's own save
        # covers it; the deck restores from active_mode anyway, so an
        # unchanged mode needs no extra write.
        self.app.cfg["nav_section"] = _PAGE_BY_MODE[mode]
        self.app._set_active_mode(mode)
        self._sync_editor_page()
        self._auto_open_for_mode(mode)

    def show_page(self, page_id: str) -> None:
        mode = _MODE_BY_PAGE.get(page_id)
        if mode is not None:
            self.set_mode(mode)
            # Asking for a mode page means asking to edit it.
            self.set_editor_open(True)
            return
        if page_id in self.drawer.page_ids():
            self.drawer.open_page(page_id)

    # -- Lifecycle -------------------------------------------------------------------

    def showEvent(self, event):  # noqa: N802 (Qt name)
        super().showEvent(event)
        self._adapt_layout()
        self._apply_splitter_sizes()
        self._sync_capture()

    def hideEvent(self, event):  # noqa: N802 (Qt name)
        super().hideEvent(event)
        self.viewport.stop()

    def tick(self) -> None:
        from ui.readiness import readiness_message
        message = readiness_message(self.app) if self.app._state_str == ClickerState.IDLE else ""
        if getattr(self.app, "_ai_preparing", False):
            message = "Preparing bot images. Stop cancels startup."
        self.readiness_label.setText(message)
        self.readiness_bar.setVisible(bool(message))
        self.setup_btn.setVisible(not getattr(self.app, "_ai_preparing", False))
        self.header.start_btn.setToolTip(message or "Start the configured automation")
        for part in (self.header, self.left, self.right, self.control_deck):
            try:
                part.tick()
            except Exception:
                pass
        if not self._viewport_collapsed():
            try:
                self.viewport.tick()
            except Exception:
                pass

    def shutdown(self) -> None:
        self.viewport.stop()
        try:
            self.drawer.close()
        except Exception:
            pass


__all__ = [
    "DeckShell", "NavShim", "initial_geometry",
    "WINDOW_W_DEFAULT", "WINDOW_H_DEFAULT", "WINDOW_W_MIN", "WINDOW_H_MIN",
    "VIEWPORT_MIN_W", "EDITOR_PANE_MIN_W",
]
