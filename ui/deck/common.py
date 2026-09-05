"""Shared building blocks for the command-deck shell.

Everything in ``ui/deck`` codes against the 2026 token contract by name
but reads each token through :func:`tok` so the shell still runs on the
old theme module while the retoken lands. Icons go through
:func:`icon_pixmap`, which prefers ``ui.icons`` and falls back to a
drawn placeholder so a missing registry never breaks construction.
"""

from __future__ import annotations

import math
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QFontMetrics, QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QToolButton,
    QVBoxLayout, QWidget,
)

from .. import theme as t


def tok(name: str, fallback):
    """Theme token by name; falls back when the token has not landed yet."""
    return getattr(t, name, fallback)


# -- Palette (contract names, contract fallbacks) ---------------------------
# ACCENT (ice blue) = selected / focused / target / primary control.
# RUN (green) = live / running / nominal. See ui/theme.py.

BG = tok("BG", "#0E1116")
SURFACE = tok("SURFACE", "#151A21")
SURFACE_HIGH = tok("SURFACE_HIGH", "#1B222B")
SURFACE_PRESS = tok("SURFACE_PRESS", "#222B36")
SURFACE_PANEL = tok("SURFACE_PANEL", "#11161C")
BORDER = tok("BORDER", "#26303B")
BORDER_STRONG = tok("BORDER_STRONG", "#34414F")
ACCENT = tok("ACCENT", "#7CC4F2")
RUN = tok("RUN", ACCENT)
STOP = tok("STOP", "#E5484D")
DANGER = tok("DANGER", "#E5484D")
WARN = tok("WARN", "#E0A83A")
TEXT_PRIMARY = tok("TEXT_PRIMARY", "#DCE3EA")
TEXT_SECONDARY = tok("TEXT_SECONDARY", "#B4BEC9")
TEXT_TERTIARY = tok("TEXT_TERTIARY", "#7C8894")
TEXT_DISABLED = tok("TEXT_DISABLED", "#5C6772")
TEXT_MICRO = tok("TEXT_TERTIARY", "#7C8894")
STATUS_IDLE = tok("STATUS_IDLE", "#3B4652")

SIZE_XS = tok("SIZE_XS", 10)
SIZE_SM = tok("SIZE_SM", 12)
SIZE_BODY = tok("SIZE_BODY", 13)
SIZE_LG = tok("SIZE_LG", 14)
SIZE_XL = tok("SIZE_XL", 18)
SIZE_TITLE = tok("SIZE_TITLE", 22)
LABEL_TRACKING = tok("LABEL_TRACKING", 1.2)
RADIUS_CARD = tok("RADIUS_CARD", 8)
RADIUS_BUTTON = tok("RADIUS_BUTTON", 6)
BUTTON_H = tok("BUTTON_H", 30)
DUR_NORMAL = tok("DUR_NORMAL", 120)
SWEEP_PERIOD_MS = tok("SWEEP_PERIOD_MS", 4000)

_FONT_MONO_STACK = tok("FONT_MONO", "JetBrains Mono, Consolas, monospace")
_FONT_LABEL_STACK = tok("FONT_LABEL", None) or tok("FONT_FAMILY", "Barlow, Segoe UI, sans-serif")
_FONT_DISPLAY_STACK = tok("FONT_DISPLAY", "Barlow, Segoe UI, sans-serif")


def _first_family(stack: str) -> str:
    return str(stack).split(",")[0].strip().strip("'\"")


FONT_MONO_FAMILY = _first_family(_FONT_MONO_STACK)
FONT_LABEL_FAMILY = _first_family(_FONT_LABEL_STACK)
FONT_DISPLAY_FAMILY = _first_family(_FONT_DISPLAY_STACK)


def _px(size: float) -> int:
    """Theme sizes are stylesheet pixels; the deck painted its own labels
    in points, which at Qt's fixed 96 dpi logical scale is 4/3 of that.
    Keep the ratio so the deck stays a notch larger than the editor."""
    return max(1, int(round(float(size) * 4.0 / 3.0)))


def _crisp(f: QFont) -> QFont:
    # Same treatment as the application font in main.py: full hinting so
    # small mono text snaps to the pixel grid on a 100 % monitor.
    f.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


def mono_font(size: float = SIZE_BODY, weight: int = QFont.Normal) -> QFont:
    """Value face: numbers, coordinates, times, keys, the log."""
    f = QFont(FONT_MONO_FAMILY)
    f.setPixelSize(_px(size))
    f.setWeight(weight)
    return _crisp(f)


def label_font(size: float = SIZE_SM, weight: int = QFont.DemiBold,
               tracking: float = 0.0) -> QFont:
    """Label face: panel titles, row keys, buttons, captions. Barlow at
    the same 4/3 scale as the mono face so the two sit on one baseline."""
    f = QFont(FONT_LABEL_FAMILY)
    f.setPixelSize(_px(size))
    f.setWeight(weight)
    if tracking:
        f.setLetterSpacing(QFont.AbsoluteSpacing, float(tracking))
    return _crisp(f)


def display_font(size: float = SIZE_TITLE, weight: int = QFont.Bold) -> QFont:
    f = QFont(FONT_DISPLAY_FAMILY)
    f.setPixelSize(_px(size))
    f.setWeight(weight)
    return _crisp(f)


def micro_font() -> QFont:
    """Uppercase tracked label: Barlow SemiBold, LABEL_TRACKING."""
    return label_font(SIZE_XS, QFont.DemiBold, float(LABEL_TRACKING))


# Engine states as the deck says them. One word per state, everywhere.
_STATE_WORDS = {
    "idle": "STANDBY",
    "starting": "ARMING",
    "active": "RUNNING",
    "paused": "HOLD",
    "stopping": "STOPPING",
}


def state_word(state) -> str:
    """``ClickerState`` (or its string) as the deck vocabulary: STANDBY,
    ARMING, RUNNING, HOLD. Unknown states pass through uppercased."""
    key = str(getattr(state, "value", state) or "").strip().lower()
    return _STATE_WORDS.get(key, key.upper() or "STANDBY")


# -- Icons -----------------------------------------------------------------

def _placeholder_pixmap(name: str, size: int, color: str, degrees: float) -> QPixmap:
    """Drawn stand-in used until ``ui.icons`` ships: a thin ring with a
    directional tick so rotated variants still read as rotated."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(size / 2, size / 2)
    p.rotate(degrees)
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.0, size / 14))
    p.setPen(pen)
    r = size * 0.36
    p.drawEllipse(QRectF(-r, -r, 2 * r, 2 * r))
    p.drawLine(0, int(-r * 0.2), 0, int(-r * 0.85))
    p.end()
    return pm


def icon_pixmap(name: str, size: int, color: str, degrees: float = 0.0) -> QPixmap:
    try:
        from ui import icons  # the registry another agent is authoring
        if degrees:
            pm = icons.rotated_pixmap(name, size, color, degrees)
        else:
            pm = icons.pixmap(name, size, color)
        if pm is not None and not pm.isNull():
            return pm
    except Exception:
        pass
    return _placeholder_pixmap(name, size, color, degrees)


class IconButton(QToolButton):
    """Square icon-only button. ``variant`` is left to the stylesheet."""

    def __init__(self, name: str, size: int = 30, icon_px: int = 16,
                 color: str = TEXT_SECONDARY, tooltip: str = "",
                 degrees: float = 0.0, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._name = name
        self._icon_px = icon_px
        self._degrees = degrees
        self.setObjectName("deck-icon-btn")
        self.setProperty("variant", "ghost")
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setAutoRaise(True)
        if tooltip:
            self.setToolTip(tooltip)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        self._color = color
        self.setIcon(icon_pixmap(self._name, self._icon_px, color, self._degrees))
        self.setIconSize(self.iconSize().expandedTo(
            QPixmap(self._icon_px, self._icon_px).size()))

    def set_icon(self, name: str, color: Optional[str] = None) -> None:
        """Swap the glyph, keeping the colour unless one is given."""
        self._name = name
        self.set_color(color if color is not None else getattr(self, "_color", TEXT_SECONDARY))


# -- Labels ------------------------------------------------------------------

class MicroLabel(QLabel):
    """Uppercase tracked micro-label. Text is uppercased in code because
    QSS ``text-transform`` is unreliable in Qt."""

    def __init__(self, text: str = "", color: str = TEXT_MICRO,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setProperty("role", "micro")
        self.setFont(micro_font())
        self._color = color
        self.setStyleSheet(f"color: {color}; background: transparent;")
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt name)
        super().setText(str(text).upper())

    def set_color(self, color: str) -> None:
        if color != self._color:
            self._color = color
            self.setStyleSheet(f"color: {color}; background: transparent;")


class MonoLabel(QLabel):
    def __init__(self, text: str = "", color: str = TEXT_PRIMARY,
                 size: float = SIZE_BODY, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setProperty("role", "mono")
        self.setFont(mono_font(size))
        self._color = color
        self.setStyleSheet(f"color: {color}; background: transparent;")

    def set_color(self, color: str) -> None:
        if color != self._color:
            self._color = color
            self.setStyleSheet(f"color: {color}; background: transparent;")


# -- Panel -------------------------------------------------------------------

class Panel(QFrame):
    """Bordered surface with a micro title row. The deck's unit of layout.

    A ``collapsible`` panel folds to its title row: :meth:`sync_open`
    opens it whenever the caller says the content matters (the engine is
    running) and otherwise leaves it as the user last set it, closed by
    default. Telemetry a new user has not earned yet stays out of the way
    until there is something to read.
    """

    def __init__(self, title: str, parent: Optional[QWidget] = None,
                 collapsible: bool = False):
        super().__init__(parent)
        self.setObjectName("deck-panel")
        self.setProperty("role", "panel")
        self.setStyleSheet(
            f"QFrame#deck-panel {{ background: {SURFACE}; border: 1px solid {BORDER}; "
            f"border-radius: {RADIUS_CARD}px; }}"
        )
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(12, 10, 12, 12)
        self._outer.setSpacing(8)
        self.title = MicroLabel(title, TEXT_TERTIARY)
        self.title.setProperty("role", "panel-title")
        # Title row: the label plus a stretch, so a panel can park a tiny
        # action (the log's CLEAR) on the right without a second header.
        self.title_row = QHBoxLayout()
        self.title_row.setContentsMargins(0, 0, 0, 0)
        self.title_row.setSpacing(8)
        self.title_row.addWidget(self.title)
        self.title_row.addStretch(1)
        self._outer.addLayout(self.title_row)
        self.body_widget = QWidget()
        self.body_widget.setAttribute(Qt.WA_StyledBackground, False)
        self.body_widget.setStyleSheet("background: transparent;")
        self._body = QVBoxLayout(self.body_widget)
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(6)
        self._outer.addWidget(self.body_widget, 1)
        self._collapsible = bool(collapsible)
        self._open = True
        self._user_open: Optional[bool] = None
        self.chevron: Optional[QLabel] = None
        if self._collapsible:
            self.chevron = QLabel()
            self.chevron.setFixedSize(14, 14)
            self.title_row.addWidget(self.chevron)
            self.setCursor(Qt.PointingHandCursor)
            self._paint_chevron()

    def body_layout(self) -> QVBoxLayout:
        return self._body

    # -- Collapse --------------------------------------------------------------

    def is_open(self) -> bool:
        return self._open

    def _paint_chevron(self) -> None:
        if self.chevron is not None:
            self.chevron.setPixmap(icon_pixmap(
                "chevron-down" if self._open else "chevron-right", 14, TEXT_TERTIARY))

    def set_open(self, open_: bool) -> None:
        open_ = bool(open_)
        if open_ == self._open:
            return
        self._open = open_
        self.body_widget.setVisible(open_)
        self._outer.setContentsMargins(12, 10, 12, 12 if open_ else 10)
        self._paint_chevron()

    def sync_open(self, needed: bool) -> None:
        """Open when ``needed``; otherwise the user's last choice, which
        defaults to closed."""
        if not self._collapsible:
            return
        self.set_open(bool(needed) or bool(self._user_open))

    def mousePressEvent(self, event):  # noqa: N802 (Qt name)
        if self._collapsible and event.button() == Qt.LeftButton \
                and event.position().y() <= self.title.geometry().bottom() + 8:
            self._user_open = not self._open
            self.set_open(self._user_open)
            event.accept()
            return
        super().mousePressEvent(event)


class KVGrid(QWidget):
    """Two-column key / value grid: Barlow keys, mono values.
    ``set_value`` recolors the value so callers can flag live (green) vs
    off (tertiary). A row can carry a micro suffix (probe age, unit) and
    be made clickable; ``rowClicked`` then fires with the row key.
    ``tips`` maps a key to the tooltip both its cells show, so every row
    can say what it measures."""

    rowClicked = Signal(str)

    def __init__(self, keys: list[str], parent: Optional[QWidget] = None,
                 tips: Optional[dict[str, str]] = None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        self._values: dict[str, MonoLabel] = {}
        self._suffixes: dict[str, MicroLabel] = {}
        self._keys: dict[str, MicroLabel] = {}
        self._cells: dict[str, QWidget] = {}
        self._clickable: set[str] = set()
        for row, key in enumerate(keys):
            k = MicroLabel(key, TEXT_MICRO)
            cell = QWidget()
            cell.setAttribute(Qt.WA_StyledBackground, False)
            cell.setStyleSheet("background: transparent;")
            h = QHBoxLayout(cell)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            h.addStretch(1)
            v = MonoLabel("··", TEXT_TERTIARY, SIZE_XS)
            v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            h.addWidget(v)
            sfx = MicroLabel("", TEXT_MICRO)
            sfx.hide()
            h.addWidget(sfx)
            grid.addWidget(k, row, 0)
            grid.addWidget(cell, row, 1)
            self._values[key] = v
            self._suffixes[key] = sfx
            self._keys[key] = k
            self._cells[key] = cell
            tip = (tips or {}).get(key)
            if tip:
                k.setToolTip(tip)
                cell.setToolTip(tip)

    def set_tip(self, key: str, tip: str) -> None:
        """Tooltip for a whole row (key cell and value cell)."""
        for w in (self._keys.get(key), self._cells.get(key)):
            if w is not None and w.toolTip() != tip:
                w.setToolTip(tip)

    def set_value(self, key: str, text: str, color: Optional[str] = None,
                  tooltip: Optional[str] = None, suffix: Optional[str] = None) -> None:
        lbl = self._values.get(key)
        if lbl is None:
            return
        # Keep the full string so a resize can re-elide it; QLabel never
        # elides on its own and a right-aligned label clips its head,
        # which is the part that carries meaning ("COM8 NOT FOUND").
        lbl.setProperty("full_text", text)
        self._apply_elide(key)
        if color is not None:
            lbl.set_color(color)
        if tooltip is not None:
            self.set_tip(key, tooltip)
        sfx = self._suffixes[key]
        if suffix:
            if sfx.text() != suffix.upper():
                sfx.setText(suffix)
            if sfx.isHidden():
                sfx.show()
        elif not sfx.isHidden():
            sfx.hide()
        self._apply_elide(key)

    def _apply_elide(self, key: str) -> None:
        lbl = self._values[key]
        full = lbl.property("full_text") or ""
        sfx = self._suffixes[key]
        avail = self._cells[key].width()
        if not sfx.isHidden():
            avail -= sfx.sizeHint().width() + 6
        shown = full
        if avail > 20:
            shown = QFontMetrics(lbl.font()).elidedText(full, Qt.ElideRight, avail)
        if lbl.text() != shown:
            lbl.setText(shown)
        # An elided value carries its full text on the cell so a hover
        # always reveals it; a row tooltip set by the caller wins.
        cell = self._cells[key]
        if shown != full and not cell.toolTip():
            lbl.setToolTip(full)
        elif shown == full and lbl.toolTip() == full:
            lbl.setToolTip("")

    def resizeEvent(self, event):  # noqa: N802 (Qt name)
        super().resizeEvent(event)
        for key in self._values:
            self._apply_elide(key)

    def set_clickable(self, key: str, tooltip: str = "") -> None:
        if key not in self._values:
            return
        self._clickable.add(key)
        for w in (self._keys[key], self._cells[key]):
            w.setCursor(Qt.PointingHandCursor)
            if tooltip:
                w.setToolTip(tooltip)

    def _key_at(self, pos) -> Optional[str]:
        # Clicks on the gap between key and value still count: match the
        # row band by y so the whole line is one target.
        for key in self._clickable:
            g = self._keys[key].geometry()
            if g.top() <= pos.y() <= g.bottom():
                return key
        return None

    def mousePressEvent(self, event):  # noqa: N802 (Qt name)
        if event.button() == Qt.LeftButton:
            key = self._key_at(event.position().toPoint())
            if key is not None:
                self.rowClicked.emit(key)
                event.accept()
                return
        super().mousePressEvent(event)


class Dot(QWidget):
    """6 px square status dot. Colored by :meth:`set_color`."""

    def __init__(self, color: str = STATUS_IDLE, size: int = 6,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(size, size)

    def set_color(self, color: str) -> None:
        c = QColor(color)
        if c != self._color:
            self._color = c
            self.update()

    def paintEvent(self, _event):  # noqa: N802 (Qt name)
        p = QPainter(self)
        p.fillRect(self.rect(), self._color)
        p.end()


# -- Click telemetry ---------------------------------------------------------

class ClickRing:
    """Ring buffer of recent clicks fed from the engine's click callback.

    Stores ``(monotonic_time, x_dip, y_dip)``. The viewport, zone map and
    cadence strip all read it; only the App writes to it, on the GUI
    thread, so no lock is needed.
    """

    def __init__(self, maxlen: int = 64) -> None:
        self._points: deque[tuple[float, int, int]] = deque(maxlen=maxlen)

    def add(self, x: int, y: int) -> None:
        self._points.append((time.monotonic(), int(x), int(y)))

    def clear(self) -> None:
        self._points.clear()

    def last(self, n: int) -> list[tuple[float, int, int]]:
        pts = list(self._points)
        return pts[-n:] if n < len(pts) else pts

    def intervals(self, n: int) -> list[float]:
        pts = list(self._points)
        out = [b[0] - a[0] for a, b in zip(pts, pts[1:])]
        return out[-n:] if n < len(out) else out

    def __len__(self) -> int:
        return len(self._points)


class EventLog:
    """Ring buffer of engine events for the deck's EVENT LOG panel.

    Entries are ``(unix_time, kind, text)``. Only the App writes to it,
    on the GUI thread (engine callbacks are marshalled through a queued
    signal first), so no lock is needed. ``version`` bumps on every
    change so a painter can skip work when nothing moved.
    """

    def __init__(self, maxlen: int = 200) -> None:
        self._entries: deque[tuple[float, str, str]] = deque(maxlen=maxlen)
        self.version = 0

    def add(self, kind: str, text: str) -> None:
        self._entries.append((time.time(), str(kind).upper(), str(text)))
        self.version += 1

    def clear(self) -> None:
        self._entries.clear()
        self.version += 1

    def entries(self) -> list[tuple[float, str, str]]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


# -- Misc formatters -----------------------------------------------------------

_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def format_clock() -> str:
    return datetime.now().strftime("%H:%M:%S")


def format_dtg() -> str:
    """Military date-time group in UTC: ``DDHHMMZ MONYY``."""
    now = datetime.now(timezone.utc)
    return f"{now:%d%H%M}Z {_MONTHS[now.month - 1]}{now:%y}"


def elide(text: str, n: int) -> str:
    """Middle-elide ``text`` to at most ``n`` characters."""
    text = str(text or "")
    if len(text) <= n:
        return text
    if n <= 1:
        return text[:n]
    head = (n - 1) // 2
    tail = n - 1 - head
    return text[:head] + "…" + text[len(text) - tail:]


def active_zone(app):
    """``(zone, key)`` the deck treats as the current target: the Click
    zone in Click mode, the running (else first) Click step zone in Record
    mode. ``key`` matches the OverlayManager's resolver key so both share
    one cached window lookup."""
    from modules.recorder import KIND_CLICK
    if app._active_mode == "clicker":
        return app._zone, "main"
    if app._active_mode == "recorder":
        steps = app._steps
        try:
            cur, total = app.clicker.current_step_index
        except Exception:
            cur, total = 0, 0
        if total > 0 and 0 < cur <= len(steps) and steps[cur - 1].zone is not None:
            return steps[cur - 1].zone, steps[cur - 1].step_id
        for s in steps:
            if s.kind == KIND_CLICK and s.zone is not None:
                return s.zone, s.step_id
    return None, None


def lock_view(app):
    """``(zone_to_draw, status, title)`` for the deck's target readouts.

    Screen-locked zones come back as-is with status ``"screen"``. Locked
    zones are resolved through ``app.zone_locks`` (throttled), and while
    the engine runs its own verdict wins so a hold shows as one.
    """
    from modules.clicker import ClickerState
    from modules.zone_lock import HOLD_STATUSES
    zone, key = active_zone(app)
    if zone is None:
        return None, "screen", None
    if getattr(zone, "lock", None) is None:
        return zone, "screen", None
    resolver = getattr(app, "zone_locks", None)
    if resolver is None:
        return zone, "screen", None
    res = resolver.resolve(zone, key)
    status, title = res.status, res.title
    if app._state_str != ClickerState.IDLE:
        try:
            e_status, e_title = app.clicker.target_status()
        except Exception:
            e_status, e_title = status, title
        if e_status in HOLD_STATUSES:
            status = e_status
            title = e_title or title
    return res.zone, status, title


def fmt_secs(v: float) -> str:
    """Compact seconds for deck readouts: ``75MS``, ``1.50S``, ``12.5S``."""
    v = float(v)
    if v < 1.0:
        return f"{v * 1000:0.0f}MS"
    if v < 10.0:
        return f"{v:0.2f}S"
    return f"{v:0.1f}S"


_BOT_NAMES: Optional[dict[str, str]] = None


def bot_display_name(slug: str) -> str:
    """The bot's manifest name for a slug ("Menaphos VIP Fishing" for
    ``menaphos_vip_fishing``). The library is read once; anything not in
    it (a bundle, a custom bot) falls back to the slug in words."""
    global _BOT_NAMES
    slug = str(slug or "").strip()
    if not slug:
        return ""
    if _BOT_NAMES is None:
        names: dict[str, str] = {}
        try:
            from ui.cards.ai import _enumerate_bots
            for bot in _enumerate_bots():
                names[str(bot.get("slug", ""))] = str(bot.get("name") or "")
        except Exception:
            pass
        _BOT_NAMES = names
    name = _BOT_NAMES.get(slug) or slug.replace("_", " ").replace("-", " ").title()
    # Manifests append the kind ("Menaphos VIP Fishing (Python bot)");
    # the deck's rows have no room for it.
    return name.split(" (", 1)[0].strip()


def format_mmss(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def session_id() -> str:
    return datetime.now().strftime("PC-%m%d-%H%M")


def git_short_hash(repo_root: Path) -> str:
    """Short hash from ``.git`` without spawning git. ``dev`` when there
    is no repo or the ref cannot be resolved."""
    git = repo_root / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
    except Exception:
        return "dev"
    if not head.startswith("ref:"):
        return head[:7] or "dev"
    ref = head[4:].strip()
    try:
        return (git / ref).read_text(encoding="utf-8").strip()[:7] or "dev"
    except Exception:
        pass
    try:
        for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split()[0][:7]
    except Exception:
        pass
    return "dev"


def build_info(repo_root: Path) -> tuple[str, str]:
    """``(short_hash, date)`` for the SYSTEM panel. ``ui/_build.py`` is
    written by the packaging step; a dev checkout falls back to reading
    ``.git`` directly, and a bare folder reports ``dev``."""
    try:
        from ui import _build  # generated at build time; absent in dev
        h = str(getattr(_build, "BUILD_HASH", "") or "").strip()
        d = str(getattr(_build, "BUILD_DATE", "") or "").strip()
        # The committed stamp says "dev"; only a real hash short-circuits
        # the .git read so a dev checkout still shows its commit.
        if h and h.lower() != "dev":
            return h[:7], d
    except Exception:
        pass
    return git_short_hash(repo_root), ""


def format_hms(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def engine_paused(app) -> bool:
    from ui import engine_bridge
    return engine_bridge.engine_paused(app)


def current_track_step(app):
    """The Track step the deck's TRK chip reports on: the running step
    when the engine is on one, else the expanded (or first) Track step.
    None outside Record mode or when there is no Track step."""
    from modules.clicker import ClickerState
    from modules.recorder import KIND_TRACK
    if app._active_mode != "recorder":
        return None
    steps = app._steps
    if app._state_str != ClickerState.IDLE:
        try:
            cur, total = app.clicker.current_step_index
        except Exception:
            cur, total = 0, 0
        if total > 0 and 0 < cur <= len(steps):
            step = steps[cur - 1]
            return step if step.kind == KIND_TRACK else None
    track = [s for s in steps if s.kind == KIND_TRACK]
    if not track:
        return None
    try:
        expanded = app.record_mode_tab._row_builder._expanded
    except Exception:
        expanded = set()
    for s in reversed(track):
        if s.step_id in expanded:
            return s
    return track[0]


def fill_policy(widget: QWidget) -> None:
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def log_to_slider(value: float, lo: float, hi: float, steps: int = 1000) -> int:
    value = clamp(value, lo, hi)
    return int(round(steps * (math.log(value) - math.log(lo)) / (math.log(hi) - math.log(lo))))


def slider_to_log(pos: int, lo: float, hi: float, steps: int = 1000) -> float:
    f = clamp(pos / float(steps), 0.0, 1.0)
    return math.exp(math.log(lo) + f * (math.log(hi) - math.log(lo)))
