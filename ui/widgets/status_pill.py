"""``StatusPill`` — compact horizontal status display for the topbar.

The 2026 redesign drops the verbose "zone summary" middle text in favor of a
clean three-token line: ``● state · countdown``. The countdown text doubles
as the static "Ready to start" hint when idle, so the eye always sees
something useful where the time-to-next normally lives.

Tick logic mirrors :class:`StatusCard` because both compute the same fields
from ``app._state_str`` + engine state. Duplication is intentional: extracting
the helpers added more friction than it saved.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from modules.clicker import ClickerPhase, ClickerState

from .. import theme as t
from .status_dot import StatusDot


# Phases worth surfacing in the topbar — the rest fall through to the
# plain countdown so we don't flicker the detail line on every tick.
# Includes anything the user *might* mistake for a stalled engine
# (hover / break / searching / skipped / distracted / pausing).
_INTERESTING_PHASES = frozenset({
    ClickerPhase.HOVERING,
    ClickerPhase.PRE_HOVERING,
    ClickerPhase.WANDERING,
    ClickerPhase.BREAKING,
    ClickerPhase.DISTRACTED,
    ClickerPhase.PAUSING,
    ClickerPhase.SEARCHING,
    ClickerPhase.SKIPPED,
    # RECOVERING is critical: when the engine retries past a transient
    # error, the user needs to see "yes, the engine noticed and is
    # recovering" rather than a silent stall.
    ClickerPhase.RECOVERING,
    # KEYPRESS is brief but important — without it, KEY steps look
    # identical to silent skips (no cursor motion, no click counter
    # change). Showing "Step N · KEY — pressing 'ctrl+x'" confirms the
    # step is firing.
    ClickerPhase.KEYPRESS,
})


class StatusPill(QFrame):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName("status-pill")

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(t.SP_SM)

        self.dot = StatusDot(self)
        row.addWidget(self.dot)

        self.state_lbl = QLabel("Idle")
        self.state_lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; font-size: {t.SIZE_BODY}px; "
            f"font-weight: 500;"
        )
        row.addWidget(self.state_lbl)

        self._sep = QLabel("·")
        self._sep.setStyleSheet(f"color: {t.TEXT_TERTIARY};")
        row.addWidget(self._sep)

        self.detail_lbl = QLabel("Ready to start")
        self.detail_lbl.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px;"
        )
        row.addWidget(self.detail_lbl, 1)

    # -- Tick -------------------------------------------------------------

    def tick(self) -> None:
        s = self.app._state_str
        if s == ClickerState.IDLE:
            self.dot.set_state("idle")
            self.state_lbl.setText("Idle")
        elif s == ClickerState.STARTING:
            self.dot.set_state("starting")
            self.state_lbl.setText("Starting")
        else:
            self.dot.set_state("active")
            self.state_lbl.setText("Active")
        self._refresh_detail(s)

    def _refresh_detail(self, s: str) -> None:
        clicker = self.app.clicker
        secs = clicker.seconds_until_next()
        # Tooltip surfaces session uptime + recovery count so a user
        # running an unattended 8-10 hour session can hover the status
        # pill and confirm "yes, still running, recovered from 2
        # transient errors." Cheap to compute every tick.
        self._refresh_uptime_tooltip(s, clicker)
        if s == ClickerState.STARTING:
            self.detail_lbl.setText(f"Starting in {secs:.1f} s")
            return
        if s == ClickerState.ACTIVE:
            # When the engine is in a phase the user might mistake for
            # a stall (hover, break, searching, paused step, etc.),
            # surface that phase verbatim so they can see why nothing
            # is being clicked. Boring phases (waiting / moving /
            # clicking) fall through to the plain countdown — those
            # update too fast to be useful as text.
            phase = clicker.current_phase
            if phase in _INTERESTING_PHASES:
                label = clicker.phase_label or phase.replace("_", " ").title()
                remaining = clicker.phase_remaining
                if remaining > 0.5:
                    self.detail_lbl.setText(f"{label}  ·  {remaining:0.0f}s left")
                else:
                    self.detail_lbl.setText(label)
                return
            # Recorder mode: include the step number / total in the
            # countdown so the user can see progress through the
            # sequence at a glance (was previously hidden behind the
            # full Status card, which is no longer in the topbar).
            cur, total = clicker.current_step_index
            if total > 0:
                ccur, ctotal = clicker.current_step_clicks
                step_part = (f"  ·  Step {cur}/{total}"
                             + (f", click {ccur}/{ctotal}" if ctotal > 1 else ""))
            else:
                step_part = ""
            self.detail_lbl.setText(
                f"Next click in {secs:.1f} s{step_part}"
            )
            return
        self.detail_lbl.setText("Ready to start")

    def _refresh_uptime_tooltip(self, s, clicker) -> None:
        if s == ClickerState.IDLE:
            self.setToolTip("")
            return
        uptime = float(getattr(clicker, "session_uptime_seconds", 0.0))
        recoveries = int(getattr(clicker, "recovery_count", 0))
        # Format uptime as HhMm or MmSs depending on magnitude — readable
        # at the durations users actually care about (multi-hour runs).
        if uptime >= 3600:
            h = int(uptime // 3600)
            m = int((uptime % 3600) // 60)
            uptime_str = f"{h}h {m:02d}m"
        elif uptime >= 60:
            m = int(uptime // 60)
            sec = int(uptime % 60)
            uptime_str = f"{m}m {sec:02d}s"
        else:
            uptime_str = f"{int(uptime)}s"
        clicks = int(getattr(clicker, "_session_clicks", 0))
        attempted = int(getattr(clicker, "clicks_attempted", 0))
        aborted = int(getattr(clicker, "cycles_aborted", 0))
        drifted = int(getattr(clicker, "clicks_with_drift", 0))
        drift_mean = float(getattr(clicker, "click_drift_mean_px", 0.0))
        drift_max = float(getattr(clicker, "click_drift_max_px", 0.0))
        rec_part = (f" · recovered from {recoveries} transient error"
                    + ("s" if recoveries != 1 else "")
                    if recoveries else "")
        # Show the abort gap only when it's non-zero — most users won't
        # care, but for a "missing 2nd click" report this is the
        # smoking gun. Shows "fired/attempted (N aborted by recheck)".
        if aborted > 0:
            click_part = f"{clicks} clicks fired / {attempted} attempted ({aborted} aborted by recheck)"
        else:
            click_part = f"{clicks} clicks"
        # Click accuracy line — only meaningful after a few clicks land
        # so we suppress noise under 5 clicks. ">2px drift" counts how
        # many clicks landed off where we aimed; mean drift is how far
        # off on average. If the user reports "missed clicks" and these
        # numbers are both ~0, the issue is game-side, not engine-side.
        if clicks >= 5:
            accuracy_part = (f"\nClick accuracy: mean drift {drift_mean:.1f} px"
                             f" · max {drift_max:.1f} px"
                             f" · {drifted}/{clicks} drifted >2 px")
        else:
            accuracy_part = ""
        self.setToolTip(
            f"Session uptime: {uptime_str} · {click_part}{rec_part}{accuracy_part}"
        )
