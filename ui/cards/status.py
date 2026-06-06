"""Status card — readiness summary + engine state + countdown + live phase.

Top-most card. Four lines:
- Animated colored dot + state word (IDLE / STARTING / ACTIVE)
- Mode-aware zone summary ("Sequence mode · ready · 2/2 click + 1 track")
- Countdown to next click (or step progress in recorder mode)
- Live activity phase (e.g. "Now: Step 2 'Drop logs' · TRACK — moving to
  target") — this is critical for distinguishing "engine is on a break"
  from "engine is searching for a target" from "engine is mid-click."

The dot uses a real color animation via :class:`StatusDot` so transitions
read as motion, not a discrete jump. All four lines refresh every 100 ms
from :meth:`tick`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from modules.clicker import ClickerPhase, ClickerState
from modules.recorder import KIND_CLICK, KIND_COLOR, KIND_LOOP, KIND_PAUSE, KIND_TRACK

from .. import theme as t
from ..widgets.card import Card
from ..widgets.status_dot import StatusDot


class StatusCard(Card):
    def __init__(self, app):
        super().__init__("◉  Status")
        self.app = app

        # Top row: dot + state word
        row = QHBoxLayout()
        row.setSpacing(t.SP_SM)
        self.dot = StatusDot(self)
        self.state_label = QLabel("IDLE")
        self.state_label.setProperty("role", "value")
        self.state_label.setStyleSheet(
            f"font-family: {t.FONT_DISPLAY}; font-size: {t.SIZE_VALUE}px; "
            f"font-weight: 700; letter-spacing: 1.2px;"
        )
        row.addWidget(self.dot)
        row.addWidget(self.state_label)
        row.addStretch(1)
        self.body_layout().addLayout(row)

        # Zone summary
        self.zone_summary = QLabel("")
        self.zone_summary.setWordWrap(True)
        self.zone_summary.setProperty("role", "secondary")
        self.zone_summary.setStyleSheet(f"color: {t.TEXT_SECONDARY};")
        self.body_layout().addWidget(self.zone_summary)

        # Countdown line
        self.countdown_label = QLabel("Next click in: —")
        self.countdown_label.setWordWrap(True)
        self.countdown_label.setStyleSheet(f"color: {t.TEXT_SECONDARY};")
        self.body_layout().addWidget(self.countdown_label)

        # Live phase line — what the engine is doing *right now*. Empty
        # while idle so the card doesn't show stale information.
        self.phase_label = QLabel("")
        self.phase_label.setWordWrap(True)
        self.phase_label.setStyleSheet(
            f"color: {t.ACCENT}; font-style: italic;"
        )
        self.body_layout().addWidget(self.phase_label)

    # -- Per-tick refresh ---------------------------------------------------

    def tick(self) -> None:
        s = self.app._state_str
        if s == ClickerState.IDLE:
            self.dot.set_state("idle")
            self.state_label.setText("IDLE")
        elif s == ClickerState.STARTING:
            self.dot.set_state("starting")
            self.state_label.setText("STARTING")
        else:
            self.dot.set_state("active")
            self.state_label.setText("ACTIVE")

        self._refresh_countdown(s)
        self._refresh_zone_summary()
        self._refresh_phase(s)

    # Phase → display word table. Defined as a class attr so the lookup
    # avoids rebuilding every tick, and so a future feature (e.g. tinted
    # background per phase) can read straight from the same map.
    _PHASE_PREFIX = {
        ClickerPhase.WAITING: "Waiting",
        ClickerPhase.MOVING: "Moving",
        ClickerPhase.CLICKING: "Clicking",
        ClickerPhase.HOVERING: "Hovering",
        ClickerPhase.PRE_HOVERING: "Pre-hovering",
        ClickerPhase.WANDERING: "Wandering",
        ClickerPhase.BREAKING: "On break",
        ClickerPhase.DISTRACTED: "Distracted",
        ClickerPhase.PAUSING: "Pausing",
        ClickerPhase.SEARCHING: "Searching",
        ClickerPhase.SKIPPED: "Skipped",
        ClickerPhase.POST_CLICK: "Post-click drift",
        ClickerPhase.STARTING: "Pre-start",
    }

    def _refresh_phase(self, s: str) -> None:
        if s == ClickerState.IDLE:
            self.phase_label.setText("")
            return
        clicker = self.app.clicker
        phase = clicker.current_phase
        # The engine sets a label that already includes the step
        # ("Step 2 'Drop logs' · TRACK — searching"). Prefer it; fall
        # back to the phase-name table when the engine's label is empty
        # (e.g. legacy code paths we haven't wired yet).
        label = clicker.phase_label or self._PHASE_PREFIX.get(phase, "")
        if not label:
            self.phase_label.setText("")
            return
        remaining = clicker.phase_remaining
        if remaining > 0.5:
            label = f"{label}  ·  {remaining:0.0f}s left"
        self.phase_label.setText(f"Now: {label}")

    def _refresh_countdown(self, s: str) -> None:
        secs = self.app.clicker.seconds_until_next()
        cur, total = self.app.clicker.current_step_index
        ccur, ctotal = self.app.clicker.current_step_clicks
        if total > 0:
            click_part = f", click {ccur}/{ctotal}" if ctotal > 1 else ""
            step_str = f"   ·   Step {cur}/{total}{click_part}"
        else:
            step_str = ""
        if s == ClickerState.STARTING:
            self.countdown_label.setText(f"Starting in: {secs:4.1f}s")
        elif s == ClickerState.ACTIVE:
            self.countdown_label.setText(f"Next click in: {secs:4.1f}s{step_str}")
        else:
            self.countdown_label.setText("Next click in: —")

    def _refresh_zone_summary(self) -> None:
        app = self.app
        if app._active_mode == "recorder":
            steps = app._steps
            click_steps = [s for s in steps if s.kind == KIND_CLICK]
            track_steps = [s for s in steps if s.kind == KIND_TRACK]
            color_steps = [s for s in steps if s.kind == KIND_COLOR]
            pause_count = sum(1 for s in steps if s.kind == KIND_PAUSE)
            loop_count = sum(1 for s in steps if s.kind == KIND_LOOP)
            valid_clicks = sum(1 for s in click_steps if s.zone is not None)
            valid_tracks = sum(1 for s in track_steps if s.template_path)
            valid_colors = sum(1 for s in color_steps if s.color_target_rgb is not None)
            total = len(steps)
            if total == 0:
                self.zone_summary.setText(
                    "Sequence mode · No clicks yet — open the Record tab and add one")
                self.zone_summary.setStyleSheet(f"color: {t.WARN};")
            elif valid_clicks + valid_tracks + valid_colors == 0:
                self.zone_summary.setText(
                    f"Sequence mode · {total} step(s) — pick a target / click area for at least one")
                self.zone_summary.setStyleSheet(f"color: {t.WARN};")
            else:
                parts: list[str] = []
                if click_steps:
                    parts.append(f"{valid_clicks}/{len(click_steps)} click")
                if track_steps:
                    parts.append(f"{valid_tracks}/{len(track_steps)} track")
                if color_steps:
                    parts.append(f"{valid_colors}/{len(color_steps)} color")
                if pause_count:
                    parts.append(f"{pause_count} pause")
                if loop_count:
                    parts.append(f"{loop_count} loop")
                self.zone_summary.setText("Sequence mode · ready · " + " + ".join(parts))
                self.zone_summary.setStyleSheet(f"color: {t.TEXT_SECONDARY};")
        else:
            if app._zone is None:
                self.zone_summary.setText(
                    "One-zone mode · Pick a click area first")
                self.zone_summary.setStyleSheet(f"color: {t.WARN};")
            else:
                z = app._zone
                if z.shape == "rect":
                    x1, y1, x2, y2 = z.rect
                    txt = f"One-zone mode · ready · {x2-x1}×{y2-y1} at ({x1},{y1})"
                elif z.shape == "circle":
                    cx, cy, r = z.circle
                    txt = f"One-zone mode · ready · circle r={r} at ({cx},{cy})"
                else:
                    txt = f"One-zone mode · ready · custom polygon ({len(z.vertices)} corners)"
                self.zone_summary.setText(txt)
                self.zone_summary.setStyleSheet(f"color: {t.TEXT_SECONDARY};")
