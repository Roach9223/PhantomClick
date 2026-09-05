"""Control deck: the 168 px strip under the viewport.

Left to right: NUDGE ZONE (3x3 arrow grid), ACTIONS (start / hold /
redraw / abort), MIN / MAX / REALISM vertical sliders, the L / R / M
button selector, the round ENGINE button and the CAPTURE button.

Every control writes through the same paths the classic cards use
(``TimingCard.range_slider.set_values``, ``BehaviorCard.apply_realism_preset``,
``ClickZoneCard._on_draw``), so the two surfaces never disagree about
what the engine will run.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QFrame, QGridLayout, QHBoxLayout,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

from modules.clicker import ClickerState
from modules.recorder import KIND_CLICK, KIND_COLOR, KIND_TRACK
from modules.zone_selector import Zone
from ui.config_io import DEFAULTS, save_config

from . import common as c

DECK_H = 168
_DELAY_LO, _DELAY_HI = 0.01, 300.0
_NUDGE_STEPS = (1, 5, 20)
_RUN_LABELS = {"clicker": "RUN CLICKS", "recorder": "RUN SEQUENCE", "ai": "RUN BOT"}


def shift_zone(zone: Zone, dx: int, dy: int) -> Optional[Zone]:
    d = zone.to_json()
    if d.get("rect"):
        x1, y1, x2, y2 = d["rect"]
        d["rect"] = [x1 + dx, y1 + dy, x2 + dx, y2 + dy]
    if d.get("circle"):
        cx, cy, r = d["circle"]
        d["circle"] = [cx + dx, cy + dy, r]
    if d.get("vertices"):
        d["vertices"] = [[vx + dx, vy + dy] for vx, vy in d["vertices"]]
    return Zone.from_json(d)


class EngineButton(QAbstractButton):
    """64 px round start / stop. Lime play triangle idle, red square live."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self.setCursor(Qt.PointingHandCursor)
        self._running = False

    def set_running(self, running: bool) -> None:
        if running != self._running:
            self._running = running
            self.setToolTip("Stop the engine" if running else "Start the engine")
            self.update()

    def paintEvent(self, _event):  # noqa: N802 (Qt name)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        fill = c.SURFACE_PRESS if self.isDown() else (c.SURFACE_HIGH if self.underMouse() else c.SURFACE)
        p.setBrush(QColor(fill))
        ring = QPen(QColor(c.STOP if self._running else c.BORDER_STRONG))
        ring.setWidthF(1.5)
        p.setPen(ring)
        p.drawEllipse(r)
        p.setPen(Qt.NoPen)
        cx, cy = r.center().x(), r.center().y()
        if self._running:
            p.setBrush(QColor(c.STOP))
            p.drawRoundedRect(QRectF(cx - 11, cy - 11, 22, 22), 2, 2)
        else:
            p.setBrush(QColor(c.ACCENT if self.isEnabled() else c.TEXT_DISABLED))
            tri = QPolygonF([QPointF(cx - 8, cy - 11), QPointF(cx + 12, cy), QPointF(cx - 8, cy + 11)])
            p.drawPolygon(tri)
        p.end()


class VSlider(QWidget):
    """Micro title over a vertical slider over a mono value readout."""

    valueChanged = Signal(int)

    def __init__(self, title: str, steps: int = 1000, parent: Optional[QWidget] = None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        self.title = c.MicroLabel(title, c.TEXT_MICRO)
        self.title.setAlignment(Qt.AlignHCenter)
        col.addWidget(self.title)
        self.slider = QSlider(Qt.Vertical)
        self.slider.setRange(0, steps)
        self.slider.setFixedWidth(22)
        self.slider.valueChanged.connect(self.valueChanged)
        col.addWidget(self.slider, 1, Qt.AlignHCenter)
        self.value = c.MonoLabel("··", c.TEXT_PRIMARY, c.SIZE_XS)
        self.value.setAlignment(Qt.AlignHCenter)
        self.value.setMinimumWidth(44)
        col.addWidget(self.value)

    def set_position(self, pos: int) -> None:
        if self.slider.isSliderDown():
            return
        self.slider.blockSignals(True)
        self.slider.setValue(int(pos))
        self.slider.blockSignals(False)


class ControlDeck(QFrame):
    def __init__(self, app, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("deck-control")
        self.setFixedHeight(DECK_H)
        self.setMinimumWidth(410)
        self.setStyleSheet(
            f"QFrame#deck-control {{ background: {c.SURFACE}; border: 1px solid {c.BORDER}; "
            f"border-radius: {c.RADIUS_CARD}px; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)

        self.nudge_section = self._build_nudge()
        self.nudge_rule = self._vrule()
        row.addWidget(self.nudge_section)
        row.addWidget(self.nudge_rule)
        row.addWidget(self._build_actions())
        row.addWidget(self._vrule())
        row.addWidget(self._build_sliders())
        row.addWidget(self._vrule())
        row.addWidget(self._build_button_seg())
        row.addStretch(1)
        self.engine_section = self._build_engine()
        self.capture_section = self._build_capture()
        row.addWidget(self.engine_section)
        row.addWidget(self.capture_section)
        self.set_compact(True)

    def set_compact(self, compact: bool) -> None:
        # Start/Stop remain in the header; F9 and the editor own capture.
        for widget in (self.nudge_section, self.nudge_rule, self.engine_section, self.capture_section):
            widget.setVisible(not compact)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.set_compact(self.width() < 760)

    def _vrule(self) -> QFrame:
        f = QFrame()
        f.setFixedWidth(1)
        f.setStyleSheet(f"background: {c.BORDER};")
        return f

    @staticmethod
    def _section() -> QWidget:
        # Plain containers must not pick up the stylesheet's QWidget fill,
        # or every section paints its own darker slab inside the deck.
        box = QWidget()
        box.setAttribute(Qt.WA_StyledBackground, False)
        box.setStyleSheet("background: transparent;")
        return box

    def _section_title(self, text: str) -> c.MicroLabel:
        return c.MicroLabel(text, c.TEXT_MICRO)

    # -- NUDGE ZONE --------------------------------------------------------

    def _build_nudge(self) -> QWidget:
        box = self._section()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        col.addWidget(self._section_title("NUDGE ZONE"))
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        self._nudge_step_idx = 0
        cells = {
            (0, 1): ("mg106", 0.0, 0, -1, "up"),
            (1, 0): ("mg108", 180.0, -1, 0, "left"),
            (1, 2): ("mg108", 0.0, 1, 0, "right"),
            (2, 1): ("mg106", 180.0, 0, 1, "down"),
        }
        self._nudge_btns: list[tuple[c.IconButton, str]] = []
        for (r, col_i), (name, deg, dx, dy, word) in cells.items():
            btn = c.IconButton(name, size=28, icon_px=16, color=c.TEXT_SECONDARY,
                               degrees=deg)
            btn.clicked.connect(lambda _=False, ddx=dx, ddy=dy: self._nudge(ddx, ddy))
            self.app.locker.register(btn)
            grid.addWidget(btn, r, col_i)
            self._nudge_btns.append((btn, word))
        center = QWidget()
        center.setFixedSize(28, 28)
        cl = QHBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(c.Dot(c.TEXT_TERTIARY, 4), 0, Qt.AlignCenter)
        grid.addWidget(center, 1, 1)
        col.addLayout(grid)
        # The step label is a button: each press cycles 1 / 5 / 20 px.
        self.nudge_step_btn = QPushButton("1 PX")
        self.nudge_step_btn.setProperty("variant", "ghost")
        self.nudge_step_btn.setFixedHeight(18)
        self.nudge_step_btn.setFont(c.mono_font(c.SIZE_XS))
        self.nudge_step_btn.setCursor(Qt.PointingHandCursor)
        self.nudge_step_btn.setStyleSheet("QPushButton { padding: 0 6px; }")
        self.nudge_step_btn.clicked.connect(self._cycle_nudge_step)
        col.addWidget(self.nudge_step_btn, 0, Qt.AlignHCenter)
        col.addStretch(1)
        self._refresh_nudge_tips()
        return box

    def nudge_step(self) -> int:
        return _NUDGE_STEPS[self._nudge_step_idx]

    def _cycle_nudge_step(self) -> None:
        self._nudge_step_idx = (self._nudge_step_idx + 1) % len(_NUDGE_STEPS)
        self._refresh_nudge_tips()

    def _refresh_nudge_tips(self) -> None:
        step = self.nudge_step()
        self.nudge_step_btn.setText(f"{step} PX")
        self.nudge_step_btn.setToolTip(f"Nudge step: {step} px. Click to cycle 1 / 5 / 20.")
        for btn, word in self._nudge_btns:
            btn.setToolTip(f"Nudge zone {word} {step} px")

    def _nudge_target(self):
        """``(zone, step_or_None)`` the pad moves: the Click zone in Click
        mode; in Record mode the running Click step's zone, else the first
        Click step with a zone. ``(None, None)`` when there is nothing."""
        app = self.app
        if app._active_mode == "clicker":
            return app._zone, None
        if app._active_mode != "recorder":
            return None, None
        zone, key = c.active_zone(app)
        if zone is None:
            return None, None
        for s in app._steps:
            if s.step_id == key and s.kind == KIND_CLICK and s.zone is not None:
                return s.zone, s
        for s in app._steps:
            if s.kind == KIND_CLICK and s.zone is not None:
                return s.zone, s
        return None, None

    def _nudge(self, dx: int, dy: int) -> None:
        app = self.app
        if app._active_mode == "ai":
            app.toasts.post("Nudge moves Click and Record zones. Bots place their own clicks.", kind="info")
            return
        zone, step = self._nudge_target()
        if zone is None:
            app.toasts.post("No zone to nudge. Draw one first.", kind="warn")
            return
        n = self.nudge_step()
        z = shift_zone(zone, dx * n, dy * n)
        if z is None:
            return
        if step is not None:
            step.zone = z
            # Same debounced path the step sliders use, so a burst of
            # presses lands as one config write.
            app.save_steps_later()
            app.overlay_manager.refresh_step_overlays()
            return
        app._zone = z
        app.cfg["zone"] = z.to_json()
        app.save_config_later()
        try:
            app.click_page.zone_card._refresh_preview()
        except Exception:
            pass
        app.overlay_manager.apply_visibility()

    # -- ACTIONS -------------------------------------------------------------

    def _build_actions(self) -> QWidget:
        box = self._section()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        col.addWidget(self._section_title("ACTIONS"))

        def mk(text: str, variant: str, tip: str) -> QPushButton:
            b = QPushButton(text)
            b.setProperty("variant", variant)
            b.setFixedHeight(c.BUTTON_H)
            b.setMinimumWidth(124)
            b.setCursor(Qt.PointingHandCursor)
            b.setFont(c.mono_font(c.SIZE_XS, QFont.DemiBold))
            b.setToolTip(tip)
            col.addWidget(b)
            return b

        self.loop_btn = mk("RUN CLICKS", "secondary", "Start the engine in the active mode.")
        self.loop_btn.clicked.connect(self.app._on_start)
        self.hold_btn = mk("HOLD", "secondary",
                           "Pause or resume whatever is running: the click engine or a bot.")
        self.hold_btn.clicked.connect(self.app._toggle_pause)
        self.redraw_btn = mk("REDRAW ZONE", "secondary", "Draw the click zone on screen.")
        self.redraw_btn.clicked.connect(self._redraw)
        self.app.locker.register(self.redraw_btn)
        self.abort_btn = mk("ABORT · ESC", "danger", "Stop everything now. Esc does the same.")
        self.abort_btn.clicked.connect(self.app._on_stop)
        return box

    def _redraw(self) -> None:
        try:
            self.app.click_page.zone_card._on_draw()
        except Exception:
            self.app.log.exception("deck redraw failed")

    # -- SLIDERS ---------------------------------------------------------------

    def _build_sliders(self) -> QWidget:
        box = self._section()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.min_slider = VSlider("MIN")
        self.max_slider = VSlider("MAX")
        self.realism_slider = VSlider("REALISM", steps=100)
        for s in (self.min_slider, self.max_slider, self.realism_slider):
            row.addWidget(s)
        self.min_slider.valueChanged.connect(lambda v: self._on_delay(v, is_min=True))
        self.max_slider.valueChanged.connect(lambda v: self._on_delay(v, is_min=False))
        self.realism_slider.valueChanged.connect(self._on_realism)
        self._sync_sliders()
        return box

    def _on_delay(self, pos: int, *, is_min: bool) -> None:
        cfg = self.app.cfg
        lo = float(cfg.get("min_delay", 5.0))
        hi = float(cfg.get("max_delay", 20.0))
        v = c.slider_to_log(pos, _DELAY_LO, _DELAY_HI)
        if is_min:
            lo = v
            hi = max(hi, lo)
        else:
            hi = v
            lo = min(lo, hi)
        # TimingCard owns the cfg write, the interval display and the
        # debounced save; routing through it keeps both surfaces in step.
        try:
            self.app.click_page.timing_card.range_slider.set_values(lo, hi)
        except Exception:
            cfg["min_delay"], cfg["max_delay"] = lo, hi
            self.app.save_config_later()
        self._sync_sliders(skip_positions=True)

    def _on_realism(self, pos: int) -> None:
        r = c.clamp(pos / 100.0, 0.0, 1.0)
        try:
            self.app.behavior_card.apply_realism_preset(r)
        except Exception:
            self.app.cfg["realism"] = r
            self.app.save_config_later()
        self._sync_sliders(skip_positions=True)

    def _sync_sliders(self, skip_positions: bool = False) -> None:
        cfg = self.app.cfg
        lo = float(cfg.get("min_delay", 5.0))
        hi = float(cfg.get("max_delay", 20.0))
        r = float(cfg.get("realism", 0.5))
        if not skip_positions:
            self.min_slider.set_position(c.log_to_slider(lo, _DELAY_LO, _DELAY_HI))
            self.max_slider.set_position(c.log_to_slider(hi, _DELAY_LO, _DELAY_HI))
            self.realism_slider.set_position(int(round(r * 100)))
        self.min_slider.value.setText(_fmt_secs(lo))
        self.max_slider.value.setText(_fmt_secs(hi))
        self.realism_slider.value.setText(f"{r:0.2f}")

    # -- L / R / M ----------------------------------------------------------------

    def _build_button_seg(self) -> QWidget:
        box = self._section()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(self._section_title("BTN"))
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        self._seg_btns: dict[str, QPushButton] = {}
        for key, label in (("left", "L"), ("right", "R"), ("middle", "M")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setFixedSize(30, 30)
            b.setProperty("variant", "secondary")
            # The app stylesheet pads buttons for text labels; at 30 px
            # that padding clips a single glyph.
            b.setStyleSheet("QPushButton { padding: 0px; }")
            b.setFont(c.mono_font(c.SIZE_SM, QFont.DemiBold))
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"Click with the {key} mouse button.")
            b.clicked.connect(lambda _=False, k=key: self._on_click_type(k))
            self._btn_group.addButton(b)
            self._seg_btns[key] = b
            col.addWidget(b)
        col.addStretch(1)
        self._sync_click_type()
        return box

    def _on_click_type(self, value: str) -> None:
        cfg = self.app.cfg
        if cfg.get("click_type") == value:
            return
        cfg["click_type"] = value
        save_config(cfg)
        self.app._push_config_to_clicker()
        try:
            self.app.click_page.timing_card._button_seg.setValue(value, emit=False)
        except Exception:
            pass

    def _sync_click_type(self) -> None:
        cur = str(self.app.cfg.get("click_type", DEFAULTS["click_type"]))
        b = self._seg_btns.get(cur)
        if b is not None and not b.isChecked():
            b.setChecked(True)

    # -- ENGINE / CAPTURE ---------------------------------------------------

    def _build_engine(self) -> QWidget:
        box = self._section()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        self.engine_btn = EngineButton()
        self.engine_btn.setToolTip("Start the engine")
        self.engine_btn.clicked.connect(self._on_engine)
        col.addStretch(1)
        col.addWidget(self.engine_btn, 0, Qt.AlignHCenter)
        self.engine_lbl = c.MicroLabel("ENGINE", c.TEXT_MICRO)
        self.engine_lbl.setAlignment(Qt.AlignHCenter)
        col.addWidget(self.engine_lbl)
        col.addStretch(1)
        return box

    def _on_engine(self) -> None:
        if self.app._state_str == ClickerState.IDLE:
            self.app._on_start()
        else:
            self.app._on_stop()

    def _build_capture(self) -> QWidget:
        box = self._section()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        self.capture_btn = c.IconButton("camera", size=40, icon_px=20, color=c.TEXT_SECONDARY)
        self.capture_btn.setProperty("variant", "secondary")
        self.capture_btn.clicked.connect(self._on_capture)
        self.app.locker.register(self.capture_btn)
        col.addStretch(1)
        col.addWidget(self.capture_btn, 0, Qt.AlignHCenter)
        self.capture_lbl = c.MicroLabel("CAPTURE", c.TEXT_MICRO)
        self.capture_lbl.setAlignment(Qt.AlignHCenter)
        col.addWidget(self.capture_lbl)
        col.addStretch(1)
        self._capture_kind: Optional[str] = None
        self._refresh_capture()
        return box

    # (icon, label, tooltip verb) per step kind the screen action serves.
    _CAPTURE_META = {
        KIND_TRACK: ("camera", "CAPTURE", "Capture the template for Track step {n}."),
        KIND_COLOR: ("target", "PICK COLOR", "Pick the target colour for Color step {n}."),
        KIND_CLICK: ("redraw", "DRAW AREA", "Draw the click area for Click step {n}."),
    }

    def _capture_target(self) -> tuple[Optional[int], Optional[str]]:
        """``(index, kind)`` of the step the screen button acts on in
        Record mode: the step picked from the SEQUENCE panel, else the
        expanded one, else the first that needs the screen (Track, Color
        or Click). ``(None, "zone")`` in Click mode, where the button
        draws the click area. ``(None, None)`` when nothing applies."""
        app = self.app
        if app._active_mode == "clicker":
            return None, "zone"
        if app._active_mode != "recorder":
            return None, None
        kinds = (KIND_TRACK, KIND_COLOR, KIND_CLICK)
        cands = [i for i, s in enumerate(app._steps) if s.kind in kinds]
        if not cands:
            return None, None
        tab = getattr(app, "record_mode_tab", None)
        try:
            selected = tab.selected_step_id() if tab is not None else None
        except Exception:
            selected = None
        try:
            expanded = tab._row_builder._expanded if tab is not None else set()
        except Exception:
            expanded = set()
        for i in cands:
            if selected and app._steps[i].step_id == selected:
                return i, app._steps[i].kind
        for i in reversed(cands):
            if app._steps[i].step_id in expanded:
                return i, app._steps[i].kind
        return cands[0], app._steps[cands[0]].kind

    def _refresh_capture(self) -> None:
        idx, kind = self._capture_target()
        enabled = kind is not None and self.app._state_str == ClickerState.IDLE
        if kind == "zone":
            icon, label, tip = "redraw", "DRAW AREA", "Draw the click area on screen."
        elif kind is not None:
            icon, label, tip = self._CAPTURE_META[kind]
            tip = tip.format(n=idx + 1)
        else:
            icon, label = "camera", "CAPTURE"
            tip = "Needs a Track, Color or Click step to act on."
        if self.capture_btn.isEnabled() != enabled:
            self.capture_btn.setEnabled(enabled)
        if kind != self._capture_kind or self.capture_btn.isEnabled() != enabled:
            self._capture_kind = kind
            self.capture_btn.set_icon(icon, c.TEXT_SECONDARY if enabled else c.TEXT_DISABLED)
            self.capture_lbl.setText(label)
        if self.capture_btn.toolTip() != tip:
            self.capture_btn.setToolTip(tip)

    def _on_capture(self) -> None:
        idx, kind = self._capture_target()
        if kind is None:
            return
        try:
            if kind == "zone":
                self.app.click_page.zone_card._on_draw()
                return
            builder = self.app.record_mode_tab._row_builder
            if kind == KIND_TRACK:
                builder._on_track_capture(idx)
            elif kind == KIND_COLOR:
                builder._on_color_pick(idx)
            else:
                builder._on_draw_step(idx)
        except Exception:
            self.app.log.exception("deck capture failed")

    # -- Tick --------------------------------------------------------------------

    def tick(self) -> None:
        state = self.app._state_str
        running = state != ClickerState.IDLE
        self.engine_btn.set_running(running)
        self.engine_lbl.set_color(c.ACCENT if running else c.TEXT_MICRO)
        self.engine_lbl.setText("LIVE" if running else "ENGINE")
        # ABORT is the stop while running; the run button just reports.
        run_text = "RUNNING" if running else _RUN_LABELS.get(self.app._active_mode, "RUN CLICKS")
        if self.loop_btn.text() != run_text:
            self.loop_btn.setText(run_text)
        self.loop_btn.setEnabled(not running)
        self.abort_btn.setEnabled(running)
        self.hold_btn.setEnabled(running)
        hold_text = "RESUME" if (running and c.engine_paused(self.app)) else "HOLD"
        if self.hold_btn.text() != hold_text:
            self.hold_btn.setText(hold_text)
        self._sync_sliders()
        self._sync_click_type()
        self._refresh_capture()


def _fmt_secs(v: float) -> str:
    if v < 1.0:
        return f"{v * 1000:0.0f}MS"
    if v < 10.0:
        return f"{v:0.2f}S"
    return f"{v:0.1f}S"
