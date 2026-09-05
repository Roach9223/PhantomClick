"""Left and right columns of the command deck.

Left: MODES (mode switcher), SEQUENCE (per-mode checklist / step list /
rule log, plus the key timers), EVENT LOG (engine events and clicks)
and SYSTEM (input, capture, scale, hotkeys, build).
Right: ENGINE STATUS, ZONE MAP, TIMING & TARGETING and MISSION (the
setup checklist while idle, the run readout while running).

Colour: ACCENT (ice) marks what is selected or targeted, RUN (green)
marks what is live. See ``ui/theme.py``.

Most of it is read-only against App state. The controls: the mode rows
(which route through ``App._set_active_mode`` exactly like the old nav),
the SEQUENCE panel's rows (step enable squares, step selection, BREAKS /
STOP AFTER / DRY RUN toggles, ZONE redraw, INTERVAL focus; see
:class:`SequencePanel`), the HID row (re-probe on click), the MONITOR row
(opens the drawer page) and the corner-abort footer (toggles
``corner_abort_enabled``). Panels refresh from ``tick()`` at the App's
100 ms cadence; the heavier probes (key backend, build hash) run on a
slower divider, and SEQUENCE rebuilds its widgets only when the row set
changes.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

from modules.clicker import ClickerState
from modules.hotkey_manager import name_to_display
from modules.recorder import (
    KIND_CLICK, KIND_COLOR, KIND_KEY, KIND_LOOP, KIND_PAUSE, KIND_TRACK,
)
from modules.zone_lock import HOLD_STATUSES, STATUS_LOCKED, STATUS_SCREEN
from ui.config_io import DEFAULTS, save_config

from . import common as c
from .zone_map import ZoneMap

COLUMN_W = 268

_MODE_DEFS = (
    ("clicker", "click", "CLICK"),
    ("recorder", "record", "RECORD"),
    ("ai", "ai", "AI"),
)


def _cfg(app, key: str):
    """cfg lookup falling back to the canonical default, never a literal."""
    return app.cfg.get(key, DEFAULTS.get(key))


# -- MODES ---------------------------------------------------------------------

class ModeRow(QFrame):
    clicked = Signal(str)

    def __init__(self, mode: str, icon_name: str, name: str,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.mode = mode
        self._icon_name = icon_name
        self.setObjectName("deck-mode-row")
        self.setProperty("active", False)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(44)
        self.setStyleSheet(
            f"QFrame#deck-mode-row {{ background: transparent; border: none; "
            f"border-left: 2px solid transparent; border-radius: 4px; }}"
            f"QFrame#deck-mode-row[active=\"true\"] {{ background: {c.SURFACE_HIGH}; "
            f"border-left: 2px solid {c.ACCENT}; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 4, 8, 4)
        row.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(18, 18)
        row.addWidget(self.icon)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        self.name = QLabel(name)
        self.name.setFont(c.label_font(c.SIZE_BODY, QFont.DemiBold, 0.6))
        self.name.setStyleSheet(f"color: {c.TEXT_PRIMARY}; background: transparent;")
        self.state = c.MicroLabel("STANDBY", c.TEXT_MICRO)
        col.addWidget(self.name)
        col.addWidget(self.state)
        row.addLayout(col, 1)
        self._active = None
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        self.setProperty("active", active)
        self.icon.setPixmap(c.icon_pixmap(
            self._icon_name, 16, c.ACCENT if active else c.TEXT_SECONDARY))
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):  # noqa: N802 (Qt name)
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.mode)
        super().mousePressEvent(event)


class ModesPanel(c.Panel):
    modeRequested = Signal(str)

    def __init__(self, app, parent: Optional[QWidget] = None):
        super().__init__("MODES", parent)
        self.app = app
        self.rows: dict[str, ModeRow] = {}
        body = self.body_layout()
        body.setSpacing(2)
        for mode, icon, name in _MODE_DEFS:
            r = ModeRow(mode, icon, name)
            r.clicked.connect(self.modeRequested)
            body.addWidget(r)
            self.rows[mode] = r
        self.refresh()

    def refresh(self) -> None:
        for mode, row in self.rows.items():
            row.set_active(mode == self.app._active_mode)

    def tick(self) -> None:
        app = self.app
        running = app._state_str != ClickerState.IDLE
        active = app._active_mode
        self.refresh()
        snap = app.stats.snapshot()
        if running and active == "clicker":
            self.rows["clicker"].state.setText(f"ACTIVE · {int(snap.get('total', 0))} CLK")
        else:
            self.rows["clicker"].state.setText(
                "STANDBY · ZONE SET" if app._zone is not None else "STANDBY · NO ZONE")
        if running and active == "recorder":
            cur, total = app.clicker.current_step_index
            self.rows["recorder"].state.setText(f"ACTIVE · STEP {cur}/{total}")
        else:
            n = len(app._steps)
            self.rows["recorder"].state.setText(f"STANDBY · {n} STEP{'S' if n != 1 else ''}")
        slug = str(app.cfg.get("ai_active_bundle") or app.cfg.get("ai_bot_slug") or "").strip()
        if running and active == "ai":
            info = {}
            try:
                info = app.bot_runner.last_fired() or {}
            except Exception:
                pass
            self.rows["ai"].state.setText(f"ACTIVE · TICK {int(info.get('current_tick', 0) or 0)}")
        else:
            # Slugs are long ("menaphos_vip_fishing"); the row is 268 px.
            name = c.elide(slug.replace("_", " "), 11) if slug else "NO BOT"
            self.rows["ai"].state.setText(f"STANDBY · {name}")
        for mode, row in self.rows.items():
            row.state.set_color(c.RUN if (running and mode == active) else c.TEXT_MICRO)


# -- SEQUENCE ------------------------------------------------------------------

@dataclass
class RowSpec:
    """One SEQUENCE line. ``key`` is the row's identity across ticks;
    ``toggle`` means the square flips something, ``click`` means the text
    opens or focuses something. Text and colours refresh in place, so a
    tick never rebuilds widgets unless the row set itself changed."""

    key: str
    text: str
    checked: Optional[bool] = None
    dot: str = c.STATUS_IDLE
    active: bool = False
    dim: bool = False
    strike: bool = False
    toggle: bool = False
    click: bool = False
    tip: str = ""

    def shape(self) -> tuple:
        return (self.key, self.toggle, self.click)


class _CheckSquare(QWidget):
    """11 px square: ice fill when checked, outline when not, dim outline
    for rows with no on / off meaning. Emits ``clicked`` when it is a
    real control."""

    clicked = Signal()

    def __init__(self, checked: Optional[bool], clickable: bool = False,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._checked = checked
        self._clickable = clickable
        self.setFixedSize(11, 11)
        if clickable:
            self.setCursor(Qt.PointingHandCursor)

    def set_checked(self, checked: Optional[bool]) -> None:
        if checked != self._checked:
            self._checked = checked
            self.update()

    def mousePressEvent(self, event):  # noqa: N802 (Qt name)
        if self._clickable and event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, _event):  # noqa: N802 (Qt name)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._checked is None:
            p.setPen(QPen(QColor(c.BORDER_STRONG), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
        elif self._checked:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c.ACCENT))
            p.drawRect(r)
        else:
            p.setPen(QPen(QColor(c.TEXT_TERTIARY), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
        p.end()


class SeqRow(QFrame):
    """One line: square check box, mono text, status dot. ``toggled`` and
    ``activated`` carry the row key; the panel decides what they mean."""

    toggled = Signal(str)
    activated = Signal(str)
    contextRequested = Signal(str, QPoint)   # row key, global position

    def __init__(self, spec: RowSpec, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.key = spec.key
        self._spec = spec
        self._active: Optional[bool] = None
        interactive = spec.toggle or spec.click
        self.setObjectName("deck-seq-row")
        self.setFixedHeight(22)
        self.setProperty("active", False)
        self.setProperty("interactive", interactive)
        # Hover fill only on rows that do something; state rows keep the
        # normal cursor and no hover so they do not read as buttons.
        self.setStyleSheet(
            f"QFrame#deck-seq-row {{ background: transparent; border-radius: 3px; "
            f"border-left: 2px solid transparent; }}"
            f"QFrame#deck-seq-row[interactive=\"true\"]:hover {{ background: {c.SURFACE_HIGH}; }}"
            f"QFrame#deck-seq-row[active=\"true\"] {{ background: {c.SURFACE_HIGH}; "
            f"border-left: 2px solid {c.ACCENT}; }}"
        )
        if interactive:
            self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 0, 6, 0)
        row.setSpacing(8)
        self.box = _CheckSquare(spec.checked, clickable=interactive)
        self.box.clicked.connect(self._on_box)
        row.addWidget(self.box)
        self.label = c.MonoLabel("", c.TEXT_SECONDARY, c.SIZE_XS)
        row.addWidget(self.label, 1)
        self.dot = c.Dot(spec.dot, 6)
        row.addWidget(self.dot)
        self.apply(spec)

    def _on_box(self) -> None:
        if self._spec.toggle:
            self.toggled.emit(self.key)
        elif self._spec.click:
            self.activated.emit(self.key)

    def contextMenuEvent(self, event):  # noqa: N802 (Qt name)
        self.contextRequested.emit(self.key, event.globalPos())
        event.accept()

    def mousePressEvent(self, event):  # noqa: N802 (Qt name)
        if event.button() == Qt.LeftButton:
            # Text click selects when the row opens something, otherwise
            # the whole row is the toggle target (BREAKS, STOP AFTER).
            if self._spec.click:
                self.activated.emit(self.key)
                event.accept()
                return
            if self._spec.toggle:
                self.toggled.emit(self.key)
                event.accept()
                return
        super().mousePressEvent(event)

    def apply(self, spec: RowSpec) -> None:
        """Refresh text and colours in place; cheap enough for every tick."""
        self._spec = spec
        if self.label.text() != spec.text:
            self.label.setText(spec.text)
        self.label.set_color(c.TEXT_DISABLED if spec.dim else c.TEXT_SECONDARY)
        font = self.label.font()
        if font.strikeOut() != spec.strike:
            font.setStrikeOut(spec.strike)
            self.label.setFont(font)
        self.dot.set_color(spec.dot)
        self.box.set_checked(spec.checked)
        if spec.tip != self.toolTip():
            self.setToolTip(spec.tip)
        if spec.active != self._active:
            self._active = spec.active
            self.setProperty("active", spec.active)
            self.style().unpolish(self)
            self.style().polish(self)


# Five 22 px rows plus the 2 px gaps between them, so SEQUENCE and the
# EVENT LOG never collapse below a readable height when they share space.
_MIN_LIST_H = 5 * 22 + 4 * 2

_KIND_TAG = {
    KIND_CLICK: "CLICK", KIND_TRACK: "TRACK", KIND_COLOR: "COLOR",
    KIND_KEY: "KEY", KIND_PAUSE: "PAUSE", KIND_LOOP: "LOOP",
}


def _reveal(widget: QWidget) -> None:
    """Scroll the nearest enclosing QScrollArea so ``widget`` is visible."""
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QScrollArea):
            try:
                parent.ensureWidgetVisible(widget, 0, 24)
            except RuntimeError:
                pass
            return
        parent = parent.parentWidget()


class SequencePanel(c.Panel):
    """Per-mode checklist that is also a control surface.

    Click mode: ZONE DRAWN redraws, INTERVAL focuses the timing card,
    NEXT BREAK and STOP AFTER toggle their cfg keys. Record mode: each
    step's square flips ``step.enabled``, its text selects the step in the
    editor pane, and ``+ STEP`` pops the record tab's add menu. AI mode:
    DRY RUN toggles ``ai_dry_run``. Everything else is read-only.
    """

    def __init__(self, app, parent: Optional[QWidget] = None):
        super().__init__("SEQUENCE", parent)
        self.app = app
        c.fill_policy(self)
        self.add_step_btn = QPushButton("+ STEP")
        self.add_step_btn.setProperty("variant", "ghost")
        self.add_step_btn.setFixedHeight(18)
        self.add_step_btn.setFont(c.micro_font())
        self.add_step_btn.setCursor(Qt.PointingHandCursor)
        self.add_step_btn.setStyleSheet("QPushButton { padding: 0 6px; }")
        self.add_step_btn.setToolTip("Append a step to the sequence (same menu as the editor).")
        self.add_step_btn.clicked.connect(self._on_add_step)
        self.add_step_btn.setVisible(app._active_mode == "recorder")
        self.app.locker.register(self.add_step_btn)
        self.title_row.addWidget(self.add_step_btn)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        scroll.setMinimumHeight(_MIN_LIST_H)
        self._inner = QWidget()
        self._inner.setStyleSheet("background: transparent;")
        self._list = QVBoxLayout(self._inner)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(2)
        self._list.addStretch(1)
        scroll.setWidget(self._inner)
        self.body_layout().addWidget(scroll, 1)
        self._rows: list[SeqRow] = []
        self._shape: Optional[tuple] = None
        self._rule_log: deque[tuple[int, str]] = deque(maxlen=8)
        self._last_rule_key: Optional[tuple] = None

    # -- Rows ------------------------------------------------------------------------

    def rows(self) -> list[SeqRow]:
        return list(self._rows)

    def row(self, key: str) -> Optional[SeqRow]:
        for r in self._rows:
            if r.key == key:
                return r
        return None

    def _rebuild(self, specs: list[RowSpec]) -> None:
        while self._list.count() > 1:
            item = self._list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows = []
        for spec in specs:
            r = SeqRow(spec)
            r.toggled.connect(self._on_toggle)
            r.activated.connect(self._on_activate)
            r.contextRequested.connect(self._on_context)
            self._list.insertWidget(self._list.count() - 1, r)
            self._rows.append(r)

    def tick(self) -> None:
        app = self.app
        mode = app._active_mode
        show_add = mode == "recorder"
        if self.add_step_btn.isVisible() != show_add:
            self.add_step_btn.setVisible(show_add)
        if mode == "clicker":
            specs = self._click_rows() + self._timer_rows()
        elif mode == "recorder":
            specs = self._record_rows() + self._timer_rows()
        else:
            specs = self._ai_rows()
        shape = tuple(s.shape() for s in specs)
        if shape != self._shape:
            self._shape = shape
            self._rebuild(specs)
        else:
            for r, spec in zip(self._rows, specs):
                r.apply(spec)

    def refresh(self) -> None:
        """Force a rebuild on the next tick (step list changed elsewhere)."""
        self._shape = None

    # -- Click mode --------------------------------------------------------------------

    def _click_rows(self) -> list[RowSpec]:
        app = self.app
        running = app._state_str != ClickerState.IDLE
        clicker = app.clicker
        rows: list[RowSpec] = []
        has_zone = app._zone is not None
        rows.append(RowSpec(
            "zone", "ZONE DRAWN" if has_zone else "NO ZONE", checked=has_zone,
            dot=c.ACCENT if has_zone else c.STATUS_IDLE, dim=not has_zone, click=True,
            tip="Click to draw the click zone again." if has_zone else "Click to draw a click zone."))
        if has_zone and getattr(app._zone, "lock", None) is not None:
            _zone, status, title = c.lock_view(app)
            if status == STATUS_LOCKED:
                dot = c.ACCENT
            elif status in HOLD_STATUSES:
                dot = c.WARN
            else:
                dot = c.STATUS_IDLE
            name = c.elide(title or app._zone.lock.title or app._zone.lock.cls, 24).upper()
            rows.append(RowSpec("target", f"TARGET {name}", dot=dot))
        lo, hi = float(_cfg(app, "min_delay")), float(_cfg(app, "max_delay"))
        rows.append(RowSpec(
            "interval", f"WAIT  {c.fmt_secs(lo)} TO {c.fmt_secs(hi)}", checked=True, dot=c.ACCENT,
            click=True, tip="Wait between clicks, drawn at random from this range. Click to edit."))
        rows.append(RowSpec(
            "engine", "ENGINE RUNNING" if running else "ENGINE STANDBY", checked=running,
            dot=c.RUN if running else c.STATUS_IDLE, active=running,
            tip="Whether the click engine is running right now. START and STOP are in the header."))
        breaks_on = bool(_cfg(app, "break_bursts_enabled"))
        fat = getattr(clicker, "_fatigue", None)
        if running and fat is not None and fat.enabled and fat.break_bursts:
            left = max(0, int(fat._next_break_at) - int(fat.click_count))
            avg = float(app.stats.snapshot().get("avg_interval", 0.0) or 0.0)
            # Fatigue schedules breaks by click count, so the clock is an
            # estimate: remaining clicks times the rolling mean interval.
            eta = c.format_mmss(left * avg) if avg > 0 else f"{left} CLK"
            rows.append(RowSpec("break", f"NEXT BREAK  {eta}", checked=True, dot=c.WARN,
                                toggle=True, tip="Periodic walk-away breaks. Click to turn off."))
        else:
            rows.append(RowSpec(
                "break", "NEXT BREAK  " + ("ARMED" if breaks_on else "OFF"), checked=breaks_on,
                dot=c.STATUS_IDLE, dim=not breaks_on, toggle=True,
                tip=("Periodic walk-away breaks are on. Click to turn off."
                     if breaks_on else "Periodic walk-away breaks are off. Click to turn on.")))
        rows.append(self._stop_after_row(running))
        return rows

    def _stop_after_row(self, running: bool) -> RowSpec:
        app = self.app
        clicker = app.clicker
        minutes_on = bool(_cfg(app, "stop_after_minutes_enabled"))
        clicks_on = bool(_cfg(app, "stop_after_clicks_enabled"))
        if minutes_on:
            total = float(_cfg(app, "stop_after_minutes")) * 60.0
            if running:
                left = max(0.0, total - float(getattr(clicker, "session_uptime_seconds", 0.0)))
                text, dot = f"STOP AFTER  {c.format_mmss(left)}", c.WARN
            else:
                text, dot = f"STOP AFTER  {c.format_mmss(total)}", c.STATUS_IDLE
        elif clicks_on:
            n = int(_cfg(app, "stop_after_clicks"))
            done = int(app.stats.snapshot().get("total", 0)) if running else 0
            text, dot = f"STOP AFTER  {done}/{n} CLK", (c.WARN if running else c.STATUS_IDLE)
        else:
            text, dot = "STOP AFTER  OFF", c.STATUS_IDLE
        on = minutes_on or clicks_on
        return RowSpec("stop", text, checked=on, dot=dot, dim=not on, toggle=True,
                       tip=("Auto-stop is armed. Click to turn it off." if on else
                            "Auto-stop is off. Click to arm it (minutes when set, else clicks)."))

    def _timer_rows(self) -> list[RowSpec]:
        """Key timers: live countdowns while the engine runs, the enabled
        timers with their interval range while idle. Click opens Timers."""
        app = self.app
        running = app._state_str != ClickerState.IDLE
        rows: list[RowSpec] = []
        tip = "Click to open the Timers page."
        if running:
            fn = getattr(app.clicker, "key_timer_countdowns", None)
            if callable(fn):
                try:
                    pairs = list(fn())
                except Exception:
                    pairs = []
                for i, (combo, secs) in enumerate(pairs):
                    rows.append(RowSpec(
                        f"timer:{i}", f"KEY {str(combo).upper()}  IN {c.format_mmss(float(secs))}",
                        dot=c.RUN, click=True, tip=tip))
                return rows
        for i, kt in enumerate(getattr(app, "_key_timers", []) or []):
            if not getattr(kt, "enabled", False):
                continue
            lo = float(getattr(kt, "interval_min", 0.0))
            hi = float(getattr(kt, "interval_max", lo))
            rng = c.format_mmss(lo) if abs(hi - lo) < 0.5 else f"{c.format_mmss(lo)} TO {c.format_mmss(hi)}"
            rows.append(RowSpec(f"timer:{i}", f"KEY {str(kt.key).upper()}  EVERY {rng}",
                                click=True, tip=tip))
        return rows

    # -- Record mode -------------------------------------------------------------------

    def _step_detail(self, step, steps) -> str:
        """Label when the user gave one, else the most useful fact about
        the step: zone centre, key combo, pause range, loop target."""
        label = (getattr(step, "label", "") or "").strip()
        if label:
            return label
        zone = getattr(step, "zone", None)
        if zone is not None:
            try:
                cx, cy = zone.centroid()
                return f"X {int(cx):04d} Y {int(cy):04d}"
            except Exception:
                pass
        kind = getattr(step, "kind", "")
        if kind == KIND_KEY:
            return (getattr(step, "key_combo", "") or "NO KEY").upper()
        if kind == KIND_PAUSE:
            return f"{float(step.delay_min):0.1f} TO {float(step.delay_max):0.1f} S"
        if kind == KIND_LOOP:
            target = getattr(step, "loop_target_step_id", None)
            for i, s in enumerate(steps):
                if s.step_id == target:
                    return f"TO {i + 1:02d}"
            return "NO TARGET"
        if kind == KIND_TRACK:
            return "TEMPLATE" if getattr(step, "template_path", None) else "NO TEMPLATE"
        if kind == KIND_COLOR:
            rgb = getattr(step, "color_target_rgb", None)
            return "RGB {:02X}{:02X}{:02X}".format(*rgb[:3]) if rgb else "NO COLOR"
        return "NO ZONE"

    def _record_rows(self) -> list[RowSpec]:
        app = self.app
        running = app._state_str != ClickerState.IDLE
        cur, _total = app.clicker.current_step_index if running else (0, 0)
        steps = app._steps
        rows: list[RowSpec] = []
        for i, s in enumerate(steps):
            enabled = bool(getattr(s, "enabled", True))
            kind = _KIND_TAG.get(getattr(s, "kind", ""), str(getattr(s, "kind", "")).upper())
            detail = c.elide(self._step_detail(s, steps), 18).upper()
            text = f"{i + 1:02d}  {kind:<5}  {detail}".rstrip()
            active = running and (i + 1) == cur
            rows.append(RowSpec(
                f"step:{s.step_id}", text, checked=enabled,
                dot=c.RUN if active else (c.STATUS_IDLE if enabled else c.TEXT_DISABLED),
                active=active, dim=not enabled, strike=not enabled, toggle=True, click=True,
                tip=("Square: skip or run this step. Text: open it in the editor."
                     if enabled else "Skipped at run time. Square re-enables it; text opens it.")))
        if not rows:
            rows.append(RowSpec("steps:none", "NO STEPS", dim=True))
        return rows

    # -- AI mode -------------------------------------------------------------------------

    def _ai_rows(self) -> list[RowSpec]:
        app = self.app
        running = app._state_str != ClickerState.IDLE
        runner = getattr(app, "bot_runner", None)
        info: dict = {}
        if runner is not None:
            try:
                info = runner.last_fired() or {}
            except Exception:
                info = {}
        rows: list[RowSpec] = []
        # Bots have no break schedule; the tick clock is their cadence.
        hz = float(_cfg(app, "ai_tick_rate_hz"))
        rows.append(RowSpec("ai:tick", f"TICK RATE  {hz:0.1f} HZ",
                            dot=c.RUN if running else c.STATUS_IDLE,
                            tip="How often the bot looks at the screen and picks a rule. Set it in the BOT pane."))
        dry = bool(_cfg(app, "ai_dry_run"))
        rows.append(RowSpec(
            "ai:dry", "DRY RUN  " + ("ON" if dry else "OFF"), checked=dry,
            dot=c.WARN if dry else c.STATUS_IDLE, toggle=True,
            tip=("Dry run: rules fire and log but never touch the mouse. Click to go live."
                 if dry else "Live input. Click for dry run (log only, no clicks).")))
        rule = info.get("last_fired_rule")
        tick = int(info.get("last_fired_tick", 0) or 0)
        if rule:
            key = (tick, str(rule))
            if key != self._last_rule_key:
                self._last_rule_key = key
                self._rule_log.append(key)
        # Keyed by position: the newest rule always sits in slot 0, so a
        # new firing only changes text, never the row set.
        for i, (tk, name) in enumerate(reversed(self._rule_log)):
            rows.append(RowSpec(f"ai:rule:{i}", f"T{tk:05d}  {name}",
                                dot=c.RUN if i == 0 else c.STATUS_IDLE, active=i == 0,
                                tip="Rules that fired, newest first, with the tick they fired on."))
        if len(rows) == 2:
            rows.append(RowSpec("ai:none", "NO RULES FIRED", dim=True))
        return rows

    # -- Actions ----------------------------------------------------------------------

    def _editor(self, open_: bool = True) -> None:
        shell = getattr(self.app, "deck", None)
        if shell is not None and open_:
            try:
                shell.set_editor_open(True)
            except Exception:
                pass

    def _on_toggle(self, key: str) -> None:
        if key.startswith("step:"):
            self._toggle_step(key[5:])
        elif key == "break":
            self._toggle_cfg("break_bursts_enabled")
        elif key == "stop":
            self._toggle_stop_after()
        elif key == "ai:dry":
            self._toggle_dry_run()
        else:
            self._on_activate(key)
            return
        self.tick()

    def _on_context(self, key: str, pos: QPoint) -> None:
        from .context_menus import click_zone_menu, step_row_menu
        app = self.app
        menu = None
        if key.startswith("step:"):
            menu = step_row_menu(app, key[5:], parent=self)
        elif key == "zone" and app._active_mode == "clicker":
            menu = click_zone_menu(app, parent=self)
        if menu is not None:
            menu.exec(pos)

    def _on_activate(self, key: str) -> None:
        app = self.app
        if key.startswith("step:"):
            self._select_step(key[5:])
        elif key == "zone":
            try:
                app.click_page.zone_card._on_draw()
            except Exception:
                app.log.exception("deck sequence redraw failed")
        elif key == "interval":
            self._focus_timing()
        elif key.startswith("timer:"):
            try:
                app.show_page("timers")
            except Exception:
                pass

    def _mirror_behavior(self) -> None:
        """Behavior page switches read cfg on demand; refresh them so the
        two surfaces agree without a second save."""
        card = getattr(self.app, "behavior_card", None)
        fn = getattr(card, "refresh_advanced", None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass

    def _toggle_cfg(self, cfg_key: str) -> None:
        app = self.app
        app.cfg[cfg_key] = not bool(_cfg(app, cfg_key))
        # save_config_later persists and pushes to the engine once the
        # debounce settles, the same path Behavior's sliders use.
        app.save_config_later()
        self._mirror_behavior()

    def _toggle_stop_after(self) -> None:
        app = self.app
        cfg = app.cfg
        on = bool(_cfg(app, "stop_after_minutes_enabled")) or bool(_cfg(app, "stop_after_clicks_enabled"))
        if on:
            cfg["stop_after_minutes_enabled"] = False
            cfg["stop_after_clicks_enabled"] = False
        else:
            try:
                minutes = int(_cfg(app, "stop_after_minutes") or 0)
            except (TypeError, ValueError):
                minutes = 0
            if minutes > 0:
                cfg["stop_after_minutes_enabled"] = True
            else:
                cfg["stop_after_clicks_enabled"] = True
        app.save_config_later()
        self._mirror_behavior()

    def _toggle_dry_run(self) -> None:
        app = self.app
        new = not bool(_cfg(app, "ai_dry_run"))
        # The switch lives on the AI page's config section.
        card = getattr(app, "ai_card", None)
        switch = getattr(getattr(card, "config", None), "dry_switch", None)
        if switch is not None and switch.isChecked() != new:
            # The AI card's handler saves, pushes to a running bot and
            # refreshes its own status line.
            switch.setChecked(new)
            return
        app.cfg["ai_dry_run"] = new
        save_config(app.cfg)
        runner = getattr(app, "bot_runner", None)
        fn = getattr(runner, "set_dry_run", None)
        if callable(fn):
            try:
                fn(new)
            except Exception:
                pass

    def _toggle_step(self, step_id: str) -> None:
        app = self.app
        for s in app._steps:
            if s.step_id == step_id:
                s.enabled = not bool(getattr(s, "enabled", True))
                break
        else:
            return
        app.save_steps_later()
        # The editor's step cards carry the same switch; rebuild them so
        # both surfaces show one truth.
        try:
            app.record_mode_tab.render_all()
        except Exception:
            pass

    def _select_step(self, step_id: str) -> None:
        self._editor(True)
        try:
            self.app.record_mode_tab.select_step(step_id)
        except Exception:
            self.app.log.exception("deck sequence select failed")

    def _on_add_step(self) -> None:
        self._editor(True)
        try:
            self.app.record_mode_tab.show_add_menu(QCursor.pos())
        except Exception:
            self.app.log.exception("deck add-step menu failed")

    def _focus_timing(self) -> None:
        self._editor(True)
        try:
            page = self.app.click_page
            page.reveal_timing()
            card = page.timing_card
        except Exception:
            return
        _reveal(card)
        try:
            card.range_slider.setFocus(Qt.OtherFocusReason)
        except Exception:
            pass


# -- EVENT LOG -----------------------------------------------------------------

_KIND_ABBREV = {
    "TARGET LOST": "LOST",
    "TARGET MINIMIZED": "MINIM",
    "TARGET REACQUIRED": "REACQ",
    "WANDER": "WDR",
    "DISTRACTION": "DISTR",
    "WATCHDOG": "WDOG",
}


def _kind_color(kind: str) -> str:
    k = kind.upper()
    if k == "CLK":
        return c.TEXT_PRIMARY
    if k in ("START", "RESUME"):
        return c.RUN
    if "LOST" in k or "WATCHDOG" in k:
        return c.STOP
    if k in ("WANDER", "BREAK", "DISTRACTION", "HOLD") or "MINIMIZED" in k:
        return c.WARN
    return c.TEXT_SECONDARY


class _LogView(QWidget):
    """Painted list of log rows: ``HHMMSSZ  KIND  text``. One widget for
    the whole list, so 200 rows cost one paint, not 200 layouts."""

    ROW_H = 16

    def __init__(self, app, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app = app
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setStyleSheet("background: transparent;")
        self._rows: list[tuple[float, str, str]] = []
        self._version = -1
        self.setFixedHeight(self.ROW_H)

    def sync(self) -> bool:
        """Pull new rows from the App's ring buffer. True when changed."""
        log = self.app.event_log
        if log.version == self._version:
            return False
        self._version = log.version
        self._rows = log.entries()
        self.setFixedHeight(max(1, len(self._rows)) * self.ROW_H)
        self.update()
        return True

    def row_count(self) -> int:
        return len(self._rows)

    def visible_texts(self, n: int) -> list[str]:
        """Last ``n`` rows as plain text (tests read this)."""
        return [f"{self._stamp(t)}  {self._abbrev(k)}  {x}" for t, k, x in self._rows[-n:]]

    @staticmethod
    def _stamp(t: float) -> str:
        return datetime.fromtimestamp(t, timezone.utc).strftime("%H%M%SZ")

    @staticmethod
    def _abbrev(kind: str) -> str:
        return _KIND_ABBREV.get(kind.upper(), kind.upper())[:6]

    def paintEvent(self, event):  # noqa: N802 (Qt name)
        p = QPainter(self)
        p.setFont(c.mono_font(c.SIZE_SM))
        fm = p.fontMetrics()
        stamp_w = fm.horizontalAdvance("000000Z") + 8
        kind_w = fm.horizontalAdvance("RESUME") + 8
        h = self.ROW_H
        top = event.rect().top()
        bottom = event.rect().bottom()
        first = max(0, top // h)
        last = min(len(self._rows) - 1, bottom // h)
        if not self._rows:
            p.setPen(QColor(c.TEXT_DISABLED))
            p.drawText(QRectF(4, 0, self.width() - 8, h), Qt.AlignVCenter | Qt.AlignLeft, "NO EVENTS")
            p.end()
            return
        for i in range(first, last + 1):
            t, kind, text = self._rows[i]
            y = i * h
            p.setPen(QColor(c.TEXT_MICRO))
            p.drawText(QRectF(4, y, stamp_w, h), Qt.AlignVCenter | Qt.AlignLeft, self._stamp(t))
            p.setPen(QColor(_kind_color(kind)))
            p.drawText(QRectF(4 + stamp_w, y, kind_w, h), Qt.AlignVCenter | Qt.AlignLeft,
                       self._abbrev(kind))
            p.setPen(QColor(c.TEXT_SECONDARY))
            x0 = 4 + stamp_w + kind_w
            p.drawText(QRectF(x0, y, max(10, self.width() - x0 - 4), h),
                       Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(text, Qt.ElideRight, max(10, self.width() - x0 - 4)))
        p.end()


class LogPanel(c.Panel):
    def __init__(self, app, parent: Optional[QWidget] = None):
        super().__init__("EVENT LOG", parent)
        self.app = app
        c.fill_policy(self)
        self.clear_btn = QPushButton("CLEAR")
        self.clear_btn.setProperty("variant", "ghost")
        self.clear_btn.setFixedHeight(18)
        self.clear_btn.setFont(c.micro_font())
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setStyleSheet("QPushButton { padding: 0 6px; }")
        self.clear_btn.setToolTip("Empty the event log. The engine keeps running.")
        self.clear_btn.clicked.connect(self._clear)
        self.title_row.addWidget(self.clear_btn)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.scroll.setMinimumHeight(_MIN_LIST_H)
        self.view = _LogView(app)
        self.scroll.setWidget(self.view)
        self.body_layout().addWidget(self.scroll, 1)
        # Newest at the bottom, follow it unless the user scrolled up.
        self._follow = True
        sb = self.scroll.verticalScrollBar()
        sb.valueChanged.connect(self._on_scrolled)
        sb.rangeChanged.connect(self._on_range)

    def _on_scrolled(self, value: int) -> None:
        sb = self.scroll.verticalScrollBar()
        self._follow = value >= sb.maximum() - _LogView.ROW_H

    def _on_range(self, _lo: int, hi: int) -> None:
        if self._follow:
            self.scroll.verticalScrollBar().setValue(hi)

    def _clear(self) -> None:
        self.app.event_log.clear()
        self._follow = True
        self.view.sync()

    def tick(self) -> None:
        if self.view.sync() and self._follow:
            sb = self.scroll.verticalScrollBar()
            sb.setValue(sb.maximum())


# -- SYSTEM ----------------------------------------------------------------------

class SystemPanel(c.Panel):
    def __init__(self, app, parent: Optional[QWidget] = None):
        super().__init__("SYSTEM", parent)
        self.app = app
        self.grid = c.KVGrid(["INPUT", "CAPTURE", "SCALE", "LOCK", "HOTKEYS", "BUILD"], tips={
            "INPUT": "How keystrokes are sent (Key steps, key timers, bots). SERIAL_HID is the Arduino path NXT does not filter. Settings > Input.",
            "CAPTURE": "Where screen frames come from and which monitor the viewport shows.",
            "SCALE": "Windows display scale of the monitor this window is on. Zones are stored in scaled pixels.",
            "LOCK": "SCREEN: the zone is fixed screen coordinates. WINDOW: it follows the game window when that moves or resizes.",
            "HOTKEYS": "Start / Stop / Hold keys. They work even when a fullscreen game has focus. Esc always stops.",
            "BUILD": "The build this window is running.",
        })
        self.body_layout().addWidget(self.grid)
        root = Path(__file__).resolve().parent.parent.parent
        self._build, self._build_date = c.build_info(root)
        self._n = 0
        self.refresh()
        self.refresh_lock()

    def refresh_lock(self) -> None:
        """LOCK row: WINDOW (ice while the window is found), SCREEN, or
        LOST / MINIMIZED in amber. Cheap: the resolver is throttled."""
        zone, status, _title = c.lock_view(self.app)
        if zone is None or status == STATUS_SCREEN:
            self.grid.set_value("LOCK", "SCREEN", c.TEXT_TERTIARY)
        elif status == STATUS_LOCKED:
            self.grid.set_value("LOCK", "WINDOW", c.ACCENT)
        else:
            self.grid.set_value("LOCK", str(status).upper(), c.WARN)

    def refresh(self) -> None:
        app = self.app
        cfg = app.cfg
        method = str(cfg.get("key_input_method", DEFAULTS["key_input_method"]) or "auto").upper()
        port = str(cfg.get("serial_hid_port", "") or "")
        self.grid.set_value("INPUT", f"{method} · {port}" if port else method, c.TEXT_SECONDARY)
        self.grid.set_value("CAPTURE", f"MSS · MON{_target_monitor_index(app)}", c.TEXT_SECONDARY)
        try:
            handle = self.window().windowHandle()
            screen = handle.screen() if handle is not None else None
            dpr = float(screen.devicePixelRatio()) if screen is not None else float(self.devicePixelRatioF())
        except Exception:
            dpr = 1.0
        self.grid.set_value("SCALE", f"{dpr * 100:0.0f}%", c.TEXT_SECONDARY)
        keys = " / ".join(name_to_display(str(cfg.get(k, DEFAULTS.get(k, "")))).upper()
                          for k in ("hotkey_start", "hotkey_stop", "hotkey_pause"))
        self.grid.set_value("HOTKEYS", keys, c.TEXT_SECONDARY)
        self.grid.set_value("BUILD", self._build, c.TEXT_SECONDARY,
                            tooltip=(f"Build {self._build} · {self._build_date}"
                                     if self._build_date else f"Build {self._build}"),
                            suffix=self._build_date or None)

    def tick(self) -> None:
        self._n += 1
        if self._n % 10 == 0:
            self.refresh()
        self.refresh_lock()


def _target_monitor_index(app) -> int:
    try:
        from PySide6.QtWidgets import QApplication
        x, y, w, h = app.target_screen_bounds()
        for i, s in enumerate(QApplication.instance().screens()):
            g = s.geometry()
            if (g.left(), g.top(), g.width(), g.height()) == (x, y, w, h):
                return i + 1
    except Exception:
        pass
    return 1


class LeftColumn(QWidget):
    def __init__(self, app, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app = app
        self.setFixedWidth(COLUMN_W)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        self.modes = ModesPanel(app)
        self.sequence = SequencePanel(app)
        self.log = LogPanel(app)
        self.system = SystemPanel(app)
        col.addWidget(self.modes)
        # SEQUENCE and EVENT LOG split the flex space evenly.
        col.addWidget(self.sequence, 1)
        col.addWidget(self.log, 1)
        col.addWidget(self.system)

    def tick(self) -> None:
        for panel in (self.modes, self.sequence, self.log, self.system):
            try:
                panel.tick()
            except Exception:
                pass


# -- ENGINE STATUS -------------------------------------------------------------

def _hid_summary(full: str, ok: bool, cfg: dict) -> str:
    """Short value for the HID row. The backend's message is a sentence
    ("could not open COM8 at 115200 baud: ..."); the row has room for
    about 14 characters, so say the one thing that matters: which port
    failed, or that the method is ready."""
    method = str(cfg.get("key_input_method", "auto") or "auto").upper()
    port = str(cfg.get("serial_hid_port", "") or "").upper()
    if ok:
        return "READY"
    low = full.lower()
    if port and port.lower() in low:
        if "could not open" in low or "not found" in low or "no such" in low:
            return f"{port} NOT OPEN"
        return f"{port} FAULT"
    if "not installed" in low or "no module" in low or "import" in low:
        return f"{method} MISSING"
    return full if len(full) <= 14 else "FAULT"


class EngineStatusPanel(c.Panel):
    def __init__(self, app, parent: Optional[QWidget] = None):
        super().__init__("ENGINE STATUS", parent)
        self.app = app
        self.grid = c.KVGrid(["ENGINE", "HUMANIZER", "HID", "HOTKEYS", "MONITOR", "FATIGUE"], tips={
            "ENGINE": "Click engine state: STANDBY, ARMING (pre-start delay), RUNNING or HOLD.",
            "HUMANIZER": "Realism dial and the profile it maps to. Higher is slower and more lifelike.",
            "HOTKEYS": "Whether the global hotkey listener is alive.",
            "FATIGUE": "Wall-clock fatigue: movement and waits slow down over a long session. Shows the multiplier while running.",
        })
        self.grid.set_clickable("HID", "Key input backend. Click to re-probe it now.")
        self.grid.set_clickable("MONITOR", "LAN monitor server. Click to open the Monitor page.")
        self.grid.rowClicked.connect(self._on_row_clicked)
        self.body_layout().addWidget(self.grid)
        self._n = 0
        self._hid = ("··", c.TEXT_TERTIARY, "", True)
        self._hid_at = 0.0
        self._probe_hid()

    def hid_state(self) -> tuple[bool, str]:
        """``(ok, message)`` from the last probe; the header strip reads it."""
        _short, _color, full, ok = self._hid
        return ok, full

    def _on_row_clicked(self, key: str) -> None:
        if key == "HID":
            self.probe_hid_now()
        elif key == "MONITOR":
            try:
                self.app.show_page("monitor")
            except Exception:
                pass

    def probe_hid_now(self) -> None:
        self._probe_hid()
        self._push_hid()

    def _probe_hid(self) -> None:
        # Opens the serial port on first use for the Arduino backend, so
        # this runs on a slow divider rather than every tick.
        try:
            ok, msg = self.app.key_backend_status()
        except Exception as e:
            ok, msg = False, str(e)
        full = (msg or ("READY" if ok else "OFF")).upper()
        self._hid = (_hid_summary(full, ok, self.app.cfg), c.RUN if ok else c.STOP, full, bool(ok))
        self._hid_at = time.monotonic()

    def _push_hid(self) -> None:
        text, color, full, ok = self._hid
        age = int(time.monotonic() - self._hid_at)
        fix = "" if ok else "\nFix the backend or port under Settings > Input."
        # The age lives in the tooltip; a suffix would push the value
        # into an ellipsis on a 268 px column.
        self.grid.set_value("HID", text, color,
                            tooltip=f"{full}\nProbed {age} s ago. Click to re-probe.{fix}")

    def _monitor_row(self) -> tuple[str, str, str]:
        """``(text, color, tooltip)`` for the MONITOR row."""
        server = getattr(self.app, "monitor_server", None)
        running = False
        if server is not None:
            probe = getattr(server, "is_running", False)
            try:
                running = bool(probe() if callable(probe) else probe)
            except Exception:
                running = False
        if not running:
            return "OFF", c.TEXT_TERTIARY, "LAN monitor server is off. Nothing leaves this PC. Click to open the Monitor page."
        try:
            url = str(server.lan_url())
        except Exception:
            url = ""
        host = url.split("://", 1)[-1].split("/", 1)[0] if url else f":{int(_cfg(self.app, 'monitor_port'))}"
        return c.elide(host, 20), c.RUN, f"Streaming at {url}\nClick to open the Monitor page."

    def tick(self) -> None:
        self._n += 1
        if self._n % 300 == 0:
            self._probe_hid()
        app = self.app
        state = app._state_str
        running = state != ClickerState.IDLE
        live, off = c.RUN, c.TEXT_TERTIARY
        self.grid.set_value("ENGINE", c.state_word(state), live if running else off)
        r = float(_cfg(app, "realism"))
        profile = "HUMAN" if r >= 0.5 else ("LIGHT" if r >= 0.2 else "MINIMAL")
        self.grid.set_value("HUMANIZER", f"{r:0.2f} · {profile}", live if running else off)
        self._push_hid()
        try:
            hk = bool(app.hotkeys.is_alive())
        except Exception:
            hk = False
        self.grid.set_value("HOTKEYS", "ARMED" if hk else "OFF", live if hk else off)
        self.grid.set_value("MONITOR", *self._monitor_row())
        self._tick_fatigue(running, live, off)

    def _tick_fatigue(self, running: bool, live: str, off: str) -> None:
        app = self.app
        if running and app._active_mode == "ai":
            fn = getattr(getattr(app, "bot_runner", None), "fatigue_multiplier", None)
            mult = None
            if callable(fn):
                try:
                    mult = fn()
                except Exception:
                    mult = None
            if mult is not None:
                self.grid.set_value("FATIGUE", f"X{float(mult):0.3f}", live)
            else:
                self.grid.set_value("FATIGUE", "··", off)
            return
        fat = getattr(app.clicker, "_fatigue", None)
        if running and fat is not None:
            try:
                self.grid.set_value("FATIGUE", f"X{fat.multiplier():0.3f}", live)
            except Exception:
                self.grid.set_value("FATIGUE", "··", off)
        else:
            enabled = bool(_cfg(app, "fatigue_enabled"))
            self.grid.set_value("FATIGUE", "ARMED" if enabled else "OFF", off)


# -- CADENCE ---------------------------------------------------------------------

class IntervalStrip(QWidget):
    """Last 24 inter-click intervals as 3 px bars, tallest = longest."""

    def __init__(self, app, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app = app
        self.setFixedHeight(30)

    def paintEvent(self, _event):  # noqa: N802 (Qt name)
        p = QPainter(self)
        gaps = self.app.click_ring.intervals(24)
        if not gaps:
            p.fillRect(0, self.height() - 2, self.width(), 1, QColor(c.BORDER_STRONG))
            p.setFont(c.micro_font())
            p.setPen(QColor(c.TEXT_DISABLED))
            p.drawText(QRectF(0, 0, self.width(), self.height() - 4),
                       Qt.AlignRight | Qt.AlignVCenter, "NO CLICKS YET")
            p.end()
            return
        n = 24
        slot = self.width() / n
        top = max((gaps or [1.0]))
        for i in range(n):
            x = int(i * slot + (slot - 3) / 2)
            j = i - (n - len(gaps))
            if j < 0:
                p.fillRect(x, self.height() - 3, 3, 3, QColor(c.STATUS_IDLE))
                continue
            h = max(3, int((gaps[j] / top) * (self.height() - 2))) if top > 0 else 3
            p.fillRect(x, self.height() - h, 3, h, QColor(c.ACCENT))
        p.end()


class CadencePanel(c.Panel):
    """Compact timing and targeting summary; never stretches to fill a column."""
    def __init__(self, app, parent=None):
        super().__init__("TIMING & TARGETING", parent)
        self.app = app
        self.setFixedHeight(166)
        body = self.body_layout()
        self.grid = c.KVGrid(["INTERVAL", "CURVE", "REALISM", "ANTI-CLUSTER"], tips={
            "CURVE": "Shape of the wait distribution. LOG-NORMAL clusters near the short end with a long tail, like real inter-action timing.",
        })
        self.grid.setFixedHeight(84)
        self.grid.set_clickable("REALISM", "Realism dial (0 to 1). Click to open Behavior settings.")
        self.grid.set_clickable("ANTI-CLUSTER", "Consecutive clicks are pushed at least this far apart so they never pile up on one spot. Click to open Behavior settings.")
        self.grid.set_clickable("INTERVAL", "Shortest and longest wait between clicks. Click to edit the timing.")
        self.grid.rowClicked.connect(self._open_settings)
        body.addWidget(self.grid)
        self.strip = IntervalStrip(app)
        self.strip.setFixedHeight(20)
        self.strip.setToolTip("Last 24 measured intervals between clicks; taller bars mean longer waits.")
        body.addWidget(self.strip)

    def _open_settings(self, key):
        if key == "INTERVAL":
            self.app.show_page({"clicker": "click", "recorder": "record", "ai": "ai"}[self.app._active_mode])
            if self.app._active_mode == "clicker":
                self.app.click_page.reveal_timing()
        else:
            self.app.show_page("behavior")

    def tick(self):
        app = self.app
        lo, hi = float(_cfg(app, "min_delay")), float(_cfg(app, "max_delay"))
        if app._active_mode == "recorder":
            idx = max(0, app.clicker.current_step_index[0] - 1)
            steps = app._steps
            if steps and idx < len(steps):
                lo, hi = steps[idx].delay_min, steps[idx].delay_max
        interval = f"{c.fmt_secs(lo)} TO {c.fmt_secs(hi)}"
        curve = str(app.clicker.delay_curve()).upper()
        if app._active_mode == "ai":
            interval = f"{float(_cfg(app, 'ai_tick_rate_hz')):g} HZ TICKS"
            curve = "RULE-DRIVEN"
        self.grid.set_value("INTERVAL", interval, c.TEXT_SECONDARY)
        self.grid.set_value("CURVE", curve, c.TEXT_SECONDARY)
        r = float(_cfg(app, "realism"))
        self.grid.set_value("REALISM", f"{r:.0%}", c.TEXT_SECONDARY)
        on = bool(_cfg(app, "anti_cluster_enabled"))
        radius = int(_cfg(app, "anti_cluster_radius"))
        self.grid.set_value("ANTI-CLUSTER", f"ON · {radius}px" if on else "OFF",
                            c.ACCENT if on else c.TEXT_TERTIARY)
        self.strip.update()


class MissionPanel(c.Panel):
    """Setup checklist while idle, run readout while running.

    Idle rows are the steps a new user takes in order (draw the zone, set
    the interval, test one click, start), each a live control: the square
    shows whether the step is done, clicking the row performs it. One
    line under the rows says what still blocks START; that sentence has
    no other home on the deck, so it is never repeated.
    """

    def __init__(self, app, parent=None):
        super().__init__("MISSION", parent)
        self.app = app
        body = self.body_layout()
        self._list = QVBoxLayout()
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(2)
        body.addLayout(self._list)
        self._rows: list[SeqRow] = []
        self._shape: Optional[tuple] = None
        self.phase = QLabel()
        self.phase.setWordWrap(True)
        self.phase.setProperty("role", "hint")
        body.addWidget(self.phase)
        self.grid = c.KVGrid(["PROGRESS", "CLICKS", "RECOVERIES"], tips={
            "PROGRESS": "Step position in a sequence, or tick count for a bot.",
            "CLICKS": "Clicks fired this session.",
            "RECOVERIES": "Times the engine re-found a lost target and carried on.",
        })
        self.grid.setFixedHeight(62)
        body.addWidget(self.grid)
        self.grid.hide()

    # -- Rows ---------------------------------------------------------------

    def _rebuild(self, specs: list[RowSpec]) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows = []
        for spec in specs:
            r = SeqRow(spec)
            r.toggled.connect(self._on_row)
            r.activated.connect(self._on_row)
            self._list.addWidget(r)
            self._rows.append(r)

    def rows(self) -> list[SeqRow]:
        return list(self._rows)

    def _ready(self) -> str:
        from ui.readiness import readiness_message
        try:
            return readiness_message(self.app)
        except Exception:
            return ""

    def _specs(self, message: str) -> list[RowSpec]:
        app = self.app
        mode = app._active_mode
        rows: list[RowSpec] = []
        ready = not message
        if mode == "clicker":
            has_zone = app._zone is not None
            lo, hi = float(_cfg(app, "min_delay")), float(_cfg(app, "max_delay"))
            tested = bool(getattr(app, "_checklist_tested", False))
            rows.append(RowSpec("m:zone", "DRAW ZONE" if not has_zone else "ZONE DRAWN", checked=has_zone,
                                dot=c.ACCENT if has_zone else c.STATUS_IDLE, click=True,
                                tip="Where clicks land. Click to draw it on screen."))
            rows.append(RowSpec("m:interval", f"WAIT  {c.fmt_secs(lo)} TO {c.fmt_secs(hi)}", checked=True,
                                dot=c.ACCENT, click=True, tip="Wait between clicks. Click to edit."))
            rows.append(RowSpec("m:test", "TEST ONE CLICK" if not tested else "TESTED", checked=tested,
                                dot=c.ACCENT if tested else c.STATUS_IDLE, click=True, dim=not has_zone,
                                tip="Fire one rehearsal click, then stop. Click to run it."))
        elif mode == "recorder":
            n = len(app._steps)
            enabled = sum(bool(getattr(s, "enabled", True)) for s in app._steps)
            rows.append(RowSpec("m:steps", f"ADD STEPS  {n}" if n else "ADD STEPS", checked=n > 0,
                                dot=c.ACCENT if n else c.STATUS_IDLE, click=True,
                                tip="Build the sequence. Click to add a step."))
            rows.append(RowSpec("m:configure", f"CONFIGURE  {enabled} ENABLED", checked=bool(n) and ready,
                                dot=c.ACCENT if (n and ready) else c.STATUS_IDLE, click=True, dim=not n,
                                tip="Every enabled step needs its zone, template, colour or key. Click to open the steps."))
        else:
            slug = str(app.cfg.get("ai_active_bundle") or app.cfg.get("ai_bot_slug") or "").strip()
            dry = bool(_cfg(app, "ai_dry_run"))
            name = c.elide(slug.replace("_", " "), 14).upper() if slug else ""
            rows.append(RowSpec("m:bot", f"BOT  {name}" if name else "PICK A BOT", checked=bool(slug),
                                dot=c.ACCENT if slug else c.STATUS_IDLE, click=True,
                                tip="Which bot runs. Click to open the BOT pane."))
            rows.append(RowSpec("m:dry", "DRY RUN  " + ("ON" if dry else "OFF"), checked=dry,
                                dot=c.WARN if dry else c.STATUS_IDLE, toggle=True,
                                tip="Dry run logs what the bot would do without touching the mouse. Click to toggle."))
        rows.append(RowSpec("m:start", "START" if ready else "START  BLOCKED", checked=False,
                            dot=c.RUN if ready else c.STATUS_IDLE, click=True, dim=not ready,
                            tip=("Start now. F6 does the same." if ready else f"Blocked: {message}")))
        return rows

    def _on_row(self, key: str) -> None:
        app = self.app
        shell = getattr(app, "deck", None)
        try:
            if key == "m:zone":
                app.click_page.zone_card._on_draw()
            elif key == "m:interval":
                if shell is not None:
                    shell.set_editor_open(True)
                app.click_page.reveal_timing()
                _reveal(app.click_page.timing_card)
            elif key == "m:test":
                app._test_click_once()
            elif key == "m:steps":
                if shell is not None:
                    shell.set_editor_open(True)
                app.record_mode_tab.show_add_menu(QCursor.pos())
            elif key in ("m:configure", "m:bot"):
                if shell is not None:
                    shell.set_editor_open(True)
            elif key == "m:dry":
                app.cfg["ai_dry_run"] = not bool(_cfg(app, "ai_dry_run"))
                save_config(app.cfg)
                card = getattr(app, "ai_card", None)
                switch = getattr(getattr(card, "config", None), "dry_switch", None)
                if switch is not None and switch.isChecked() != bool(app.cfg["ai_dry_run"]):
                    switch.setChecked(bool(app.cfg["ai_dry_run"]))
            elif key == "m:start":
                app._on_start()
        except Exception:
            app.log.exception("mission row failed: %s", key)
        self.tick()

    # -- Tick ---------------------------------------------------------------

    def tick(self):
        app = self.app
        running = app._state_str != ClickerState.IDLE
        self.title.setText("CURRENT RUN" if running else "MISSION")
        if not running:
            message = self._ready()
            specs = self._specs(message)
            shape = tuple(sp.shape() for sp in specs)
            if shape != self._shape:
                self._shape = shape
                self._rebuild(specs)
            else:
                for r, sp in zip(self._rows, specs):
                    r.apply(sp)
            for r in self._rows:
                if not r.isVisible():
                    r.show()
            self.phase.setText(message or "Ready. START runs it, F6 does the same.")
            if not self.grid.isHidden():
                self.grid.hide()
            return
        for r in self._rows:
            if r.isVisible():
                r.hide()
        if self.grid.isHidden():
            self.grid.show()
        if app._active_mode == "ai":
            snap = app.bot_runner.last_fired() if app.bot_runner else {}
            phase = snap.get("last_fired_rule") or "Waiting for a matching rule"
            progress = f"Tick {snap.get('current_tick', 0)}"
            clicks = snap.get("click_count", 0)
            recovery = "··"
        else:
            phase = app.clicker.phase_label or "Running"
            idx, total = app.clicker.current_step_index
            progress = f"Step {idx}/{total}" if total else "Repeat clicks"
            clicks = app.stats.snapshot().get("total", 0)
            recovery = str(app.clicker.recovery_count)
        self.phase.setText(str(phase))
        self.grid.set_value("PROGRESS", progress, c.TEXT_SECONDARY)
        self.grid.set_value("CLICKS", str(clicks), c.TEXT_SECONDARY)
        self.grid.set_value("RECOVERIES", recovery, c.TEXT_SECONDARY)


# Old name, kept for anything that imported it.
RunProgressPanel = MissionPanel


# -- CORNER ABORT FOOTER ---------------------------------------------------------

class CornerAbortFooter(QFrame):
    """Zone-map footer: dot + label reporting the corner watchdog, and a
    click target that toggles ``corner_abort_enabled``. The config key
    keeps its name; the deck says CORNER STOP, like every other stop."""

    def __init__(self, app, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("deck-corner-footer")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QFrame#deck-corner-footer { background: transparent; border: none; }")
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(8)
        self.dot = c.Dot(c.TEXT_TERTIARY, 6)
        row.addWidget(self.dot)
        self.label = c.MicroLabel("CORNER STOP", c.TEXT_TERTIARY)
        row.addWidget(self.label, 1)
        self.tick()

    def enabled(self) -> bool:
        return bool(_cfg(self.app, "corner_abort_enabled"))

    def toggle(self) -> None:
        cfg = self.app.cfg
        cfg["corner_abort_enabled"] = not self.enabled()
        save_config(cfg)
        self.app._push_config_to_clicker()
        self.tick()

    def mousePressEvent(self, event):  # noqa: N802 (Qt name)
        if event.button() == Qt.LeftButton:
            self.toggle()
            event.accept()
            return
        super().mousePressEvent(event)

    def tick(self) -> None:
        app = self.app
        enabled = self.enabled()
        running = app._state_str != ClickerState.IDLE
        armed: Optional[bool] = None
        fn = getattr(app.clicker, "corner_abort_armed", None)
        if callable(fn):
            try:
                armed = bool(fn())
            except Exception:
                armed = None
        if not running:
            color = c.TEXT_TERTIARY
            text = "CORNER STOP AT START" if enabled else "CORNER STOP OFF"
        else:
            live = armed if armed is not None else enabled
            color = c.RUN if live else c.STATUS_IDLE
            text = "CORNER STOP ARMED" if live else "CORNER STOP DISARMED"
        self.dot.set_color(color)
        self.label.set_color(color)
        self.label.setText(text)
        self.setToolTip(
            ("Moving the cursor into any screen corner stops the engine. Click to turn it off."
             if enabled else
             "Corner emergency stop is off. Click to turn it on; it arms on the next START."))


class RightColumn(QWidget):
    def __init__(self, app, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app = app
        self.setFixedWidth(COLUMN_W)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        self.engine_status = EngineStatusPanel(app)
        col.addWidget(self.engine_status)

        # All cards keep compact natural heights; telemetry never stretches.
        self.zone_panel = c.Panel("ZONE MAP")
        self.zone_map = ZoneMap(app)
        self.zone_panel.body_layout().addWidget(self.zone_map)
        self.corner_footer = CornerAbortFooter(app)
        self.zone_panel.body_layout().addWidget(self.corner_footer)
        col.addWidget(self.zone_panel)

        self.cadence = CadencePanel(app)
        col.addWidget(self.cadence)
        self.progress = MissionPanel(app)
        col.addWidget(self.progress)
        col.addStretch(1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.progress.setVisible(self.height() >= 800)

    def tick(self) -> None:
        for panel in (self.engine_status, self.cadence, self.progress, self.corner_footer):
            try:
                panel.tick()
            except Exception:
                pass
        self.zone_map.sync_sweep()
        if not self.zone_map.sweep_active():
            self.zone_map.update()
