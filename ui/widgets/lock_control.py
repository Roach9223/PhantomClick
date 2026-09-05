"""``ZoneLockControl``: LOCK  WINDOW | SCREEN plus a picker of the windows
the zone can follow.

One row shared by the Click zone card and the Record step bodies so the
lock switch looks and behaves the same everywhere. The control never
touches the zone itself; it emits ``modeChanged`` when the segment flips
and ``windowChosen`` (a ``WindowInfo``) when the user picks a different
window from the list, and the owner decides how to re-anchor (see
``modules.zone_lock.apply_lock_mode`` / ``retarget_lock``).

The picker lists every lockable top-level window (``Title  ·  exe``),
refreshed each time it opens, with the locked window selected. Switching
from one game client to another is one pick; the zone keeps its place
relative to the window.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSizePolicy, QWidget

from .. import theme as t
from .segmented import SegmentedControl

MODE_WINDOW = "window"
MODE_SCREEN = "screen"

_READOUT_MAX_PX = 220


class _WindowPicker(QComboBox):
    """Combo that re-enumerates the desktop's windows every time it opens,
    so a game launched after the app still shows up."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        # Elides to whatever width the row leaves it; the pane floor is
        # 480 px and the LOCK label plus segment take about 270 of it.
        self.setMinimumWidth(120)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(10)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._current: Optional[tuple[str, str]] = None   # (title, cls) selected
        self._infos: list = []

    def _matches(self, info, title: str, cls: str) -> bool:
        if info.cls != cls:
            return False
        a, b = (info.title or "").lower(), (title or "").lower()
        return a == b or (bool(a) and bool(b) and (a in b or b in a))

    def repopulate(self, selected: Optional[tuple[str, str]] = None) -> None:
        """Rebuild the list from the live desktop; keep ``selected`` (or
        the previous selection) current. A locked window that is not on
        the desktop right now is listed once as unavailable so the row
        still says what the zone is waiting for."""
        try:
            from utils.window_finder import list_lock_targets
            infos = list(list_lock_targets())
        except Exception:
            infos = []
        if selected is not None:
            self._current = selected
        self._infos = infos
        self.blockSignals(True)
        self.clear()
        pick = -1
        for i, info in enumerate(infos):
            self.addItem(info.label, userData=i)
            self.setItemData(i, f"{info.title}\nClass: {info.cls}\nProcess: {info.exe or '?'}",
                             Qt.ToolTipRole)
            if pick < 0 and self._current and self._matches(info, *self._current):
                pick = i
        if self._current and pick < 0:
            title, cls = self._current
            self.addItem(f"{title or cls}  ·  not open", userData=-1)
            pick = self.count() - 1
        if pick >= 0:
            self.setCurrentIndex(pick)
        self.blockSignals(False)

    def chosen_info(self):
        idx = self.currentData()
        if isinstance(idx, int) and 0 <= idx < len(self._infos):
            return self._infos[idx]
        return None

    def showPopup(self) -> None:  # noqa: N802 (Qt name)
        self.repopulate()
        super().showPopup()


class ZoneLockControl(QWidget):
    modeChanged = Signal(str)       # "window" | "screen"
    windowChosen = Signal(object)   # utils.window_finder.WindowInfo

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(t.SP_MD)

        lbl = QLabel("LOCK")
        lbl.setProperty("role", "section-label")
        font = lbl.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, t.LABEL_TRACKING)
        lbl.setFont(font)
        lbl.setFixedWidth(96)
        lbl.setToolTip(
            "WINDOW: the zone follows the window picked on the right, so a "
            "dragged or resized game window keeps the clicks on target, and "
            "you can switch it to another window at any time. "
            "SCREEN: fixed screen coordinates."
        )
        row.addWidget(lbl)

        self.seg = SegmentedControl(
            [(MODE_WINDOW, "Window"), (MODE_SCREEN, "Screen")],
            value=MODE_SCREEN,
            tooltips={
                MODE_WINDOW: (
                    "WINDOW: the zone is tied to a window. Drag or resize "
                    "that window and the clicks follow it. If the window is "
                    "minimised or closed the engine holds instead of clicking "
                    "whatever is underneath. Pick the window from the list."),
                MODE_SCREEN: (
                    "SCREEN: the zone stays at fixed screen coordinates no "
                    "matter which window is there. Use it for things that "
                    "never move, like a full-screen game."),
            },
        )
        self.seg.valueChanged.connect(self.modeChanged)
        row.addWidget(self.seg)

        self.picker = _WindowPicker()
        self.picker.setToolTip(
            "The window the zone follows. Open the list to see every window "
            "on the desktop and pick another one; the zone keeps its place "
            "relative to the window.")
        self.picker.activated.connect(self._on_pick)
        row.addWidget(self.picker, 1)

        self.readout = QLabel("")
        self.readout.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_SM}px; background: transparent;"
        )
        self.readout.setMaximumWidth(_READOUT_MAX_PX)
        self.readout.setToolTip("SCREEN lock: the zone is a fixed screen position.")
        row.addWidget(self.readout, 1)
        self._full_title = ""
        self._locked: Optional[tuple[str, str]] = None
        self._show_mode(MODE_SCREEN)

    def _show_mode(self, mode: str) -> None:
        # isHidden, not isVisible: before the row is shown both read as
        # not visible and the readout would leak into WINDOW mode.
        window = mode == MODE_WINDOW
        if self.picker.isHidden() == window:
            self.picker.setVisible(window)
        if self.readout.isHidden() != window:
            self.readout.setVisible(not window)

    def _on_pick(self, _index: int) -> None:
        info = self.picker.chosen_info()
        if info is None:
            return
        if self._locked and self.picker._matches(info, *self._locked):
            return
        self.windowChosen.emit(info)

    def set_zone(self, zone) -> None:
        """Mirror ``zone``'s lock without emitting anything."""
        has_zone = zone is not None
        self.setEnabled(has_zone)
        lock = getattr(zone, "lock", None) if has_zone else None
        mode = MODE_WINDOW if lock is not None else MODE_SCREEN
        self.seg.setValue(mode, emit=False)
        self._show_mode(mode)
        if lock is not None:
            self._locked = (lock.title or "", lock.cls or "")
            self._full_title = lock.title or lock.cls or "(untitled window)"
            self.picker.repopulate(self._locked)
        else:
            self._locked = None
            self._full_title = "Fixed screen position" if has_zone else ""
        self._apply_elide()

    def _apply_elide(self) -> None:
        fm = QFontMetrics(self.readout.font())
        self.readout.setText(fm.elidedText(self._full_title, Qt.ElideMiddle, _READOUT_MAX_PX))

    def resizeEvent(self, event):  # noqa: N802 (Qt name)
        super().resizeEvent(event)
        self._apply_elide()
