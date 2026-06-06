"""HumanizerConfig — single tunable struct that drives every humanize
feature. Loaded from :class:`~PySide6.QtCore.QSettings` in the Studio
and optionally overridden per-task via the Task's ``params`` dict.

The defaults were lifted from the PhantomClick tuning that "feels
organic" in side-by-side A/B tests against raw `pyautogui` + linear
mouse moves.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HumanizerConfig:
    """All humanization tunables in one place.

    Instances are cheap to construct; the Studio keeps one long-lived
    config and passes it to every runtime run.
    """

    # ── master ────────────────────────────────────────────
    enabled: bool = True                   # master toggle; False ⇒ direct click/move
    bezier_fallback: bool = False          # use Bezier instead of Wind/Hooke for A/B tests

    # ── movement ──────────────────────────────────────────
    move_base_s: float = 0.05              # minimum move duration before distance/jitter
    move_max_extra_s: float = 0.15         # ceiling added by long-distance scaling
    move_jitter_lo: float = 0.85           # uniform U(lo, hi) multiplier on duration
    move_jitter_hi: float = 1.15
    step_cadence_lo_s: float = 0.005       # inter-waypoint sleep bounds
    step_cadence_hi_s: float = 0.010
    path_jitter_px: float = 1.5            # ±px wobble during the walk

    # ── overshoot ─────────────────────────────────────────
    overshoot_enabled: bool = True
    overshoot_probability: float = 0.15    # base probability; fatigue boosts it
    overshoot_min_px: float = 3.0
    overshoot_max_px: float = 12.0
    overshoot_pause_lo_s: float = 0.020
    overshoot_pause_hi_s: float = 0.060
    overshoot_correction_scale: float = 0.35  # correction hop takes this × original duration

    # ── click timing ──────────────────────────────────────
    pre_click_pause_lo_s: float = 0.020    # after cursor arrives, before press
    pre_click_pause_hi_s: float = 0.080
    click_hold_lo_s: float = 0.040         # press → release hold duration
    click_hold_hi_s: float = 0.120
    double_click_gap_lo_s: float = 0.040
    double_click_gap_hi_s: float = 0.120

    # ── fatigue ───────────────────────────────────────────
    fatigue_enabled: bool = True
    fatigue_intensity: float = 0.25        # multiplier drift per hour (cap at 1.5×)

    # ── break bursts ──────────────────────────────────────
    break_bursts_enabled: bool = True
    break_min_clicks: int = 40
    break_max_clicks: int = 70
    break_min_duration_s: float = 30.0
    break_max_duration_s: float = 90.0

    # ── click-location anti-clustering ────────────────────
    anti_cluster_enabled: bool = True
    anti_cluster_min_sep_px: float = 18.0  # push new targets apart by at least this
    anti_cluster_history: int = 10         # number of recent click positions to repel from
    anti_cluster_micro_jitter_px: float = 3.0  # ±px nudge applied to every target

    # ── corner failsafe ──────────────────────────────────
    corner_failsafe_enabled: bool = True
    corner_failsafe_margin_px: int = 2     # distance from corner that counts as "hit"

    # ── Studio-only safety ───────────────────────────────
    require_foreground_window: bool = False  # when True, abort if foreground isn't rs3client.exe
    target_window_exe: str = "rs2client.exe"  # RS3 NXT client

    # ────────────────────────────────────────────────────────────
    # Helpers
    # ────────────────────────────────────────────────────────────
    def with_overrides(self, overrides: dict) -> "HumanizerConfig":
        """Return a new config with ``overrides`` merged in.

        Unknown keys are ignored so per-task ``params`` dicts can
        include non-humanizer entries without raising.
        """
        import dataclasses
        kwargs = dataclasses.asdict(self)
        for k, v in (overrides or {}).items():
            if k in kwargs:
                kwargs[k] = v
        return HumanizerConfig(**kwargs)
