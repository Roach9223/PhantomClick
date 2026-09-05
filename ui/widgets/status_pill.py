"""``StatusPill``: rectangular status chip for the topbar.

Layout: ``STATUS  [square dot] VALUE  detail``. The "STATUS" label sits in
TEXT_TERTIARY; the value is lime when running, amber when paused or
starting, TEXT_TERTIARY when idle. The 6 px square dot follows the same
colour. Chip: SURFACE fill, 1 px BORDER, 6 px radius.

``tick()`` is called every frame by the topbar and reads engine state from
``app._state_str`` plus the clicker / bot runner.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from modules.clicker import ClickerPhase, ClickerState

from .. import theme as t
from .status_dot import StatusDot


_INTERESTING_PHASES = frozenset({
    ClickerPhase.HOVERING,
    ClickerPhase.PRE_HOVERING,
    ClickerPhase.WANDERING,
    ClickerPhase.BREAKING,
    ClickerPhase.DISTRACTED,
    ClickerPhase.PAUSING,
    ClickerPhase.SEARCHING,
    ClickerPhase.SKIPPED,
    ClickerPhase.RECOVERING,
    ClickerPhase.KEYPRESS,
})


def _tracked(lbl: QLabel, px: float = 1.0) -> QLabel:
    font = lbl.font()
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, px)
    lbl.setFont(font)
    return lbl


class StatusPill(QFrame):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName("status-pill")
        self.setStyleSheet(
            f"QFrame#status-pill {{"
            f"  background: {t.SURFACE}; "
            f"  border: 1px solid {t.BORDER}; "
            f"  border-radius: {t.RADIUS_PILL}px; "
            f"}}"
            f"QFrame#status-pill QLabel {{ background: transparent; }}"
        )
        self.setMinimumHeight(t.BUTTON_H)

        row = QHBoxLayout(self)
        row.setContentsMargins(t.SP_MD, 0, t.SP_MD, 0)
        row.setSpacing(t.SP_SM)

        self.caption_lbl = _tracked(QLabel("STATUS"), t.LABEL_TRACKING)
        self.caption_lbl.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px; "
            f"font-weight: 600;"
        )
        row.addWidget(self.caption_lbl)

        self.dot = StatusDot(self, size=6)
        row.addWidget(self.dot)

        self.state_lbl = _tracked(QLabel("IDLE"), t.LABEL_TRACKING)
        row.addWidget(self.state_lbl)

        self.detail_lbl = QLabel("Ready to start")
        self.detail_lbl.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px;"
        )
        row.addWidget(self.detail_lbl, 1)
        self._apply_value_color(t.TEXT_TERTIARY)

    def _apply_value_color(self, color: str) -> None:
        self.state_lbl.setStyleSheet(
            f"color: {color}; font-size: {t.SIZE_SM}px; font-weight: 600;"
        )

    # -- Tick -------------------------------------------------------------

    def tick(self) -> None:
        s = self.app._state_str
        paused = self._paused()
        if s == ClickerState.IDLE:
            self.dot.set_state("idle")
            self.state_lbl.setText("IDLE")
            self._apply_value_color(t.TEXT_TERTIARY)
        elif s == ClickerState.STARTING or paused:
            self.dot.set_state("paused")
            self.state_lbl.setText("PAUSED" if paused else "ARMING")
            self._apply_value_color(t.WARN)
        else:
            self.dot.set_state("active")
            self.state_lbl.setText("LIVE")
            self._apply_value_color(t.ACCENT)
        self._refresh_detail(s)

    def _paused(self) -> bool:
        # Bot or click engine; paused still counts as running for the
        # locker, this only picks the amber PAUSED reading.
        from .. import engine_bridge
        return engine_bridge.engine_paused(self.app)

    def _refresh_detail(self, s: str) -> None:
        clicker = self.app.clicker
        if s != ClickerState.IDLE and getattr(self.app, "_bot_running", False) \
                and clicker.state == ClickerState.IDLE:
            self._refresh_bot_detail()
            return
        secs = clicker.seconds_until_next()
        self._refresh_uptime_tooltip(s, clicker)
        if self._paused():
            self.detail_lbl.setText("engine on hold")
            return
        if s == ClickerState.STARTING:
            self.detail_lbl.setText(f"starting in {secs:.1f} s")
            return
        if s == ClickerState.ACTIVE:
            phase = clicker.current_phase
            if phase in _INTERESTING_PHASES:
                label = clicker.phase_label or phase.replace("_", " ").title()
                remaining = clicker.phase_remaining
                if remaining > 0.5:
                    self.detail_lbl.setText(f"{label}  {remaining:0.0f}s left")
                else:
                    self.detail_lbl.setText(label)
                return
            cur, total = clicker.current_step_index
            if total > 0:
                ccur, ctotal = clicker.current_step_clicks
                step_part = (f"  step {cur}/{total}"
                             + (f", click {ccur}/{ctotal}" if ctotal > 1 else ""))
            else:
                step_part = ""
            self.detail_lbl.setText(f"next click in {secs:.1f} s{step_part}")
            return
        self.detail_lbl.setText("Ready to start")

    def _refresh_bot_detail(self) -> None:
        runner = getattr(self.app, "bot_runner", None)
        info: dict = {}
        paused = False
        if runner is not None:
            try:
                info = runner.last_fired() or {}
                paused = bool(runner.is_paused())
            except Exception:
                info = {}
        if paused:
            self.detail_lbl.setText("bot paused, F8 to resume")
            self.setToolTip("")
            return
        tick = int(info.get("current_tick", 0) or 0)
        rule = info.get("last_fired_rule") or ""
        clicks = int(info.get("click_count", 0) or 0)
        parts = [f"bot running, tick {tick}"]
        if rule:
            parts.append(str(rule))
        if clicks:
            parts.append(f"{clicks} clicks")
        self.detail_lbl.setText("  ".join(parts))
        self.setToolTip("")

    def _refresh_uptime_tooltip(self, s, clicker) -> None:
        if s == ClickerState.IDLE:
            self.setToolTip("")
            return
        uptime = float(getattr(clicker, "session_uptime_seconds", 0.0))
        recoveries = int(getattr(clicker, "recovery_count", 0))
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
        rec_part = (f", recovered from {recoveries} transient error"
                    + ("s" if recoveries != 1 else "")
                    if recoveries else "")
        if aborted > 0:
            click_part = f"{clicks} clicks fired / {attempted} attempted ({aborted} aborted by recheck)"
        else:
            click_part = f"{clicks} clicks"
        if clicks >= 5:
            accuracy_part = (f"\nClick accuracy: mean drift {drift_mean:.1f} px"
                             f", max {drift_max:.1f} px"
                             f", {drifted}/{clicks} drifted >2 px")
        else:
            accuracy_part = ""
        self.setToolTip(
            f"Session uptime: {uptime_str}, {click_part}{rec_part}{accuracy_part}"
        )
