"""BotRunner: executes a :class:`Bot` on a background QThread and
emits Qt signals the AI tab consumes (log, status, frame thumbnails,
rule fired, finished).

Per tick:

1. Grab a frame from the run's :class:`FrameSource`, set
   ``ctx.current_frame``.
2. Bind the context via ``contextvars`` so ``find_color`` etc. inside
   rule bodies pick it up implicitly.
3. Walk rules in definition order. First one that returns truthy
   "wins"; later rules skip this tick. A rule marked ``idle=True`` (or
   returning ``IDLE``) wins the tick but counts as dry.
4. Emit ``block_executed`` telemetry per fired rule.
5. Sleep whatever is left of the tick period.
6. AFK reliability:
   - Consecutive dry ticks; auto-stop at ``bot.auto_stop_dry_ticks``.
   - Time since the actuator last did anything; auto-stop after
     ``bot.watchdog_no_click_s``.

Threading: the worker owns every mutable field. The GUI thread only
does single attribute assignments (tick rate, dry-run, pause flag) or
reads snapshots; the two read-modify-write spots (pause/resume) take
``_lock``.
"""

from __future__ import annotations

import threading
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt

from ..graph.runtime import RuntimeContext
from ..input.frame_source import MssFrameSource, ReplaySource
from . import api
from .bot import IDLE, Bot


# Width the AI card's preview thumbnail renders at (ui/cards/ai.py
# _PreviewThumb.THUMB_W). Frames are downscaled to this in the worker
# so the GUI thread never receives a full 4K copy per tick.
_THUMB_WIDTH = 280
# Thumbnail emission cap. The card throttles to ~5 fps itself; doing it
# here too avoids the copy + signal for frames it would drop anyway.
_THUMB_MIN_INTERVAL = 0.20


# ─────────────────────────────────────────────────────────────────
# Worker (lives on its own QThread)
# ─────────────────────────────────────────────────────────────────


class _BotWorker(QObject):
    """Drives the tick loop for a :class:`Bot`."""

    log = Signal(str)
    status = Signal(str)
    finished = Signal(str)
    frame_captured = Signal(object)
    block_executed = Signal(object)
    tick_started = Signal(int)

    def __init__(
        self,
        bot: Bot,
        *,
        tick_rate_hz: float,
        default_monitor: int,
        default_roi: Any = None,
        dry_run: bool = False,
        humanizer_config: Any = None,
        actuator: Any = None,
        world_calibration: Optional[dict] = None,
    ) -> None:
        super().__init__()
        self._bot = bot
        self._tick_interval = 1.0 / max(0.5, tick_rate_hz)
        self._default_monitor = int(default_monitor)
        self._default_roi = default_roi
        # The script's own dry_run is a floor the app toggle cannot
        # lower; a bot that ships dry stays dry until its author says
        # otherwise.
        self._dry_run = bool(dry_run) or bool(getattr(bot, "dry_run", False))
        self._humanizer_config = humanizer_config
        # The app's ClickerActuatorBackend. Required: AI clicks share
        # Clicker's humanization state and AI keystrokes go through the
        # Arduino HID backend (the only NXT-resistant keyboard path).
        self._actuator = actuator
        self._lock = threading.Lock()
        # Deadline of the sleep the tick loop is in (monotonic), 0 before
        # the first tick. Single float write, read lock-free by
        # BotRunner.seconds_until_next_tick().
        self._next_tick_at: float = 0.0
        # User-calibrated ROIs for the awareness layer. Copied onto
        # ctx._world_calibration at startup so WorldState can read it
        # via the contextvars-bound ctx during each tick.
        self._world_calibration: dict = dict(world_calibration or {})
        # Optional per-bot item library: if attached to the Bot via
        # ``bot.item_library``, the runner makes it visible to
        # WorldState. Bots that don't use item identification leave
        # this as None.
        self._item_library: Any = getattr(bot, "item_library", None)
        self._ctx: Optional[RuntimeContext] = None
        self._stop_requested = threading.Event()
        self._capture_failures = 0
        # Procedural-program runtime state: only used when the bot
        # carries a compiled program (set by ai.bot.compile_program).
        # Lazy-initialized in _run_program_tick on first call.
        self._program_initialized = False
        self._active_proc: str = ""
        self._active_pc: int = 0
        self._call_stack: List[Tuple[str, int]] = []
        self._interrupt_cooldowns: Dict[str, int] = {}
        # Closed-loop verification state. When the active step's
        # verify field is set and the step's closure returned truthy,
        # the runner installs a Verifier here and polls it each tick
        # until success/timeout, then advances or runs on_fail.
        self._pending_verifier: Any = None
        self._pending_verifier_step_label: str = ""
        self._step_retry_count: int = 0
        # Optional bundle reference: when set, failure screenshots
        # land at <bundle.runs_dir>/<session>/failures/. Without one
        # we just skip the screenshot (no place to put it).
        self._bundle: Any = None
        self._failure_dir: Any = None       # lazy-created on first failure
        # Minimap tracker: stateful across ticks (motion-diff needs
        # the previous crop). Pre-loaded with the bundle's run-energy
        # max_fill so percentages are meaningful from the first tick.
        from ..algorithms.minimap import MinimapTracker
        mm_max = int(
            (self._world_calibration.get("orbs_max_fill") or {}).get(
                "run_energy", 0
            ) or 0
        )
        self._minimap_tracker = MinimapTracker(run_energy_max_fill=mm_max)
        # AFK state. ``_last_click_at`` is stamped by the actuator's
        # input listener (worker thread) and re-anchored on resume
        # (GUI thread); both are single float assignments.
        self._consecutive_dry_ticks = 0
        self._last_click_at: float = 0.0
        self._click_count: int = 0
        self._last_fired_name: Optional[str] = None
        self._last_fired_tick: int = 0
        self._current_tick: int = 0
        # Auto-camera state: burst count resets every time a rule fires.
        self._camera_bursts: int = 0
        # Pause flag. When True the tick loop skips rule eval, AFK
        # accounting, and verifier ticking; it just sleeps and checks
        # again next pass.
        self._paused: bool = False
        # Frame source. None means "live mss on default_monitor", built
        # in run(). play_replay installs a ReplaySource instead.
        self._frame_source: Any = None
        self._thumb_last_emit: float = 0.0

    # ── live controls ───────────────────────────────────
    def set_tick_rate(self, hz: float) -> None:
        self._tick_interval = 1.0 / max(0.5, float(hz))

    def set_dry_run(self, enabled: bool) -> None:
        # Floor: the bot script's own dry_run can never be lowered.
        value = (bool(enabled) or bool(getattr(self._bot, "dry_run", False))
                 or isinstance(self._frame_source, ReplaySource))
        self._dry_run = value
        ctx = self._ctx
        if ctx is not None:
            ctx.dry_run = value

    def stop(self) -> None:
        self._stop_requested.set()
        # Two flags: the context flag ends the loop at the next check,
        # the actuator's event aborts a move / click that is mid-flight
        # right now (Critical Rule 4: stop is instant).
        ctx = self._ctx
        if ctx is not None:
            ctx.request_stop("user pressed Stop")
        act = self._actuator
        fn = getattr(act, "request_stop", None)
        if callable(fn):
            fn()

    def pause(self) -> bool:
        """Pause the tick loop. Returns True iff state changed."""
        with self._lock:
            if self._paused:
                return False
            self._paused = True
            return True

    def resume(self) -> bool:
        """Resume from pause. Re-anchors the no-click watchdog to now so
        the paused interval does not count against it. Returns True iff
        state changed."""
        with self._lock:
            if not self._paused:
                return False
            self._paused = False
            self._last_click_at = time.monotonic()
            return True

    def is_paused(self) -> bool:
        return bool(self._paused)

    # ── main loop ───────────────────────────────────────
    def run(self) -> None:
        try:
            self._run()
        except Exception as exc:
            # Setup can fail before the main loop's cleanup is installed.
            # Always finish the worker so the UI can stop and start again.
            reason = f"bot startup failed: {type(exc).__name__}: {exc}"
            self.log.emit(reason)
            for obj, method in ((self._actuator, "request_stop"),
                                (self._frame_source, "close")):
                try:
                    fn = getattr(obj, method, None)
                    if callable(fn):
                        fn()
                except Exception:
                    pass
            self.status.emit("Stopped")
            self.finished.emit(reason)

    def _run(self) -> None:
        if self._stop_requested.is_set():
            self.status.emit("Stopped")
            self.finished.emit("stopped before startup")
            return
        self.status.emit("Running")

        ctx = RuntimeContext(
            log_fn=lambda m: self.log.emit(m),
            input_backend=None,
            default_monitor=self._default_monitor,
            default_roi=self._default_roi,
            dry_run=self._dry_run,
        )
        backend = self._actuator
        if backend is None:
            self.log.emit("[bot] no input actuator was provided; cannot run.")
            self.status.emit("Stopped")
            self.finished.emit("no input actuator")
            return
        ctx.input_backend = backend
        ctx.current_frame = None
        # Frame source: live mss on the configured monitor unless a
        # replay was installed. The context owns the frame <-> screen
        # mapper from here on.
        if self._frame_source is None:
            self._frame_source = MssFrameSource(self._default_monitor)
        ctx.set_frame_source(self._frame_source)

        # Arm the actuator for this run: clear its stop flag (a previous
        # Stop leaves it set) and listen for inputs so the no-click
        # watchdog sees click.fire() / keys / drags, not just click().
        reset = getattr(backend, "reset_stop", None)
        if callable(reset):
            reset()
        self._click_count = 0
        ctx._bot_click_count = 0

        def _on_input(kind: str) -> None:
            self._last_click_at = time.monotonic()
            if kind == "click":
                self._click_count += 1
                ctx._bot_click_count = self._click_count

        set_listener = getattr(backend, "set_input_listener", None)
        if callable(set_listener):
            set_listener(_on_input)

        self._ctx = ctx
        if self._stop_requested.is_set():
            ctx.request_stop("stopped during startup")
            stop_input = getattr(backend, "request_stop", None)
            if callable(stop_input):
                stop_input()
        # Awareness-layer calibration: pulled by WorldState each tick.
        ctx._world_calibration = dict(self._world_calibration)
        # Item library (if any): exposed to WorldState as ctx.item_library.
        if self._item_library is not None:
            ctx.item_library = self._item_library
        # Chat-event ring buffer + minimap-derived player delta;
        # consumed by on_chat / chat_match / on_player_moved.
        from collections import deque as _deque
        ctx.recent_chat_events = _deque(maxlen=50)
        ctx.player_move_delta_tiles = 0.0
        ctx.minimap_state = None
        self._last_click_at = time.monotonic()
        self._consecutive_dry_ticks = 0

        n_rules = sum(1 for r in self._bot.rules if r.enabled)
        self.log.emit(
            f"[bot] starting {self._bot.name!r} "
            f"({n_rules}/{len(self._bot.rules)} rules, "
            f"tick={int(1/self._tick_interval)} Hz, dry_run={self._dry_run})"
        )
        if self._dry_run and getattr(self._bot, "dry_run", False):
            self.log.emit(
                "[bot] dry-run is forced by the bot script (Bot(dry_run=True)); "
                "edit the script to allow real input."
            )

        tick = 0
        try:
            while not ctx.should_stop():
                tick_started_at = time.monotonic()
                # Pause gate: skip the entire tick body when paused so
                # AFK accounting, frame capture, and verifier ticking
                # all freeze. Stop is still honoured (the outer
                # should_stop() check above runs first).
                if self._paused:
                    if self._sleep_until(ctx, tick_started_at + self._tick_interval):
                        break
                    continue
                tick += 1
                self._current_tick = tick
                self.tick_started.emit(tick)
                frame = self._capture()
                if frame is None:
                    if self._sleep_until(ctx, tick_started_at + self._tick_interval):
                        break
                    continue
                self._emit_thumbnail(frame)
                ctx.current_frame = frame
                # Update the stateful minimap tracker (cheap diff vs
                # previous tick) BEFORE WorldState is built: the
                # WorldState reads ctx.minimap_state instead of doing
                # its own scan, so the tracker's previous-frame
                # memory is preserved across ticks.
                mm_rect = (ctx._world_calibration or {}).get("minimap_rect")
                if mm_rect is not None:
                    try:
                        ms = self._minimap_tracker.tick(
                            frame, tuple(ctx.screen_rect_to_frame(mm_rect))
                        )
                    except Exception as e:
                        self.log.emit(
                            f"[bot] minimap tick crashed: {type(e).__name__}: {e}"
                        )
                        ms = None
                    if ms is not None:
                        ctx.minimap_state = ms
                        # Trigger feed: the on_player_moved trigger
                        # reads ctx.player_move_delta_tiles directly.
                        ctx.player_move_delta_tiles = ms.motion_tiles
                # Per-tick WorldState: lazy fields cache once each tick.
                from .world import build_world
                ctx.world = build_world(ctx, frame, tick)

                token = api._set_ctx(ctx)
                fired_name = None
                productive = False
                try:
                    if getattr(self._bot, "program", None) is not None:
                        fired_name = self._run_program_tick(ctx, tick)
                        productive = fired_name is not None
                    else:
                        fired_name, productive = self._run_legacy_tick(ctx, tick)
                finally:
                    api._reset_ctx(token)

                # An idle fallthrough rule "fires" every tick; only a
                # productive rule resets the dry-tick watchdog.
                if not productive:
                    self._consecutive_dry_ticks += 1
                else:
                    self._consecutive_dry_ticks = 0
                    self._camera_bursts = 0  # any successful fire resets

                # Auto-camera fallback: rotate after N dry ticks so a
                # bad camera angle doesn't immediately trip the AFK
                # watchdog. Give up after ``max_bursts`` rotations.
                if (
                    not productive
                    and self._bot.auto_camera
                    and self._bot.auto_camera_dry_ticks > 0
                    and self._consecutive_dry_ticks > 0
                    and self._consecutive_dry_ticks % self._bot.auto_camera_dry_ticks == 0
                    and self._camera_bursts < self._bot.auto_camera_max_bursts
                ):
                    self._camera_bursts += 1
                    step = self._bot.auto_camera_step_deg
                    self.log.emit(
                        f"[auto-camera] dry for {self._consecutive_dry_ticks} ticks: "
                        f"rotating right {step:.0f}° "
                        f"(burst {self._camera_bursts}/{self._bot.auto_camera_max_bursts})"
                    )
                    token = api._set_ctx(ctx)
                    try:
                        # Late import to avoid a bot → camera → api → bot cycle.
                        from . import camera as _camera
                        try:
                            _camera.rotate_right(degrees=step)
                        except Exception as e:
                            self.log.emit(
                                f"[auto-camera] rotate failed: {type(e).__name__}: {e}"
                            )
                    finally:
                        api._reset_ctx(token)

                # AFK watchdogs.
                if (
                    self._bot.auto_stop_dry_ticks > 0
                    and self._consecutive_dry_ticks >= self._bot.auto_stop_dry_ticks
                ):
                    ctx.request_stop(
                        f"AFK watchdog: {self._consecutive_dry_ticks} consecutive "
                        "dry ticks: no rule fired. Check if you got logged out "
                        "or the screen changed."
                    )
                    break
                since_click = time.monotonic() - self._last_click_at
                if (
                    self._bot.watchdog_no_click_s > 0
                    and since_click > self._bot.watchdog_no_click_s
                ):
                    ctx.request_stop(
                        f"AFK watchdog: no input in {since_click:.0f} s "
                        f"(limit {self._bot.watchdog_no_click_s:.0f} s)"
                    )
                    break

                # Hold the tick rate whether or not a rule fired. A rule
                # that already waited longer than the period costs no
                # extra sleep.
                if self._sleep_until(ctx, tick_started_at + self._tick_interval):
                    break
        except Exception as e:
            self.log.emit(
                f"[bot] crashed: {type(e).__name__}: {e}\n{traceback.format_exc()}"
            )
            ctx.request_stop(f"exception: {type(e).__name__}: {e}")

        # Backend cleanup: drop our listener and make sure nothing is
        # left mid-move.
        try:
            if callable(set_listener):
                set_listener(None)
            request_stop = getattr(backend, "request_stop", None)
            if callable(request_stop):
                request_stop()
            shutdown = getattr(backend, "shutdown", None)
            if callable(shutdown):
                shutdown()
        except Exception as e:
            self.log.emit(f"[bot] backend shutdown failed: {type(e).__name__}: {e}")
        close = getattr(self._frame_source, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

        reason = ctx.stop_reason() or "stopped"
        self.log.emit(
            f"[bot] finished after {tick} tick(s): {reason} "
            f"(clicks={self._click_count})"
        )
        self.status.emit("Stopped")
        self.finished.emit(reason)

    # ── helpers ──────────────────────────────────────────
    def _capture(self):
        """One frame from the run's frame source, or None.

        None from a replay means the replay ended; that is a clean stop.
        None from live capture is logged and the tick is skipped.
        """
        src = self._frame_source
        try:
            frame = src.grab()
        except Exception as e:
            self.log.emit(f"[bot] capture failed: {type(e).__name__}: {e}")
            frame = None
        if frame is None:
            if isinstance(src, ReplaySource) and self._ctx is not None:
                self._ctx.request_stop("replay finished")
            else:
                self._capture_failures += 1
                if self._capture_failures >= 5 and self._ctx is not None:
                    self._ctx.request_stop("screen capture failed 5 consecutive times")
            return None
        self._capture_failures = 0
        return frame

    def _emit_thumbnail(self, frame) -> None:
        """Downscale + rate-limit the preview so the GUI thread gets a
        small array a few times a second instead of a full frame copy
        every tick."""
        now = time.monotonic()
        if now - self._thumb_last_emit < _THUMB_MIN_INTERVAL:
            return
        self._thumb_last_emit = now
        try:
            h, w = frame.shape[:2]
            if w > _THUMB_WIDTH:
                import cv2
                scale = _THUMB_WIDTH / float(w)
                small = cv2.resize(
                    frame, (_THUMB_WIDTH, max(1, int(round(h * scale)))),
                    interpolation=cv2.INTER_AREA,
                )
            else:
                small = frame.copy()
            self.frame_captured.emit(np.ascontiguousarray(small))
        except Exception:
            pass

    def _sleep_until(self, ctx: RuntimeContext, deadline: float) -> bool:
        """Sleep until ``deadline`` (monotonic), polling the stop flag.
        Returns True when stop was requested."""
        self._next_tick_at = float(deadline)
        while True:
            if ctx.should_stop():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.05, remaining))

    # ── Legacy tick (flat priority list) ────────────────────────
    def _run_legacy_tick(
        self, ctx: RuntimeContext, tick: int,
    ) -> Tuple[Optional[str], bool]:
        """Walk ``self._bot.rules`` first-match-wins.

        Returns ``(name, productive)``: ``name`` is the rule that fired
        (None when nothing did); ``productive`` is False for idle rules
        so the dry-tick watchdog still counts the tick.
        """
        for rule in self._bot.rules:
            if ctx.should_stop():
                return None, False
            if not rule.enabled:
                continue
            t0 = time.monotonic()
            try:
                result = rule.func()
            except Exception as e:
                self.log.emit(
                    f"[bot] rule {rule.name!r} crashed: "
                    f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
                )
                ctx.request_stop(f"rule {rule.name} raised {type(e).__name__}")
                return None, False
            if not result:
                continue
            idle = bool(getattr(rule, "idle", False)) or result is IDLE
            self._last_fired_name = rule.name
            self._last_fired_tick = tick
            self.block_executed.emit({
                "identifier": f"bot.rule.{rule.name}",
                "node_id": f"rule_{rule.name}",
                "params": {"phase": rule.phase} if rule.phase else {},
                "inputs": {},
                "outputs": {"fired": True, "phase": rule.phase, "idle": idle},
                "elapsed_ms": (time.monotonic() - t0) * 1000.0,
            })
            # Idle rules fire every tick; logging each one buries the
            # lines that matter.
            if not idle:
                self.log.emit(f"▶ {rule.name} (phase={rule.phase or '-'})")
            return rule.name, not idle
        return None, False

    # ── Program tick (procedures + interrupts) ──────────────────
    def _run_program_tick(self, ctx: RuntimeContext, tick: int) -> Optional[str]:
        """Procedural runtime: execute one step of the active procedure
        unless an interrupt fires. Returns whatever name the dashboard
        should associate with this tick (interrupt name or
        ``proc.step``), or ``None`` when nothing fired."""
        bot = self._bot
        # Lazy init runtime state on first program tick.
        if not self._program_initialized:
            self._active_proc = getattr(bot, "_program_entry", "main")
            self._active_pc = 0
            self._call_stack = []
            self._interrupt_cooldowns = {}
            self._pending_verifier = None
            self._pending_verifier_step_label = ""
            self._step_retry_count = 0
            self._program_initialized = True
            self.log.emit(
                f"[bot] entering procedure {self._active_proc!r}"
            )

        # Pending verification: poll first. While a verifier is in
        # flight, step execution is paused but interrupts still
        # evaluate (HP-low / disconnect handling has to work even
        # mid-verification). Set a flag so the bottom of this method
        # skips step execution if we're still waiting.
        verifying = False
        if self._pending_verifier is not None:
            verdict = None
            try:
                verdict = self._pending_verifier.tick(ctx)
            except Exception as e:
                self.log.emit(
                    f"[bot] verifier crashed: {type(e).__name__}: {e}"
                )
                self._pending_verifier = None
                self._step_retry_count = 0
            if verdict is not None and verdict.success:
                self.log.emit(
                    f"  ✓ verified {self._pending_verifier_step_label!r} "
                    f"via {verdict.signal} ({verdict.elapsed_ticks} ticks)"
                )
                self._pending_verifier = None
                self._pending_verifier_step_label = ""
                self._step_retry_count = 0
                self._active_pc += 1
                return None
            if verdict is not None and verdict.timed_out:
                label = self._pending_verifier_step_label
                signal = self._pending_verifier.signal
                self._pending_verifier = None
                self._pending_verifier_step_label = ""
                self._handle_verification_failure(ctx, label, signal)
                return None
            verifying = self._pending_verifier is not None

        # Decay interrupt cooldowns by 1 per tick.
        if self._interrupt_cooldowns:
            for nm in list(self._interrupt_cooldowns):
                self._interrupt_cooldowns[nm] -= 1
                if self._interrupt_cooldowns[nm] <= 0:
                    del self._interrupt_cooldowns[nm]

        # Evaluate interrupts in declaration order. First non-cooldown
        # trigger that fires wins this tick.
        from .procedures import HANDLER_ABORT
        for intr in getattr(bot, "_compiled_interrupts", []):
            if ctx.should_stop():
                return None
            if intr.name in self._interrupt_cooldowns:
                continue
            try:
                fired = bool(intr.trigger())
            except Exception as e:
                self.log.emit(
                    f"[bot] interrupt {intr.name!r} crashed: "
                    f"{type(e).__name__}: {e}"
                )
                continue
            if not fired:
                continue
            # Reset its cooldown so a sticky condition (HP staying
            # low for several ticks) doesn't re-trigger every tick.
            if intr.cooldown_ticks > 0:
                self._interrupt_cooldowns[intr.name] = intr.cooldown_ticks
            if intr.handler == HANDLER_ABORT:
                self.log.emit(f"⚡ interrupt {intr.name!r} → abort")
                ctx.request_stop(f"interrupt {intr.name!r} → abort")
                return f"interrupt:{intr.name}"
            # Push current state, jump to handler.
            self._call_stack.append((self._active_proc, self._active_pc))
            self._active_proc = intr.handler
            self._active_pc = 0
            self.log.emit(f"⚡ interrupt {intr.name!r} → procedure {intr.handler!r}")
            self._last_fired_name = f"interrupt:{intr.name}"
            self._last_fired_tick = tick
            self.block_executed.emit({
                "identifier": f"bot.rule.interrupt:{intr.name}",
                "node_id": f"interrupt_{intr.name}",
                "params": {"handler": intr.handler},
                "inputs": {},
                "outputs": {"fired": True},
                "elapsed_ms": 0.0,
            })
            return f"interrupt:{intr.name}"

        # No interrupt fired. If we're mid-verification, just wait;
        # don't execute another step until the prior action's signal
        # confirms or times out.
        if verifying:
            return None

        # Execute the next step of the active proc.
        compiled_procs: Dict[str, list] = getattr(bot, "_compiled_procedures", {})
        # Normalize the active state: if we're parked at or past the
        # end of a procedure (which can happen when a popped pc lands
        # exactly past the suspended caller's last step), pop / restart
        # repeatedly until pc is inside the procedure. Keeps the tick
        # productive instead of wasting it on a "phantom" pc.
        for _ in range(8):           # bounded so a malformed program can't loop
            proc_steps = compiled_procs.get(self._active_proc, [])
            if self._active_pc < len(proc_steps):
                break
            if self._call_stack:
                self._active_proc, prev_pc = self._call_stack.pop()
                self._active_pc = prev_pc + 1
                self.log.emit(
                    f"↩ resuming procedure {self._active_proc!r} at step {self._active_pc}"
                )
                continue
            entry = getattr(bot, "_program_entry", "main")
            if self._active_proc != entry:
                self._active_proc = entry
            self._active_pc = 0
            self.log.emit(f"↻ restarting entry procedure {self._active_proc!r}")
            break
        else:
            # 8 normalizations and we're still past the end: bail.
            ctx.request_stop(
                f"runaway procedure normalization in {self._active_proc!r}"
            )
            return None
        proc_steps = compiled_procs.get(self._active_proc, [])
        if self._active_pc >= len(proc_steps):
            # Couldn't find anything to do (entry is empty). Stop.
            ctx.request_stop(
                f"entry procedure {self._active_proc!r} has no enabled steps"
            )
            return None

        step = proc_steps[self._active_pc]
        if not step.enabled:
            self._active_pc += 1
            return None
        t0 = time.monotonic()
        try:
            result = step.func()
        except Exception as e:
            label = f"{self._active_proc}.{step.name}"
            self.log.emit(
                f"[bot] step {label!r} crashed: "
                f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            )
            self._save_failure_artifact(
                ctx, label, f"step crashed: {type(e).__name__}: {e}",
            )
            ctx.request_stop(
                f"step {label} raised {type(e).__name__}"
            )
            return None
        rule_label = f"{self._active_proc}.{step.name}"
        if not result:
            return None              # step didn't satisfy: retry next tick
        self._last_fired_name = rule_label
        self._last_fired_tick = tick
        self.block_executed.emit({
            "identifier": f"bot.rule.{rule_label}",
            "node_id": f"rule_{rule_label}",
            "params": {"phase": step.phase} if step.phase else {},
            "inputs": {},
            "outputs": {"fired": True, "phase": step.phase},
            "elapsed_ms": (time.monotonic() - t0) * 1000.0,
        })
        self.log.emit(f"▶ {rule_label}")

        # Install a verifier if the step asked for one. The pc is NOT
        # advanced yet: we'll advance only after the verifier confirms
        # success on a later tick. ``verify_spec`` is the raw JSON dict
        # captured at compile time.
        spec = getattr(step, "verify_spec", None)
        if spec:
            from ..algorithms.verify import from_json as _verify_from_json
            try:
                v = _verify_from_json(spec, tick_rate_hz=1.0 / max(0.001, self._tick_interval))
            except Exception as e:
                self.log.emit(
                    f"[bot] verify spec rejected for {rule_label!r}: {e}"
                )
                v = None
            if v is not None:
                self._pending_verifier = v
                self._pending_verifier_step_label = rule_label
                self.log.emit(
                    f"  ↳ verifying via {v.signal} (≤ {v.timeout_ticks} ticks)"
                )
                return rule_label

        # No verification: advance immediately.
        self._active_pc += 1
        return rule_label

    def _save_failure_artifact(
        self, ctx: RuntimeContext, label: str, reason: str,
    ) -> None:
        """Write the current frame + a small JSON of ctx state to
        ``<bundle>/runs/<session>/failures/`` so failures at 4 AM can
        be diagnosed in the morning. No-op when no bundle is attached
        (legacy / library bot path)."""
        bundle = self._bundle
        if bundle is None:
            return
        try:
            import time as _time
            from pathlib import Path
            from PIL import Image
            import numpy as np
            import json
            import traceback

            if self._failure_dir is None:
                ts = _time.strftime("%Y-%m-%d_%H-%M-%S")
                self._failure_dir = bundle.runs_dir / ts / "failures"
                self._failure_dir.mkdir(parents=True, exist_ok=True)

            stamp = _time.strftime("%H-%M-%S")
            slug = "".join(
                c if c.isalnum() else "_" for c in (label or "step")
            ).strip("_")[:40] or "step"
            base = self._failure_dir / f"{stamp}_{slug}"

            frame = getattr(ctx, "current_frame", None)
            if frame is not None and isinstance(frame, np.ndarray) and frame.ndim == 3:
                rgb = np.ascontiguousarray(frame[..., ::-1])
                Image.fromarray(rgb).save(str(base.with_suffix(".png")))

            info = {
                "timestamp": _time.time(),
                "label": label,
                "reason": reason,
                "active_proc": self._active_proc,
                "active_pc": self._active_pc,
                "call_stack": list(self._call_stack),
                "retry_count": int(self._step_retry_count),
                "stop_reason": ctx.stop_reason() or "",
            }
            base.with_suffix(".json").write_text(
                json.dumps(info, indent=2), encoding="utf-8",
            )
            self.log.emit(
                f"  📸 failure artifact: {base.name}.png/.json"
            )
        except Exception as e:
            self.log.emit(
                f"[bot] couldn't save failure artifact: "
                f"{type(e).__name__}: {e}"
            )

    def _handle_verification_failure(
        self, ctx: RuntimeContext, step_label: str, signal: str,
    ) -> None:
        """Apply the active step's ``on_fail`` policy.

        Strategy ``"retry"`` (default): bump the retry counter; if the
        budget is exhausted, escalate to abort. ``"abort"``: stop the
        bot. ``"goto_procedure:<name>"``: push current state and run
        the named procedure.
        """
        bot = self._bot
        compiled_procs = getattr(bot, "_compiled_procedures", {})
        proc_steps = compiled_procs.get(self._active_proc, [])
        step = (
            proc_steps[self._active_pc]
            if 0 <= self._active_pc < len(proc_steps) else None
        )
        on_fail = getattr(step, "on_fail", "retry") if step is not None else "retry"
        budget = getattr(step, "retry_budget", 3) if step is not None else 3

        self.log.emit(
            f"  ✗ verification timed out for {step_label!r} "
            f"(signal={signal})  policy={on_fail}"
        )

        if on_fail == "abort":
            self._save_failure_artifact(
                ctx, step_label, f"verify timeout signal={signal} → abort",
            )
            ctx.request_stop(f"verification timeout: {step_label}")
            return

        if on_fail.startswith("goto_procedure:"):
            target = on_fail.split(":", 1)[1].strip()
            if target and target in compiled_procs:
                self._save_failure_artifact(
                    ctx, step_label,
                    f"verify timeout signal={signal} → goto {target}",
                )
                self._call_stack.append((self._active_proc, self._active_pc))
                self._active_proc = target
                self._active_pc = 0
                self._step_retry_count = 0
                self.log.emit(
                    f"  ↪ on_fail → procedure {target!r}"
                )
                return
            self._save_failure_artifact(
                ctx, step_label,
                f"verify timeout: handler {target!r} not found",
            )
            self.log.emit(
                f"  ⚠ on_fail target {target!r} not found; aborting"
            )
            ctx.request_stop(f"verification fail handler missing: {target}")
            return

        # "retry" (default). Bump the counter; on overflow, escalate.
        self._step_retry_count += 1
        if self._step_retry_count >= max(1, int(budget)):
            self._save_failure_artifact(
                ctx, step_label,
                f"verify timeout signal={signal}: retry budget {budget} exhausted",
            )
            self.log.emit(
                f"  ⚠ retry budget exhausted ({budget}): aborting step"
            )
            ctx.request_stop(
                f"step {step_label!r} exhausted retry budget"
            )
            return
        # Re-run the step on the next tick (don't advance pc).
        self.log.emit(
            f"  ↻ retry {self._step_retry_count}/{budget}"
        )


# ─────────────────────────────────────────────────────────────────
# Controller
# ─────────────────────────────────────────────────────────────────


class BotRunner(QObject):
    """Owns the worker QThread for one bot run and re-emits its signals
    on the GUI thread.

    Lifecycle: ``play`` / ``play_replay`` start a run, ``stop`` requests
    a stop (returns immediately), ``wait(ms)`` blocks up to ``ms`` for
    the thread to exit, ``is_running`` reports the thread state. The
    worker's ``finished`` triggers a bounded, non-blocking reap of the
    thread; a slow exit is retried from a QTimer instead of freezing
    the GUI.
    """

    log = Signal(str)
    status = Signal(str)
    finished = Signal(str)
    frame_captured = Signal(object)
    block_executed = Signal(object)
    tick_started = Signal(int)
    _workerCompleted = Signal(int, str)

    # How long _on_finished blocks for the thread before deferring to a
    # timer. The worker has already returned from run() when finished
    # fires, so this is normally a few milliseconds.
    _REAP_WAIT_MS = 200
    _REAP_RETRY_MS = 100
    _REAP_MAX_RETRIES = 50

    def __init__(self) -> None:
        super().__init__()
        self._thread: Optional[QThread] = None
        self._worker: Optional[_BotWorker] = None
        self._reap_retries = 0
        self._generation = 0
        self._workerCompleted.connect(self._on_finished)

    # ── state ────────────────────────────────────────────────────
    def is_running(self) -> bool:
        t = self._thread
        return t is not None and t.isRunning()

    def wait(self, ms: int = 2000) -> bool:
        """Block up to ``ms`` for the worker thread to finish.

        Returns True when no thread is running afterwards. Meant for
        shutdown paths (closeEvent) that must not exit with a live
        worker; everyday stop handling should rely on ``finished``.
        """
        t = self._thread
        if t is None:
            return True
        if not t.isRunning():
            return True
        done = bool(t.wait(max(0, int(ms))))
        if done:
            self._release_thread()
        return done

    # ── loading ──────────────────────────────────────────────────
    def load_bot_safe(self, path) -> Optional[Bot]:
        """Import a bot script by path, surfacing any failure through
        ``log`` / ``status`` instead of raising. Returns None on error
        so the caller can simply bail."""
        from .loader import load_bot_from_path
        try:
            return load_bot_from_path(path)
        except Exception as e:
            msg = f"[bot] could not load {path}: {type(e).__name__}: {e}"
            self.log.emit(msg)
            self.status.emit("Load failed")
            return None

    # ── start ────────────────────────────────────────────────────
    def play(
        self,
        bot: Bot,
        *,
        tick_rate_hz: float = 5.0,
        default_monitor: int = 1,
        default_roi=None,
        dry_run: bool = False,
        humanizer_config=None,
        actuator=None,
        world_calibration: Optional[dict] = None,
        bundle: Any = None,
    ) -> None:
        """Start ``bot`` on a fresh worker thread.

        ``dry_run`` is OR-ed with the script's own ``Bot(dry_run=...)``;
        the app toggle can add dry-run but not remove it.
        """
        self._start(
            bot,
            frame_source=None,
            tick_rate_hz=tick_rate_hz,
            default_monitor=default_monitor,
            default_roi=default_roi,
            dry_run=dry_run,
            humanizer_config=humanizer_config,
            actuator=actuator,
            world_calibration=world_calibration,
            bundle=bundle,
        )

    def play_replay(
        self,
        bot: Bot,
        replay_path: str,
        *,
        loop: bool = False,
        tick_rate_hz: float = 5.0,
        actuator: Any = None,
        humanizer_config: Any = None,
        world_calibration: Optional[dict] = None,
        bundle: Any = None,
    ) -> None:
        """Run ``bot`` against frames pulled from ``replay_path``.

        Replay is always dry-run: its value is detection tuning against
        frames the user last saw fail, not action playback. End of
        replay is a clean stop (``stop_reason = "replay finished"``).
        """
        from .replay import FrameReplay
        source = ReplaySource(FrameReplay(replay_path, loop=bool(loop)))
        self._start(
            bot,
            frame_source=source,
            tick_rate_hz=tick_rate_hz,
            default_monitor=1,
            default_roi=None,
            dry_run=True,
            humanizer_config=humanizer_config,
            actuator=actuator,
            world_calibration=world_calibration,
            bundle=bundle,
        )

    def _start(
        self,
        bot: Bot,
        *,
        frame_source: Any,
        tick_rate_hz: float,
        default_monitor: int,
        default_roi,
        dry_run: bool,
        humanizer_config,
        actuator,
        world_calibration: Optional[dict],
        bundle: Any,
    ) -> None:
        if self.is_running():
            self.log.emit("[bot] already running; stop first.")
            return
        self._release_thread()
        if bot is None or not hasattr(bot, "rules"):
            self.log.emit("[bot] nothing to run: no bot object.")
            self.status.emit("Load failed")
            return
        if actuator is None:
            self.log.emit("[bot] no input actuator; AI mode needs the app's actuator.")
            self.status.emit("Stopped")
            return
        cfg = humanizer_config
        if cfg is not None and getattr(bot, "humanizer_overrides", None):
            cfg = cfg.with_overrides(bot.humanizer_overrides)
        try:
            worker = _BotWorker(
                bot,
                tick_rate_hz=tick_rate_hz,
                default_monitor=default_monitor,
                default_roi=default_roi,
                dry_run=dry_run,
                humanizer_config=cfg,
                actuator=actuator,
                world_calibration=world_calibration,
            )
        except Exception as e:
            self.log.emit(
                f"[bot] could not prepare run: {type(e).__name__}: {e}\n"
                f"{traceback.format_exc()}"
            )
            self.status.emit("Stopped")
            return
        worker._bundle = bundle
        worker._frame_source = frame_source
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log.connect(self.log.emit)
        worker.status.connect(self.status.emit)
        self._generation += 1
        generation = self._generation
        worker.finished.connect(
            lambda reason: self._workerCompleted.emit(generation, reason), Qt.DirectConnection)
        # Quit without depending on the GUI event loop (closeEvent may be
        # waiting for this thread). Never drop a live QThread reference.
        worker.finished.connect(thread.quit, Qt.DirectConnection)
        thread.finished.connect(worker.deleteLater)
        worker.frame_captured.connect(self.frame_captured.emit)
        worker.block_executed.connect(self.block_executed.emit)
        worker.tick_started.connect(self.tick_started.emit)
        self._worker = worker
        self._thread = thread
        self._reap_retries = 0
        thread.start()

    # ── controls ─────────────────────────────────────────────────
    def stop(self) -> None:
        """Ask the running bot to stop. Returns at once; ``finished``
        fires when the worker has actually exited."""
        w = self._worker
        if w is not None:
            w.stop()

    def pause(self) -> bool:
        """Pause the running bot. No-op when no bot is running."""
        w = self._worker
        if w is None or not self.is_running():
            return False
        return w.pause()

    def resume(self) -> bool:
        """Resume a paused bot. No-op when not paused."""
        w = self._worker
        if w is None or not self.is_running():
            return False
        return w.resume()

    def is_paused(self) -> bool:
        w = self._worker
        return bool(w.is_paused()) if w is not None else False

    def toggle_pause(self) -> Optional[bool]:
        """Flip pause state. Returns the new ``is_paused`` value, or
        None if no bot is running."""
        w = self._worker
        if w is None or not self.is_running():
            return None
        if w.is_paused():
            w.resume()
            return False
        w.pause()
        return True

    def set_tick_rate(self, hz: float) -> None:
        w = self._worker
        if w is not None:
            w.set_tick_rate(hz)

    def set_dry_run(self, enabled: bool) -> None:
        w = self._worker
        if w is not None:
            w.set_dry_run(enabled)

    # ── snapshots (polled from GUI + monitor HTTP threads) ─────────
    def dry_run_reason(self) -> str:
        w = self._worker
        if w is None:
            return ""
        if isinstance(w._frame_source, ReplaySource):
            return "Replay: input disabled"
        if getattr(w._bot, "dry_run", False):
            return "Script requires dry run: input disabled"
        if w._dry_run:
            return "Dry run: input disabled"
        return ""

    def last_fired(self) -> dict:
        # Reads only plain attributes the worker assigns atomically, so
        # this is safe from any thread without a lock.
        w = self._worker
        last_click_at = float(getattr(w, "_last_click_at", 0.0) or 0.0)
        no_click_age_s = 0.0
        if last_click_at > 0.0:
            no_click_age_s = max(0.0, time.monotonic() - last_click_at)
        return {
            "running": self.is_running(),
            "last_fired_rule": getattr(w, "_last_fired_name", None),
            "last_fired_tick": int(getattr(w, "_last_fired_tick", 0) or 0),
            "current_tick": int(getattr(w, "_current_tick", 0) or 0),
            "consecutive_dry_ticks": int(getattr(w, "_consecutive_dry_ticks", 0) or 0),
            "click_count": int(getattr(w, "_click_count", 0) or 0),
            "no_click_age_s": no_click_age_s,
        }

    def seconds_until_next_tick(self) -> Optional[float]:
        """Seconds until the worker's next tick, or None when no bot is
        running (or it has not slept yet). Lock-free single-attribute read."""
        w = self._worker
        if w is None or not self.is_running():
            return None
        at = float(getattr(w, "_next_tick_at", 0.0) or 0.0)
        if at <= 0.0:
            return None
        return max(0.0, at - time.monotonic())

    def fatigue_multiplier(self) -> Optional[float]:
        """The actuator's own Fatigue multiplier for this run, or None when
        no bot is running or the actuator has no fatigue model."""
        w = self._worker
        if w is None or not self.is_running():
            return None
        fn = getattr(getattr(w, "_actuator", None), "fatigue_multiplier", None)
        if not callable(fn):
            return None
        try:
            return float(fn())
        except Exception:
            return None

    def current_step_info(self) -> Optional[dict]:
        """Return the active procedural step's display metadata for the
        BotOverlay HUD, or ``None`` when no program is running.

        Shape: ``{"proc": str, "pc": int, "name": str, "kind": str,
        "roi": (x1, y1, x2, y2) | None}``.
        """
        w = self._worker
        if w is None or not self.is_running():
            return None
        bot = getattr(w, "_bot", None)
        if bot is None or getattr(bot, "program", None) is None:
            return None
        proc_name = str(getattr(w, "_active_proc", "") or "")
        pc = int(getattr(w, "_active_pc", 0) or 0)
        compiled_procs = getattr(bot, "_compiled_procedures", {}) or {}
        steps = compiled_procs.get(proc_name) or []
        if not (0 <= pc < len(steps)):
            return {"proc": proc_name, "pc": pc, "name": "",
                    "kind": "", "roi": None}
        step = steps[pc]
        return {
            "proc": proc_name,
            "pc": pc,
            "name": getattr(step, "name", ""),
            "kind": getattr(step, "kind", ""),
            "roi": getattr(step, "roi", None),
        }

    # ── teardown ─────────────────────────────────────────────────
    @Slot(int, str)
    def _on_finished(self, generation: int, reason: str) -> None:
        if generation != self._generation:
            return
        t = self._thread
        if t is None:
            self.finished.emit(reason)
            return
        t.quit()
        if t.wait(self._REAP_WAIT_MS):
            self._release_thread()
            self.finished.emit(reason)
            return
        # Still winding down; poll from the event loop rather than
        # blocking the GUI.
        self._reap_retries = 0
        QTimer.singleShot(self._REAP_RETRY_MS, lambda: self._reap_later(generation, reason))

    def _reap_later(self, generation: int, reason: str) -> None:
        if generation != self._generation:
            return
        t = self._thread
        if t is None:
            self.finished.emit(reason)
            return
        if t.wait(0) or not t.isRunning():
            self._release_thread()
            self.finished.emit(reason)
            return
        self._reap_retries += 1
        if self._reap_retries >= self._REAP_MAX_RETRIES:
            self.log.emit("[bot] still waiting for worker shutdown; retaining the thread.")
            self._reap_retries = 0
        QTimer.singleShot(self._REAP_RETRY_MS, lambda: self._reap_later(generation, reason))

    def _release_thread(self) -> None:
        thread = self._thread
        if thread is not None and thread.isRunning():
            return
        self._thread = None
        self._worker = None
        if thread is not None:
            thread.deleteLater()
