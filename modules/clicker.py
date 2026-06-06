"""Click engine. Runs in a dedicated thread; all waits are interruptible.

Features per plan:
  - Pre-start grace delay (Start -> wait -> first click) so the user can alt-tab.
  - Gaussian-biased random target via zone.random_point().
  - Anti-clustering: keep last 10 click positions; repel new target away from them.
  - Exact-repeat prevention (last position equality).
  - ±1-3 px micro-jitter on top.
  - Humanizer does the actual physical move + click (Wind/Hooke + overshoot).
  - Fatigue + break bursts.
  - Corner failsafe: separate watchdog thread stops the engine if cursor hits
    any screen corner.
  - Optional idle-wander drifts during the inter-click wait.
"""

from __future__ import annotations

import math
import random
import threading
import time
from collections import deque
from typing import Callable, Optional

from pynput import keyboard
from pynput.mouse import Controller

from utils import dpi_cursor, humanizer, idle_wanderer, mouse_trace
from utils.fatigue import Fatigue
from utils.logger import get_logger
from .key_timer import KeyTimer, fire as fire_combo, parse_combo, run_timer_loop
from .recorder import (
    KIND_CLICK, KIND_KEY, KIND_PAUSE, KIND_TRACK, KIND_LOOP, KIND_COLOR,
    RecorderStep,
)
from .stats import Stats
from .tracker import TemplateTracker
from .zone_selector import Zone

_mouse = Controller()


class ClickerState:
    IDLE = "idle"
    STARTING = "starting"
    ACTIVE = "active"


_TRANSIENT_ERRORS: tuple = (OSError,)
try:
    import mss.exception as _mss_exc
    _TRANSIENT_ERRORS = _TRANSIENT_ERRORS + (_mss_exc.ScreenShotError,)
except Exception:
    pass
try:
    import cv2 as _cv2_for_err
    # cv2.error inherits from Exception, not OSError, so we add it
    # explicitly. Transient cv2 errors typically come from a bad screen
    # grab feeding matchTemplate — recoverable on the next cycle.
    _TRANSIENT_ERRORS = _TRANSIENT_ERRORS + (_cv2_for_err.error,)
except Exception:
    pass


class ClickerPhase:
    """Fine-grained activity tracking surfaced live to the UI.

    ClickerState says "is the engine running"; ClickerPhase says "what is
    it doing right now" — moving, clicking, hovering, on a break, waiting
    for a tracked target to reappear, etc. Without this the user can't
    tell whether a 30-second pause is a scheduled break, a long pause
    step, or a stalled track step. Strings (not Enum) so JSON traces and
    UI labels can use the same values without coercion.
    """
    IDLE = "idle"
    STARTING = "starting"
    WAITING = "waiting"            # in inter-click delay, no detour active
    MOVING = "moving"              # cursor traveling to a click target
    CLICKING = "clicking"          # mouse button press (very brief)
    HOVERING = "hovering"          # visiting a hover zone (no click)
    PRE_HOVERING = "pre_hovering"  # drifting partway toward the next zone
    WANDERING = "wandering"        # idle wander between clicks
    BREAKING = "breaking"          # scheduled break burst sleep
    DISTRACTED = "distracted"      # "looked away" distraction spike
    PAUSING = "pausing"            # KIND_PAUSE step
    SEARCHING = "searching"        # track/color step waiting for target
    SKIPPED = "skipped"            # cycle aborted by recheck-before-click
    POST_CLICK = "post_click"      # post-click micro-wander
    KEYPRESS = "keypress"          # KIND_KEY step firing a key combo
    RECOVERING = "recovering"      # transient error retry-with-backoff


class Clicker:
    def __init__(self, stats: Stats, on_state_change: Optional[Callable[[str], None]] = None):
        self.stats = stats
        self.on_state_change = on_state_change
        # Live activity indicator — see ClickerPhase. The UI polls
        # current_phase / phase_label / phase_remaining each tick. We use
        # plain string fields (no callback fan-out) because the Status
        # card already polls every 100 ms; pushing on-change adds thread
        # safety burden for no benefit.
        self._phase: str = ClickerPhase.IDLE
        self._phase_label: str = ""
        self._phase_until: float = 0.0
        # Debug hook: called from the engine thread on every successful click
        # with (target_x, target_y, actual_x, actual_y). target = what the
        # engine asked humanizer to land on; actual = mouse position right
        # after the click fired. App registers a callback to draw an on-
        # screen marker for each click so the user can diagnose accuracy.
        self.on_click_fired: Optional[Callable[[int, int, int, int, str], None]] = None
        # Engine-thread event hooks for UX surfaces. Bridge marshals these
        # back to the Qt main thread and the App turns them into toasts.
        # `on_track_error(step_id, reason)` fires when a track step's primary
        # template can't be loaded; cooldown-throttled so a persistently
        # broken step doesn't spam toasts.
        # `on_session_complete(reason)` fires when stop-after limits hit.
        # `on_engine_halt(msg, level)` surfaces every other reason the
        # engine stops or stalls (level: "error" | "warn" | "info") so
        # the user never sees a silent halt.
        self.on_track_error: Optional[Callable[[str, str], None]] = None
        self.on_session_complete: Optional[Callable[[str], None]] = None
        self.on_engine_halt: Optional[Callable[[str, str], None]] = None
        self.log = get_logger()

        # Live config (mutable from GUI thread).
        self.zone: Optional[Zone] = None
        self.min_delay: float = 5.0
        self.max_delay: float = 20.0
        self.click_type: str = "left"
        self.click_mode: str = "single"
        self.prestart_delay: float = 2.5
        self.idle_wander_enabled: bool = False
        self.idle_wander_frequency: float = 0.3
        self.idle_wander_padding: int = 200
        self.fatigue_enabled: bool = True
        self.fatigue_intensity: float = 0.25
        self.break_bursts_enabled: bool = True
        self.break_min_clicks: int = 40
        self.break_max_clicks: int = 70
        self.break_min_duration: float = 30.0
        self.break_max_duration: float = 90.0
        self.overshoot_enabled: bool = True
        self.overshoot_probability: float = 0.15
        self.anti_cluster_enabled: bool = True
        self.anti_cluster_radius: float = 18.0
        self.idle_wander_whole_screen: bool = False
        # Stop-after limits. Both gates default off; when on, the matching
        # threshold ends the session cleanly via on_session_complete().
        self.stop_after_clicks_enabled: bool = False
        self.stop_after_clicks: int = 1000
        self.stop_after_minutes_enabled: bool = False
        self.stop_after_minutes: int = 60
        # (x, y, w, h) of the monitor the engine should treat as "the
        # screen" for ambient features. Pushed by the bridge from
        # App.target_screen_bounds(), which resolves cfg["target_monitor"].
        # Defaults to a sentinel that means "use primary monitor via
        # GetSystemMetrics" — so legacy / pre-bridge callers behave as
        # they did before the multi-monitor selector existed.
        self.target_screen_bounds: tuple[int, int, int, int] = (0, 0, 0, 0)

        # Hover zones: periodically moves cursor into one and dwells, no click.
        # Backward-compat single zone retained but multi-zone list takes priority.
        self.hover_zone = None
        self.hover_zones: list[Zone] = []
        self.hover_selection: str = "random"   # "random" | "order"
        self.hover_enabled: bool = True
        self.hover_frequency: float = 0.15  # probability per wait-tick
        self.hover_dwell_min: float = 1.0
        self.hover_dwell_max: float = 4.0

        # Recorder mode: ordered sequence of steps cycled forever.
        # Track is a step kind (KIND_TRACK) inside Recorder, not a mode.
        self.mode: str = "clicker"             # "clicker" | "recorder"
        self.recorder_steps: list[RecorderStep] = []
        self.tracker: Optional[TemplateTracker] = None
        # Tracks which KIND_TRACK step's template is currently loaded into
        # self.tracker so we don't re-imread on every loop tick.
        self._active_track_step_id: Optional[str] = None
        # Cooldown maps for step-level announcements. Each value is the
        # monotonic time of the last toast; a 30 s cooldown applies before
        # the same step re-fires. Cleared on session start; entries get
        # discarded when the corresponding step recovers (e.g. tracker
        # locks again, color matches again, recapture succeeds).
        self._track_error_last_at: dict[str, float] = {}
        self._color_no_match_last_at: dict[str, float] = {}
        self._loop_orphan_last_at: dict[str, float] = {}
        self._step_skip_last_at: dict[str, float] = {}
        self._step_timeout_last_at: dict[str, float] = {}
        # Per-step "stuck since" timestamps. Used by the cycle loop to
        # decide when to surface a "still searching" toast (~10 s after
        # the last successful match).
        self._track_stuck_since: dict[str, float] = {}
        self._color_no_match_since: dict[str, float] = {}
        # Per-step "target was present last cycle" flag used to detect
        # the no-target → target transition. On that transition we wait
        # a randomized "see → decide → move" reaction delay before the
        # cursor starts moving. Once clicking the same locked target
        # repeatedly, subsequent cycles skip the delay (humans don't
        # re-react when the target hasn't changed). Cleared on step
        # advance so re-entry via a loop counts as a fresh reaction.
        self._step_target_present: dict[str, bool] = {}
        # Last successful click position per KIND_COLOR step. Used by
        # _find_color_target to prefer the matching pixel closest to
        # the prior click — stabilizes click position on buttons with
        # antialiased edges / hover glows where many pixels match the
        # picked color. Without this anchor, the engine would pick a
        # random match per cycle and clicks would scatter across the
        # match cluster instead of settling on a consistent center.
        self._color_last_click_pos: dict[str, tuple[int, int]] = {}

        # Single dial that all four "human realism" features read from. The
        # GUI's Realism slider pushes this directly so the engine doesn't have
        # to know about the per-feature derivation.
        self.realism: float = 0.5

        self._state: str = ClickerState.IDLE
        self._step_idx: int = 0
        self._step_clicks_done: int = 0
        # Per-run iteration counter for KIND_LOOP. Keyed by step.step_id so
        # the count survives in-list reordering. Reset on each start().
        self._loop_iterations_remaining: dict[str, int] = {}
        self._hover_idx: int = 0
        self._clicks_since_distraction: int = 0
        self._next_distraction_at: int = random.randint(60, 180)
        # Last micro-jitter timestamp + the minimum gap until the next
        # one is allowed. Sampled fresh each fire so the cadence is
        # irregular (real human idle isn't periodic). Initial 0 means
        # the first jitter can fire as soon as its probability gate
        # passes — no startup suppression.
        self._last_micro_jitter_at: float = 0.0
        self._next_micro_jitter_min_gap: float = 0.0
        self._thread: Optional[threading.Thread] = None
        self._stop: threading.Event = threading.Event()
        self._watchdog_stop: threading.Event = threading.Event()
        self._watchdog_thread: Optional[threading.Thread] = None
        self._next_click_at: float = 0.0
        self._prestart_ends_at: float = 0.0
        self._recent: deque[tuple[int, int]] = deque(maxlen=10)
        # Per-zone non-stationary sampling state. Keyed by zone identity:
        # "clicker" for the single zone, step.step_id for recorder steps,
        # f"track:{step_id}" for live tracker zones (which are reconstructed
        # each cycle, so the drift state has to live outside the Zone).
        # Value: dict with "off_x", "off_y", "heading", "sigma_scale".
        self._zone_drift_state: dict[str, dict] = {}
        # Session-scoped counters for stop-after limits.
        self._session_start: float = 0.0
        self._session_clicks: int = 0
        # Counts how many times the engine resilience layer has retried
        # past a transient error this session. Surfaced to the UI so the
        # user can see "running 6h, recovered from 2 transient errors"
        # without digging through logs.
        self._recovery_count: int = 0
        # Click diagnostics — the gap between attempted and fired
        # ("how many cycles set up to click but didn't") tells a user
        # reporting "missing 2nd click" whether the click was rejected
        # by a recheck (track moved, color vanished, weak match) or
        # actually fired but the OS / game window dropped it.
        # Attempts increments at the start of every cycle that's about
        # to click; fires increments after humanizer.click() returns
        # cleanly. The delta = aborted-by-recheck cycles.
        self._clicks_attempted: int = 0
        self._cycles_aborted: int = 0
        # Per-click drift accounting — distance between the intended
        # target and where the cursor actually was when the press
        # fired. When this is > a few px, something is moving the
        # cursor between humanizer.move() and humanizer.click()
        # (Windows snap, anti-cheat hook, etc.) and the click won't
        # land where the user expected.
        self._clicks_with_drift: int = 0
        self._click_drift_total_px: float = 0.0
        self._click_drift_max_px: float = 0.0
        # Persistent mss handle for color-step scans. Created lazily on the
        # engine thread (mss instances aren't thread-safe), torn down in
        # stop(). Reusing one across cycles avoids per-call DC handshake.
        self._mss_engine = None
        # Lazy keyboard controller for KIND_KEY steps. Created on first use
        # (engine thread) and reused for the rest of the session — pynput
        # Controllers are cheap but no point re-allocating per fire.
        self._key_controller: Optional[keyboard.Controller] = None

        # Passive concurrent keypresses ("press Z every 6 min for the
        # potion macro"). Each enabled timer gets its own daemon thread
        # spawned on start() and reaped via self._stop on stop().
        self.key_timers: list[KeyTimer] = []
        # (KeyTimer, Thread) pairs so the health watchdog can identify
        # dead timers and respawn them with the original config.
        self._key_timer_threads: list[tuple[KeyTimer, threading.Thread]] = []
        # Throttle for the timer health check — runs at most every 30 s so
        # it doesn't add noticeable overhead per cycle.
        self._last_timer_health_check: float = 0.0
        # Global jitter toggle for key timers. When enabled (default), each
        # timer's wait is multiplied by a small random factor so equal
        # min/max values don't produce exact-periodic fires (which RS-style
        # bot detection flags). The percentage is hardcoded at 10% — a
        # sensible default that doesn't drift the user's intended timing
        # noticeably while breaking the periodic signature.
        self.key_timer_jitter_enabled: bool = True
        # Which keyboard-event backend to use for KIND_KEY steps + key
        # timers. ``"auto"`` picks Interception when the driver+wrapper
        # are both available, else SendInput. ``"sendinput"`` forces
        # the standard path; ``"interception"`` forces hardware mode
        # (errors clearly when not installed). Pushed by the App from
        # cfg["key_input_method"] before start().
        self.key_input_method: str = "auto"
        # COM port for the Serial HID backend (Arduino bridge). Empty
        # until the user picks one; the SerialHidBackend surfaces a
        # clear ``_init_error`` if the engine starts without one set.
        self.serial_hid_port: str = ""

    # -- public API ---------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    def seconds_until_next(self) -> float:
        if self._state == ClickerState.STARTING:
            return max(0.0, self._prestart_ends_at - time.monotonic())
        if self._state == ClickerState.ACTIVE:
            return max(0.0, self._next_click_at - time.monotonic())
        return 0.0

    def start(self) -> None:
        if self._state != ClickerState.IDLE:
            return
        # Mode-aware safety: clicker needs a zone; recorder needs at least
        # one CLICK or TRACK step that's actually usable (zone or template).
        if self.mode == "recorder":
            has_runnable_step = any(
                (s.kind == KIND_CLICK and s.zone is not None)
                or (s.kind == KIND_TRACK and s.template_path)
                or (s.kind == KIND_COLOR and s.color_target_rgb is not None)
                or (s.kind == KIND_KEY and s.key_combo
                    and parse_combo(s.key_combo) is not None)
                for s in self.recorder_steps
            )
            if not has_runnable_step:
                self._announce_engine_halt(
                    "Sequence has no runnable steps — capture a target, "
                    "pick a click area, or pick a color, then try again.",
                    "warn",
                )
                return
        else:
            if self.zone is None:
                self._announce_engine_halt(
                    "Click mode has no zone — draw one in the Click Zone "
                    "card before starting.",
                    "warn",
                )
                return
        self._stop.clear()
        # Push the active monitor rect into humanizer so every walked +
        # planned cursor position stays clear of the watchdog's 2-px
        # corner zone. Re-pushed per watchdog tick so monitor changes
        # mid-run update the safe rect.
        humanizer.set_safe_bounds(self._resolve_screen_bounds())
        self._recent.clear()
        self._step_idx = 0
        self._step_clicks_done = 0
        self._loop_iterations_remaining = {}
        self._hover_idx = 0
        self._clicks_since_distraction = 0
        self._next_distraction_at = random.randint(60, 180)
        self._last_micro_jitter_at = 0.0
        self._next_micro_jitter_min_gap = 0.0
        self._zone_drift_state = {}
        self._session_start = time.monotonic()
        self._session_clicks = 0
        self._recovery_count = 0
        self._clicks_attempted = 0
        self._cycles_aborted = 0
        self._clicks_with_drift = 0
        self._click_drift_total_px = 0.0
        self._click_drift_max_px = 0.0
        self._track_error_last_at = {}
        self._color_no_match_last_at = {}
        self._loop_orphan_last_at = {}
        self._step_skip_last_at = {}
        self._step_timeout_last_at = {}
        self._track_stuck_since = {}
        self._color_no_match_since = {}
        self._step_target_present = {}
        self._color_last_click_pos = {}
        self.stats.reset()
        # Pick + push the active key backend so the very first KIND_KEY
        # step (and any concurrent key timers) use the configured path.
        # Logged below so a post-mortem of any session shows whether
        # SendInput / Interception / Serial HID was active.
        from . import key_input_backend
        from . import key_timer
        key_backend = key_input_backend.get_backend(
            self.key_input_method,
            serial_port=getattr(self, "serial_hid_port", "") or "",
        )
        key_timer.set_backend(key_backend)
        mouse_trace.event(
            "engine_start",
            mode=self.mode,
            realism=round(self.realism, 3),
            min_d=self.min_delay, max_d=self.max_delay,
            target=list(self.target_screen_bounds),
        )
        # Structured log so a session post-mortem can see the exact step
        # list the engine was given. Critical for debugging "step skipped"
        # reports — proves whether key_combo / template_path / etc. arrived.
        self.log.info(
            "engine_start mode=%s steps=%d realism=%.2f key_method=%s key_backend=%s%s",
            self.mode, len(self.recorder_steps), self.realism,
            self.key_input_method,
            getattr(key_backend, "name", "?"),
            "" if getattr(key_backend, "available", True)
            else f" (UNAVAILABLE: {getattr(key_backend, '_init_error', '')})",
        )
        if self.mode == "recorder":
            for i, s in enumerate(self.recorder_steps):
                self.log.info(
                    "  step[%d] kind=%s id=%s combo=%r zone=%s template=%s color=%s",
                    i, s.kind, s.step_id,
                    s.key_combo if s.kind == KIND_KEY else None,
                    "set" if s.zone is not None else None,
                    s.template_path if s.kind == KIND_TRACK else None,
                    s.color_target_rgb if s.kind == KIND_COLOR else None,
                )
        self._set_state(ClickerState.STARTING)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._start_watchdog()
        self._start_key_timers()
        # Tracker loop is owned by the App (so the user gets a live preview
        # overlay even while idle); we just read tracker.state in _tracker_zone().

    def _start_key_timers(self) -> None:
        """Spawn one daemon thread per enabled, parseable key timer.
        Each thread fires the configured combo on its own clock until
        ``self._stop`` is set. Safe to call when ``self.key_timers`` is
        empty — it's a no-op."""
        self._key_timer_threads = []
        if not self.key_timers:
            return
        # Snapshot to avoid races with the GUI thread mutating the list
        # mid-start.
        timers_snapshot = [
            KeyTimer(
                key=t.key, interval_min=t.interval_min,
                interval_max=t.interval_max, enabled=t.enabled,
            )
            for t in self.key_timers
        ]
        for t in timers_snapshot:
            if not t.enabled or not t.key:
                continue
            th = self._spawn_one_timer_thread(t)
            self._key_timer_threads.append((t, th))

    def _spawn_one_timer_thread(self, t: KeyTimer) -> threading.Thread:
        """Build + start a daemon thread that drives one ``KeyTimer``.
        Factored out of ``_spawn_key_timer_threads`` so the health
        watchdog can respawn an individual timer without rebuilding the
        whole list."""
        th = threading.Thread(
            target=run_timer_loop,
            args=(t, self._stop),
            kwargs={
                "jitter_enabled": bool(self.key_timer_jitter_enabled),
                "jitter_pct": 0.10,
            },
            daemon=True,
        )
        th.start()
        return th

    def _check_key_timer_health(self) -> None:
        """Walk the timer-thread list and respawn any that have died.

        For 8-10 hour sessions this matters: a transient exception
        inside ``run_timer_loop`` (e.g. ``fire()`` raising on a bad VK
        resolution after a layout change) silently kills the thread,
        and the user later notices their potion macro stopped firing
        without any toast or log line.

        Throttled to once per 30 s so we don't churn ``is_alive()``
        calls every cycle (~600/hr); a dead timer noticed 30 s late is
        still recovered before the next planned fire on most schedules.
        """
        if not self._key_timer_threads:
            return
        now = time.monotonic()
        if now - self._last_timer_health_check < 30.0:
            return
        self._last_timer_health_check = now
        new_pairs: list[tuple[KeyTimer, threading.Thread]] = []
        for t, th in self._key_timer_threads:
            if th.is_alive():
                new_pairs.append((t, th))
                continue
            if self._stop.is_set():
                # Engine is shutting down; let dead threads stay dead.
                continue
            self.log.warning(
                "key timer thread for combo=%r died; respawning",
                t.key,
            )
            try:
                fresh = self._spawn_one_timer_thread(t)
                new_pairs.append((t, fresh))
            except Exception as e:
                self.log.exception(
                    "failed to respawn key timer combo=%r: %s",
                    t.key, e,
                )
        self._key_timer_threads = new_pairs

    @property
    def current_step_index(self) -> tuple[int, int]:
        """(1-based current step, total steps). 0/0 when not in recorder mode."""
        if self.mode != "recorder" or not self.recorder_steps:
            return (0, 0)
        return (self._step_idx + 1, len(self.recorder_steps))

    @property
    def current_step_clicks(self) -> tuple[int, int]:
        """(clicks-done-so-far + 1 = current click number, total for this step).
        0/0 outside recorder mode, when no step is current, or when the
        current step is a pause (no click counter to show)."""
        if self.mode != "recorder" or not self.recorder_steps:
            return (0, 0)
        if self._step_idx >= len(self.recorder_steps):
            return (0, 0)
        step = self.recorder_steps[self._step_idx]
        if step.kind in (KIND_PAUSE, KIND_LOOP, KIND_KEY):
            return (0, 0)
        total = max(1, int(step.click_count))
        # Show the click that's about to fire (or just fired) — clamp to total.
        cur = min(total, self._step_clicks_done + 1)
        return (cur, total)

    def stop(self) -> None:
        if self._state == ClickerState.IDLE:
            return
        mouse_trace.event("engine_stop", clicks=self._session_clicks)
        self._stop.set()
        self._watchdog_stop.set()
        if self._mss_engine is not None:
            try:
                self._mss_engine.close()
            except Exception:
                pass
            self._mss_engine = None
        # Key timer threads honor self._stop and exit on their own; just
        # drop the references so the next start() begins clean.
        self._key_timer_threads = []
        self._set_state(ClickerState.IDLE)

    def toggle(self) -> None:
        if self._state == ClickerState.IDLE:
            self.start()
        else:
            self.stop()

    def fire_step_once(self, step: RecorderStep, *, delay_s: float = 0.0) -> bool:
        """Run a single step in isolation, off the main loop.

        Powers the per-step "▶ Test" buttons. Click steps move the cursor
        and click; Key steps push the configured backend then fire the
        combo through the same code path the running engine uses, so a
        Test press through Serial HID actually exercises the Arduino.

        ``delay_s`` defers the fire by N seconds — used by the Key Test
        button so the user can alt-tab to the target window (e.g.
        RuneScape) before the keystroke lands. Click Test runs with
        no delay because the cursor visibly moves to the zone, which
        is feedback enough.

        No-op if the engine is busy or the step doesn't have what it
        needs (zone for Click, key_combo for Key). Returns True if a
        worker was scheduled.
        """
        if self._state != ClickerState.IDLE:
            return False
        if step.kind == KIND_CLICK:
            if step.zone is None:
                return False
        elif step.kind == KIND_KEY:
            if not step.key_combo or parse_combo(step.key_combo) is None:
                return False
        else:
            return False
        threading.Thread(
            target=self._fire_step_once_worker,
            args=(step, float(delay_s)),
            daemon=True,
        ).start()
        return True

    def _fire_step_once_worker(self, step: RecorderStep, delay_s: float = 0.0) -> None:
        # One-shot, so the stop event is local — Test never waits long enough
        # to need user-cancel, and we don't want it to honor the engine's
        # main stop event since that's about loop-level state.
        stop = threading.Event()
        if delay_s > 0:
            # ``stop.wait`` keeps the thread interruptible if anyone needs
            # to cancel later, but the engine never sets ``stop`` here so
            # this is effectively a sleep.
            stop.wait(delay_s)
        try:
            if step.kind == KIND_CLICK:
                zone = step.zone
                if zone is None:
                    return
                target = self._jitter(zone.random_point(), zone)
                if humanizer.move(
                    target, stop=stop, fatigue=1.0,
                    overshoot_enabled=self.overshoot_enabled,
                    overshoot_probability=self.overshoot_probability,
                ):
                    return
                humanizer.click(step.click_type, step.click_mode,
                                stop=stop, fatigue=1.0)
                return
            if step.kind == KIND_KEY:
                # Push the currently-configured backend so Test fires
                # through the same path the running engine would. We
                # re-resolve every call so a UI backend change between
                # tests takes effect without an engine restart.
                from . import key_input_backend
                from . import key_timer
                backend = key_input_backend.get_backend(
                    self.key_input_method,
                    serial_port=getattr(self, "serial_hid_port", "") or "",
                )
                key_timer.set_backend(backend)
                if self._key_controller is None:
                    self._key_controller = keyboard.Controller()
                fire_combo(
                    self._key_controller,
                    step.key_combo,
                    hold_s=max(0.0, float(step.key_hold_s)),
                    stop=stop,
                )
                return
        except Exception:
            pass

    # -- internal: watchdog -------------------------------------------------

    def _start_watchdog(self) -> None:
        self._watchdog_stop.clear()
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

    def _watchdog_loop(self) -> None:
        """Corner failsafe: cursor in any of the target monitor's corners
        triggers an emergency stop. Targeting the *target* monitor means
        a multi-monitor user can rely on the corner-stop reaching the
        screen the cursor is actually on, not just the OS primary.

        Bounds are re-resolved each tick so a monitor unplug, DPI change,
        or target-monitor switch mid-run doesn't leave stale corners that
        false-trigger.
        """
        while not self._watchdog_stop.wait(0.05):
            bx, by, sw, sh = self._resolve_screen_bounds()
            if sw <= 0 or sh <= 0:
                continue
            humanizer.set_safe_bounds((bx, by, sw, sh))
            x_min, y_min = bx, by
            x_max, y_max = bx + sw, by + sh
            try:
                # _mouse.position is physical px (pynput uses GetCursorPos
                # which returns physical when the process is per-monitor-v2
                # DPI aware — see main._enable_dpi_awareness). The bounds
                # above are DIPs from _resolve_screen_bounds(), so convert
                # cursor pos to DIPs before comparing or the corner-stop
                # mis-fires on non-100%-scaled monitors.
                px, py = _mouse.position
                x, y = dpi_cursor.physical_to_dip(float(px), float(py))
            except Exception:
                continue
            in_corner = (
                (x <= x_min + 2 and y <= y_min + 2)
                or (x >= x_max - 2 and y <= y_min + 2)
                or (x <= x_min + 2 and y >= y_max - 2)
                or (x >= x_max - 2 and y >= y_max - 2)
            )
            if in_corner:
                self.log.info(
                    "watchdog corner stop at cursor=(%d,%d) "
                    "bounds=(%d,%d,%d,%d)",
                    int(x), int(y), bx, by, sw, sh,
                )
                self._announce_engine_halt(
                    "Stopped: cursor reached a screen corner "
                    "(emergency stop).",
                    "info",
                )
                self._stop.set()
                self._set_state(ClickerState.IDLE)
                return

    # -- internal: main loop ------------------------------------------------

    def _step_log_tag(self) -> str:
        """Compact "step=N/M(kind,'label')" tag for log lines. Greppable
        and deterministic so a user can grep their log for "step=2/3"
        and see every event tied to step 2.

        Returns "step=-(clicker)" for single-zone (non-recorder) mode
        so log lines from both modes share the same key.
        """
        if self.mode != "recorder":
            return "step=-(clicker)"
        if not (0 <= self._step_idx < len(self.recorder_steps)):
            return "step=?(?)"
        s = self.recorder_steps[self._step_idx]
        n = len(self.recorder_steps)
        label_part = (f",'{s.label}'"
                      if (getattr(s, "label", "") or "").strip()
                      else "")
        return f"step={self._step_idx + 1}/{n}({s.kind}{label_part})"

    def _step_phase_prefix(self) -> str:
        """Short "Step N · KIND" / "Step N 'label' · KIND" phrase used as
        the leading half of phase labels. Empty string in non-recorder
        mode so single-zone phase labels stay clean ("Moving" not
        "Step 1 · Moving")."""
        if self.mode != "recorder":
            return ""
        if not (0 <= self._step_idx < len(self.recorder_steps)):
            return ""
        s = self.recorder_steps[self._step_idx]
        kind_word = {
            "click": "CLICK", "track": "TRACK", "color": "COLOR",
            "pause": "PAUSE", "key": "KEY", "loop": "LOOP",
        }.get(s.kind, s.kind.upper())
        user_label = (getattr(s, "label", "") or "").strip()
        if user_label:
            return f"Step {self._step_idx + 1} '{user_label}' · {kind_word}"
        return f"Step {self._step_idx + 1} · {kind_word}"

    def _set_phase(self, phase: str, label: str = "",
                    duration: float = 0.0) -> None:
        """Update the live activity indicator. ``label`` is a one-liner
        the Status card displays verbatim ("Hover visit · zone 2",
        "On break", "Searching for target"); ``duration`` is the
        expected duration in seconds, used to compute "X s left" — set
        to 0 when unknown (e.g. moving / clicking — too brief to bother).

        Called from the engine thread; the UI polls the property values
        on its own cadence so there's no cross-thread Qt risk.
        """
        self._phase = phase
        self._phase_label = label
        self._phase_until = (time.monotonic() + duration) if duration > 0 else 0.0

    @property
    def current_phase(self) -> str:
        return self._phase

    @property
    def phase_label(self) -> str:
        return self._phase_label

    @property
    def phase_remaining(self) -> float:
        """Seconds remaining in the current phase, or 0 when unknown /
        phase has no fixed duration. Clamps negative to 0."""
        if self._phase_until <= 0:
            return 0.0
        return max(0.0, self._phase_until - time.monotonic())

    @property
    def session_uptime_seconds(self) -> float:
        """How long the current run has been going. 0 when idle."""
        if self._session_start <= 0 or self._state == ClickerState.IDLE:
            return 0.0
        return max(0.0, time.monotonic() - self._session_start)

    @property
    def recovery_count(self) -> int:
        """Number of transient-error recoveries during this session."""
        return self._recovery_count

    @property
    def clicks_attempted(self) -> int:
        """Cycles that set up to fire a click this session. The gap
        between this and ``_session_clicks`` is ``cycles_aborted`` —
        rechecks that bailed before the click went out."""
        return self._clicks_attempted

    @property
    def cycles_aborted(self) -> int:
        """Cycles aborted by track-lost / color-vanished / weak-match
        rechecks before the click fired."""
        return self._cycles_aborted

    @property
    def clicks_with_drift(self) -> int:
        """Number of clicks where actual cursor pos diverged from the
        intended target by > 2 px at press time. High counts indicate
        the OS / another process is moving the cursor between our
        ``move()`` and ``click()`` calls."""
        return self._clicks_with_drift

    @property
    def click_drift_mean_px(self) -> float:
        """Average drift distance per fired click. ~0 means clicks are
        landing exactly where the engine intended; > 2 px indicates
        consistent cursor displacement between move and press."""
        if self._session_clicks <= 0:
            return 0.0
        return self._click_drift_total_px / self._session_clicks

    @property
    def click_drift_max_px(self) -> float:
        """Largest single-click drift this session, in px."""
        return self._click_drift_max_px

    def _set_state(self, state: str) -> None:
        self._state = state
        # Keep the phase coherent with the high-level state so the UI
        # never shows e.g. "Hovering" while the engine is back at IDLE
        # after a stop. STARTING and ACTIVE leave the phase to the
        # cycle loop (which sets it explicitly).
        if state == ClickerState.IDLE:
            self._set_phase(ClickerPhase.IDLE)
        elif state == ClickerState.STARTING:
            self._set_phase(ClickerPhase.STARTING, "Pre-start countdown")
        if self.on_state_change:
            try:
                self.on_state_change(state)
            except Exception:
                pass

    # Tunables for the engine resilience loop. Transient errors (mss
    # screen-grab failure during screen lock, momentary cv2 hiccup, OS
    # I/O blip) get up to MAX_RECOVERIES retries with exponential backoff
    # capped at MAX_BACKOFF_S. Past that we give up — repeated failures
    # at this rate are no longer "transient." Resets after any successful
    # cycle (tracked inside _run_inner via _record_successful_tick).
    _MAX_RECOVERIES: int = 5
    _RECOVERY_BASE_BACKOFF_S: float = 1.0
    _MAX_BACKOFF_S: float = 30.0

    def _run(self) -> None:
        """Top-level engine loop with transient-error resilience.

        For 8-10 hour unattended sessions, a single mss.ScreenShotError
        (e.g. user RDP-disconnected or locked the screen briefly) used
        to kill the entire engine. Now we catch a known set of transient
        errors and retry with exponential backoff before halting. Logic
        errors (NameError, TypeError, etc.) still kill the engine —
        retrying a bug is pointless.
        """
        consecutive_failures = 0
        # Snapshot click count so we can tell whether _run_inner made any
        # forward progress between failures. If yes, reset the consecutive
        # counter — otherwise the engine could give up on a long, healthy
        # run just because errors clustered far apart.
        clicks_at_last_failure = self._session_clicks
        while not self._stop.is_set():
            try:
                self._run_inner()
                # Inner returned cleanly (stop was requested or session
                # complete fired). Don't retry — exit the resilience loop.
                return
            except _TRANSIENT_ERRORS as e:
                if self._session_clicks > clicks_at_last_failure:
                    # Made progress since the last failure → not really
                    # consecutive. Reset the counter so a long run doesn't
                    # accumulate towards halt.
                    consecutive_failures = 0
                clicks_at_last_failure = self._session_clicks
                consecutive_failures += 1
                self._recovery_count += 1
                self.log.warning(
                    "engine cycle hit transient error (%s); recovery %d/%d",
                    type(e).__name__, consecutive_failures, self._MAX_RECOVERIES,
                )
                if consecutive_failures > self._MAX_RECOVERIES:
                    self._announce_engine_halt(
                        f"Engine gave up after {consecutive_failures} "
                        f"transient errors ({type(e).__name__}: {e}). "
                        "Check screen access / display state.",
                        "error",
                    )
                    self._stop.set()
                    self._set_state(ClickerState.IDLE)
                    return
                # Exponential backoff: 1s, 2s, 4s, 8s, 16s, 30s (cap).
                backoff = min(
                    self._MAX_BACKOFF_S,
                    self._RECOVERY_BASE_BACKOFF_S * (2 ** (consecutive_failures - 1)),
                )
                self._set_phase(
                    ClickerPhase.RECOVERING,
                    f"Recovering from {type(e).__name__} ({consecutive_failures}/{self._MAX_RECOVERIES})",
                    backoff,
                )
                # Drop cached screen-grab handles so the retry rebuilds
                # them from scratch (fixes "stale DC after display change").
                if self._mss_engine is not None:
                    try:
                        self._mss_engine.close()
                    except Exception:
                        pass
                    self._mss_engine = None
                if self.tracker is not None:
                    try:
                        self.tracker.close()
                    except Exception:
                        pass
                if self._stop.wait(backoff):
                    return
                # Loop continues — _run_inner picks up where state allows
                # (step index, click counters preserved on the instance).
            except Exception as e:
                # Non-transient: bug in our code or misconfiguration.
                # Surface and stop — no point in retrying.
                self.log.exception("engine loop crashed")
                self._announce_engine_halt(
                    f"Engine crashed: {type(e).__name__}: {e}",
                    "error",
                )
                self._stop.set()
                self._set_state(ClickerState.IDLE)
                return

    _STUCK_TOAST_AFTER_S: float = 10.0

    def _run_inner(self) -> None:
        fatigue = Fatigue(
            enabled=self.fatigue_enabled,
            break_bursts=self.break_bursts_enabled,
            intensity=self.fatigue_intensity,
            break_min_clicks=self.break_min_clicks,
            break_max_clicks=self.break_max_clicks,
            break_min_duration=self.break_min_duration,
            break_max_duration=self.break_max_duration,
        )

        # -- pre-start grace period --
        self._prestart_ends_at = time.monotonic() + self.prestart_delay
        if self._stop.wait(self.prestart_delay):
            self._set_state(ClickerState.IDLE)
            return
        self._set_state(ClickerState.ACTIVE)

        while not self._stop.is_set():
            mouse_trace.event(
                "cycle",
                idx=self._step_idx,
                done=self._step_clicks_done,
                clicks=self._session_clicks,
            )
            # Stop-after time limit check (cheap, runs every cycle).
            if self.stop_after_minutes_enabled and self.stop_after_minutes > 0:
                elapsed = time.monotonic() - self._session_start
                if elapsed >= self.stop_after_minutes * 60.0:
                    self._announce_session_complete(
                        f"Session complete: {self.stop_after_minutes} min reached"
                    )
                    break
            # Resolve per-cycle inputs based on mode.
            track_step: Optional[RecorderStep] = None
            color_step: Optional[RecorderStep] = None
            color_target_point: Optional[tuple[int, int]] = None
            if self.mode == "recorder":
                # Peek current step (without advancing); skip empties.
                step = self._peek_recorder_step()
                if step is None:
                    self._announce_engine_halt(
                        "Sequence has no usable steps — every step is "
                        "missing required data (zone / template / color).",
                        "warn",
                    )
                    break
                # Pause steps fire no click — just wait (with cursor wander)
                # then advance. Returns to the top of the loop.
                if step.kind == KIND_PAUSE:
                    pause_dur = self._human_delay(step.delay_min, step.delay_max)
                    self._next_click_at = time.monotonic() + pause_dur
                    self._set_phase(
                        ClickerPhase.PAUSING,
                        f"{self._step_phase_prefix()} — pausing",
                        pause_dur,
                    )
                    if self._wait_with_wander(
                            pause_dur, fatigue,
                            next_anchor=self._next_action_anchor()):
                        break
                    self._advance_recorder_step("pause_complete")
                    continue
                if step.kind == KIND_KEY:
                    # Keyboard step — fire ``key_repeat`` presses of ``key_combo``,
                    # then wait the per-step delay before advancing. The cursor
                    # still wanders during the wait so the engine doesn't freeze
                    # mid-macro. Each keypress can hold for ``key_hold_s`` (0 =
                    # ordinary tap); the hold is interruptible via ``self._stop``.
                    if self._key_controller is None:
                        self._key_controller = keyboard.Controller()
                    repeats = max(1, int(step.key_repeat))
                    # Phase tag so the topbar shows "Step N · KEY — pressing
                    # 'ctrl+x' (1/3)" — without this, KEY steps look identical
                    # to silent skips since the phase indicator never updated.
                    self._set_phase(
                        ClickerPhase.KEYPRESS,
                        f"{self._step_phase_prefix()} — pressing {step.key_combo!r}"
                        + (f" ×{repeats}" if repeats > 1 else ""),
                    )
                    self.log.info(
                        "KIND_KEY dispatch step=%s combo=%r repeats=%d hold=%.3f",
                        step.step_id, step.key_combo, repeats,
                        float(step.key_hold_s),
                    )
                    for i in range(repeats):
                        if self._stop.is_set():
                            break
                        ok = fire_combo(
                            self._key_controller,
                            step.key_combo,
                            hold_s=max(0.0, float(step.key_hold_s)),
                            stop=self._stop,
                        )
                        self.log.info(
                            "KIND_KEY fire combo=%r ok=%s iter=%d/%d",
                            step.key_combo, ok, i + 1, repeats,
                        )
                        if not ok:
                            self._announce_engine_halt(
                                f"⚠ {self._step_label_for(step.step_id)} has "
                                f"an unrecognized key combo: {step.key_combo!r}",
                                "warn",
                            )
                            break
                        # Inter-press gap for repeating taps. The old fixed
                        # 40-120 ms range was so tight that a 5-tap macro
                        # finished in ~500 ms — distinctly mechanical and
                        # detection-friendly. Bumped to 80-300 ms × the
                        # current fatigue multiplier so the cadence:
                        #   • clears game input poll windows reliably
                        #   • varies enough per press to break exact-period
                        #     bot signatures
                        #   • slows down with the same fatigue arc as
                        #     clicks do as a session wears on
                        # Skipped on the last iteration (no trailing gap).
                        if i < repeats - 1:
                            gap = random.uniform(0.080, 0.300) * fatigue.multiplier()
                            if self._stop.wait(gap):
                                break
                    if self._stop.is_set():
                        break
                    wait_dur = self._human_delay(step.delay_min, step.delay_max)
                    self._next_click_at = time.monotonic() + wait_dur
                    if self._wait_with_wander(
                            wait_dur, fatigue,
                            next_anchor=self._next_action_anchor()):
                        break
                    self._advance_recorder_step("key_complete")
                    continue
                if step.kind == KIND_LOOP:
                    target_idx = self._resolve_loop_target(step)
                    # Bail out as no-op for missing/orphaned target, self-
                    # target, or forward jump (engine guard even though the
                    # UI prevents the latter two).
                    if target_idx is None or target_idx >= self._step_idx:
                        if target_idx is None:
                            self._announce_loop_orphan(step.step_id)
                        self._advance_recorder_step(
                            "loop_orphan" if target_idx is None
                            else "loop_target_invalid"
                        )
                        continue
                    if step.loop_count > 0:
                        remaining = self._loop_iterations_remaining.get(
                            step.step_id, step.loop_count)
                        if remaining <= 0:
                            self._loop_iterations_remaining.pop(
                                step.step_id, None)
                            self._advance_recorder_step("loop_exhausted")
                            continue
                        self._loop_iterations_remaining[step.step_id] = (
                            remaining - 1)
                    # Jump back; reset within-step click counter so the
                    # destination step starts fresh.
                    self.log.info(
                        "step_loop_jump from=%s to_step_idx=%d remaining=%s",
                        self._step_log_tag(), target_idx + 1,
                        ("inf" if step.loop_count <= 0
                         else str(self._loop_iterations_remaining.get(
                             step.step_id, 0))),
                    )
                    self._step_idx = target_idx
                    self._step_clicks_done = 0
                    continue
                if step.kind == KIND_TRACK:
                    # Make sure the tracker is matching this step's template.
                    self._activate_track_step(step)
                    cycle_zone = self._tracker_zone()
                    if cycle_zone is None:
                        self._set_phase(
                            ClickerPhase.SEARCHING,
                            f"{self._step_phase_prefix()} — searching for target",
                        )
                        # Not locked yet — short wait, the App-owned tracker
                        # thread keeps trying. If we've been stuck without a
                        # lock for a while, surface a warn toast (cooldowned)
                        # so the user knows why nothing is happening.
                        now = time.monotonic()
                        first_stuck = self._track_stuck_since.setdefault(
                            step.step_id, now)
                        elapsed = now - first_stuck
                        # Per-step timeout: if the user set one and it has
                        # passed, dispatch the on_timeout action so the
                        # sequence doesn't stall here forever. Checked
                        # before the toast so a fast timeout doesn't fire
                        # both messages on the same cycle.
                        if (step.timeout_seconds > 0
                                and elapsed >= step.timeout_seconds):
                            self._track_stuck_since.pop(step.step_id, None)
                            self._step_target_present[step.step_id] = False
                            self._announce_step_timeout(step, elapsed)
                            if step.on_timeout == "stop":
                                break
                            self._advance_recorder_step("track_timeout")
                            continue
                        if elapsed >= self._STUCK_TOAST_AFTER_S:
                            self._announce_track_stuck(step.step_id, elapsed)
                        self._step_target_present[step.step_id] = False
                        if self._stop.wait(0.10):
                            break
                        continue
                    # Locked — clear the stuck-since clock for this step.
                    self._track_stuck_since.pop(step.step_id, None)
                    if self._react_to_fresh_target(step.step_id):
                        break
                    # Re-fetch the lock zone AFTER the reaction delay so a
                    # moving target doesn't get clicked on stale coords.
                    # If the lock dropped during the delay, abort and retry
                    # next loop iteration rather than firing on a phantom.
                    cycle_zone = self._tracker_zone()
                    if cycle_zone is None:
                        self._step_target_present[step.step_id] = False
                        continue
                    track_step = step
                elif step.kind == KIND_COLOR:
                    # Find any pixel matching the picked color (within
                    # tolerance) and click as close to it as possible.
                    # The cycle zone is intentionally tiny (3×3 centered on
                    # the matched pixel): we already know the exact target
                    # coord, so the cursor spread that's helpful for click /
                    # track steps is harmful here — it widens a click that
                    # should land on a specific small UI element. Bezier
                    # path, overshoot, and timing humanization still apply
                    # via humanizer.move() / humanizer.click(). If nothing
                    # matches, wait briefly and retry next cycle without
                    # advancing — same pattern as KIND_TRACK on lock-loss.
                    point = self._find_color_target(step)
                    if point is None:
                        self._set_phase(
                            ClickerPhase.SEARCHING,
                            f"{self._step_phase_prefix()} — searching for color",
                        )
                        now = time.monotonic()
                        first_no_match = self._color_no_match_since.setdefault(
                            step.step_id, now)
                        elapsed = now - first_no_match
                        # Per-step timeout: if the user set one and it has
                        # passed, dispatch on_timeout so the engine can
                        # advance or halt instead of hanging on a missing
                        # pixel forever.
                        if (step.timeout_seconds > 0
                                and elapsed >= step.timeout_seconds):
                            self._color_no_match_since.pop(step.step_id, None)
                            self._step_target_present[step.step_id] = False
                            self._announce_step_timeout(step, elapsed)
                            if step.on_timeout == "stop":
                                break
                            self._advance_recorder_step("color_timeout")
                            continue
                        if elapsed >= self._STUCK_TOAST_AFTER_S:
                            self._announce_color_no_match(
                                step.step_id, elapsed)
                        self._step_target_present[step.step_id] = False
                        if self._stop.wait(0.20):
                            break
                        continue
                    # Match found — clear the no-match-since clock for this step.
                    self._color_no_match_since.pop(step.step_id, None)
                    if self._react_to_fresh_target(step.step_id):
                        break
                    # Re-fetch after reaction delay so a moving / disappearing
                    # pixel doesn't get clicked on stale coords. Track step
                    # by step_id so we can do a proper recheck-before-click
                    # too (see below).
                    point = self._find_color_target(step)
                    if point is None:
                        self._step_target_present[step.step_id] = False
                        continue
                    color_step = step
                    color_target_point = point
                    # 5×5 click zone instead of 3×3 — absorbs cursor
                    # tremor (~2 px) + jitter (~1 px) so the click reliably
                    # lands on the matched pixel even under sway. Still
                    # well inside any clickable UI element.
                    cycle_zone = Zone.make_rect(
                        point[0] - 2, point[1] - 2,
                        point[0] + 2, point[1] + 2,
                    )
                else:
                    cycle_zone = step.zone
                base_delay = self._human_delay(step.delay_min, step.delay_max)
                cycle_click_type = step.click_type
                cycle_click_mode = step.click_mode
            else:
                if self.zone is None:
                    self._announce_engine_halt(
                        "Click zone was cleared while running — "
                        "draw a new zone before starting again.",
                        "warn",
                    )
                    break
                cycle_zone = self.zone
                base_delay = self._human_delay(self.min_delay, self.max_delay)
                cycle_click_type = self.click_type
                cycle_click_mode = self.click_mode

            # Inter-click delay (with fatigue stretch + optional idle wanders).
            delay = base_delay * fatigue.multiplier()
            self._next_click_at = time.monotonic() + delay

            # Default phase for this stretch — overridden inside
            # _wait_with_wander when a hover / wander / pre-hover fires.
            self._set_phase(
                ClickerPhase.WAITING,
                (f"{self._step_phase_prefix()} — waiting"
                 if self.mode == "recorder" else "Waiting"),
                delay,
            )

            # Pre-hover toward THIS cycle's zone — when stacked CLICK / TRACK
            # / COLOR steps target different areas, the cursor drifts partway
            # toward the upcoming click during the wait so it isn't sitting
            # on the previous click point until the very last second.
            if self._wait_with_wander(delay, fatigue, next_anchor=cycle_zone):
                break

            if self._stop.is_set():
                break

            # Apply non-stationary drift to the sampling distribution so a
            # detector watching N clicks doesn't see a clean Gaussian bell
            # centered on the same point. The drift state lives outside
            # the Zone (in _zone_drift_state) so transient zones (tracker /
            # color) accumulate drift across cycles too.
            if self.mode == "recorder":
                _drift_step = self.recorder_steps[self._step_idx] if (
                    0 <= self._step_idx < len(self.recorder_steps)) else None
                if _drift_step is not None and _drift_step.kind == KIND_TRACK:
                    _drift_key = f"track:{_drift_step.step_id}"
                elif _drift_step is not None and _drift_step.kind == KIND_COLOR:
                    _drift_key = f"color:{_drift_step.step_id}"
                elif _drift_step is not None:
                    _drift_key = _drift_step.step_id
                else:
                    _drift_key = "clicker"
            else:
                _drift_key = "clicker"
            self._apply_zone_drift(cycle_zone, _drift_key)

            # Pick target inside whichever zone applies this cycle.
            target = cycle_zone.random_point()
            if self.anti_cluster_enabled:
                target = self._anti_cluster(target, cycle_zone)
            target = self._jitter(target, cycle_zone)
            if self._recent and target == self._recent[-1]:
                # Bump a couple px so we don't hit the exact same pixel; but
                # only commit the bump if it's still inside the zone — for
                # narrow polygons the bump can otherwise push the click off
                # the zone entirely.
                bumped = (target[0] + random.choice([-2, -1, 1, 2]),
                          target[1] + random.choice([-2, -1, 1, 2]))
                if cycle_zone is None or cycle_zone.contains(bumped[0], bumped[1]):
                    target = bumped

            # Strict final guard: nothing past this point should produce
            # an out-of-zone click. Catches edge cases where anti-cluster
            # + jitter combined push the target past the boundary in a
            # way each individual guard missed.
            target = self._clamp_target_to_zone(target, cycle_zone)
            mouse_trace.event(
                "target",
                x=int(target[0]), y=int(target[1]),
                key=_drift_key,
            )
            mult = fatigue.multiplier()
            move_mult = mult * self._muscle_memory_factor()
            # Diagnostic: count this cycle as a click attempt now (before
            # the move). If a recheck aborts it, _cycles_aborted ticks
            # below and the gap between attempted and session_clicks
            # tells the user how many cycles set up to click but didn't.
            self._clicks_attempted += 1
            self._set_phase(
                ClickerPhase.MOVING,
                (f"{self._step_phase_prefix()} — moving to target"
                 if self.mode == "recorder" else "Moving to target"),
            )
            if humanizer.move(target, stop=self._stop, fatigue=move_mult,
                              overshoot_enabled=self.overshoot_enabled,
                              overshoot_probability=self.overshoot_probability):
                break

            # Recheck-before-click for moving (Track) targets: if the target
            # has drifted significantly during the move, do a quick correction
            # so the click lands on the new position instead of where the
            # target *was* when we sampled it.
            if track_step is not None:
                fresh_zone = self._tracker_zone()
                snap = self.tracker.snapshot_state() if self.tracker else None
                if snap is None or not snap.is_locked or fresh_zone is None:
                    # Lock dropped during the move — abort this cycle, don't
                    # fire on wrong pixels. Surface this in the status card
                    # so the user can tell "missed click" from "engine
                    # silently retried because target moved."
                    self._cycles_aborted += 1
                    self.log.warning(
                        "cycle_abort %s reason=track_lock_lost "
                        "intended_target=(%d,%d)",
                        self._step_log_tag(), target[0], target[1],
                    )
                    self._set_phase(
                        ClickerPhase.SKIPPED,
                        f"{self._step_phase_prefix()} — target moved, retrying",
                        1.5,
                    )
                    continue
                # Reject "barely re-locked" matches. The tracker considers
                # anything ≥ match_threshold (0.65 default) a lock, but a
                # score in the 0.65-0.70 band is often a partial / similar
                # object (think two of the same skill icon side-by-side).
                # Require a +0.05 confidence margin past threshold or abort.
                threshold = float(self.tracker.cfg.match_threshold) if self.tracker else 0.65
                if snap.last_score < threshold + 0.05:
                    mouse_trace.event(
                        "track_weak_score",
                        score=round(float(snap.last_score), 3),
                        thr=round(threshold, 3),
                    )
                    self._step_target_present[track_step.step_id] = False
                    self._cycles_aborted += 1
                    self.log.warning(
                        "cycle_abort %s reason=weak_match score=%.3f thr=%.3f",
                        self._step_log_tag(),
                        float(snap.last_score), threshold + 0.05,
                    )
                    self._set_phase(
                        ClickerPhase.SKIPPED,
                        f"{self._step_phase_prefix()} — match too weak, retrying",
                        1.5,
                    )
                    continue
                fresh_target = self._jitter(
                    fresh_zone.random_point(), fresh_zone)
                drift = math.hypot(fresh_target[0] - target[0],
                                    fresh_target[1] - target[1])
                tw, th = self.tracker.cfg.template_size
                drift_threshold = max(8.0, min(tw, th) * 0.4)
                if drift > drift_threshold:
                    # Quick corrective re-aim — Wind/Hooke curve still applies
                    # (no straight-line snap), just slightly hurried and no
                    # overshoot since this is verify-correct, not fresh aim.
                    mouse_trace.event(
                        "track_correct",
                        drift=round(drift, 1),
                        thr=round(drift_threshold, 1),
                        nx=int(fresh_target[0]), ny=int(fresh_target[1]),
                    )
                    if humanizer.move(fresh_target, stop=self._stop,
                                      fatigue=0.85,
                                      overshoot_enabled=False,
                                      overshoot_probability=0.0):
                        break
                    target = fresh_target

            # Recheck-before-click for COLOR steps. The matched pixel may
            # have moved or disappeared during the inter-click wait + move.
            # Re-find a match: if it's gone, abort this cycle so we don't
            # click a phantom; if it's drifted, do a quick correction.
            if color_step is not None and color_target_point is not None:
                fresh_point = self._find_color_target(color_step)
                if fresh_point is None:
                    # Pixel disappeared during the move — abort cycle.
                    self._step_target_present[color_step.step_id] = False
                    self._cycles_aborted += 1
                    self.log.warning(
                        "cycle_abort %s reason=color_vanished "
                        "intended_target=(%d,%d)",
                        self._step_log_tag(),
                        color_target_point[0], color_target_point[1],
                    )
                    self._set_phase(
                        ClickerPhase.SKIPPED,
                        f"{self._step_phase_prefix()} — color vanished, retrying",
                        1.5,
                    )
                    continue
                drift = math.hypot(fresh_point[0] - color_target_point[0],
                                    fresh_point[1] - color_target_point[1])
                if drift > 6.0:
                    fresh_target = (fresh_point[0], fresh_point[1])
                    mouse_trace.event(
                        "color_correct",
                        drift=round(drift, 1),
                        nx=int(fresh_target[0]), ny=int(fresh_target[1]),
                    )
                    if humanizer.move(fresh_target, stop=self._stop,
                                      fatigue=0.85,
                                      overshoot_enabled=False,
                                      overshoot_probability=0.0):
                        break
                    target = fresh_target

            self._set_phase(
                ClickerPhase.CLICKING,
                (f"{self._step_phase_prefix()} — clicking"
                 if self.mode == "recorder" else "Clicking"),
            )
            if humanizer.click(cycle_click_type, cycle_click_mode,
                               stop=self._stop, fatigue=mult):
                break

            # Capture where the cursor actually ended up post-click — useful
            # for diagnosing accuracy issues (target vs actual). Falls back
            # to target on failure.
            try:
                actual_x, actual_y = dpi_cursor.get_pos()
                actual_x, actual_y = int(actual_x), int(actual_y)
            except Exception:
                actual_x, actual_y = target[0], target[1]
            # Drift accounting — track the gap between intended target
            # and where the cursor actually clicked. Surfaced to the
            # user via StatusPill tooltip so they can answer "are my
            # missed clicks because the click landed off-target, or
            # because the game ignored a perfectly-placed click?"
            drift_px = math.hypot(actual_x - target[0], actual_y - target[1])
            self._click_drift_total_px += drift_px
            if drift_px > self._click_drift_max_px:
                self._click_drift_max_px = drift_px
            if drift_px > 2.0:
                self._clicks_with_drift += 1
            # Per-click diagnostic line. Greppable, parseable, contains
            # everything needed to diagnose missed clicks from a session
            # log alone (no need to enable mouse_trace separately). One
            # line per click — at typical click rates (300-800/hour)
            # this stays well within the 5 MB rotation budget.
            self.log.info(
                "click %s target=(%d,%d) actual=(%d,%d) drift=%.1f "
                "type=%s mode=%s wait=%.2fs n=%d",
                self._step_log_tag(),
                target[0], target[1], actual_x, actual_y, drift_px,
                cycle_click_type, cycle_click_mode, delay,
                self._session_clicks + 1,
            )
            # Cache successful COLOR-step click positions so the next
            # cycle's match selection anchors on this point — converges
            # the click cluster onto a stable center within a few cycles.
            if color_step is not None:
                self._color_last_click_pos[color_step.step_id] = (
                    actual_x, actual_y)
            if self.on_click_fired is not None:
                kind = "color" if (
                    self.mode == "recorder"
                    and 0 <= self._step_idx < len(self.recorder_steps)
                    and self.recorder_steps[self._step_idx].kind == KIND_COLOR
                ) else "click"
                try:
                    self.on_click_fired(
                        int(target[0]), int(target[1]),
                        actual_x, actual_y, kind,
                    )
                except Exception:
                    pass

            self.stats.record(target)
            self._recent.append(target)
            fatigue.record_click()
            self._session_clicks += 1

            # Stop-after click limit — checked right after the increment so
            # the very last click counted *is* the limit click, not the one
            # past it.
            if (self.stop_after_clicks_enabled
                    and self.stop_after_clicks > 0
                    and self._session_clicks >= self.stop_after_clicks):
                self._announce_session_complete(
                    f"Session complete: {self._session_clicks} clicks"
                )
                break

            # In recorder mode: increment within-step counter, advance step
            # when its click_count is reached.
            if self.mode == "recorder" and self.recorder_steps:
                self._step_clicks_done += 1
                step_total = max(1, int(self.recorder_steps[self._step_idx].click_count))
                if self._step_clicks_done >= step_total:
                    self._advance_recorder_step("click_count_met")

            # Sometimes drift a few pixels after the click; sometimes don't.
            # An AFK player sits still for stretches — constant post-click
            # motion is itself a mechanical pattern. Probability rises with
            # the realism dial (~25% at low realism, ~70% at max).
            wander_p = 0.25 + 0.45 * max(0.0, min(1.0, self.realism))
            if random.random() < wander_p:
                self._set_phase(ClickerPhase.POST_CLICK, "Post-click drift")
                if self._post_click_micro_wander(fatigue.multiplier()):
                    break

            # Once per cycle we check that all key-timer daemon threads
            # are still alive; respawn any that died silently. Throttled
            # internally to once per 30 s so this is essentially free.
            self._check_key_timer_health()

            # Realism: occasional "looked away" pause unrelated to scheduled
            # breaks. Returns True if the user emergency-stopped during the
            # spike. _maybe_distraction_spike sets its own phase when it
            # actually fires (no-op rolls leave the phase alone).
            if self._maybe_distraction_spike():
                break

            brk = fatigue.maybe_break()
            if brk > 0:
                self._next_click_at = time.monotonic() + brk
                self._set_phase(
                    ClickerPhase.BREAKING,
                    f"On break — taking a breather",
                    brk,
                )
                # Break bursts are the largest scheduled idle window —
                # always log so a multi-minute gap in click events is
                # explained ("yes, took a 4-minute break") instead of
                # looking like a hang.
                self.log.info(
                    "break_burst %s duration=%.2fs after_clicks=%d",
                    self._step_log_tag(), brk, self._session_clicks,
                )
                if self._stop.wait(brk):
                    break

        # Single end-of-session summary line — pairs with engine_start at
        # the top, so a user who shares the log gets totals at a glance
        # without grepping every "click ..." line. Includes the same
        # counters the StatusPill tooltip surfaces, plus an explicit
        # uptime so multi-hour AFK sessions are easy to triage.
        try:
            uptime = (max(0.0, time.monotonic() - self._session_start)
                      if self._session_start > 0 else 0.0)
            mean_drift = (self._click_drift_total_px / self._session_clicks
                          if self._session_clicks > 0 else 0.0)
            self.log.info(
                "engine_stop mode=%s clicks=%d attempted=%d aborted=%d "
                "drift_mean=%.2fpx drift_max=%.1fpx drifted_gt2=%d "
                "recoveries=%d uptime=%.1fs",
                self.mode, self._session_clicks, self._clicks_attempted,
                self._cycles_aborted, mean_drift, self._click_drift_max_px,
                self._clicks_with_drift, self._recovery_count, uptime,
            )
        except Exception:
            self.log.debug("engine_stop summary log failed", exc_info=True)
        # Tell daemon helpers (watchdog, key timers) to wind down. Setting
        # _stop here is critical for key timers — they only honor _stop and
        # would otherwise keep firing after the main loop exits.
        self._stop.set()
        self._watchdog_stop.set()
        self._active_track_step_id = None
        if self._mss_engine is not None:
            try:
                self._mss_engine.close()
            except Exception:
                pass
            self._mss_engine = None
        self._key_timer_threads = []
        self._set_state(ClickerState.IDLE)

    def _wait_with_wander(
        self, total: float, fatigue: Fatigue,
        next_anchor: Optional[Zone] = None,
    ) -> bool:
        """Sleep `total` seconds, possibly interleaved with idle drifts and
        an optional pre-hover toward the next click area.

        ``next_anchor`` is the zone of the step whose click is about to
        fire (or, for pause/key waits, the next step that *has* a click
        area). When set, the cursor drifts partway toward that zone once
        per wait window — so stacked steps don't leave the cursor sitting
        on the previous click point until the last second. Random-gated
        and capped at one pre-hover per wait so it stays human.

        Returns True if stop was set.
        """
        remaining = total
        # Per-wait caps so long waits don't compound chunk-level rolls into
        # near-certain triggers. Hover = at most 1 visit. Idle drift = at
        # most 2 drifts per wait window. Pre-hover = at most 1.
        hovered = False
        pre_hovered = False
        drift_count = 0
        MAX_DRIFTS = 2
        while remaining > 0:
            if self._stop.is_set():
                return True

            # Pre-hover toward the next click area. Probability scales with
            # realism (more realism = more aggressive pre-positioning) but
            # is gated so sometimes the cursor just sits — that's also
            # human, and the random-chance memory rule applies.
            if (next_anchor is not None
                    and not pre_hovered
                    and remaining > 0.6
                    and random.random() < (0.45 + 0.40 * self.realism)):
                self._set_phase(
                    ClickerPhase.PRE_HOVERING,
                    "Drifting toward next target",
                )
                interrupted, elapsed = self._pre_hover_toward(
                    next_anchor, fatigue.multiplier())
                pre_hovered = True
                # Restore the WAITING phase so the remaining wait is
                # accurately labeled (the pre-hover is brief).
                self._set_phase(
                    ClickerPhase.WAITING,
                    (f"{self._step_phase_prefix()} — waiting"
                     if self.mode == "recorder" else "Waiting"),
                    max(0.0, remaining - elapsed),
                )
                if interrupted:
                    return True
                remaining -= elapsed
                if remaining <= 0:
                    break
                continue

            # Hover visits are rare and special — low base rate, capped at 1.
            has_hover = self.hover_zone is not None or any(
                z is not None for z in self.hover_zones
            )
            if not hovered:
                roll = random.random()
                gate_p = self.hover_frequency * 0.02
                meets_pos_conditions = (
                    self.hover_enabled
                    and has_hover
                    and remaining > self.hover_dwell_min + 1.0
                )
                # Trace WHY hover does or doesn't fire — the gate is the
                # most common reason users see "hover never visits" so
                # logging the four-way condition makes diagnosis trivial.
                if mouse_trace.is_enabled():
                    mouse_trace.event(
                        "hover_gate",
                        en=bool(self.hover_enabled),
                        has=bool(has_hover),
                        rem=round(remaining, 2),
                        dwell=round(self.hover_dwell_min, 2),
                        p=round(gate_p, 5),
                        roll=round(roll, 5),
                        pass_=bool(meets_pos_conditions and roll < gate_p),
                    )
                if meets_pos_conditions and roll < gate_p:
                    self._set_phase(
                        ClickerPhase.HOVERING, "Hover-zone visit",
                    )
                    interrupted, elapsed = self._do_hover_visit(fatigue.multiplier())
                    hovered = True
                    # Restore WAITING with the recomputed remainder so
                    # the status card's "X s left" reflects reality
                    # after the hover ate part of the wait.
                    self._set_phase(
                        ClickerPhase.WAITING,
                        (f"{self._step_phase_prefix()} — waiting"
                         if self.mode == "recorder" else "Waiting"),
                        max(0.0, remaining - elapsed),
                    )
                    if interrupted:
                        return True
                    remaining -= elapsed
                    continue

            # Idle drifts: lower rate, capped at MAX_DRIFTS.
            anchor_zone = self._wander_anchor_zone()
            if (drift_count < MAX_DRIFTS
                    and self.idle_wander_enabled
                    and (anchor_zone is not None or self.idle_wander_whole_screen)
                    and remaining > 0.8
                    and random.random() < self.idle_wander_frequency * 0.08):
                wander_zone = None if self.idle_wander_whole_screen else anchor_zone
                _bx, _by, _bw, _bh = self._resolve_screen_bounds()
                _screen_lrtb = (_bx, _by, _bx + _bw, _by + _bh)
                mouse_trace.event(
                    "idle_wander_start",
                    pad=int(self.idle_wander_padding),
                    whole=bool(self.idle_wander_whole_screen),
                )
                self._set_phase(ClickerPhase.WANDERING, "Idle wander")
                interrupted, elapsed = idle_wanderer.wander(
                    wander_zone, self.idle_wander_padding,
                    stop=self._stop, fatigue=fatigue.multiplier(),
                    screen_bounds=_screen_lrtb,
                )
                drift_count += 1
                self._set_phase(
                    ClickerPhase.WAITING,
                    (f"{self._step_phase_prefix()} — waiting"
                     if self.mode == "recorder" else "Waiting"),
                    max(0.0, remaining - elapsed),
                )
                if interrupted:
                    return True
                remaining -= elapsed
                continue
            chunk = min(remaining, random.uniform(0.2, 0.6))
            if self._stop.wait(chunk):
                return True
            remaining -= chunk
            # Background micro-jitter. Used to fire 30-75% per chunk
            # (~1.5 jitters/sec at default realism — visibly buzzy and
            # not at all how real humans sit). Now gated by both a low
            # per-chunk probability AND a minimum interval since the
            # last jitter, so the cursor stays still for stretches and
            # only occasionally shifts a couple px. Stillness IS human;
            # constant micro-bounce is a stronger bot tell than no
            # jitter at all.
            if self.realism > 0.10:
                self._maybe_micro_jitter()
        return False

    def _pre_hover_toward(
        self, anchor: Zone, fatigue_mult: float,
    ) -> tuple[bool, float]:
        """Drift cursor partway toward a future target zone — no click.

        Moves a random fraction of the way toward a random point inside
        ``anchor`` so the actual click move still has a meaningful aim
        phase (not "pre-position to the exact pixel"). Returns
        ``(interrupted, elapsed_seconds)``. Skips entirely when the
        cursor is already close enough that a pre-hover would just be
        noise.
        """
        try:
            cx, cy = dpi_cursor.get_pos()
        except Exception:
            return (False, 0.0)
        # If the cursor is already inside the upcoming zone, skip the
        # pre-hover entirely. Drifting "partway toward" a sample inside
        # a zone we're already in is just unnecessary motion that can
        # walk the cursor past the boundary on tight zones (where the
        # zone is small enough that a partway hop crosses out + back).
        try:
            if anchor.contains(int(cx), int(cy)):
                return (False, 0.0)
        except Exception:
            pass
        try:
            sample = anchor.random_point()
        except Exception:
            return (False, 0.0)
        dist = math.hypot(sample[0] - cx, sample[1] - cy)
        # Already close — let the click move handle it. A pre-hover that
        # only travels a few px would look more robotic, not less.
        if dist < 60.0:
            return (False, 0.0)
        # Travel 40-80% of the way; the click move covers the remainder
        # with the usual humanizer Bezier + jitter.
        frac = random.uniform(0.40, 0.80)
        dest = (
            int(cx + (sample[0] - cx) * frac),
            int(cy + (sample[1] - cy) * frac),
        )
        mouse_trace.event(
            "pre_hover", dx=int(sample[0] - cx), dy=int(sample[1] - cy),
            frac=round(frac, 2), dist=int(dist),
        )
        t0 = time.monotonic()
        # Slightly hurried, no overshoot — this is a setup motion, not an
        # aim. fatigue_mult * 0.85 keeps it feeling natural even at
        # high fatigue (where the click move itself slows).
        interrupted = humanizer.move(
            dest, stop=self._stop, fatigue=fatigue_mult * 0.85,
            overshoot_enabled=False, overshoot_probability=0.0,
        )
        return (bool(interrupted), time.monotonic() - t0)

    def _next_action_anchor(self) -> Optional[Zone]:
        """Walk forward from the current step looking for the next step
        with a known spatial anchor (CLICK / TRACK / COLOR). Skips PAUSE,
        LOOP, and KEY because they have no click area to pre-hover toward.
        Used by Pause and Key step waits so the cursor still drifts toward
        the upcoming click during macro gaps.
        """
        n = len(self.recorder_steps)
        if n == 0:
            return None
        for i in range(1, n + 1):
            idx = (self._step_idx + i) % n
            s = self.recorder_steps[idx]
            if s.kind == KIND_CLICK and s.zone is not None:
                return s.zone
            if s.kind == KIND_TRACK:
                if self.tracker is not None:
                    snap = self.tracker.snapshot_state()
                    if snap is not None and snap.is_locked:
                        z = self._tracker_zone()
                        if z is not None:
                            return z
                if s.capture_rect:
                    x1, y1, x2, y2 = s.capture_rect
                    return Zone.make_rect(x1, y1, x2, y2)
            if s.kind == KIND_COLOR:
                if s.zone is not None:
                    return s.zone
                if s.color_search_rect is not None:
                    x1, y1, x2, y2 = s.color_search_rect
                    return Zone.make_rect(x1, y1, x2, y2)
        return None

    def _next_zone_min_dim(self) -> Optional[int]:
        """Smaller dimension of the next click area, or None if unknown.

        Used by post-click drift + pre-hover gating to keep cursor
        motion proportional to where it's actually going next. We try
        the current step's zone first (the common case for
        ``click_count > 1`` or repeating cycles), then fall back to
        ``_next_action_anchor`` for sequences that hop between steps.
        """
        cand = None
        if self.mode == "recorder" and self.recorder_steps:
            if 0 <= self._step_idx < len(self.recorder_steps):
                step = self.recorder_steps[self._step_idx]
                cand = getattr(step, "zone", None)
                if cand is None and step.kind == KIND_TRACK:
                    cand = self._tracker_zone()
        if cand is None:
            cand = self._next_action_anchor()
        if cand is None and self.zone is not None:
            cand = self.zone
        if cand is None:
            return None
        try:
            x1, y1, x2, y2 = cand.aabb()
            return max(1, min(x2 - x1, y2 - y1))
        except Exception:
            return None

    # -- realism helpers ---------------------------------------------------

    def _human_delay(self, lo: float, hi: float) -> float:
        """Realism-scaled delay sample.

        Low realism (<0.05): plain uniform in [lo, hi].
        Otherwise: log-normal centered at the lower-middle of the range
        with a soft upper tail allowing occasional overshoot above `hi`
        (the "distracted briefly" tail real humans show in inter-action
        timing studies).

        ## Why this isn't a hard clamp anymore

        The earlier version computed ``val = exp(gauss(mu, sigma))`` then
        clamped via ``max(lo, min(upper_soft, val))``. On typical user
        ranges (0.5–1.0 s wide) this clamped ~60 % of samples to exactly
        ``lo`` or exactly ``upper_soft`` — visible as two huge spikes at
        the boundaries of the wait-time histogram, and a fingerprint in
        any inter-action timing analysis (the same boundary value
        repeats hundreds of times per session). See
        ``project_human_delay_clamp_fix`` memory for the diagnostic.

        Two changes:

        1. **Sigma scales with the user's log-space range** so the
           distribution actually fits inside ``[lo, hi + overshoot]``.
           At r=1.0 ~5% of samples exceed ``hi`` naturally; at r=0.5
           ~1% do. That preserves the "occasional overshoot" intent
           without forcing samples to the boundary by clamping.
        2. **Rejection sampling** replaces the hard clamp. Out-of-range
           samples are rejected and resampled (up to 8 retries). If
           we exhaust the budget — rare with a properly-scaled sigma —
           we fall back to a uniform draw inside ``[lo, upper_soft]``
           instead of pinning to a boundary.
        """
        r = max(0.0, min(1.0, self.realism))
        if r < 0.05 or hi <= lo:
            return random.uniform(lo, hi)
        span = hi - lo
        # Median sits 30% into the user's range — most clicks feel snappy.
        median = lo + 0.30 * span
        mu = math.log(max(0.05, median))
        # Allow occasional overshoot up to hi + 50% of span at max realism.
        upper_soft = hi + span * 0.5 * r
        # Scale sigma to the user's log-space range so most samples land
        # in [lo, upper_soft] without the old hard-clamp spike. At r=1.0
        # we sit roughly 1.65σ below hi (≈5% above-hi tail); at r=0.5
        # we sit ~2.5σ below hi (≈1% above-hi tail).
        log_lo = math.log(max(0.05, lo))
        log_hi = math.log(max(0.05, hi))
        span_log = max(0.05, log_hi - log_lo)
        sigma = span_log * (0.20 + 0.30 * r)
        # Rejection-sample: keep the first in-range draw. Boundary
        # clamping is what created the histogram spikes; rejection
        # preserves the log-normal shape inside the allowed window.
        for _ in range(8):
            val = math.exp(random.gauss(mu, sigma))
            if lo <= val <= upper_soft:
                return val
        # Budget exhausted (very rare with the recalibrated sigma).
        # Uniform fallback — still random, still in range, never
        # pins to an exact boundary value.
        return lo + random.random() * (upper_soft - lo)

    def _maybe_micro_jitter(self) -> None:
        """Decide whether to fire a single micro-jitter, gated by both
        a low per-chunk probability AND a minimum interval since the
        last jitter.

        Real human idle isn't continuous tremor — it's long stillness
        punctuated by occasional small shifts (settling, posture
        adjustment). The previous implementation fired ~1.5 jitters/sec
        at default realism, which read as a constant 1-3 px buzz. This
        targets ~1 jitter every 8-30 seconds depending on realism, with
        the exact cadence randomized so it isn't periodic.
        """
        now = time.monotonic()
        # Minimum-gap gate: even if probability passes, never fire two
        # jitters within ``_next_micro_jitter_min_gap`` seconds. The gap
        # is randomized per fire so consecutive jitters aren't on a
        # detectable rhythm.
        if now - self._last_micro_jitter_at < self._next_micro_jitter_min_gap:
            return
        # Per-chunk probability — small at any realism. Real idle:
        #   realism 0.3 → ~1.5% per chunk → ~1 jitter/30 s
        #   realism 0.5 → ~2.5% per chunk → ~1 jitter/20 s
        #   realism 1.0 → ~5%   per chunk → ~1 jitter/10 s
        gate = 0.005 + 0.045 * max(0.0, min(1.0, self.realism))
        if random.random() >= gate:
            return
        self._last_micro_jitter_at = now
        # Next minimum gap: 4-15 s, biased longer at low realism so a
        # mostly-still session stays mostly still even through a long
        # wait window.
        self._next_micro_jitter_min_gap = random.uniform(
            4.0 + 6.0 * (1.0 - self.realism),
            10.0 + 5.0 * (1.0 - self.realism),
        )
        self._micro_jitter_tick()

    def _micro_jitter_tick(self) -> None:
        """Execute one micro-jitter. Caller is responsible for gating
        frequency (see ``_maybe_micro_jitter``); this just runs the
        physical movement.

        A single 1-2 px curved drift over 80-180 ms — looks like a
        settling hand, not a pixel snap. Most of the time the radius
        sits at 1-2 px (sensor-noise scale); occasionally bumps to 3 px
        for a slightly larger "shift" that mimics posture adjustment.
        """
        try:
            cx, cy = dpi_cursor.get_pos()
        except Exception:
            return
        angle = random.uniform(0.0, 2.0 * math.pi)
        # Bimodal: 80% small (1-2 px tremor), 20% slightly larger
        # (2-3 px shift). Single uniform 1-3 was too uniform-looking.
        if random.random() < 0.80:
            radius = random.uniform(1.0, 2.0)
        else:
            radius = random.uniform(2.0, 3.0)
        tx = int(round(cx + radius * math.cos(angle)))
        ty = int(round(cy + radius * math.sin(angle)))
        duration = random.uniform(0.080, 0.180)
        mouse_trace.event("jitter_tick",
                          dx=tx - cx, dy=ty - cy, dur=round(duration, 3))
        try:
            humanizer.drift((tx, ty), self._stop, duration,
                            curvature=random.uniform(0.0, 0.20))
        except Exception:
            pass

    def _maybe_distraction_spike(self) -> bool:
        """Inject a "looked away" pause every 60-180 clicks.

        Distinct from the explicit Breaks feature — these are short,
        unannounced delays (3-12s scaled by realism) that just happen.
        Returns True if interrupted."""
        if self.realism < 0.2:
            return False
        self._clicks_since_distraction += 1
        if self._clicks_since_distraction < self._next_distraction_at:
            return False
        spike = random.uniform(3.0, 12.0) * (0.5 + self.realism)
        self._clicks_since_distraction = 0
        self._next_distraction_at = random.randint(60, 180)
        self._set_phase(
            ClickerPhase.DISTRACTED, "Looked away briefly", spike,
        )
        # Logged so a "no clicks for 8 seconds" report is explained by
        # the log itself instead of looking like a stalled engine.
        self.log.info(
            "distraction_spike %s duration=%.2fs next_in_clicks=%d",
            self._step_log_tag(), spike, self._next_distraction_at,
        )
        return self._stop.wait(spike)

    def _muscle_memory_factor(self) -> float:
        """Movement-duration multiplier: cold at session start, warm later.

        Returns ~1.20 for the first click, decaying exponentially to ~0.92
        by ~click 10 then plateauing. Mimics how repeated motor patterns
        speed up. Scales by realism (no effect at realism≈0)."""
        if self.realism < 0.1:
            return 1.0
        try:
            n = int(self.stats.snapshot().get("total", 0))
        except Exception:
            n = 0
        floor = 1.0 - 0.08 * self.realism
        cold = 1.0 + 0.20 * self.realism
        return floor + (cold - floor) * math.exp(-n / 5.0)

    def _wander_anchor_zone(self) -> Optional[Zone]:
        """Pick a zone to anchor idle drifts to. Falls back across modes."""
        if self.zone is not None:
            return self.zone
        if self.mode == "recorder":
            for s in self.recorder_steps:
                if s.zone is not None:
                    return s.zone
            # Fall back to whichever track step is currently locked, if any.
            tz = self._tracker_zone()
            if tz is not None:
                return tz
        return None

    def _read_template_png(self, rel_or_abs_path: str):
        """cv2.imread with a project-root fallback so per-step PNGs resolve
        even when the cwd isn't the install dir (frozen .exe, alt launcher,
        etc.). Returns the BGR ndarray or None on failure."""
        try:
            import cv2 as _cv2
            import os as _os
            img = _cv2.imread(rel_or_abs_path, _cv2.IMREAD_COLOR)
            if img is None and not _os.path.isabs(rel_or_abs_path):
                # Per-step PNGs are stored relative to the writable install
                # root (next to the .exe when frozen, repo root in dev) —
                # NOT relative to this module's dir, which is _MEIPASS in a
                # frozen build and never holds user-captured templates.
                from utils.paths import writable_root
                img = _cv2.imread(
                    str(writable_root() / rel_or_abs_path),
                    _cv2.IMREAD_COLOR,
                )
            return img
        except Exception:
            self.log.debug(
                "template png read failed: path=%r", rel_or_abs_path,
                exc_info=True,
            )
            return None

    def _resolve_screen_bounds(self) -> tuple[int, int, int, int]:
        """Return ``(x, y, w, h)`` of the engine's target monitor.

        Falls back to the primary monitor via GetSystemMetrics when the
        bridge hasn't pushed bounds yet (e.g. tests, hot-paths during
        shutdown). All ambient features (post-click drift, idle wander,
        watchdog corners, tracker locate) read through this so the
        Settings card's monitor selector works without the engine
        knowing anything about Qt.
        """
        b = self.target_screen_bounds
        if b and b[2] > 0 and b[3] > 0:
            return b
        try:
            import ctypes
            sw = ctypes.windll.user32.GetSystemMetrics(0)
            sh = ctypes.windll.user32.GetSystemMetrics(1)
        except Exception:
            sw, sh = 1920, 1080
        return (0, 0, sw, sh)

    _ANNOUNCE_COOLDOWN_S: float = 30.0

    def _announce_track_error(self, step_id: str, reason: str) -> None:
        """Fire ``on_track_error`` for ``step_id`` with a per-step cooldown
        so a persistently broken step doesn't spam the toast queue but
        also doesn't go silent forever after the first hit. Safe to call
        from the engine thread; the bridge marshals to the Qt main thread."""
        now = time.monotonic()
        last = self._track_error_last_at.get(step_id, 0.0)
        if now - last < self._ANNOUNCE_COOLDOWN_S:
            return
        self._track_error_last_at[step_id] = now
        cb = self.on_track_error
        if cb is None:
            return
        try:
            cb(step_id, reason)
        except Exception:
            pass

    def _announce_color_no_match(self, step_id: str, secs_since: float) -> None:
        """Surface a "color step has been searching for X s" warn toast on
        the same cooldown shape as track errors."""
        now = time.monotonic()
        last = self._color_no_match_last_at.get(step_id, 0.0)
        if now - last < self._ANNOUNCE_COOLDOWN_S:
            return
        self._color_no_match_last_at[step_id] = now
        idx = self._step_label_for(step_id)
        msg = (
            f"⚠ {idx} has found no matching pixels for "
            f"{int(secs_since)} s — check tolerance, click area, or monitor."
        )
        self._announce_engine_halt(msg, "warn")

    def _announce_track_stuck(self, step_id: str, secs_since: float) -> None:
        """Surface a "track step has been searching for X s" warn toast.
        Distinct from ``_announce_track_error`` (which is for the *load*
        failure of a missing/unreadable PNG) — this one fires when the
        template loads fine but the tracker can't lock onto a match."""
        now = time.monotonic()
        # Reuse the track-error cooldown bucket so we don't double-toast
        # when load + lock are both failing.
        last = self._track_error_last_at.get(step_id, 0.0)
        if now - last < self._ANNOUNCE_COOLDOWN_S:
            return
        self._track_error_last_at[step_id] = now
        idx = self._step_label_for(step_id)
        msg = (
            f"⚠ {idx} has been searching for {int(secs_since)} s — "
            "target may be off-screen or hidden."
        )
        self._announce_engine_halt(msg, "warn")

    def _announce_step_timeout(self, step: "RecorderStep",
                                secs_elapsed: float) -> None:
        """Surface a "step timed out" toast when a Track or Color step's
        per-step timeout fires. Cooldowned by step_id so a fast loop that
        keeps tripping the same timeout doesn't spam the toast layer.

        The action ("skipped" vs "engine stopped") is included so the user
        can tell at a glance what the engine did about it without having
        to inspect the log.
        """
        sid = step.step_id
        now = time.monotonic()
        last = self._step_timeout_last_at.get(sid, 0.0)
        if now - last < self._ANNOUNCE_COOLDOWN_S:
            return
        self._step_timeout_last_at[sid] = now
        idx = self._step_label_for(sid)
        action = ("engine stopped" if step.on_timeout == "stop"
                  else "skipped")
        self._announce_engine_halt(
            f"⚠ {idx} timed out after {int(secs_elapsed)} s — {action}.",
            "warn",
        )

    def _announce_loop_orphan(self, step_id: str) -> None:
        """Loop step's ``loop_target_step_id`` no longer exists. Cooldowned
        so a forever-loop on the orphan doesn't spam toasts."""
        now = time.monotonic()
        last = self._loop_orphan_last_at.get(step_id, 0.0)
        if now - last < self._ANNOUNCE_COOLDOWN_S:
            return
        self._loop_orphan_last_at[step_id] = now
        idx = self._step_label_for(step_id)
        self._announce_engine_halt(
            f"⚠ {idx} (Loop) points to a deleted step — skipping.",
            "warn",
        )

    def _announce_engine_halt(self, msg: str, level: str) -> None:
        """Fire ``on_engine_halt`` with no de-dupe (callers gate cooldowns
        themselves where appropriate). Safe to call from any thread."""
        cb = self.on_engine_halt
        if cb is None:
            return
        try:
            cb(msg, level)
        except Exception:
            pass

    def _step_label_for(self, step_id: str) -> str:
        """Render a step's display label ("Step 3 (track)" or
        "Step 3 'Drop logs' (track)") for toasts. Including the
        user-set label when present makes timeout / no-match toasts
        actually scannable in long sequences with multiple track steps.
        """
        for i, s in enumerate(self.recorder_steps):
            if getattr(s, "step_id", None) == step_id:
                user_label = (getattr(s, "label", "") or "").strip()
                if user_label:
                    return f"Step {i + 1} '{user_label}' ({s.kind})"
                return f"Step {i + 1} ({s.kind})"
        return "A step"

    def _announce_session_complete(self, reason: str) -> None:
        """Fire ``on_session_complete`` once; engine loop is responsible
        for breaking out of ``_run`` after this returns."""
        cb = self.on_session_complete
        if cb is None:
            return
        try:
            cb(reason)
        except Exception:
            pass

    def _activate_track_step(self, step: RecorderStep) -> None:
        """Make sure ``self.tracker`` is matching ``step``'s template.

        Lazy: a no-op when the same step was active on the previous tick
        (we still re-push settings since they're cheap and pick up edits).
        On a new step, loads the per-step PNG, seeds the last-known position
        from the captured rect, and forces an immediate first locate so the
        tracker doesn't need a full App-loop tick to lock.
        """
        if self.tracker is None:
            from .tracker import TrackerConfig as _TrackerConfig
            self.tracker = TemplateTracker(_TrackerConfig())
        same_step = self._active_track_step_id == step.step_id
        if not same_step:
            if not step.template_path or not step.capture_rect:
                self._announce_track_error(step.step_id, "no_template_path")
                return
            primary = self._read_template_png(step.template_path)
            if primary is None:
                self._announce_track_error(step.step_id, "missing_or_unreadable")
                return
            extras: list = []
            for ep in step.extra_template_paths or []:
                img = self._read_template_png(ep)
                if img is not None:
                    extras.append(img)
            self.tracker.set_templates(
                primary, extras, tuple(step.capture_rect))
            self._active_track_step_id = step.step_id
            # Successful load — drop any prior cooldown so a later
            # regression on the same step toasts again right away.
            self._track_error_last_at.pop(step.step_id, None)
        # Always re-push per-step settings (cheap; covers user edits).
        j = max(0.0, min(0.5, float(step.tracker_scale_jitter)))
        with self.tracker._lock:
            self.tracker.cfg.match_threshold = float(step.tracker_threshold)
            self.tracker.cfg.search_radius = int(step.tracker_search_radius)
            self.tracker.cfg.full_rescan_on_loss = bool(step.tracker_full_rescan)
            self.tracker.cfg.scale_min = max(0.5, 1.0 - j)
            self.tracker.cfg.scale_max = min(1.5, 1.0 + j)
            self.tracker.cfg.scale_steps = 1 if j < 1e-3 else 5
            self.tracker.cfg.update_rate_hz = float(step.tracker_update_rate_hz)
        if not same_step:
            # First-locate uses the target monitor's bounds so a tracker
            # on a non-primary screen can still cold-lock without waiting
            # a full App-loop tick. mss / cv2 work in absolute virtual-
            # desktop coords, so passing width × height is sufficient
            # here (the tracker uses GetCursorPos for offset).
            _bx, _by, sw, sh = self._resolve_screen_bounds()
            try:
                self.tracker.locate(sw, sh)  # immediate first lock
            except Exception:
                pass

    def _tracker_zone(self) -> Optional[Zone]:
        """Build a click-zone rectangle from the tracker's current match.

        Returns ``None`` when the tracker isn't currently locked onto its
        target — the click loop uses that as a "skip this cycle" signal.

        The zone size comes from the template that *won* the last locate
        (state.last_template_size), not always the primary, so that clicks
        on a side-view match aren't sized by the front-view template.
        """
        if self.tracker is None or not self.tracker.has_template():
            return None
        snap = self.tracker.snapshot_state()
        if not snap.is_locked or snap.last_position is None:
            return None
        cx, cy = snap.last_position
        tw, th = snap.last_template_size
        # Fallback to primary size if state hasn't been written yet.
        if tw <= 0 or th <= 0:
            tw, th = self.tracker.cfg.template_size
        if tw <= 0 or th <= 0:
            return None
        x1 = cx - tw // 2
        y1 = cy - th // 2
        x2 = x1 + tw
        y2 = y1 + th
        return Zone.make_rect(x1, y1, x2, y2)

    def _post_click_micro_wander(self, fatigue_mult: float) -> bool:
        """Tiny curved drift right after a click.

        Always runs — keeps the cursor visibly alive between clicks even when
        Idle wander is off. Drift is short (5-30 px, 0.10-0.25 s) so it never
        eats meaningful inter-click time. Result: cursor never freezes on the
        exact click point, which is one of the loudest auto-clicker tells.

        Drift radius shrinks when the next click lands in a tight zone:
        on a 10×10 zone a 5-30 px drift jumps fully outside, then the
        next move has to come back, which adds a complex trajectory and
        an opportunity for the click to mis-land near the boundary. For
        a tight upcoming zone we keep the drift small (2-8 px) so the
        cursor stays in/near the same area.
        """
        try:
            cx, cy = dpi_cursor.get_pos()
        except Exception:
            return False
        # Look up the next click area to size the drift sensibly.
        next_zone_min_dim = self._next_zone_min_dim()
        if next_zone_min_dim is not None and next_zone_min_dim <= 20:
            dist_lo, dist_hi = 2.0, 8.0
        else:
            dist_lo, dist_hi = 5.0, 30.0
        angle = random.uniform(0.0, 2.0 * math.pi)
        dist = random.uniform(dist_lo, dist_hi)
        tx = int(round(cx + dist * math.cos(angle)))
        ty = int(round(cy + dist * math.sin(angle)))
        # Clamp inside the target monitor (and clear of the watchdog's
        # 2-px corner zone) so a corner-adjacent click's drift can't
        # trip the emergency stop.
        bx, by, sw, sh = self._resolve_screen_bounds()
        margin = humanizer.SAFE_MARGIN
        tx = max(bx + margin, min(bx + sw - margin, tx))
        ty = max(by + margin, min(by + sh - margin, ty))
        duration = random.uniform(0.10, 0.25) * max(1.0, fatigue_mult)
        curvature = random.uniform(0.15, 0.45)
        mouse_trace.event(
            "post_click_drift",
            cx=int(round(cx)), cy=int(round(cy)),
            tx=tx, ty=ty, dur=round(duration, 4),
        )
        from utils import humanizer as _h
        return _h.drift((tx, ty), self._stop, duration, curvature)

    def _pick_hover_zone(self) -> Optional[Zone]:
        """Choose which hover zone to visit. Honors hover_selection mode."""
        # Priority: multi-zone list. Fall back to legacy single zone.
        zones = [z for z in self.hover_zones if z is not None]
        if not zones:
            return self.hover_zone if self.hover_zone is not None else None
        if self.hover_selection == "order":
            z = zones[self._hover_idx % len(zones)]
            self._hover_idx = (self._hover_idx + 1) % len(zones)
            return z
        return random.choice(zones)

    def _do_hover_visit(self, fatigue_mult: float) -> tuple[bool, float]:
        """Drift into a hover zone and dwell there for a randomized time."""
        t0 = time.monotonic()
        zone = self._pick_hover_zone()
        if zone is None:
            # The hover gate passed but no zone is configured. Surface
            # this so the user can see exactly why hover never visits
            # — easiest way to spot "I forgot to draw a hover zone".
            mouse_trace.event("hover_no_zone")
            return False, 0.0
        target = zone.random_point()
        duration = random.uniform(0.45, 0.95) * fatigue_mult
        curvature = random.uniform(0.3, 0.7)
        dwell = random.uniform(self.hover_dwell_min, self.hover_dwell_max) * fatigue_mult
        mouse_trace.event(
            "hover_visit_start",
            tx=int(target[0]), ty=int(target[1]),
            dur=round(duration, 3),
            dwell=round(dwell, 2),
        )
        # Surface hover visits in the session log so a user reporting "the
        # engine looks frozen" can see "no, it was hovering for 3.4s at
        # (1234, 567)" rather than guessing.
        self.log.info(
            "hover_start %s target=(%d,%d) drift=%.2fs dwell=%.2fs",
            self._step_log_tag(),
            int(target[0]), int(target[1]),
            duration, dwell,
        )
        # clamp=False so hover zones drawn on a non-primary monitor (or
        # near a screen corner) aren't pushed back inside the engine's
        # current safe rect. Hover doesn't click, so the corner-stop
        # watchdog isn't relevant here.
        if humanizer.drift(target, self._stop, duration, curvature, clamp=False):
            mouse_trace.event("hover_visit_end", interrupted=True, phase="drift")
            return True, time.monotonic() - t0
        if self._stop.wait(dwell):
            mouse_trace.event("hover_visit_end", interrupted=True, phase="dwell")
            return True, time.monotonic() - t0
        mouse_trace.event("hover_visit_end", interrupted=False)
        return False, time.monotonic() - t0

    def _peek_recorder_step(self) -> Optional[RecorderStep]:
        """Return the current step (does NOT advance). Pause / Loop steps
        are honored even without a zone. Click steps without a zone are
        skipped. Returns None if no usable step exists."""
        n = len(self.recorder_steps)
        if n == 0:
            return None
        for _ in range(n):
            step = self.recorder_steps[self._step_idx]
            # User-disabled steps rotate past silently — same effect as
            # commenting the step out for testing. No toast (it's intentional).
            if not getattr(step, "enabled", True):
                self._step_idx = (self._step_idx + 1) % n
                self._step_clicks_done = 0
                continue
            if step.kind in (KIND_PAUSE, KIND_LOOP):
                return step
            if step.kind == KIND_TRACK and step.template_path:
                return step
            if step.kind == KIND_COLOR and step.color_target_rgb is not None:
                return step
            if step.kind == KIND_CLICK and step.zone is not None:
                return step
            if (step.kind == KIND_KEY and step.key_combo
                    and parse_combo(step.key_combo) is not None):
                return step
            # Step is missing its required data — surface why so the user
            # isn't left wondering why the engine "skipped past" their step.
            self._announce_step_skipped(step)
            self._step_idx = (self._step_idx + 1) % n
            self._step_clicks_done = 0
        return None

    # Tighter cooldown specifically for step-skipped messages. The
    # default 30 s was too quiet — a user debugging "why doesn't my KEY
    # step run" needed to see the warning loud + often.
    _STEP_SKIP_COOLDOWN_S: float = 5.0

    def _announce_step_skipped(self, step: RecorderStep) -> None:
        """Surface a warn toast AND set the SKIPPED phase when the engine
        rotates past a step that's missing required data. Critical for
        keyboard steps — without this, an unbound key combo silently
        disappears from the cycle and the user thinks the engine is
        broken. Keeps the phase active so the topbar shows the issue
        between cooldowned toasts."""
        sid = step.step_id
        label = self._step_label_for(sid)
        if step.kind == KIND_KEY:
            reason = "no key bound. Use 🎯 Press a key to bind one."
        elif step.kind == KIND_CLICK:
            reason = "no click area. Pick one with the body's “Set click area” button."
        elif step.kind == KIND_TRACK:
            reason = "no target captured. Use “🎯 Capture target”."
        elif step.kind == KIND_COLOR:
            reason = "no color picked. Use “🎯 Pick target color”."
        else:
            reason = "missing required data."
        # Set the SKIPPED phase every time, so the topbar reflects the
        # current state of the engine even when the toast is cooled down.
        # 5 s lets the user actually see it before the next cycle moves
        # on (the silent rotation through _peek_recorder_step is otherwise
        # too fast to notice).
        self._set_phase(
            ClickerPhase.SKIPPED,
            f"{label} skipped — {reason}",
            5.0,
        )
        now = time.monotonic()
        last = self._step_skip_last_at.get(sid, 0.0)
        # Always fire on first hit (last==0.0); after that, throttle to
        # _STEP_SKIP_COOLDOWN_S so a tight rotation through 3 broken
        # steps doesn't spam the toast layer but still re-fires every 5 s.
        if last > 0 and now - last < self._STEP_SKIP_COOLDOWN_S:
            return
        self._step_skip_last_at[sid] = now
        self.log.info("skipping step %s (%s): %s", sid, step.kind, reason)
        self._announce_engine_halt(f"⚠ {label} skipped — {reason}", "warn")

    def _resolve_loop_target(self, step: RecorderStep) -> Optional[int]:
        """Look up a loop step's target by step_id; return its current index
        in ``recorder_steps`` or ``None`` if missing."""
        if not step.loop_target_step_id:
            return None
        for i, s in enumerate(self.recorder_steps):
            if s.step_id == step.loop_target_step_id:
                return i
        return None

    def _get_engine_mss(self):
        """Lazy persistent mss handle for the engine thread. mss instances
        aren't thread-safe, so this MUST only be touched from the click
        thread (the only consumer)."""
        if self._mss_engine is None:
            import mss as _mss
            self._mss_engine = _mss.mss()
        return self._mss_engine

    def _find_color_target(self, step: RecorderStep
                            ) -> Optional[tuple[int, int]]:
        """Snapshot the configured screen rect and return a random pixel
        whose RGB is within ``step.color_tolerance`` of
        ``step.color_target_rgb``. Returns absolute screen coords or
        ``None`` if nothing matches.

        Bounded by ``step.color_search_rect`` (set to the picked monitor's
        bounds when the user picks a color) so multi-monitor users don't
        pay for the full virtual desktop on every cycle. Falls back to the
        full virtual screen if the rect isn't set (legacy configs).
        """
        if step.color_target_rgb is None:
            return None
        try:
            import numpy as _np
            import cv2 as _cv2
            tol = max(0, int(step.color_tolerance))

            # All accepted colors: primary + every extra. Each gets its own
            # inRange mask; the masks are OR'd together so a pixel that
            # matches ANY color counts as a hit.
            colors: list[tuple[int, int, int]] = [step.color_target_rgb]
            colors.extend(step.color_extra_rgbs or [])

            sct = self._get_engine_mss()
            if step.color_search_rect is not None:
                bl, bt, br, bb = step.color_search_rect
            else:
                v = sct.monitors[0]
                bl, bt = int(v["left"]), int(v["top"])
                br, bb = bl + int(v["width"]), bt + int(v["height"])

            # If the user drew a "click area" zone, intersect its AABB with
            # the search rect so we capture and scan only the relevant pixels
            # — keeps HUD elements / on-screen UI of the same color out of
            # the candidate set, and is cheaper too.
            if step.zone is not None:
                zx1, zy1, zx2, zy2 = step.zone.aabb()
                bl = max(bl, int(zx1))
                bt = max(bt, int(zy1))
                br = min(br, int(zx2))
                bb = min(bb, int(zy2))
                if br - bl < 2 or bb - bt < 2:
                    # Zone is outside the search rect (or off-screen entirely).
                    return None

            mon = {"left": bl, "top": bt,
                   "width": br - bl, "height": bb - bt}
            shot = sct.grab(mon)
            h, w = shot.height, shot.width

            # Zero-copy view of the BGRA buffer; slice to BGR. Avoids the
            # full-buffer copy that ``np.array(shot)`` does.
            frame = _np.frombuffer(shot.bgra, dtype=_np.uint8).reshape(h, w, 4)
            screen = frame[:, :, :3]  # BGR

            # Auto-downsample for large scan areas. inRange is O(pixels),
            # so halving each axis cuts the mask scan to ~25% of its
            # original cost. Click jitter (±1–3 px) absorbs the half-px
            # snap on the recovered coord so accuracy is unaffected for
            # the kinds of regions the eyedropper picks.
            if h * w > 4_000_000:
                screen = screen[::2, ::2]
                step_px = 2
            else:
                step_px = 1

            mask = None
            for (tr, tg, tb) in colors:
                lower = _np.array(
                    [max(0, tb - tol), max(0, tg - tol), max(0, tr - tol)],
                    dtype=_np.uint8)
                upper = _np.array(
                    [min(255, tb + tol), min(255, tg + tol), min(255, tr + tol)],
                    dtype=_np.uint8)
                m = _cv2.inRange(screen, lower, upper)
                mask = m if mask is None else _cv2.bitwise_or(mask, m)

            # findNonZero is a single C call; faster than np.where +
            # parallel index arrays for sparse-to-medium match counts.
            pts = _cv2.findNonZero(mask) if mask is not None else None
            if pts is None or len(pts) == 0:
                return None

            # Distance-anchored selection. Without an anchor, picking a
            # random match per cycle scatters clicks across antialiased
            # edges / hover glows. With one, clicks settle on a stable
            # center within ~3 cycles. Anchor priority:
            #   1. last successful click for this step (cached across cycles)
            #   2. cluster centroid (geometric center of the match cluster)
            # We sort all matches by squared distance to the anchor, then
            # walk in order returning the first that satisfies the zone
            # shape (rect zones always pass; polygon/circle may not).
            n = len(pts)
            need_filter = (
                step.zone is not None and step.zone.shape != "rect"
            )
            coords = pts[:, 0, :].astype(_np.int32)
            coords[:, 0] = coords[:, 0] * step_px + int(mon["left"])
            coords[:, 1] = coords[:, 1] * step_px + int(mon["top"])
            hint = self._color_last_click_pos.get(step.step_id)
            if hint is not None:
                ax, ay = int(hint[0]), int(hint[1])
            else:
                ax = int(coords[:, 0].mean())
                ay = int(coords[:, 1].mean())
            dx = coords[:, 0] - ax
            dy = coords[:, 1] - ay
            d2 = dx * dx + dy * dy
            order = _np.argsort(d2)
            tries = min(n, 64) if need_filter else 1
            for ix in order[:tries]:
                x = int(coords[int(ix), 0])
                y = int(coords[int(ix), 1])
                if not need_filter or step.zone.contains(x, y):
                    return (x, y)
            # Sampled tries all landed outside the shape (very narrow
            # polygon vs. a sparse colour). Fall back to a full scan of
            # all candidates so we don't miss a real hit.
            if need_filter:
                for ix in order:
                    x = int(coords[int(ix), 0])
                    y = int(coords[int(ix), 1])
                    if step.zone.contains(x, y):
                        return (x, y)
            return None
        except Exception:
            self.log.debug(
                "color target search failed: step_id=%r",
                getattr(step, "step_id", None), exc_info=True,
            )
            return None

    def _advance_recorder_step(self, reason: str = "unspecified") -> None:
        """Move to the next step and reset the click-in-step counter.

        ``reason`` is logged so a session log alone tells the story of why
        each step ended (click_count_met, pause_complete, key_complete,
        loop_orphan, loop_exhausted, track_timeout, color_timeout, etc.).
        """
        n = len(self.recorder_steps)
        if n == 0:
            return
        cur_step = self.recorder_steps[self._step_idx]
        self._step_target_present.pop(getattr(cur_step, "step_id", ""), None)
        from_tag = self._step_log_tag()
        self._step_idx = (self._step_idx + 1) % n
        self._step_clicks_done = 0
        self.log.info(
            "step_advance from=%s to=%s reason=%s",
            from_tag, self._step_log_tag(), reason,
        )

    def _react_to_fresh_target(self, step_id: str) -> bool:
        """Pause for a randomized 'see → decide → move' delay when a TRACK
        lock or COLOR match has just transitioned from absent to present.
        Returns True if interrupted (caller should bail). Skips the wait
        when the same target was already present last cycle (you don't
        re-react to a target you're still clicking on)."""
        prev = self._step_target_present.get(step_id, False)
        self._step_target_present[step_id] = True
        if prev:
            return False
        delay = self._reaction_delay()
        if delay <= 0:
            return False
        return self._stop.wait(delay)

    def _reaction_delay(self) -> float:
        """Sample a humanlike reaction delay scaled by the realism dial.

        At realism 1.0 the range is ~100-400 ms; at 0.5 it's ~50-200 ms;
        at 0 it's effectively instant. Real human reaction to a visible
        stimulus is 200-300 ms median, with the move itself starting a
        bit before; this models the gap between target appearing and
        the cursor leaving its current position."""
        r = max(0.0, min(1.0, self.realism))
        if r <= 0.05:
            return 0.0
        return random.uniform(0.100 * r, 0.400 * r)

    def _apply_zone_drift(self, zone: Zone, key: str) -> None:
        """Write the current drift offset + σ-scale onto ``zone`` so the
        next ``random_point()`` call samples from a slowly-walking
        Gaussian instead of a stationary one.
        """
        x1, y1, x2, y2 = zone.aabb()
        w = max(2, x2 - x1)
        h = max(2, y2 - y1)
        # Cap drift to a quarter of the smaller dimension so the mean
        # never leaves a sensible band — small zones drift less.
        max_offset = max(2.0, min(w, h) * 0.25)
        ox, oy, sscale = self._advance_zone_drift(key, max_offset)
        zone.drift_offset_x = ox
        zone.drift_offset_y = oy
        zone.sigma_scale = sscale

    def _advance_zone_drift(self, key: str, max_offset: float
                             ) -> tuple[float, float, float]:
        """Advance the drift state for ``key`` by one step and return
        ``(off_x, off_y, sigma_scale)``. Heading walks slowly, offset
        accumulates 0–3 px per call along the heading, σ-scale grows
        from 1.0 toward ~1.4 over a session (asymptotic on call count).
        """
        state = self._zone_drift_state.get(key)
        if state is None:
            state = {
                "off_x": 0.0,
                "off_y": 0.0,
                "heading": random.uniform(0.0, 2.0 * math.pi),
                "calls": 0,
            }
            self._zone_drift_state[key] = state
        state["calls"] = int(state["calls"]) + 1
        state["heading"] = float(state["heading"]) + random.uniform(-0.2, 0.2)
        step_len = random.uniform(0.0, 3.0)
        state["off_x"] = float(state["off_x"]) + step_len * math.cos(state["heading"])
        state["off_y"] = float(state["off_y"]) + step_len * math.sin(state["heading"])
        # Magnitude clamp so we don't push the mean off the zone forever;
        # when clamped, also flip heading so we drift back toward center.
        mag = math.hypot(state["off_x"], state["off_y"])
        if mag > max_offset and mag > 0:
            k = max_offset / mag
            state["off_x"] *= k
            state["off_y"] *= k
            state["heading"] = float(state["heading"]) + math.pi
        sigma_scale = 1.4 - 0.4 * math.exp(-state["calls"] / 200.0)
        return (float(state["off_x"]), float(state["off_y"]), float(sigma_scale))

    def _anti_cluster(self, target: tuple[int, int],
                       zone: Optional[Zone] = None) -> tuple[int, int]:
        """Repel target away from recent click points.

        On out-of-zone repulsion (tight zones where the push direction
        leaves the shape), don't fall back to the original target — that
        defeats the feature entirely. Instead, draw 5 fresh zone samples
        and return the one with the largest minimum distance from the
        recent deque (i.e. the candidate that's furthest from any cluster
        point). This keeps anti-cluster behavior even on narrow polygons.
        """
        if not self._recent:
            return target
        tx, ty = float(target[0]), float(target[1])
        # Zone-aware effective radius. The user's configured radius is a
        # cap, not a target — for tight zones (small game buttons),
        # repelling by 18+ px from the previous click pushes the cursor
        # to or past the button edge, making the second click miss. We
        # clamp the effective radius to ~1/4 of the zone's smaller
        # dimension so anti-cluster can never dominate the zone
        # geometry. For zones bigger than ~32 px (the common case),
        # the configured radius is used as-is.
        z = zone if zone is not None else self.zone
        if z is not None:
            try:
                x1, y1, x2, y2 = z.aabb()
                zone_min_dim = max(2, min(x2 - x1, y2 - y1))
                # Tight zones: the user explicitly drew a small box around
                # a single small target. Anti-cluster's bot-evasion benefit
                # is moot — the zone IS the click target — and any
                # repulsion can push the click onto a margin where the
                # actual game element doesn't reach. Skip entirely.
                if zone_min_dim <= 16:
                    return target
                # /4 keeps the second click in the inner half of the
                # zone where the actual clickable element usually lives,
                # not at the edge where it might overlap the boundary.
                ceiling = max(2.0, zone_min_dim / 4.0)
            except Exception:
                ceiling = float("inf")
        else:
            ceiling = float("inf")
        min_sep = max(2.0, min(float(self.anti_cluster_radius), ceiling))
        for (px, py) in self._recent:
            dx, dy = tx - px, ty - py
            d = math.hypot(dx, dy)
            if d < min_sep and d > 0.5:
                push = (min_sep - d) + 2
                tx += dx / d * push
                ty += dy / d * push
        # Re-clip to zone so we don't push outside.
        z = zone if zone is not None else self.zone
        if z is not None and not z.contains(int(tx), int(ty)):
            best = None
            best_min_d = -1.0
            for _ in range(5):
                cand = z.random_point()
                cmin = min(
                    (math.hypot(cand[0] - px, cand[1] - py)
                     for (px, py) in self._recent),
                    default=float("inf"),
                )
                if cmin > best_min_d:
                    best_min_d = cmin
                    best = cand
            return best if best is not None else target
        return (int(round(tx)), int(round(ty)))

    def _clamp_target_to_zone(
        self, target: tuple[int, int], zone: Optional[Zone],
    ) -> tuple[int, int]:
        """Final hard guard before the cursor moves to click.

        Anti-cluster, jitter, the bump-deduplicate, and the
        recheck-corrections all do their own zone-containment checks,
        but in combination they can occasionally produce an out-of-zone
        target (e.g. a float-rounding boundary case on a polygon
        vertex). This catches any such leak and snaps to a fresh
        in-zone sample. Called as the LAST step in the target pipeline
        — after this point, the cursor moves and clicks at exactly
        ``target``.

        No-op when ``zone`` is None (legacy callers without a cycle
        zone — e.g. the standalone test-click path).
        """
        if zone is None:
            return target
        try:
            inside = zone.contains(int(target[0]), int(target[1]))
        except Exception:
            return target
        if inside:
            return target
        # Re-sample. random_point is guaranteed to return in-zone for
        # any non-degenerate zone (rejection sampling for rect, geometric
        # clamp for circle, AABB-rejection then centroid fallback for
        # polygon). Logged so we can audit whether any humanization
        # step is reliably producing out-of-zone targets.
        fresh = zone.random_point()
        mouse_trace.event(
            "clamp_to_zone",
            ox=int(target[0]), oy=int(target[1]),
            nx=int(fresh[0]), ny=int(fresh[1]),
        )
        self.log.debug(
            "click target outside cycle zone, re-sampled: %s -> %s",
            target, fresh,
        )
        return fresh

    def _jitter(self, target: tuple[int, int],
                 zone: Optional[Zone] = None) -> tuple[int, int]:
        # Aim-point noise applied to the click target before pathing.
        # Gaussian with σ scaled by realism: clean precise aim at low
        # realism (σ≈0.4 px), sloppier human aim at high realism
        # (σ≈1.6 px). Clipped to ±cap px so we never miss a small zone.
        # This is NOT visible jitter — it just shifts where the smooth
        # Bezier path ends. Visible wobble lives in `_walk_phys`.
        sigma = 0.4 + 1.2 * max(0.0, min(1.0, self.realism))
        # Zone-size-aware cap. For a 30×30 button the original ±3 px
        # was fine (10% of zone), but for a 10×10 (tight UI element) or
        # the 5×5 cycle zone color steps build, ±3 was 30–60% of the
        # zone width. Scale to ~15% of the smaller dim, capped at 3
        # for big zones. Keep a 1 px floor so jitter is always present
        # (otherwise the click clusters become too clean and bot-
        # detectable).
        z = zone if zone is not None else self.zone
        cap = 3.0
        if z is not None:
            try:
                x1, y1, x2, y2 = z.aabb()
                zone_min = max(2, min(x2 - x1, y2 - y1))
                cap = max(1.0, min(3.0, zone_min * 0.15))
            except Exception:
                pass
        jx = max(-cap, min(cap, random.gauss(0.0, sigma)))
        jy = max(-cap, min(cap, random.gauss(0.0, sigma)))
        x, y = int(round(target[0] + jx)), int(round(target[1] + jy))
        if z is not None and not z.contains(x, y):
            return target
        return (x, y)
